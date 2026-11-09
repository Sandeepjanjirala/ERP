# Step 1 of 3 moving FeePlan.grade from text to the Grade table (see academics 0002-0004).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("fees", "0002_order_capture_details"),
        ("academics", "0003_classroom_grades_from_text"),
    ]

    operations = [
        # Removed here, not in step 3, so a backwards migration restores it after the names.
        migrations.RemoveConstraint(model_name="feeplan", name="one_fee_plan_per_grade"),
        migrations.AddField(
            model_name="feeplan",
            name="grade_ref",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="fee_plans", to="academics.grade"),
        ),
        migrations.AlterField(
            model_name="feeplan",
            name="grade",
            field=models.CharField(default="", max_length=25),
        ),
    ]
