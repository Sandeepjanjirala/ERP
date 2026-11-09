# Step 3 of 3: every exam has a term now; from here on it is required.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("exams", "0004_exams_into_terms")]

    operations = [
        migrations.AlterField(
            model_name="exam",
            name="term",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="exams", to="academics.term"),
        ),
    ]
