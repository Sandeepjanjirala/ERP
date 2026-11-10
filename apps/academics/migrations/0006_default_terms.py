# Every existing year gets Term 1 and Term 2, splitting it in half, so every existing exam (which
# already falls inside its year) has a term and creating exams keeps working. Schools adjust the
# dates in Academic setup.

from datetime import timedelta

from django.db import migrations


def halves(year):
    middle = year.starts_on + timedelta(days=(year.ends_on - year.starts_on).days // 2)
    return [
        ("Term 1", year.starts_on, middle),
        ("Term 2", middle + timedelta(days=1), year.ends_on),
    ]


def forwards(apps, schema_editor):
    AcademicYear = apps.get_model("academics", "AcademicYear")
    Term = apps.get_model("academics", "Term")
    for year in AcademicYear.objects.all():
        if not Term.objects.filter(year=year).exists():
            for name, starts_on, ends_on in halves(year):
                Term.objects.create(year=year, name=name, starts_on=starts_on, ends_on=ends_on)


def backwards(apps, schema_editor):
    apps.get_model("academics", "Term").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("academics", "0005_term")]

    operations = [migrations.RunPython(forwards, backwards)]
