# Step 2 of 3: each exam goes into the term of its classroom's year that its date falls in.
# Nothing else about the exam changes. An exam no term covers stops the migration with its id
# rather than being guessed (academics 0006 gives every year terms covering all of it).

from django.db import migrations


def forwards(apps, schema_editor):
    Exam = apps.get_model("exams", "Exam")
    Term = apps.get_model("academics", "Term")
    for exam in Exam.objects.select_related("classroom"):
        term = Term.objects.filter(
            year_id=exam.classroom.year_id, starts_on__lte=exam.date, ends_on__gte=exam.date
        ).first()
        if term is None:
            raise RuntimeError(
                f"Exam {exam.pk} ({exam.date}) is outside every term of its year. "
                "Add a term covering it, then migrate again."
            )
        Exam.objects.filter(pk=exam.pk).update(term=term)


class Migration(migrations.Migration):
    dependencies = [("exams", "0003_exam_term")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
