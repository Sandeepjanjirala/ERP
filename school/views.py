import csv
import unicodedata
from collections import defaultdict
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError, connection
from django.db.models import Q, Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.http import require_POST
from .models import *
from .forms import *
from . import permissions as access
from .services import audit, save_register, save_marks, transition_exam, attendance_summary, mark_summary


def throttle(namespace, value, limit=8, minutes=15):
    normalized = unicodedata.normalize('NFKC', value).strip().lower()[:300]
    key = salted_hmac(namespace, normalized).hexdigest()
    with transaction.atomic():
        LoginAttempt.objects.get_or_create(key=key, defaults={'started_at':timezone.now()})
        record = LoginAttempt.objects.select_for_update().get(pk=key)
        if record.started_at <= timezone.now() - timedelta(minutes=minutes):
            record.count, record.started_at = 0, timezone.now()
        if record.count >= limit:
            return False, key
        record.count += 1
        record.save()
    return True, key


class LoginView(auth_views.LoginView):
    authentication_form = LoginForm
    template_name = 'registration/login.html'
    redirect_authenticated_user = True
    def post(self, request, *args, **kwargs):
        allowed, self.throttle_key = throttle('portal-login', request.POST.get('username',''))
        if not allowed:
            return render(request, self.template_name, {'form':self.get_form_class()(request=request), 'login_error':'Too many attempts. Please wait 15 minutes before trying again.'}, status=429)
        return super().post(request, *args, **kwargs)
    def form_valid(self, form):
        LoginAttempt.objects.filter(pk=self.throttle_key).delete()
        response = super().form_valid(form)
        audit(self.request.user, self.request.user.branch, 'account.login', self.request.user.username)
        return response


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = 'registration/auth_form.html'
    extra_context = {'heading':'Set your password','description':'Choose a private password with at least 12 characters.'}
    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=['must_change_password'])
        audit(self.request.user, self.request.user.branch, 'account.password_changed', self.request.user.username)
        return response


class PasswordResetView(auth_views.PasswordResetView):
    template_name = 'registration/auth_form.html'
    email_template_name = 'registration/password_reset_email.txt'
    subject_template_name = 'registration/password_reset_subject.txt'
    extra_context = {'heading':'Reset your password','description':'Enter your account email. If an active account exists, you will receive a reset link.'}
    def post(self, request, *args, **kwargs):
        allowed, _ = throttle('portal-reset', request.POST.get('email',''), limit=3)
        if not allowed:
            return redirect('password_reset_done')
        return super().post(request, *args, **kwargs)


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'registration/auth_form.html'
    extra_context = {'heading':'Choose a new password','description':'Reset links expire after one hour.'}
    def form_valid(self, form):
        response = super().form_valid(form)
        form.user.must_change_password = False
        form.user.save(update_fields=['must_change_password'])
        audit(form.user, form.user.branch, 'account.password_reset', form.user.username)
        return response


def health(request):
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return JsonResponse({'status':'ok'})


def selected_branch(request):
    value = request.GET.get('branch')
    return get_object_or_404(access.branches(request.user), pk=value) if value and value.isdigit() else None


def page(request, qs, size=25):
    return Paginator(qs, size).get_page(request.GET.get('page'))


@login_required
def dashboard(request):
    if request.user.role == 'student':
        profile = get_object_or_404(Student, user=request.user)
        return redirect('student_report', pk=profile.pk)
    branch = selected_branch(request)
    classes = access.classrooms(request.user)
    people = access.students(request.user)
    exams_qs = access.exams(request.user)
    attendance = access.attendance_rows(request.user)
    if branch:
        classes = classes.filter(branch=branch)
        people = people.filter(user__branch=branch)
        exams_qs = exams_qs.filter(classroom__branch=branch)
        attendance = attendance.filter(session__classroom__branch=branch)
    today = timezone.localdate()
    today_attendance = attendance_summary(attendance.filter(session__date=today))
    stats = {'students':people.filter(user__is_active=True).count(), 'classes':classes.count(), 'pending':exams_qs.filter(status='submitted').count(), 'attendance':today_attendance['rate']}
    class_rows = list(classes.annotate(student_count=Count('enrollments', filter=Q(enrollments__left_on__isnull=True), distinct=True))[:12])
    sessions = {s.classroom_id:s for s in AttendanceSession.objects.filter(classroom__in=class_rows, date=today)}
    for c in class_rows:
        c.register = sessions.get(c.pk)
    return render(request, 'school/dashboard.html', {'title':'Overview','stats':stats,'class_rows':class_rows,'recent_exams':exams_qs[:5],'branches':access.branches(request.user),'selected_branch':branch,'today':today})


