"""The report card PDF. Layout helpers, letterhead and footer: apps/core/pdf.py."""

from apps.core.pdf import Paragraph, Spacer, escape, letterhead, mm, render, styles, table


def result_rows(marks):
    """The results table: a header row, then one row per published mark."""
    rows = [["Subject", "Assessment", "Date", "Score", "Maximum", "Result"]]
    for mark in marks:
        rows.append(
            [
                mark.exam.subject.name,
                mark.exam.title,
                f"{mark.exam.date:%d %b %Y}",
                "Absent" if mark.absent else str(mark.score),
                str(mark.exam.max_marks),
                "Pass" if mark.passed else "Below pass mark",
            ]
        )
    return rows


def render_report_card(student, report, school_name):
    """The report card for one student and one year, as PDF bytes.

    `report` is reports.selectors.student_report(): only published results are in it.
    """
    sheet = styles()
    year = report["selected_year"]
    classes = ", ".join(f"{e.classroom.grade}-{e.classroom.section}" for e in report["enrollments"])
    summary, attendance = report["summary"], report["attendance_summary"]

    story = [
        *letterhead(school_name, f"{student.user.branch.name} · Student progress report"),
        table(
            [
                ["Student", student.user.display_name],
                ["Admission number", student.admission_number],
                ["Class", classes or "-"],
                ["Academic year", year.name if year else "-"],
            ],
            [45 * mm, 125 * mm],
        ),
        Spacer(1, 6 * mm),
        Paragraph("Published results", sheet["Heading2"]),
        table(
            result_rows(report["marks"]),
            [32 * mm, 38 * mm, 24 * mm, 18 * mm, 20 * mm, 38 * mm],
        ),
        Spacer(1, 3 * mm),
        Paragraph(
            escape(
                f"{summary['passed']} of {summary['count']} assessments passed. "
                f"Overall {summary['percentage'] if summary['percentage'] is not None else '-'}%."
            ),
            sheet["BodyText"],
        ),
        Spacer(1, 6 * mm),
        Paragraph("Attendance", sheet["Heading2"]),
        table(
            [
                ["Present", "Late", "Absent", "Excused", "Attendance rate"],
                [
                    attendance["P"],
                    attendance["L"],
                    attendance["A"],
                    attendance["E"],
                    f"{attendance['rate']}%" if attendance["rate"] is not None else "-",
                ],
            ],
            [30 * mm, 30 * mm, 30 * mm, 30 * mm, 50 * mm],
        ),
    ]
    if attendance["below_minimum"]:
        story += [
            Spacer(1, 3 * mm),
            Paragraph(
                "<b>Attendance is below 75%.</b> Please speak to the class teacher.",
                sheet["BodyText"],
            ),
        ]
    return render(story, f"Report card: {student.user.display_name}", school_name)


def report_card_filename(student, report):
    year = report["selected_year"]
    suffix = f"-{year.starts_on:%Y}" if year else ""
    return f"report-card-{student.admission_number}{suffix}.pdf"
