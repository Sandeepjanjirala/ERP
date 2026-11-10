import csv
import zipfile
from io import BytesIO

from apps.academics.models import AcademicYear
from apps.audit.services import audit
from apps.core.exports import safe_csv
from apps.fees.pdf import receipt_filename, render_receipt, render_statement
from apps.fees.selectors import invoices, payments
from apps.organization.selectors import school_name

from .pdf import render_report_card, report_card_filename
from .selectors import student_report

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


def records_pack(actor, student):
    """A ZIP of everything a family may want to keep: a report card for every year the student
    was enrolled, and (for parents and finance staff) the fee statement and every receipt.
    Built from what `actor` may see, so it never holds more than the pages they could open."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pack:
        for year in AcademicYear.objects.filter(enrollment__student=student).distinct():
            report = student_report(actor, student, year.pk)
            if report["enrollments"]:
                pack.writestr(
                    f"report-cards/{report_card_filename(student, report)}",
                    render_report_card(student, report, school_name()),
                )
        student_invoices = invoices(actor).filter(student=student).order_by("issued_on", "pk")
        if student_invoices:
            pack.writestr(
                f"fee-statement-{student.admission_number}.pdf",
                render_statement(student, student_invoices),
            )
        received = (
            payments(actor)
            .filter(invoice__student=student, receipt__isnull=False)
            .prefetch_related("invoice__payments")
            .order_by("paid_at", "pk")
        )
        for payment in received:
            pack.writestr(f"receipts/{receipt_filename(payment)}", render_receipt(payment))
    audit(actor, student.user.branch, "report.records_downloaded", student.user.display_name)
    return buffer.getvalue()
