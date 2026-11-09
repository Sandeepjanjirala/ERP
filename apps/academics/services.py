from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.services import audit
from apps.organization.models import Organization

from .models import AcademicYear, Term
from .policies import GROUP_LEVEL, can_manage_setup


def setup_branch(kind, record):
    """The branch a setup record belongs to; None for group-level records."""
    if kind in GROUP_LEVEL:
        return None
    return getattr(record, "branch", None) or record.classroom.branch


def default_terms(year):
    """Term 1 and Term 2, splitting the year in half. Schools adjust them in Academic setup."""
    middle = year.starts_on + timedelta(days=(year.ends_on - year.starts_on).days // 2)
    Term.objects.create(year=year, name="Term 1", starts_on=year.starts_on, ends_on=middle)
    Term.objects.create(
        year=year, name="Term 2", starts_on=middle + timedelta(days=1), ends_on=year.ends_on
    )


@transaction.atomic
def save_setup_record(actor, kind, record):
    """Save an organisation, branch, academic year, grade, classroom, subject or teacher
    assignment. A new academic year gets two default terms."""
    branch = setup_branch(kind, record)
    if not can_manage_setup(actor, kind, branch):
        raise PermissionDenied
    if kind == "branch":
        record.organization, _ = Organization.objects.get_or_create(pk=1)
    new_year = kind == "year" and record.pk is None
    record.save()
    if new_year:
        default_terms(record)
    audit(actor, branch, f"setup.{kind}.saved", record)
    return record


@transaction.atomic
def update_setup_record(actor, kind, record, before, changed_fields):
    """Save edits to a grade, classroom, subject or assignment, recording what changed."""
    branch = setup_branch(kind, record)
    if not can_manage_setup(actor, kind, branch):
        raise PermissionDenied
    record.save()
    audit(
        actor,
        branch,
        f"setup.{kind}.updated",
        record,
        {"before": before, "changed_fields": changed_fields},
    )
    return record


# Terms -------------------------------------------------------------------------------------
#
# A year's terms are saved together, as one set: moving the boundary between Term 1 and Term 2
# changes both, and one at a time would always pass through a gap or an overlap.


def _exams_of(year):
    # exams sits above academics, so the Exam model is reached through Term's reverse relation.
    exam_model = Term._meta.get_field("exams").related_model
    return exam_model.objects.filter(classroom__year=year)


def _check_terms(year, rows):
    """Every rule for a whole set of terms, with messages naming the term at fault."""
    if not rows:
        raise ValidationError("A year needs at least one term.")
    names = [row["name"].strip() for row in rows]
    if not all(names):
        raise ValidationError("Every term needs a name.")
    if len({name.casefold() for name in names}) != len(names):
        raise ValidationError("Each term needs its own name.")
    for row in rows:
        if row["ends_on"] < row["starts_on"]:
            raise ValidationError(f"{row['name']} ends before it starts.")
        if not year.starts_on <= row["starts_on"] <= row["ends_on"] <= year.ends_on:
            raise ValidationError(
                f"{row['name']} must fall within {year.name} "
                f"({year.starts_on:%d %b %Y} to {year.ends_on:%d %b %Y})."
            )
    for earlier, later in zip(rows, rows[1:], strict=False):
        if later["starts_on"] <= earlier["ends_on"]:
            raise ValidationError(f"{earlier['name']} and {later['name']} overlap.")


@transaction.atomic
def save_terms(actor, year, rows):
    """Replace a year's terms with `rows` (dicts: name, starts_on, ends_on, and id for a term that
    already exists; a term left out is removed).

    Each exam then moves to the term its date falls in. If any exam would be outside every term,
    nothing is saved. Super admins only; audited with the terms before and after.
    """
    if not can_manage_setup(actor, "term"):
        raise PermissionDenied
    year = AcademicYear.objects.select_for_update().get(pk=year.pk)  # one save per year at a time
    rows = sorted(rows, key=lambda row: row["starts_on"])
    _check_terms(year, rows)
    existing = {term.pk: term for term in year.terms.all()}
    kept = {row["id"] for row in rows if row.get("id")}
    if kept - existing.keys():
        raise ValidationError("A term in the list doesn't belong to this year.")
    before = [f"{t.name}: {t.starts_on} to {t.ends_on}" for t in existing.values()]

    # Park every existing term's name first, so names can swap or be reused by a new term
    # without a clash (terms being removed keep exams until they move, so they go last).
    # Updates and inserts skip the per-term checks: the whole set was checked above.
    for pk in existing:
        Term.objects.filter(pk=pk).update(name=f"#{pk}")
    terms = []
    for row in rows:
        fields = {
            "name": row["name"].strip(),
            "starts_on": row["starts_on"],
            "ends_on": row["ends_on"],
        }
        if row.get("id"):
            Term.objects.filter(pk=row["id"]).update(**fields)
            terms.append(Term(pk=row["id"], year=year, **fields))
        else:
            terms.extend(Term.objects.bulk_create([Term(year=year, **fields)]))

    moved = 0
    for exam in _exams_of(year).only("pk", "title", "date", "term_id"):
        term = next((t for t in terms if t.starts_on <= exam.date <= t.ends_on), None)
        if term is None:
            raise ValidationError(
                f"“{exam.title}” on {exam.date:%d %b %Y} would be outside every term. "
                "Keep a term covering that day."
            )
        if term.pk != exam.term_id:
            _exams_of(year).filter(pk=exam.pk).update(term_id=term.pk)
            moved += 1
    Term.objects.filter(pk__in=existing.keys() - kept).delete()  # no exams left in them
    audit(
        actor,
        None,
        "setup.terms.saved",
        year,
        {
            "before": before,
            "after": [f"{t.name}: {t.starts_on} to {t.ends_on}" for t in terms],
            "exams_moved": moved,
        },
    )
    return terms
