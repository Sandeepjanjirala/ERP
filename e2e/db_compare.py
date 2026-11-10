"""Compare two snapshots from db_snapshot.py: every table that existed before must have the same
rows after. Exit status 1 on any difference.

    python e2e/db_compare.py before.json after.json
"""

import json
import sys


def compare(before, after):
    problems = []
    for table, count in before["counts"].items():
        if after["counts"].get(table) != count:
            problems.append(f"{table}: {count} rows before, {after['counts'].get(table)} after")
    for key in ("classrooms", "fee_plans"):
        if key in before and before[key] != after.get(key):
            problems.append(f"{key} differ (grade names or links changed)")
    for key, value in before.items():
        if isinstance(value, dict) and "sha256" in value and after.get(key) != value:
            problems.append(f"{key} rows changed")
    if after.get("exams_without_term"):
        problems.append(f"{after['exams_without_term']} exams have no term")
    return problems


if __name__ == "__main__":
    before, after = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:3])
    problems = compare(before, after)
    print(
        f"{sum(before['counts'].values())} rows in {len(before['counts'])} tables compared; "
        f"{len(before['classrooms'])} classrooms and {len(before.get('fee_plans', []))} fee plans field by field"
    )
    print("IDENTICAL" if not problems else "DIFFERENCES:\n  " + "\n  ".join(problems))
    sys.exit(1 if problems else 0)
