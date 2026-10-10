from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import *
from .forms import AccountForm, AssignmentForm, ClassroomForm
from .services import *
from . import permissions as access

PASSWORD = 'Testing-only-strong-password-892!'

class PortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Test Organisation')
        cls.a = Branch.objects.create(organization=cls.org,name='North',code='north',city='Hyderabad')
        cls.b = Branch.objects.create(organization=cls.org,name='South',code='south',city='Vijayawada')
        cls.today = timezone.localdate()
        cls.year = AcademicYear.objects.create(name='Test year', starts_on=cls.today-timedelta(days=90), ends_on=cls.today+timedelta(days=90))
        cls.root = User.objects.create_superuser('root','root@example.com',PASSWORD)
        def user(name,role,branch):
            return User.objects.create_user(name,name+'@example.com',PASSWORD,role=role,branch=branch,first_name=name,must_change_password=False)
        cls.admin = user('admin','admin',cls.a)
        cls.principal = user('principal','principal',cls.a)
        cls.teacher = user('teacher','teacher',cls.a)
        cls.other_teacher = user('otherteacher','teacher',cls.a)
        cls.foreign_teacher = user('foreignteacher','teacher',cls.b)
        cls.c = Classroom.objects.create(branch=cls.a,year=cls.year,grade='9',section='A',homeroom_teacher=cls.teacher)
        cls.foreign_class = Classroom.objects.create(branch=cls.b,year=cls.year,grade='9',section='B',homeroom_teacher=cls.foreign_teacher)
        cls.math = Subject.objects.create(branch=cls.a,name='Mathematics',code='math')
        cls.science = Subject.objects.create(branch=cls.a,name='Science',code='science')
        cls.foreign_subject = Subject.objects.create(branch=cls.b,name='South Science',code='science')
        TeachingAssignment.objects.create(teacher=cls.teacher,classroom=cls.c,subject=cls.math)
        TeachingAssignment.objects.create(teacher=cls.other_teacher,classroom=cls.c,subject=cls.science)
        TeachingAssignment.objects.create(teacher=cls.foreign_teacher,classroom=cls.foreign_class,subject=cls.foreign_subject)
        def enroll(name,branch,classroom):
            u = user(name,'student',branch)
            s = Student.objects.create(user=u,admission_number=name.upper())
            return Enrollment.objects.create(student=s,classroom=classroom,year=cls.year,joined_on=cls.year.starts_on)
        cls.e1 = enroll('alice',cls.a,cls.c)
        cls.e2 = enroll('bob',cls.a,cls.c)
        cls.foreign_enrollment = enroll('charlie',cls.b,cls.foreign_class)
        cls.exam = Exam.objects.create(classroom=cls.c,subject=cls.math,title='Midterm',date=cls.today,max_marks=100,pass_marks=35)
        cls.science_exam = Exam.objects.create(classroom=cls.c,subject=cls.science,title='Science test',date=cls.today,max_marks=50,pass_marks=20)
        cls.foreign_exam = Exam.objects.create(classroom=cls.foreign_class,subject=cls.foreign_subject,title='Private south exam',date=cls.today,max_marks=100,pass_marks=35)

    def sign_in(self,user):
        self.client.force_login(user)

    def fill(self,exam=None):
        exam = exam or self.exam
        exam.refresh_from_db()
        save_marks(self.teacher,exam,{self.e1.pk:(Decimal('80'),False),self.e2.pk:(Decimal('30'),False)},exam.version)
        exam.refresh_from_db()
        return exam

    def publish(self):
        exam = self.fill()
        transition_exam(self.teacher,exam,'submit',exam.version)
        exam.refresh_from_db()
        transition_exam(self.principal,exam,'publish',exam.version)
        exam.refresh_from_db()
        return exam

    def test_login_required_for_all_portal_pages(self):
        for url in ['/','/students/','/attendance/','/exams/','/reports/','/setup/','/users/','/activity/']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code,302)

    def test_wrong_password_and_rate_limit(self):
        for _ in range(8):
            self.assertEqual(self.client.post(reverse('login'),{'username':'teacher','password':'wrong'}).status_code,200)
        self.assertEqual(self.client.post(reverse('login'),{'username':'teacher','password':PASSWORD}).status_code,429)

    def test_normalized_login_and_password_hash(self):
        response = self.client.post(reverse('login'),{'username':'TEACHER','password':PASSWORD})
        self.assertEqual(response.status_code,302)
        self.assertNotEqual(self.teacher.password,PASSWORD)
        self.assertTrue(self.teacher.check_password(PASSWORD))

    def test_csrf_blocks_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teacher)
        self.assertEqual(client.post(reverse('exam_detail',args=[self.exam.pk]),{'action':'save'}).status_code,403)

    def test_get_cannot_logout_or_change_account(self):
        self.sign_in(self.admin)
        self.assertEqual(self.client.get(reverse('logout')).status_code,405)
        self.assertEqual(self.client.get(reverse('toggle_user',args=[self.teacher.pk])).status_code,405)

    def test_first_password_change_is_mandatory(self):
        self.teacher.must_change_password=True
        self.teacher.save()
        self.sign_in(self.teacher)
        self.assertRedirects(self.client.get('/'),reverse('password_change'),fetch_redirect_response=False)

    def test_inactive_account_cannot_login(self):
        self.teacher.is_active=False
        self.teacher.save()
        self.client.post(reverse('login'),{'username':'teacher','password':PASSWORD})
        self.assertNotIn('_auth_user_id',self.client.session)

    def test_deactivation_revokes_existing_session(self):
        self.sign_in(self.teacher)
        self.teacher.is_active=False
        self.teacher.save()
        self.assertEqual(self.client.get('/').status_code,302)

    def test_branch_student_query_isolation(self):
        self.sign_in(self.admin)
        response=self.client.get(reverse('students'))
        self.assertContains(response,'alice')
        self.assertNotContains(response,'charlie')
        self.assertEqual(self.client.get(reverse('student_report',args=[self.foreign_enrollment.student_id])).status_code,404)

    def test_student_cannot_browse_peers_or_staff(self):
        self.sign_in(self.e1.student.user)
        for url in ['/students/','/users/','/setup/','/attendance/','/reports/','/activity/']:
            self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.get(reverse('student_report',args=[self.e2.student_id])).status_code,404)

    def test_teacher_cannot_view_foreign_exam_or_roster(self):
        self.sign_in(self.teacher)
        self.assertEqual(self.client.get(reverse('exam_detail',args=[self.foreign_exam.pk])).status_code,404)
        self.assertNotIn(self.foreign_class,list(access.classrooms(self.teacher)))

    def test_admin_cannot_create_or_promote_admin_principal(self):
        data={'username':'malicious','first_name':'Mallory','email':'malicious@example.com','password':PASSWORD,'role':'principal','branch':self.a.pk}
        form=AccountForm(data,actor=self.admin)
        self.assertFalse(form.is_valid())
        self.assertIn('role',form.errors)
        self.sign_in(self.admin)
        self.assertEqual(self.client.post(reverse('toggle_user',args=[self.principal.pk])).status_code,403)

    def test_admin_cannot_create_cross_branch_user(self):
        form=AccountForm({'username':'someone','first_name':'Someone','email':'someone@example.com','password':PASSWORD,'role':'teacher','branch':self.b.pk},actor=self.admin)
        self.assertFalse(form.is_valid())
        self.assertIn('branch',form.errors)

    def test_create_teacher_uses_hashed_password_and_forces_change(self):
        self.sign_in(self.admin)
        response=self.client.post(reverse('user_create'),{'username':'newteacher','first_name':'New','last_name':'Teacher','email':'newteacher@example.com','password':PASSWORD,'role':'teacher','branch':self.a.pk})
        self.assertEqual(response.status_code,302)
        user=User.objects.get(username='newteacher')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(user.must_change_password)
        self.assertFalse(user.is_superuser)

    def test_roles_require_matching_branch_and_privileges(self):
        user=User(username='broken',email='broken@example.com',role='teacher',branch=self.a,is_superuser=True)
        with self.assertRaises(ValidationError): user.save()

    def test_branch_assignment_validation(self):
        with self.assertRaises(ValidationError):
            TeachingAssignment.objects.create(teacher=self.foreign_teacher,classroom=self.c,subject=self.math)
        with self.assertRaises(ValidationError):
            Classroom.objects.create(branch=self.a,year=self.year,grade='8',section='A',homeroom_teacher=self.foreign_teacher)

    def test_teacher_subject_permissions_on_save(self):
        with self.assertRaises(PermissionDenied):
            save_marks(self.teacher,self.science_exam,{self.e1.pk:(Decimal('30'),False),self.e2.pk:(Decimal('40'),False)},1)

    def test_teacher_cannot_record_daily_attendance_without_homeroom(self):
        with self.assertRaises(PermissionDenied):
            save_register(self.other_teacher,self.c,self.today,{self.e1.pk:'P',self.e2.pk:'A'},0)

    def test_attendance_complete_roster_required(self):
        with self.assertRaises(ValidationError):save_register(self.teacher,self.c,self.today,{self.e1.pk:'P'},0)
        self.assertEqual(AttendanceSession.objects.count(),0)

    def test_attendance_rejects_foreign_enrollment(self):
        with self.assertRaises(ValidationError):save_register(self.teacher,self.c,self.today,{self.e1.pk:'P',self.e2.pk:'P',self.foreign_enrollment.pk:'P'},0)

    def test_attendance_rejects_future_date(self):
        with self.assertRaises(ValidationError):save_register(self.teacher,self.c,self.today+timedelta(days=1),{self.e1.pk:'P',self.e2.pk:'P'},0)

    def test_attendance_correction_audit_and_single_register(self):
        session=save_register(self.teacher,self.c,self.today,{self.e1.pk:'P',self.e2.pk:'A'},0)
        with self.assertRaises(ValidationError):save_register(self.teacher,self.c,self.today,{self.e1.pk:'P',self.e2.pk:'P'},session.version)
        save_register(self.teacher,self.c,self.today,{self.e1.pk:'P',self.e2.pk:'P'},session.version,'Late arrival confirmed')
        self.assertEqual(AttendanceSession.objects.count(),1)
        self.assertEqual(Attendance.objects.count(),2)
        self.assertEqual(AuditEvent.objects.filter(action='attendance.saved').count(),2)

    def test_stale_attendance_write_is_rejected(self):
        save_register(self.teacher,self.c,self.today,{self.e1.pk:'P',self.e2.pk:'A'},0)
        with self.assertRaises(Conflict):save_register(self.teacher,self.c,self.today,{self.e1.pk:'A',self.e2.pk:'A'},0,'retry')

    def test_excused_excluded_late_included(self):
        save_register(self.teacher,self.c,self.today,{self.e1.pk:'L',self.e2.pk:'E'},0)
        summary=attendance_summary(Attendance.objects.all())
        self.assertEqual(summary['rate'],100)
        self.assertEqual(summary['total'],2)

    def test_invalid_marks_rollback_whole_save(self):
        with self.assertRaises(ValidationError):save_marks(self.teacher,self.exam,{self.e1.pk:(Decimal('80'),False),self.e2.pk:(Decimal('101'),False)},1)
        self.assertEqual(Mark.objects.count(),0)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.version,1)

    def test_negative_marks_and_absent_with_score_rejected(self):
        for entry in [(Decimal('-1'),False),(Decimal('0'),True)]:
            with self.subTest(entry=entry):
                with self.assertRaises(ValidationError):save_marks(self.teacher,self.exam,{self.e1.pk:entry,self.e2.pk:(Decimal('10'),False)},1)

    def test_stale_mark_save_is_rejected(self):
        self.fill()
        with self.assertRaises(Conflict):save_marks(self.teacher,self.exam,{self.e1.pk:(Decimal('20'),False),self.e2.pk:(Decimal('20'),False)},1)

    def test_cannot_submit_incomplete_marks(self):
        with self.assertRaises(ValidationError):transition_exam(self.teacher,self.exam,'submit',1)

    def test_teacher_cannot_publish(self):
        exam=self.fill()
        transition_exam(self.teacher,exam,'submit',exam.version)
        exam.refresh_from_db()
        with self.assertRaises(PermissionDenied):transition_exam(self.teacher,exam,'publish',exam.version)

    def test_submitted_marks_locked(self):
        exam=self.fill()
        transition_exam(self.teacher,exam,'submit',exam.version)
        exam.refresh_from_db()
        with self.assertRaises(ValidationError):save_marks(self.teacher,exam,{self.e1.pk:(Decimal('90'),False),self.e2.pk:(Decimal('90'),False)},exam.version)

    def test_student_cannot_see_draft_data(self):
        self.fill()
        self.sign_in(self.e1.student.user)
        response=self.client.get(reverse('student_report',args=[self.e1.student_id]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['summary']['count'],0)
        self.assertEqual(self.client.get(reverse('exam_detail',args=[self.exam.pk])).status_code,404)

    def test_published_report_contains_only_self(self):
        self.publish()
        self.sign_in(self.e1.student.user)
        response=self.client.get(reverse('student_report',args=[self.e1.student_id]))
        self.assertEqual(response.context['summary']['percentage'],Decimal('80.0'))
        self.assertNotContains(response,'bob')
        self.assertEqual(len(response.context['marks']),1)

    def test_reopen_hides_results_until_republished(self):
        exam=self.publish()
        transition_exam(self.principal,exam,'reopen',exam.version,'Correction requested')
        self.assertFalse(access.exams(self.e1.student.user).exists())

    def test_csv_export_scoped_and_audited(self):
        self.publish()
        Mark.objects.create(exam=self.foreign_exam,enrollment=self.foreign_enrollment,score=99)
        self.foreign_exam.status='published'
        self.foreign_exam.save()
        self.sign_in(self.admin)
        response=self.client.get(reverse('reports')+'?format=csv')
        self.assertEqual(response.status_code,200)
        self.assertIn('alice',response.content.decode())
        self.assertNotIn('charlie',response.content.decode())
        self.assertTrue(AuditEvent.objects.filter(action='report.exported').exists())

    def test_csv_formula_neutralization(self):
        from .views import safe_csv
        self.assertEqual(safe_csv('=HYPERLINK("x")'),"'=HYPERLINK(\"x\")")

    def test_teacher_report_subject_scope(self):
        self.publish()
        self.assertNotIn(self.exam.pk, access.exams(self.other_teacher).values_list('pk',flat=True))

    def test_retroactive_enrollment_after_recording_rejected(self):
        save_register(self.teacher,self.c,self.today,{self.e1.pk:'P',self.e2.pk:'P'},0)
        user=User.objects.create_user('latejoin','latejoin@example.com',PASSWORD,role='student',branch=self.a)
        student=Student.objects.create(user=user,admission_number='LATE')
        with self.assertRaises(ValidationError):Enrollment.objects.create(student=student,classroom=self.c,year=self.year,joined_on=self.today)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_password_reset_sends_link_without_disclosing_unknown_account(self):
        known=self.client.post(reverse('password_reset'),{'email':self.teacher.email})
        unknown=self.client.post(reverse('password_reset'),{'email':'unknown@example.com'})
        self.assertEqual(known.status_code,302)
        self.assertEqual(known.url,unknown.url)
        self.assertEqual(len(mail.outbox),1)
        self.assertIn('/accounts/password/reset/',mail.outbox[0].body)

    def test_security_headers_and_no_store(self):
        self.sign_in(self.admin)
        response=self.client.get('/')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertIn("frame-ancestors 'none'",response['Content-Security-Policy'])

    def test_pages_render_for_each_role(self):
        paths=['/','/students/','/exams/','/reports/','/attendance/','/setup/','/users/','/activity/']
        for actor in [self.root,self.admin,self.principal,self.teacher,self.e1.student.user]:
            self.sign_in(actor)
            for path in paths:
                with self.subTest(actor=actor.role,path=path):
                    response=self.client.get(path)
                    self.assertIn(response.status_code,[200,302,403])
        self.sign_in(self.teacher)
        for path in [reverse('exam_detail',args=[self.exam.pk]),reverse('attendance')+f'?classroom={self.c.pk}&date={self.today.isoformat()}',reverse('student_report',args=[self.e1.student_id])]:
            self.assertEqual(self.client.get(path).status_code,200)

    def test_bad_transition_renders_validation_error(self):
        self.sign_in(self.teacher)
        response=self.client.post(reverse('exam_detail',args=[self.exam.pk]),{'action':'submit','version':1})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'every enrolled student')

    def test_attendance_http_post_records_all_students(self):
        self.sign_in(self.teacher)
        response=self.client.post(reverse('attendance')+f'?classroom={self.c.pk}&date={self.today.isoformat()}',{'version':0,f'status_{self.e1.pk}':'P',f'status_{self.e2.pk}':'A'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Attendance.objects.count(),2)

    def test_branch_query_tampering_denied(self):
        self.sign_in(self.admin)
        self.assertEqual(self.client.get('/reports/?branch='+str(self.b.pk)).status_code,404)

    def test_audit_scope(self):
        audit(self.foreign_teacher,self.b,'private.change','South private target')
        self.sign_in(self.admin)
        self.assertNotContains(self.client.get('/activity/'),'South private target')

    def test_no_data_is_no_percentage(self):
        self.assertIsNone(attendance_summary(Attendance.objects.none())['rate'])
        self.assertIsNone(mark_summary([])['percentage'])

    def test_absent_zero_is_not_a_pass_even_when_pass_threshold_zero(self):
        self.exam.pass_marks=0
        self.exam.save()
        mark=Mark.objects.create(exam=self.exam,enrollment=self.e1,absent=True)
        self.assertFalse(mark.passed)
        self.assertEqual(mark.percentage,0)

    def test_single_org_enforced(self):
        with self.assertRaises(ValidationError):Organization.objects.create(id=2,name='Other')

    def test_no_duplicate_enrollment_same_year(self):
        with self.assertRaises(ValidationError):Enrollment.objects.create(student=self.e1.student,classroom=self.c,year=self.year,joined_on=self.today)

    def test_user_edit_ignores_role_and_branch_escalation(self):
        self.sign_in(self.admin)
        response=self.client.post(reverse('user_edit',args=[self.teacher.pk]),{'first_name':'Updated','last_name':'Teacher','email':self.teacher.email,'role':'superadmin','branch':self.b.pk,'is_superuser':'true'})
        self.assertEqual(response.status_code,302)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.first_name,'Updated')
        self.assertEqual(self.teacher.role,'teacher')
        self.assertEqual(self.teacher.branch_id,self.a.pk)
        self.assertFalse(self.teacher.is_superuser)

    def test_user_edit_forbidden_for_principal_and_foreign_users(self):
        self.sign_in(self.admin)
        self.assertEqual(self.client.get(reverse('user_edit',args=[self.principal.pk])).status_code,403)
        self.assertEqual(self.client.get(reverse('user_edit',args=[self.foreign_teacher.pk])).status_code,404)

    def test_assignment_edit_preserves_class_and_subject(self):
        self.sign_in(self.admin)
        assignment=TeachingAssignment.objects.get(teacher=self.teacher,classroom=self.c,subject=self.math)
        response=self.client.post(reverse('setup_edit',args=['assignment',assignment.pk]),{'teacher':self.other_teacher.pk,'classroom':self.foreign_class.pk,'subject':self.foreign_subject.pk})
        self.assertEqual(response.status_code,302)
        assignment.refresh_from_db()
        self.assertEqual(assignment.teacher_id,self.other_teacher.pk)
        self.assertEqual(assignment.classroom_id,self.c.pk)
        self.assertEqual(assignment.subject_id,self.math.pk)
        self.assertFalse(access.can_mark(self.teacher,self.exam))
        self.assertTrue(access.can_mark(self.other_teacher,self.exam))

    def test_unicode_login_rate_limit_uses_normalized_username(self):
        from .views import throttle
        for _ in range(8):throttle('portal-login','teacher')
        allowed,_=throttle('portal-login','ｔｅａｃｈｅｒ')
        self.assertFalse(allowed)

    def test_setup_form_pages_render(self):
        self.sign_in(self.root)
        for kind in ('organization','branch','year','classroom','subject','assignment','enrollment'):
            with self.subTest(kind=kind):
                self.assertEqual(self.client.get(reverse('setup_create',args=[kind])).status_code,200)

    def test_password_change_completes_forced_change(self):
        self.teacher.must_change_password=True
        self.teacher.save()
        self.sign_in(self.teacher)
        new_password='A-new-testing-passphrase-94302!'
        response=self.client.post(reverse('password_change'),{'old_password':PASSWORD,'new_password1':new_password,'new_password2':new_password})
        self.assertEqual(response.status_code,302)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.must_change_password)
        self.assertTrue(self.teacher.check_password(new_password))
        self.assertEqual(self.client.get('/').status_code,200)

    def test_duplicate_username_different_case_rejected(self):
        with self.assertRaises(ValidationError):User.objects.create_user('TEACHER','different@example.com',PASSWORD,role='teacher',branch=self.a)

