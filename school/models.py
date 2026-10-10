from decimal import Decimal
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, F
from django.db.models.functions import Lower


class ValidatedModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Organization(ValidatedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=120, default='Vidya Schools')
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name='single_organization')]
    def __str__(self):
        return self.name


class Branch(ValidatedModel):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=20, unique=True)
    city = models.CharField(max_length=80)
    class Meta:
        ordering = ['name']
    def __str__(self):
        return f'{self.name} · {self.city}'


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.update(role='superadmin', branch=None, must_change_password=False)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER = 'superadmin', 'Super admin'
        ADMIN = 'admin', 'Branch admin'
        PRINCIPAL = 'principal', 'Principal'
        TEACHER = 'teacher', 'Teacher'
        STUDENT = 'student', 'Student'
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, related_name='users')
    must_change_password = models.BooleanField(default=True)
    objects = UserManager()
    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('username'), name='username_case_insensitive'),
            models.UniqueConstraint(Lower('email'), name='email_case_insensitive'),
            models.CheckConstraint(condition=(Q(role='superadmin', branch__isnull=True, is_superuser=True, is_staff=True) | (Q(role__in=['admin','principal','teacher','student'], branch__isnull=False, is_superuser=False, is_staff=False))), name='role_branch_privileges'),
        ]
    def clean(self):
        super().clean()
        self.username = self.username.strip().lower()
        self.email = self.email.strip().lower()
        if self.role == self.Role.SUPER:
            if self.branch_id or not self.is_superuser or not self.is_staff:
                raise ValidationError('Super admins require system privileges and no branch assignment.')
        elif not self.branch_id or self.is_superuser or self.is_staff:
            raise ValidationError('Branch users require a branch and cannot hold system privileges.')
    def save(self, *args, **kwargs):
        self.full_clean(exclude=['password'])
        return super().save(*args, **kwargs)
    @property
    def display_name(self):
        return self.get_full_name() or self.username
    @property
    def system_admin(self):
        return self.is_active and self.is_superuser and self.role == self.Role.SUPER


class AcademicYear(ValidatedModel):
    name = models.CharField(max_length=30, unique=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    class Meta:
        ordering = ['-starts_on']
        constraints = [models.CheckConstraint(condition=Q(ends_on__gt=F('starts_on')), name='year_dates_ordered')]
    def __str__(self):
        return self.name


class Classroom(ValidatedModel):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT)
    grade = models.CharField(max_length=25)
    section = models.CharField(max_length=10)
    homeroom_teacher = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='homerooms')
    class Meta:
        ordering = ['branch__name', 'grade', 'section']
        constraints = [models.UniqueConstraint(fields=['branch', 'year', 'grade', 'section'], name='unique_classroom')]
    def clean(self):
        if self.homeroom_teacher_id and (self.homeroom_teacher.role != 'teacher' or self.homeroom_teacher.branch_id != self.branch_id):
            raise ValidationError({'homeroom_teacher': 'Choose a teacher from this branch.'})
    def __str__(self):
        return f'{self.grade}-{self.section} · {self.branch.name} · {self.year.name}'


class Subject(ValidatedModel):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    name = models.CharField(max_length=60)
    code = models.SlugField(max_length=20)
    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['branch', 'code'], name='subject_branch_code')]
    def __str__(self):
        return f'{self.name} · {self.branch.name}'


class TeachingAssignment(ValidatedModel):
    teacher = models.ForeignKey(User, on_delete=models.PROTECT, related_name='teaching')
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name='teaching')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['classroom', 'subject'], name='one_subject_teacher_per_class')]
    def clean(self):
        if self.teacher_id and self.classroom_id and (self.teacher.role != 'teacher' or self.teacher.branch_id != self.classroom.branch_id):
            raise ValidationError('The teacher must belong to the classroom branch.')
        if self.subject_id and self.classroom_id and self.subject.branch_id != self.classroom.branch_id:
            raise ValidationError('The subject must belong to the classroom branch.')
    def __str__(self):
        return f'{self.teacher.display_name} — {self.subject.name} — {self.classroom}'


class Student(ValidatedModel):
    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name='student_profile')
    admission_number = models.CharField(max_length=30, unique=True)
    def clean(self):
        if self.user_id and self.user.role != 'student':
            raise ValidationError('A student profile requires a student account.')
    def __str__(self):
        return f'{self.user.display_name} ({self.admission_number})'


