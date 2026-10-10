from django import forms
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils import timezone
from . import permissions as access
from .models import User, Branch, Organization, AcademicYear, Classroom, Subject, TeachingAssignment, Student, Enrollment, Exam, Attendance

class LoginForm(AuthenticationForm):
    def clean_username(self):
        return self.cleaned_data['username'].strip().lower()

class DateInput(forms.DateInput):
    input_type = 'date'

class AccountForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, help_text='At least 12 characters. Share privately; the user must change this on first login.')
    class Meta:
        model = User
        fields = ['username','first_name','last_name','email','role','branch']
    def __init__(self, *args, actor, student=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor, self.student = actor, student
        self.fields['branch'].queryset = access.branches(actor)
        self.fields['branch'].required = True
        self.fields['first_name'].required = True
        self.fields['role'].choices = [('student','Student')] if student else ([('admin','Branch admin'), ('principal','Principal'), ('teacher','Teacher')] if actor.system_admin else [('teacher','Teacher')])
        if not actor.system_admin:
            self.fields['branch'].initial = actor.branch_id
        if student:
            self.fields['admission_number'] = forms.CharField(max_length=30)
            self.fields['classroom'] = forms.ModelChoiceField(queryset=access.classrooms(actor))
            self.fields['joined_on'] = forms.DateField(widget=DateInput, initial=timezone.localdate)
    def clean_username(self):
        value = self.cleaned_data['username'].strip().lower()
        if User.objects.filter(username__iexact=value).exists():
            raise ValidationError('This username is already in use.')
        return value
    def clean_email(self):
        value = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise ValidationError('This email is already in use.')
        return value
    def clean(self):
        data = super().clean()
        temp = User(username=data.get('username',''), first_name=data.get('first_name',''), last_name=data.get('last_name',''), email=data.get('email',''))
        if data.get('password'):
            validate_password(data['password'], user=temp)
        if self.student and data.get('classroom'):
            c = data['classroom']
            if data.get('branch') and c.branch_id != data['branch'].pk:
                self.add_error('classroom', 'Choose a classroom in the selected branch.')
            if data.get('joined_on') and not c.year.starts_on <= data['joined_on'] <= c.year.ends_on:
                self.add_error('joined_on', 'Joining date must fall within the classroom academic year.')
            if Student.objects.filter(admission_number=data.get('admission_number')).exists():
                self.add_error('admission_number', 'This admission number is already in use.')
        return data

class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name']


class AccountEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
    def clean_email(self):
        value = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise ValidationError('This email is already in use.')
        return value

class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['name','code','city']

class YearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ['name','starts_on','ends_on']
        widgets = {'starts_on': DateInput(), 'ends_on': DateInput()}

class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ['branch','year','grade','section','homeroom_teacher']
    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = access.branches(actor)
        self.fields['homeroom_teacher'].queryset = User.objects.filter(branch__in=access.branches(actor), role='teacher', is_active=True)
        if not actor.system_admin:
            self.fields['branch'].initial = actor.branch_id

class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['branch','name','code']
    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = access.branches(actor)
        if not actor.system_admin:
            self.fields['branch'].initial = actor.branch_id

class AssignmentForm(forms.ModelForm):
    class Meta:
        model = TeachingAssignment
        fields = ['teacher','classroom','subject']
    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teacher'].queryset = User.objects.filter(branch__in=access.branches(actor), role='teacher', is_active=True)
        self.fields['classroom'].queryset = access.classrooms(actor)
        self.fields['subject'].queryset = Subject.objects.filter(branch__in=access.branches(actor))

class EnrollmentForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = ['student','classroom','joined_on','left_on']
        widgets = {'joined_on': DateInput(), 'left_on': DateInput()}
    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['student'].queryset = access.students(actor)
        self.fields['classroom'].queryset = access.classrooms(actor)
    def clean(self):
        data = super().clean()
        if data.get('classroom'):
            self.instance.year = data['classroom'].year
            if data.get('student') and Enrollment.objects.filter(student=data['student'], year=self.instance.year).exclude(pk=self.instance.pk).exists():
                self.add_error('student','This student already has an enrollment for that year.')
        return data

class ExamForm(forms.ModelForm):
    class Meta:
        model = Exam
        fields = ['classroom','subject','title','date','max_marks','pass_marks']
        widgets = {'date': DateInput()}
    def __init__(self, *args, actor, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        self.fields['classroom'].queryset = access.classrooms(actor)
        subjects = Subject.objects.filter(branch__in=access.branches(actor))
        if actor.role == 'teacher':
            subjects = subjects.filter(pk__in=TeachingAssignment.objects.filter(teacher=actor).values('subject_id'))
        self.fields['subject'].queryset = subjects
    def clean(self):
        data = super().clean()
        if self.actor.role == 'teacher' and data.get('classroom') and data.get('subject') and not TeachingAssignment.objects.filter(teacher=self.actor, classroom=data['classroom'], subject=data['subject']).exists():
            raise ValidationError('You can create exams only for your assigned class and subject.')
        return data

class RegisterSelection(forms.Form):
    classroom = forms.ModelChoiceField(queryset=Classroom.objects.none())
    date = forms.DateField(widget=DateInput(), initial=timezone.localdate)
    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['classroom'].queryset = access.classrooms(actor)
    def clean(self):
        d = super().clean()
        if d.get('date'):
            if d['date'] > timezone.localdate():
                self.add_error('date','Future attendance is not allowed.')
            elif d.get('classroom') and not d['classroom'].year.starts_on <= d['date'] <= d['classroom'].year.ends_on:
                self.add_error('date','Select a date within the classroom academic year.')
        return d

class RegisterForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    reason = forms.CharField(required=False, max_length=250, help_text='Required when correcting an existing register.')
    def __init__(self, *args, roster, initial_statuses, version, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['version'].initial = version
        self.rows = []
        for enrollment in roster:
            key = f'status_{enrollment.pk}'
            self.fields[key] = forms.ChoiceField(choices=[('','Choose status'), *Attendance.Status.choices], initial=initial_statuses.get(enrollment.pk))
            self.rows.append((enrollment, self[key]))

class MarkSheetForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    def __init__(self, *args, roster, marks, exam, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['version'].initial = exam.version
        self.rows = []
        for enrollment in roster:
            mark = marks.get(enrollment.pk)
            score_key, absent_key = f'score_{enrollment.pk}', f'absent_{enrollment.pk}'
            self.fields[score_key] = forms.DecimalField(required=False, min_value=0, max_value=exam.max_marks, decimal_places=2, max_digits=6, initial=mark.score if mark else None)
            self.fields[absent_key] = forms.BooleanField(required=False, initial=mark.absent if mark else False)
            self.rows.append((enrollment, self[score_key], self[absent_key]))
    def clean(self):
        d = super().clean()
        for enrollment, score, absent in self.rows:
            if d.get(absent.name) and d.get(score.name) is not None:
                self.add_error(score.name,'Use either a score or absent, not both.')
        return d
