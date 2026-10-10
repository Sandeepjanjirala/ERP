import secrets
from datetime import date, timedelta
from decimal import Decimal
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from school.models import Organization, Branch, User, AcademicYear, Classroom, Subject, TeachingAssignment, Student, Enrollment, Exam
from school.services import save_register, save_marks, transition_exam

class Command(BaseCommand):
    help = 'Seed an empty development database with synthetic school data.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Demo seeding is disabled outside development mode.')
        if User.objects.exists() or Branch.objects.exists():
            raise CommandError('Demo seeding requires an empty database. Existing records were not changed.')
        password = secrets.token_urlsafe(18)
        org = Organization.objects.create(name='Vidya Schools · Demo')
        root = User.objects.create_superuser('superadmin','superadmin@example.invalid',password,first_name='Sandeep')
        today = timezone.localdate()
        start = today.year if today.month >= 4 else today.year - 1
        year = AcademicYear.objects.create(name=f'{start}–{start+1}',starts_on=date(start,4,1),ends_on=date(start+1,3,31))
        names = [('Aarav','Sharma'),('Ananya','Rao'),('Ishaan','Reddy'),('Meera','Nair'),('Rohan','Kumar'),('Saanvi','Patel')]
        for index,(code,city) in enumerate([('madhapur','Hyderabad'),('benz-circle','Vijayawada')]):
            branch = Branch.objects.create(organization=org,name='Madhapur' if index == 0 else 'Benz Circle',code=code,city=city)
            staff = {}
            for role,first,last in [('admin','Kiran','Rao'),('principal','Lakshmi','Devi'),('teacher','Priya','Sharma'),('mentor','Ravi','Kumar')]:
                staff[role] = User.objects.create_user(f'{role}.{code}',f'{role}.{code}@example.invalid',password,first_name=first,last_name=last,role='teacher' if role=='mentor' else role,branch=branch,must_change_password=False)
            classroom = Classroom.objects.create(branch=branch,year=year,grade='Class 9',section='A',homeroom_teacher=staff['teacher'])
            roster = []
            for n,(first,last) in enumerate(names,1):
                username = f'student{n}.{code}'
                user = User.objects.create_user(username,f'{username}@example.invalid',password,first_name=first,last_name=last,role='student',branch=branch,must_change_password=False)
                student = Student.objects.create(user=user,admission_number=f'VD-{index+1}{n:03}')
                roster.append(Enrollment.objects.create(student=student,classroom=classroom,year=year,joined_on=year.starts_on))
            for sidx,(name,teacher) in enumerate([('Mathematics',staff['teacher']),('Science',staff['mentor'])]):
                subject = Subject.objects.create(branch=branch,name=name,code=name.lower())
                TeachingAssignment.objects.create(teacher=teacher,classroom=classroom,subject=subject)
                exam = Exam.objects.create(classroom=classroom,subject=subject,title='Term 1 assessment',date=max(year.starts_on,today-timedelta(days=3-sidx)),max_marks=100,pass_marks=35)
                save_marks(teacher,exam,{e.pk:(Decimal([87,92,74,83,68,95][n]-index*3-sidx*2),False) for n,e in enumerate(roster)},exam.version)
                exam.refresh_from_db()
                transition_exam(teacher,exam,'submit',exam.version)
                if not sidx:
                    exam.refresh_from_db()
                    transition_exam(staff['principal'],exam,'publish',exam.version)
            for offset in range(5):
                day = today-timedelta(days=offset)
                if day < year.starts_on:
                    continue
                save_register(staff['teacher'],classroom,day,{e.pk:('A' if (n+offset+index)%11==0 else 'L' if n==4 and offset==2 else 'P') for n,e in enumerate(roster)},0)
        self.stdout.write(self.style.SUCCESS('Synthetic demo data created. Do not use these accounts for real student records.'))
        self.stdout.write('Demo password for all accounts: '+password)
        self.stdout.write('Logins: superadmin, admin.madhapur, principal.madhapur, teacher.madhapur, mentor.madhapur, student1.madhapur')
        self.stdout.write('Second branch: admin.benz-circle, principal.benz-circle, teacher.benz-circle, student1.benz-circle')
        self.stdout.write('The password is generated for this installation; it is not stored in project files.')