class SeedTests(TestCase):
    @override_settings(DEBUG=True)
    def test_seed_generates_synthetic_data_and_wont_overwrite(self):
        out=StringIO()
        call_command('seed_demo',stdout=out)
        self.assertEqual(Branch.objects.count(),2)
        self.assertEqual(Student.objects.count(),12)
        self.assertEqual(Exam.objects.filter(status='published').count(),2)
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):call_command('seed_demo',stdout=out)

    @override_settings(DEBUG=False)
    def test_demo_disabled_in_production(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):call_command('seed_demo',stdout=StringIO())


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks; run the provided PostgreSQL CI job or Docker test command.')
class ConcurrentWritesTests(TransactionTestCase):
    def setUp(self):
        PortalTests.setUpTestData.__func__(type(self))

    def race(self, operation):
        barrier=Barrier(2)
        def worker(index):
            close_old_connections()
            try:
                actor=User.objects.get(pk=self.teacher.pk)
                barrier.wait(timeout=10)
                try:
                    operation(actor,index)
                    return 'saved'
                except Conflict:
                    return 'conflict'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker,index) for index in range(2)]
            results=[f.result(timeout=30) for f in futures]
        self.assertEqual(sorted(results),['conflict','saved'])

    def test_concurrent_register_creation_cannot_duplicate_or_overwrite(self):
        self.race(lambda actor,index:save_register(actor,self.c,self.today,{self.e1.pk:'P' if index else 'A',self.e2.pk:'P'},0))
        self.assertEqual(AttendanceSession.objects.count(),1)
        self.assertEqual(Attendance.objects.count(),2)
        self.assertEqual(AuditEvent.objects.filter(action='attendance.saved').count(),1)

    def test_concurrent_mark_updates_reject_stale_writer(self):
        self.race(lambda actor,index:save_marks(actor,self.exam,{self.e1.pk:(Decimal(70+index),False),self.e2.pk:(Decimal(70+index),False)},1))
        self.assertEqual(Mark.objects.count(),2)
        self.assertEqual(len(set(Mark.objects.values_list('score',flat=True))),1)
        self.assertEqual(AuditEvent.objects.filter(action='marks.saved').count(),1)