@access.roles('superadmin','admin','principal','teacher')
def student_list(request):
    qs = access.students(request.user).order_by('user__first_name','admission_number')
    query = request.GET.get('q','').strip()
    if query:
        qs = qs.filter(Q(user__first_name__icontains=query)|Q(user__last_name__icontains=query)|Q(admission_number__icontains=query))
    branch = selected_branch(request)
    if branch:
        qs = qs.filter(user__branch=branch)
    return render(request, 'school/students.html', {'title':'Students','page_obj':page(request,qs),'query':query,'branches':access.branches(request.user),'selected_branch':branch})


@access.roles(*access.MANAGERS)
def account_create(request, kind='staff'):
    is_student = kind == 'student'
    form = AccountForm(request.POST or None, actor=request.user, student=is_student)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                if is_student:
                    Classroom.objects.select_for_update().get(pk=form.cleaned_data['classroom'].pk)
                user = form.save(commit=False)
                user.set_password(form.cleaned_data['password'])
                user.must_change_password = True
                user.save()
                if is_student:
                    profile = Student.objects.create(user=user, admission_number=form.cleaned_data['admission_number'])
                    classroom = form.cleaned_data['classroom']
                    Enrollment.objects.create(student=profile, classroom=classroom, year=classroom.year, joined_on=form.cleaned_data['joined_on'])
                audit(request.user, user.branch, 'account.created', user.username, {'role':user.role})
            messages.success(request, f'{user.display_name} can now sign in. Their first login requires a password change.')
            return redirect('students' if is_student else 'users')
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, '; '.join(exc.messages) if isinstance(exc,ValidationError) else 'A matching account or enrollment already exists. Please review the details.')
    return render(request,'school/form.html',{'title':'Add student' if is_student else 'Create staff account','form':form,'description':'Accounts belong to one branch. Initial passwords must be shared privately.'})


@access.roles(*access.LEADERS)
def user_list(request):
    qs = User.objects.filter(branch__in=access.branches(request.user)).order_by('branch__name','role','first_name')
    if request.user.system_admin:
        qs = User.objects.all().order_by('role','first_name')
    return render(request,'school/users.html',{'title':'People & access','page_obj':page(request,qs)})


@require_POST
@access.roles(*access.MANAGERS)
@transaction.atomic
def toggle_user(request, pk):
    user = get_object_or_404(User.objects.select_for_update().filter(branch__in=access.branches(request.user)), pk=pk)
    if user.pk == request.user.pk or user.role == 'superadmin' or (not request.user.system_admin and user.role not in ('teacher','student')):
        raise PermissionDenied
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    audit(request.user,user.branch,'account.activated' if user.is_active else 'account.deactivated',user.username)
    messages.success(request,'Account access updated.')
    return redirect('users')


@access.roles(*access.MANAGERS)
def user_edit(request, pk):
    person = get_object_or_404(User.objects.filter(branch__in=access.branches(request.user)), pk=pk)
    if person.role == 'superadmin' or (not request.user.system_admin and person.role not in ('teacher', 'student')):
        raise PermissionDenied
    before = {key: getattr(person, key) for key in ('first_name','last_name','email')}
    form = AccountEditForm(request.POST or None, instance=person)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            audit(request.user,person.branch,'account.profile_updated',person.username,{'before':before,'after':form.cleaned_data})
        messages.success(request,'Account details updated. Role and branch are unchanged.')
        return redirect('users')
    return render(request,'school/form.html',{'title':f'Edit {person.display_name}','form':form,'description':'Update contact details. Role and branch reassignment require a supervised administrator migration.'})


SETUP_FORMS = {'organization':OrganizationForm,'branch':BranchForm,'year':YearForm,'classroom':ClassroomForm,'subject':SubjectForm,'assignment':AssignmentForm,'enrollment':EnrollmentForm}

@access.roles(*access.LEADERS)
def setup(request):
    return render(request,'school/setup.html',{'title':'Academic setup','branches':access.branches(request.user),'years':AcademicYear.objects.all(),'classrooms':access.classrooms(request.user).annotate(student_count=Count('enrollments')),'subjects':Subject.objects.filter(branch__in=access.branches(request.user)),'assignments':TeachingAssignment.objects.filter(classroom__in=access.classrooms(request.user)).select_related('teacher','classroom__branch','classroom__year','subject')})


