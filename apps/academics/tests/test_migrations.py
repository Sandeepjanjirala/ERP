"""Phase 5 data migrations run for real: rows made the old way, migrated forwards and checked.

- Grade text to Grade records (academics 0002-0004, fees 0003-0005), and back again.
- Default terms for every year, and every exam placed in one (academics 0005-0006, exams 0003-0005).
"""

from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("academics", "0001_initial"), ("fees", "0002_order_capture_details")]
AFTER = [("academics", "0004_classroom_grade_link"), ("fees", "0005_feeplan_grade_link")]


class MigrationTestCase(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        # Leave the database fully migrated for the next test.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


class GradeMigrationTests(MigrationTestCase):
    def test_text_grades_become_ordered_grade_records(self):
        old = self.migrate(BEFORE)
        org = old.get_model("organization", "Organization").objects.create(name="Group")
        Branch = old.get_model("organization", "Branch")
        north = Branch.objects.create(organization=org, name="North", code="north", city="X")
        south = Branch.objects.create(organization=org, name="South", code="south", city="Y")
        year = old.get_model("academics", "AcademicYear").objects.create(
            name="2026-27", starts_on="2026-04-01", ends_on="2027-03-31"
        )
        Classroom = old.get_model("academics", "Classroom")
        rooms = {}
        for branch, grade, section in [
            (north, "Class 10", "A"),
            (north, "Class 9", "A"),
            (north, "Class 9", "B"),
            (north, "Nursery", "A"),
            (south, "Class 9", "A"),
        ]:
            room = Classroom.objects.create(branch=branch, year=year, grade=grade, section=section)
            rooms[room.pk] = (branch.pk, grade, section)
        FeePlan = old.get_model("fees", "FeePlan")
        plan = FeePlan.objects.create(branch=north, year=year, grade="Class 9")
        orphan = FeePlan.objects.create(branch=south, year=year, grade="Old grade")

        new = self.migrate(AFTER)
        Grade = new.get_model("academics", "Grade")
        orders = {(g.branch_id, g.name): g.order for g in Grade.objects.all()}
        self.assertEqual(
            orders,
            {
                (north.pk, "Class 9"): 9,
                (north.pk, "Class 10"): 10,
                (north.pk, "Nursery"): 11,  # no number: after the numbered grades
                (south.pk, "Class 9"): 9,
                (south.pk, "Old grade"): 10,  # only a fee plan had it: still kept
            },
        )
        # Every classroom keeps its branch, section and grade name, now as a record.
        for room in new.get_model("academics", "Classroom").objects.select_related("grade"):
            self.assertEqual((room.branch_id, room.grade.name, room.section), rooms[room.pk])
            self.assertEqual(room.grade.branch_id, room.branch_id)
        NewPlan = new.get_model("fees", "FeePlan")
        self.assertEqual(NewPlan.objects.get(pk=plan.pk).grade.name, "Class 9")
        self.assertEqual(NewPlan.objects.get(pk=plan.pk).grade.branch_id, north.pk)
        self.assertEqual(NewPlan.objects.get(pk=orphan.pk).grade.name, "Old grade")

        # And back: the text returns exactly as it was.
        old = self.migrate(BEFORE)
        texts = {
            room.pk: (room.branch_id, room.grade, room.section)
            for room in old.get_model("academics", "Classroom").objects.all()
        }
        self.assertEqual(texts, rooms)
        self.assertEqual(old.get_model("fees", "FeePlan").objects.get(pk=plan.pk).grade, "Class 9")


class TermMigrationTests(MigrationTestCase):
    def test_every_year_gets_terms_and_every_exam_its_term(self):
        old = self.migrate(
            [("academics", "0004_classroom_grade_link"), ("exams", "0002_alter_exam_options")]
        )
        org = old.get_model("organization", "Organization").objects.create(name="Group")
        branch = old.get_model("organization", "Branch").objects.create(
            organization=org, name="North", code="north", city="X"
        )
        year = old.get_model("academics", "AcademicYear").objects.create(
            name="2026-27", starts_on=date(2026, 4, 1), ends_on=date(2027, 3, 31)
        )
        empty_year = old.get_model("academics", "AcademicYear").objects.create(
            name="2027-28", starts_on=date(2027, 4, 1), ends_on=date(2028, 3, 31)
        )
        grade = old.get_model("academics", "Grade").objects.create(branch=branch, name="9", order=9)
        room = old.get_model("academics", "Classroom").objects.create(
            branch=branch, year=year, grade=grade, section="A"
        )
        subject = old.get_model("academics", "Subject").objects.create(
            branch=branch, name="Maths", code="maths"
        )
        Exam = old.get_model("exams", "Exam")
        days = [date(2026, 4, 1), date(2026, 9, 30), date(2026, 10, 1), date(2027, 3, 31)]
        exams = {
            Exam.objects.create(
                classroom=room, subject=subject, title=f"Test {n}", date=day,
                max_marks=10, pass_marks=4, status="published", version=3,
            ).pk: day
            for n, day in enumerate(days)
        }  # fmt: skip

        new = self.migrate([("exams", "0005_exam_term_required")])
        Term = new.get_model("academics", "Term")
        spans = [(t.name, t.starts_on, t.ends_on) for t in Term.objects.filter(year_id=year.pk)]
        self.assertEqual(
            spans,
            [
                ("Term 1", date(2026, 4, 1), date(2026, 9, 30)),
                ("Term 2", date(2026, 10, 1), date(2027, 3, 31)),
            ],
        )
        self.assertEqual(Term.objects.filter(year_id=empty_year.pk).count(), 2)
        for exam in new.get_model("exams", "Exam").objects.select_related("term"):
            expected = "Term 1" if exams[exam.pk] <= date(2026, 9, 30) else "Term 2"
            self.assertEqual(exam.term.name, expected)
            # Nothing else about the exam changed.
            self.assertEqual(
                (exam.date, exam.status, exam.version), (exams[exam.pk], "published", 3)
            )
