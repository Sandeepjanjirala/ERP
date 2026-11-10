# Step 3 of 3: the text column goes and the link takes its name, required from now on.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fees", "0004_fee_plan_grades_from_text")]

    operations = [
        migrations.RemoveField(model_name="feeplan", name="grade"),
        migrations.RenameField(model_name="feeplan", old_name="grade_ref", new_name="grade"),
        migrations.AlterField(
            model_name="feeplan",
            name="grade",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="fee_plans", to="academics.grade"),
        ),
        migrations.AddConstraint(
            model_name="feeplan",
            constraint=models.UniqueConstraint(fields=("branch", "year", "grade"), name="one_fee_plan_per_grade"),
        ),
    ]
