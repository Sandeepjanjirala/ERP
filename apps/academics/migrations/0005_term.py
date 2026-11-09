import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("academics", "0004_classroom_grade_link")]

    operations = [
        migrations.CreateModel(
            name="Term",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=30)),
                ("starts_on", models.DateField()),
                ("ends_on", models.DateField()),
                ("year", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="terms", to="academics.academicyear")),
            ],
            options={
                "ordering": ["starts_on", "pk"],
                "constraints": [
                    models.UniqueConstraint(fields=("year", "name"), name="term_name_per_year"),
                    models.CheckConstraint(condition=models.Q(("ends_on__gte", models.F("starts_on"))), name="term_dates_ordered"),
                ],
            },
        ),
    ]
