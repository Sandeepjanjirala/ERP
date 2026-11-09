"""The move from grade text to Grade records (academics 0002-0004, fees 0003-0005), run for real:
rows made the old way, migrated forwards, checked, and migrated back."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("academics", "0001_initial"), ("fees", "0002_order_capture_details")]
AFTER = [("academics", "0004_classroom_grade_link"), ("fees", "0005_feeplan_grade_link")]


class GradeMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        # Leave the database fully migrated for the next test.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

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
