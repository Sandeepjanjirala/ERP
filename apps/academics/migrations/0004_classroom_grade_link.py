# Step 3 of 3: the text column goes and the link takes its name, required from now on.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("academics", "0003_classroom_grades_from_text")]

    operations = [
        migrations.RemoveField(model_name="classroom", name="grade"),
        migrations.RenameField(model_name="classroom", old_name="grade_ref", new_name="grade"),
        migrations.AlterField(
            model_name="classroom",
            name="grade",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="classrooms", to="academics.grade"),
        ),
        migrations.AddConstraint(
            model_name="classroom",
            constraint=models.UniqueConstraint(fields=("branch", "year", "grade", "section"), name="unique_classroom"),
        ),
    ]
