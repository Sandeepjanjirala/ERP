from functools import wraps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from .models import Branch, Classroom, Subject, User, Student, Enrollment, Exam, Attendance, TeachingAssignment

MANAGERS = ('superadmin', 'admin')
LEADERS = ('superadmin', 'admin', 'principal')

def roles(*allowed):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.role not in allowed:
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorator

def branches(user):
    return Branch.objects.all() if user.system_admin else Branch.objects.filter(pk=user.branch_id)

def classrooms(user):
    qs = Classroom.objects.filter(branch__in=branches(user)).select_related('branch','year','homeroom_teacher')
    if user.role == 'teacher':
        qs = qs.filter(Q(homeroom_teacher=user) | Q(teaching__teacher=user)).distinct()
    elif user.role == 'student':
        qs = qs.filter(enrollments__student__user=user).distinct()
    return qs

def students(user):
    qs = Student.objects.filter(user__branch__in=branches(user)).select_related('user','user__branch')
    if user.role == 'student':
        return qs.filter(user=user)
    if user.role == 'teacher':
        return qs.filter(enrollments__classroom__in=classrooms(user)).distinct()
    return qs

def enrollments(user):
    qs = Enrollment.objects.filter(classroom__in=classrooms(user)).select_related('student__user','classroom__branch','classroom__year')
    if user.role == 'student':
        qs = qs.filter(student__user=user)
    return qs

def exams(user):
    qs = Exam.objects.filter(classroom__in=classrooms(user)).select_related('classroom__branch','classroom__year','subject','published_by')
    if user.role == 'student':
        return qs.filter(status='published', marks__enrollment__student__user=user).distinct()
    if user.role == 'teacher':
        assigned = TeachingAssignment.objects.filter(teacher=user).values('classroom_id','subject_id')
        condition = Q(classroom__homeroom_teacher=user)
        for row in assigned:
            condition |= Q(classroom_id=row['classroom_id'], subject_id=row['subject_id'])
        return qs.filter(condition).distinct()
    return qs

def can_mark(user, exam):
    return user.system_admin or (user.role == 'teacher' and user.branch_id == exam.classroom.branch_id and TeachingAssignment.objects.filter(teacher=user, classroom=exam.classroom, subject=exam.subject).exists())

def can_attend(user, classroom):
    return user.system_admin or (user.branch_id == classroom.branch_id and (user.role == 'admin' or (user.role == 'teacher' and classroom.homeroom_teacher_id == user.pk)))

def can_publish(user, exam):
    return user.system_admin or (user.role == 'principal' and user.branch_id == exam.classroom.branch_id)

def roster(classroom, day):
    return classroom.enrollments.filter(joined_on__lte=day).filter(Q(left_on__isnull=True) | Q(left_on__gte=day)).select_related('student__user')

def attendance_rows(user):
    qs = Attendance.objects.filter(enrollment__in=enrollments(user)).select_related('session','enrollment__student__user')
    return qs
