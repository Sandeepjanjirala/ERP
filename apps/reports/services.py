import csv

from apps.audit.services import audit

CSV_HEADER = [
    "Branch",
    "Class",
    "Student",
    "Admission number",
    "Subject",
    "Exam",
    "Score",
    "Maximum",
    "Result",
]


def safe_csv(value):
    """Stop spreadsheet apps from running a cell as a formula (CSV injection)."""
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text


def export_results_csv(actor, branch, marks, out):
    """Write published results as CSV to `out` (a file or HttpResponse) and record the export."""
    writer = csv.writer(out)
    writer.writerow(CSV_HEADER)
    for m in marks:
        writer.writerow(
            [
                safe_csv(value)
                for value in [
                    m.exam.classroom.branch.name,
                    f"{m.exam.classroom.grade}-{m.exam.classroom.section}",
                    m.enrollment.student.user.display_name,
                    m.enrollment.student.admission_number,
                    m.exam.subject.name,
                    m.exam.title,
                    "Absent" if m.absent else m.score,
                    m.exam.max_marks,
                    "Pass" if m.passed else "Below pass mark",
                ]
            ]
        )
    audit(
        actor,
        branch or actor.branch,
        "report.exported",
        "Published results CSV",
        {"rows": len(marks)},
    )