@access.roles(*access.MANAGERS)
def setup_create(request, kind):
    if kind not in SETUP_FORMS or (kind in ('organization','branch','year') and not request.user.system_admin):
        raise PermissionDenied
    options = {} if kind in ('organization','branch','year') else {'actor':request.user}
    if kind == 'organization':
        options['instance'] = Organization.objects.first()
    form = SETUP_FORMS[kind](request.POST or None, **options)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                obj = form.save(commit=False)
                if kind == 'branch':
                    obj.organization, _ = Organization.objects.get_or_create(pk=1)
                if kind == 'enrollment':
                    Classroom.objects.select_for_update().get(pk=obj.classroom_id)
                obj.save()
                branch = getattr(obj,'branch',None) or getattr(getattr(obj,'classroom',None),'branch',None)
                audit(request.user,branch,f'setup.{kind}.saved',obj)
            messages.success(request,'Saved successfully.')
            return redirect('setup')
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'This record already exists.')
    return render(request,'school/form.html',{'title':f'Set up {kind}','form':form,'description':'Choose matching branch, classroom, and academic-year details.'})


@access.roles(*access.MANAGERS)
def setup_edit(request, kind, pk):
    editable = {
        'classroom': (access.classrooms(request.user), ClassroomForm, ('branch','year')),
        'subject': (Subject.objects.filter(branch__in=access.branches(request.user)), SubjectForm, ('branch',)),
        'assignment': (TeachingAssignment.objects.filter(classroom__in=access.classrooms(request.user)), AssignmentForm, ('classroom','subject')),
    }
    if kind not in editable:
        raise PermissionDenied
    qs, form_class, immutable = editable[kind]
    obj = get_object_or_404(qs,pk=pk)
    before = str(obj)
    form = form_class(request.POST or None,instance=obj,actor=request.user)
    for field in immutable:
        form.fields[field].disabled = True
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            branch = getattr(obj,'branch',None) or obj.classroom.branch
            audit(request.user,branch,f'setup.{kind}.updated',obj,{'before':before,'changed_fields':form.changed_data})
        messages.success(request,'Assignment details updated.')
        return redirect('setup')
    return render(request,'school/form.html',{'title':f'Edit {kind}','form':form,'description':'Branch and academic-year boundaries are preserved. Changes are recorded in the activity log.'})


@access.roles('superadmin','admin','principal','teacher')
def attendance(request):
    selection = RegisterSelection(request.GET or None, actor=request.user)
    context = {'title':'Daily attendance','selection':selection}
    if not selection.is_valid():
        return render(request,'school/attendance.html',context)
    classroom, day = selection.cleaned_data['classroom'], selection.cleaned_data['date']
    roster = list(access.roster(classroom,day))
    session = AttendanceSession.objects.filter(classroom=classroom,date=day).first()
    statuses = dict(session.records.values_list('enrollment_id','status')) if session else {}
    writable = access.can_attend(request.user,classroom)
    form = RegisterForm(request.POST if request.method == 'POST' else None, roster=roster, initial_statuses=statuses, version=session.version if session else 0)
    if request.method == 'POST':
        if not writable:
            raise PermissionDenied
        if form.is_valid():
            try:
                save_register(request.user,classroom,day,{e.pk:form.cleaned_data[f'status_{e.pk}'] for e in roster},form.cleaned_data['version'],form.cleaned_data['reason'])
                messages.success(request,'Daily attendance saved.')
                return redirect(request.get_full_path())
            except ValidationError as exc:
                form.add_error(None,'; '.join(exc.messages))
    if not writable:
        for field in form.fields.values():
            field.disabled = True
    context.update({'classroom':classroom,'day':day,'form':form,'can_write':writable,'session':session,'roster_count':len(roster)})
    return render(request,'school/attendance.html',context)


@login_required
def exam_list(request):
    qs = access.exams(request.user)
    status = request.GET.get('status','')
    if status in Exam.Status.values:
        qs = qs.filter(status=status)
    return render(request,'school/exams.html',{'title':'Exams & marks','page_obj':page(request,qs),'status':status,'can_create':request.user.role in ('superadmin','admin','teacher')})


@access.roles('superadmin','admin','teacher')
def exam_create(request):
    form = ExamForm(request.POST or None,actor=request.user)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            exam = form.save()
            audit(request.user,exam.classroom.branch,'exam.created',exam)
        messages.success(request,'Exam created. Enter marks, then submit for review.')
        return redirect('exam_detail',pk=exam.pk)
    return render(request,'school/form.html',{'title':'Create exam','form':form,'description':'Set the maximum and pass mark for this subject assessment.'})


