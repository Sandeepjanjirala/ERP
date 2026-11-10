# Step 1 of 3 linking each exam to its term: a nullable link.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exams", "0002_alter_exam_options"),
        ("academics", "0006_default_terms"),
    ]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="term",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="exams", to="academics.term"),
        ),
    ]
