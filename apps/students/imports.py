"""Reading a students CSV: size, encoding, columns and row count. Checking each row's content is
the services' job (check_import)."""

import csv
import io

from django.core.exceptions import ValidationError

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500
REQUIRED = ["admission_number", "first_name", "last_name", "email", "classroom", "joined_on"]
OPTIONAL = [
    "phone",
    "guardian_first_name",
    "guardian_last_name",
    "guardian_email",
    "guardian_phone",
    "relationship",
]
COLUMNS = REQUIRED + OPTIONAL
EXAMPLE = {
    "admission_number": "GF-2001",
    "first_name": "Aarav",
    "last_name": "Sharma",
    "email": "aarav.sharma@example.com",
    "classroom": "Class 9-A",
    "joined_on": "2026-06-01",
    "phone": "",
    "guardian_first_name": "Radha",
    "guardian_last_name": "Sharma",
    "guardian_email": "radha.sharma@example.com",
    "guardian_phone": "+91 98480 00000",
    "relationship": "mother",
}


def read_csv(upload):
    """The rows of an uploaded CSV as dicts of stripped text, keyed by the known column names.

    Refused as a whole (ValidationError) if the file is over 2 MB, isn't UTF-8, lacks a required
    column, has an unknown one (a misspelt column would otherwise be silently ignored), or has
    no rows or more than 500.
    """
    if upload.size > MAX_BYTES:
        raise ValidationError("The file is larger than 2 MB. Split it into smaller files.")
    try:
        text = upload.read().decode("utf-8-sig")  # -sig: Excel's "CSV UTF-8" starts with a BOM
    except UnicodeDecodeError:
        raise ValidationError(
            'The file isn\'t UTF-8 text. In your spreadsheet, save it as "CSV UTF-8".'
        ) from None
    reader = csv.DictReader(io.StringIO(text))
    headers = [(name or "").strip().lower().replace(" ", "_") for name in reader.fieldnames or []]
    missing = [name for name in REQUIRED if name not in headers]
    unknown = [name for name in headers if name and name not in COLUMNS]
    if missing:
        raise ValidationError(f"Missing columns: {', '.join(missing)}.")
    if unknown:
        raise ValidationError(
            f"Unknown columns: {', '.join(unknown)}. The columns are: {', '.join(COLUMNS)}."
        )
    reader.fieldnames = headers
    rows = []
    for raw in reader:
        row = {name: (raw.get(name) or "").strip() for name in COLUMNS}
        if any(row.values()):  # skip blank lines
            rows.append(row)
    if not rows:
        raise ValidationError("The file has no rows below the header.")
    if len(rows) > MAX_ROWS:
        raise ValidationError(
            f"The file has {len(rows)} rows; at most {MAX_ROWS} are imported at once."
        )
    return rows


def template_csv():
    """A CSV with the header and one example row, to start from."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerow(EXAMPLE)
    return out.getvalue()