class Enrollment(ValidatedModel):
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='enrollments')
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name='enrollments')
    year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT)
    joined_on = models.DateField()
    left_on = models.DateField(null=True, blank=True)
    class Meta:
        ordering = ['student__user__first_name', 'student__admission_number']
        constraints = [models.UniqueConstraint(fields=['student', 'year'], name='one_enrollment_each_year'), models.CheckConstraint(condition=Q(left_on__isnull=True) | Q(left_on__gte=F('joined_on')), name='enrollment_dates_ordered')]
    def clean(self):
        if self.classroom_id:
            if self.year_id != self.classroom.year_id:
                raise ValidationError('Academic year must match the classroom.')
            if self.student_id and self.student.user.branch_id != self.classroom.branch_id:
                raise ValidationError('Student and classroom must belong to the same branch.')
            if self.joined_on and not self.classroom.year.starts_on <= self.joined_on <= self.classroom.year.ends_on:
                raise ValidationError('Joining date must fall within the academic year.')
            if self.left_on and self.left_on > self.classroom.year.ends_on:
                raise ValidationError('Leaving date must fall within the academic year.')
            if not self.pk and self.joined_on:
                if AttendanceSession.objects.filter(classroom_id=self.classroom_id, date__gte=self.joined_on).exists() or Exam.objects.filter(classroom_id=self.classroom_id, date__gte=self.joined_on).exclude(status='draft').exists():
                    raise ValidationError('This joining date would change a completed register or locked exam roster. Use a later joining date; historical roster corrections require a supervised data migration.')
    def __str__(self):
        return f'{self.student} · {self.classroom}'


class AttendanceSession(ValidatedModel):
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT)
    date = models.DateField()
    version = models.PositiveIntegerField(default=1)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['classroom', 'date'], name='one_daily_register')]
    def clean(self):
        if self.classroom_id and self.date and not self.classroom.year.starts_on <= self.date <= self.classroom.year.ends_on:
            raise ValidationError('Attendance date must fall within the academic year.')


class Attendance(ValidatedModel):
    class Status(models.TextChoices):
        PRESENT = 'P', 'Present'
        ABSENT = 'A', 'Absent'
        LATE = 'L', 'Late'
        EXCUSED = 'E', 'Excused'
    session = models.ForeignKey(AttendanceSession, on_delete=models.PROTECT, related_name='records')
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name='attendance')
    status = models.CharField(max_length=1, choices=Status.choices)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['session', 'enrollment'], name='one_attendance_student_day'), models.CheckConstraint(condition=Q(status__in=['P','A','L','E']), name='valid_attendance_status')]
    def clean(self):
        if self.session_id and self.enrollment_id and self.session.classroom_id != self.enrollment.classroom_id:
            raise ValidationError('Attendance must use the matching classroom enrollment.')


class Exam(ValidatedModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SUBMITTED = 'submitted', 'Awaiting approval'
        PUBLISHED = 'published', 'Published'
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name='exams')
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT)
    title = models.CharField(max_length=80)
    date = models.DateField()
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal('1'))])
    pass_marks = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=1)
    published_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-date', 'title']
        constraints = [models.CheckConstraint(condition=Q(max_marks__gte=1, pass_marks__gte=0, pass_marks__lte=F('max_marks')), name='valid_exam_marks'), models.UniqueConstraint(fields=['classroom','subject','title','date'], name='unique_exam')]
    def clean(self):
        if self.classroom_id and self.subject_id and self.classroom.branch_id != self.subject.branch_id:
            raise ValidationError('Exam subject and classroom must belong to the same branch.')
        if self.classroom_id and self.date and not self.classroom.year.starts_on <= self.date <= self.classroom.year.ends_on:
            raise ValidationError('Exam date must fall within the academic year.')
    def __str__(self):
        return f'{self.title} · {self.subject.name} · {self.classroom}'


class Mark(ValidatedModel):
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name='marks')
    enrollment = models.ForeignKey(Enrollment, on_delete=models.PROTECT, related_name='marks')
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    absent = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['exam','enrollment'], name='one_mark_per_exam'), models.CheckConstraint(condition=(Q(absent=True, score__isnull=True) | Q(absent=False, score__gte=0, score__isnull=False)), name='score_or_absent')]
    def clean(self):
        if self.exam_id and self.enrollment_id and self.exam.classroom_id != self.enrollment.classroom_id:
            raise ValidationError('The student must be enrolled in the exam classroom.')
        if self.absent and self.score is not None:
            raise ValidationError('Absent students cannot also have a score.')
        if not self.absent and self.score is None:
            raise ValidationError('Enter a score or mark the student absent.')
        if self.score is not None and self.exam_id and self.score > self.exam.max_marks:
            raise ValidationError('Score cannot exceed the exam maximum.')
    @property
    def percentage(self):
        return round((self.score or Decimal(0)) / self.exam.max_marks * 100, 1)
    @property
    def passed(self):
        return not self.absent and self.score >= self.exam.pass_marks


class AuditEvent(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=180)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField()