@login_required
def exam_detail(request, pk):
    exam = get_object_or_404(access.exams(request.user),pk=pk)
    if request.user.role == 'student':
        return redirect('student_report',pk=request.user.student_profile.pk)
    roster = list(access.roster(exam.classroom,exam.date))
    marks = {m.enrollment_id:m for m in exam.marks.select_related('enrollment__student__user','exam')}
    writer, publisher = access.can_mark(request.user,exam), access.can_publish(request.user,exam)
    form = MarkSheetForm(request.POST if request.method == 'POST' else None, roster=roster,marks=marks,exam=exam)
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'save':
                if not writer:
                    raise PermissionDenied
                if form.is_valid():
                    entries = {e.pk:(form.cleaned_data[f'score_{e.pk}'],form.cleaned_data[f'absent_{e.pk}']) for e in roster}
                    save_marks(request.user,exam,entries,form.cleaned_data['version'])
                    messages.success(request,'Marks saved as a draft.')
                    return redirect('exam_detail',pk=pk)
            else:
                try:
                    version = int(request.POST.get('version','0'))
                except ValueError:
                    raise ValidationError('Invalid form version. Reload the page.')
                transition_exam(request.user,exam,action,version,request.POST.get('reason','')[:250])
                messages.success(request,{'submit':'Exam sent to the principal.','publish':'Results published to students.','reopen':'Exam reopened. Results are hidden from students until republished.'}[action])
                return redirect('exam_detail',pk=pk)
        except ValidationError as exc:
            form.add_error(None,'; '.join(exc.messages))
    writable = writer and exam.status == 'draft'
    if not writable:
        for field in form.fields.values():
            field.disabled = True
    return render(request,'school/exam_detail.html',{'title':exam.title,'exam':exam,'form':form,'can_write':writable,'can_submit':writer and exam.status == 'draft','can_publish':publisher,'summary':mark_summary(marks.values())})


@login_required
def student_report(request, pk):
    student = get_object_or_404(access.students(request.user),pk=pk)
    student_enrollments = access.enrollments(request.user).filter(student=student)
    year_id = request.GET.get('year')
    year = get_object_or_404(AcademicYear,pk=year_id) if year_id and year_id.isdigit() else AcademicYear.objects.filter(enrollment__in=student_enrollments).distinct().first()
    if year:
        student_enrollments = student_enrollments.filter(year=year)
    marks = list(Mark.objects.filter(enrollment__in=student_enrollments, exam__in=access.exams(request.user).filter(status='published')).select_related('exam__subject','exam__classroom'))
    rows = access.attendance_rows(request.user).filter(enrollment__in=student_enrollments).order_by('-session__date')
    return render(request,'school/student_report.html',{'title':'Student report','student':student,'enrollments':student_enrollments,'marks':marks,'summary':mark_summary(marks),'attendance_summary':attendance_summary(rows),'attendance_page':page(request,rows,15),'years':AcademicYear.objects.filter(enrollment__student=student).distinct(),'selected_year':year})


def safe_csv(value):
    text = str(value)
    return "'"+text if text.startswith(('=','+','-','@','\t','\r','\n')) else text


@access.roles('superadmin','admin','principal','teacher')
def reports(request):
    permitted = access.exams(request.user).filter(status='published')
    year_id = request.GET.get('year')
    if year_id and year_id.isdigit():
        permitted = permitted.filter(classroom__year_id=year_id)
    branch = selected_branch(request)
    if branch:
        permitted = permitted.filter(classroom__branch=branch)
    marks = list(Mark.objects.filter(exam__in=permitted).select_related('exam__subject','exam__classroom__branch','enrollment__student__user'))
    if request.GET.get('format') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="published-results.csv"'
        writer = csv.writer(response)
        writer.writerow(['Branch','Class','Student','Admission number','Subject','Exam','Score','Maximum','Result'])
        for m in marks:
            writer.writerow([safe_csv(x) for x in [m.exam.classroom.branch.name,f'{m.exam.classroom.grade}-{m.exam.classroom.section}',m.enrollment.student.user.display_name,m.enrollment.student.admission_number,m.exam.subject.name,m.exam.title,'Absent' if m.absent else m.score,m.exam.max_marks,'Pass' if m.passed else 'Below pass mark']])
        audit(request.user,branch or request.user.branch,'report.exported','Published results CSV',{'rows':len(marks)})
        return response
    groups = defaultdict(list)
    for m in marks:
        groups[(m.exam.classroom.branch.name,m.exam.subject.name)].append(m)
    subjects = [{'branch':k[0],'name':k[1],**mark_summary(v)} for k,v in sorted(groups.items())]
    return render(request,'school/reports.html',{'title':'Performance analysis','summary':mark_summary(marks),'subjects':subjects,'years':AcademicYear.objects.all(),'year_id':year_id or '', 'branches':access.branches(request.user),'selected_branch':branch})


@access.roles(*access.LEADERS)
def audit_log(request):
    qs = AuditEvent.objects.select_related('actor','branch')
    if not request.user.system_admin:
        qs = qs.filter(branch=request.user.branch)
    return render(request,'school/audit.html',{'title':'Activity log','page_obj':page(request,qs)})
