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
    return converted, counts


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
