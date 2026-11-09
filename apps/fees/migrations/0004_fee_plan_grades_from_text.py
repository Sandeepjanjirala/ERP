# Step 2 of 3: point each fee plan at the Grade with the same branch and name (created from the
# classrooms in academics 0003). A plan whose grade text matches no classroom gets its own Grade
# after the branch's last one, so no plan is lost.

from django.db import migrations
from django.db.models import Max


def forwards(apps, schema_editor):
    FeePlan = apps.get_model("fees", "FeePlan")
    Grade = apps.get_model("academics", "Grade")
    for plan in FeePlan.objects.all():
        grade = Grade.objects.filter(branch_id=plan.branch_id, name=plan.grade).first()
        if grade is None:
            last = Grade.objects.filter(branch_id=plan.branch_id).aggregate(n=Max("order"))["n"]
            grade = Grade.objects.create(
                branch_id=plan.branch_id, name=plan.grade, order=(last or 0) + 1
            )
        plan.grade_ref = grade
        plan.save(update_fields=["grade_ref"])


def backwards(apps, schema_editor):
    FeePlan = apps.get_model("fees", "FeePlan")
    for plan in FeePlan.objects.select_related("grade_ref"):
        plan.grade = plan.grade_ref.name
        plan.save(update_fields=["grade"])


class Migration(migrations.Migration):
    dependencies = [("fees", "0003_feeplan_grade_ref")]

    operations = [migrations.RunPython(forwards, backwards)]
