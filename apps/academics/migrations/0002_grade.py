# Step 1 of 3 moving Classroom.grade from text to the Grade table: add the table and a nullable
# link. Each step is its own migration, so on PostgreSQL the data copy (step 2) commits before the
# columns change (step 3).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0001_initial"),
        ("organization", "0002_branch_receipt_prefix"),
    ]

    operations = [
        migrations.CreateModel(
            name="Grade",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=25)),
                ("order", models.PositiveSmallIntegerField(help_text="Position in the school, lowest first: Class 1 is 1, Class 10 is 10.")),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="grades", to="organization.branch")),
            ],
            options={
                "ordering": ["order", "pk"],
                "constraints": [
                    models.UniqueConstraint(fields=("branch", "name"), name="grade_name_per_branch"),
                    models.UniqueConstraint(fields=("branch", "order"), name="grade_order_per_branch"),
                ],
            },
        ),
        # The old uniqueness rule names the text column. It goes now, not in step 3, so that when
        # migrating backwards it returns only after step 2 has put the names back.
        migrations.RemoveConstraint(model_name="classroom", name="unique_classroom"),
        migrations.AddField(
            model_name="classroom",
            name="grade_ref",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="classrooms", to="academics.grade"),
        ),
        # A default lets step 3 be reversed: the text column comes back empty, then step 2's
        # reverse fills it from the grade names.
        migrations.AlterField(
            model_name="classroom",
            name="grade",
            field=models.CharField(default="", max_length=25),
        ),
    ]
