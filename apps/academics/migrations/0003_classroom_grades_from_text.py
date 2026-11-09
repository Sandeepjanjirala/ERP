# Step 2 of 3: one Grade per distinct (branch, grade text) found on classrooms, and each classroom
# linked to it. Names are kept exactly as typed, so nothing a person sees changes.

import re

from django.db import migrations


def grade_orders(names):
    """Position of each grade name: the number in it ("Class 10" -> 10) when that number is free,
    then names without a usable number after the highest, alphabetically."""
    orders, used = {}, set()
    numbered = sorted(
        (int(match.group()), name)
        for name in names
        if (match := re.search(r"\d+", name)) and int(match.group()) > 0
    )
    for number, name in numbered:
        if number not in used and number <= 32767:
            orders[name] = number
            used.add(number)
    following = max(used, default=0)
    for name in sorted(names):
        if name not in orders:
            following += 1
            orders[name] = following
    return orders


def forwards(apps, schema_editor):
    Classroom = apps.get_model("academics", "Classroom")
    Grade = apps.get_model("academics", "Grade")
    pairs = Classroom.objects.values_list("branch_id", "grade").distinct()
    by_branch = {}
    for branch_id, name in pairs:
        by_branch.setdefault(branch_id, set()).add(name)
    for branch_id, names in by_branch.items():
        for name, order in grade_orders(names).items():
            grade = Grade.objects.create(branch_id=branch_id, name=name, order=order)
            Classroom.objects.filter(branch_id=branch_id, grade=name).update(grade_ref=grade)


def backwards(apps, schema_editor):
    Classroom = apps.get_model("academics", "Classroom")
    Grade = apps.get_model("academics", "Grade")
    for classroom in Classroom.objects.select_related("grade_ref"):
        classroom.grade = classroom.grade_ref.name
        classroom.save(update_fields=["grade"])
    Classroom.objects.update(grade_ref=None)
    Grade.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("academics", "0002_grade")]

    operations = [migrations.RunPython(forwards, backwards)]
