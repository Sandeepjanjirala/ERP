"""Convert a `dumpdata school` export from the single-app version into the domain-app layout.

Phase 1 split the old `school` app into domain apps and restarted the migration history, so
tables were renamed (school_user -> accounts_user, ...). The fields did not change, so the old
data can be moved with Django's own fixtures:

    old code:  python manage.py dumpdata school --indent 2 -o legacy.json
    new code:  python manage.py convert_legacy_data legacy.json upgraded.json
               python manage.py migrate
               python manage.py loaddata upgraded.json

Primary keys, password hashes and relations are kept. See docs/UPGRADING.md.
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

# Old model label -> new model label. None means the rows are deliberately not carried over.
LABELS = {
    "school.organization": "organization.organization",
    "school.branch": "organization.branch",
    "school.user": "accounts.user",
    "school.loginattempt": None,  # temporary sign-in throttle counters
    "school.auditevent": "audit.auditevent",
    "school.academicyear": "academics.academicyear",
    "school.classroom": "academics.classroom",
    "school.subject": "academics.subject",
    "school.teachingassignment": "academics.teachingassignment",
    "school.student": "students.student",
    "school.enrollment": "students.enrollment",
    "school.attendancesession": "attendance.attendancesession",
    "school.attendance": "attendance.attendance",
    "school.exam": "exams.exam",
    "school.mark": "exams.mark",
}


def convert(records):
    """Return the records relabelled for the new apps, plus a count of rows per new label."""
    converted, counts = [], {}
    for record in records:
        label = record.get("model", "")
        if label not in LABELS:
            raise CommandError(f"Unexpected model {label!r}: export only the `school` app.")
        new_label = LABELS[label]
        if new_label is None:
            continue
        fields = dict(record["fields"])
        if new_label == "accounts.user" and (
            fields.get("groups") or fields.get("user_permissions")
        ):
            # EduNexa uses roles, not Django groups; permission ids differ between databases.
            raise CommandError(
                f"User {fields.get('username')!r} has Django groups or permissions; "
                "remove them before exporting."
            )
        converted.append({**record, "model": new_label, "fields": fields})
        counts[new_label] = counts.get(new_label, 0) + 1
    grades, terms = link_grades(converted), link_terms(converted)
    # New records go first, before the classrooms and exams that point at them.
    converted[:0] = grades + terms
    for label, added in (("academics.grade", grades), ("academics.term", terms)):
        if added:
            counts[label] = len(added)
    return converted, counts


def grade_orders(names):
    """Position of each grade name: the number in it ("Class 10" -> 10) when that number is free,
    then names without a usable number after the highest, alphabetically. The same rule as
    migration academics 0003, which converts databases made before Phase 5."""
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


def link_grades(records):
    """Since Phase 5 a classroom's grade is a Grade record, not text. Create one Grade per
    (branch, grade name), ordered as migration academics 0003 orders them, and point each
    classroom at it. Returns the new Grade records."""
    classrooms = [r for r in records if r["model"] == "academics.classroom"]
    names = {}
    for record in classrooms:
        names.setdefault(record["fields"]["branch"], set()).add(record["fields"]["grade"])
    grades, ids = [], {}
    for branch in sorted(names, key=str):
        for name, order in sorted(grade_orders(names[branch]).items(), key=lambda pair: pair[1]):
            ids[branch, name] = len(grades) + 1
            grades.append(
                {
                    "model": "academics.grade",
                    "pk": ids[branch, name],
                    "fields": {"branch": branch, "name": name, "order": order},
                }
            )
    for record in classrooms:
        fields = record["fields"]
        fields["grade"] = ids[fields["branch"], fields["grade"]]
    return grades


def link_terms(records):
    """Since Phase 5 every exam belongs to a term. Give each year Term 1 and Term 2, splitting it
    in half as migration academics 0006 does, and put each exam in the term of its date.
    Returns the new Term records."""
    years = {r["pk"]: r["fields"] for r in records if r["model"] == "academics.academicyear"}
    terms, spans = [], {}
    for year_pk, year in years.items():
        starts_on, ends_on = (
            date.fromisoformat(year["starts_on"]),
            date.fromisoformat(year["ends_on"]),
        )
        middle = starts_on + timedelta(days=(ends_on - starts_on).days // 2)
        for name, first, last in (
            ("Term 1", starts_on, middle),
            ("Term 2", middle + timedelta(days=1), ends_on),
        ):
            pk = len(terms) + 1
            terms.append(
                {
                    "model": "academics.term",
                    "pk": pk,
                    "fields": {
                        "year": year_pk,
                        "name": name,
                        "starts_on": first.isoformat(),
                        "ends_on": last.isoformat(),
                    },
                }
            )
            spans.setdefault(year_pk, []).append((first, last, pk))
    classroom_years = {
        r["pk"]: r["fields"]["year"] for r in records if r["model"] == "academics.classroom"
    }
    for record in records:
        if record["model"] != "exams.exam":
            continue
        fields = record["fields"]
        day = date.fromisoformat(fields["date"])
        year_spans = spans.get(classroom_years.get(fields["classroom"]), [])
        fields["term"] = next((pk for first, last, pk in year_spans if first <= day <= last), None)
        if fields["term"] is None:
            raise CommandError(f"Exam {record['pk']} ({day}) is outside its academic year.")
    return terms


class Command(BaseCommand):
    help = "Relabel a `dumpdata school` export from the single-app version for the domain apps."

    def add_arguments(self, parser):
        parser.add_argument("source", type=Path, help="JSON from `dumpdata school` (old code)")
        parser.add_argument("target", type=Path, help="Where to write the converted fixture")

    def handle(self, *args, source, target, **options):
        try:
            records = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read {source}: {exc}") from exc
        converted, counts = convert(records)
        target.write_text(json.dumps(converted, indent=2, ensure_ascii=False), encoding="utf-8")
        for label, count in sorted(counts.items()):
            self.stdout.write(f"  {label}: {count}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(converted)} records to {target}. Next: loaddata {target}"
            )
        )
