# Attendance, marks, fees, timetables, and history

## Academic structure

There is exactly one organisation. Each branch contains its staff, students, subjects, grades, and classrooms. A classroom belongs to an academic year and to one of its branch's **grades** ("Class 9"), which are ordered (Class 9 is 9) so promotion knows what comes next. Each student can have at most one classroom enrollment per academic year.

An academic year is divided into **terms** that stay inside the year and never overlap. A new year starts with Term 1 and Term 2 splitting it in half; the super admin changes a year's terms together, as one set ([ADR 0009](adr/0009-grades-and-terms.md)).

This permits retaining earlier years while creating the next year. The student’s account stays the same. Enrollment dates determine who belongs on a daily register or an exam roster. Branch transfers are not a self-service feature in this version.

To avoid silently changing completed work, a new enrollment cannot be backdated across existing class attendance or a submitted/published exam. Historical enrollment corrections require a supervised migration. Future enrollment and exam setup are allowed within the academic-year dates, but future daily attendance and future exam publication are rejected.

## Daily attendance

One saved register per classroom/date, with one status per enrolled student. Every roster student must receive a status before saving. Weekends and holidays are not automatically excluded because the school calendar has not been supplied; no register means an unrecorded day, not an absence.

| Status | Meaning | Included in percentage? |
|---|---|---|
| P | Present | Numerator and denominator |
| L | Late | Numerator and denominator |
| A | Absent | Denominator only |
| E | Excused | Excluded |

Attendance percentage = `100 × (present + late) / (present + late + absent)`.

If there are no counted days, the dashboard shows a dash. It does not invent 0% or 100%. Updating a saved register requires a reason and writes before/after statuses to the audit log.

Each register has a version. A form loaded before someone else saved a correction is rejected instead of overwriting that correction. PostgreSQL transactions lock the classroom while creating/updating its register.

A student is flagged when their attendance rate falls **below 75%**: on their report, their report card, their family's dashboard, and the staff dashboard's list.

## Absence alerts

When **today's** register is saved, each student newly marked absent, and their guardians, get a notification and an email. A correction alerts only students who weren't already absent. Saving a register for an earlier day alerts nobody, so a teacher catching up on last week doesn't send families stale news. If a student is corrected back to present before the alert goes out, it isn't sent.

## Leave requests

A parent asks for leave for their own child: one to 31 days, not overlapping another pending or approved request for the same child, starting on a day the child is enrolled in a class. The people who keep that class's register decide: its class teacher, a branch admin or a super admin. Refusing needs a reason.

Approving leave marks those days as excused:

- On registers already saved for those days, the child's **Absent** becomes **Excused**. **Present** is never changed. Each changed register gets a new version, so anyone with it open must reload.
- Registers saved later suggest **Excused** for the child, labelled "On approved leave". The teacher still saves the register.

The class teacher is told about a new request; the parent and the student are told the decision, in the app and by email.

## Marks and publication

Each exam defines a classroom, subject, title, date, maximum marks, and pass marks. Its **term** is the one its date falls in, set automatically on every save; a date that no term covers is refused with a clear message, and changing a year's terms moves each exam to the term its date then falls in (or is refused if one would be left outside every term). Maximum is at least 1; pass marks must be between 0 and maximum. Scores use decimal arithmetic and two decimal places.

- A score must be between zero and the exam maximum.
- An absent attempt has no numeric score and counts as zero in analysis.
- A blank draft entry means unfinished; it cannot be published.
- A teacher must save changes before selecting “Submit saved marks for review”.
- Submission requires every enrolled student to have a score or absence.
- Principals publish only submitted, complete exams.
- Submitted and published mark sheets are locked against editing.
- Reopening requires a principal or super admin and a correction reason. It hides that exam’s results from students until republished.

The application checks version numbers and uses transactions for mark changes and state transitions. An invalid entry rolls back the whole submitted mark sheet. PostgreSQL locks serialize concurrent writes; SQLite local mode is for exploration, not the concurrent pilot.

## Reports

Only published exams are included in reports and CSV analysis.

Overall percentage = `100 × sum(earned marks) / sum(exam maximums)`.

This is weighted by the exam maximum, not an average of percentages. For example, 45/50 and 80/100 produce 125/150 = 83.3%. Absent attempts contribute zero earned marks and the full maximum. An absent attempt never passes, even if an exam’s pass mark is zero.

A passing result means the student was not absent and their score meets that exam’s configured pass mark. No ranks, board-specific formulas, or AI predictions are invented.

**Grades** (A1, A2, ...) come from the grading scale: each band starts at a percentage and runs up to the next band, and the lowest starts at 0%. The scale is versioned. A published result is graded by the version its exam was published with, so a later change never alters it; a draft or an exam awaiting approval shows the newest version. The overall grade uses the version of the most recently published exam among the results. Exams published before any scale existed show no grade ([ADR 0010](adr/0010-versioned-grading-scale.md)).

The **report card** is a PDF (A4) with the school's name and branch as the letterhead, the student, all published results for the chosen year, and the attendance summary; its footer says it was generated by EduNexa. The report page can also be printed from the browser.

When an exam is published, the students who sat it and their guardians are told, in the app and by email. Publishing again after a reopen tells them again.

CSV exports respect the same scope as the on-screen results. Text cells beginning with spreadsheet formula characters are prefixed with an apostrophe to prevent formula execution.

## Fees

- **Money is whole paise** (₹1 = 100 paise) everywhere in the database and the API; screens, PDFs and CSV show rupees. Nothing is ever rounded.
- **Fee heads** are kinds of charge (Tuition, Transport). A **fee plan** is what one student of a grade pays in a year: one plan per branch, year and grade, with an amount per head.
- **A plan's grade is one of the branch's grades.** Plans made before Phase 5 named the grade as text; the Phase 5 migration pointed each at the Grade with the same branch and name.
- **Issuing** creates one invoice per student currently in a classroom of that grade, copying the plan's lines. Issuing the same title again skips students who already have it. Changing a plan later never changes invoices already issued.
- **Invoice status** is Issued, Partly paid, Paid or Cancelled. **Overdue is computed, never stored**: past the due date with a balance still owed.
- **Concessions** (admins) reduce the total, with a reason, by at most the balance. **Cancelling** (admins) needs a reason and is allowed only while nothing has been paid.
- **Office payments** (cash, UPI, cheque) are at most the balance; UPI and cheques need their reference.
- **Online payments** are recorded only when the provider confirms them with a valid signature. The same provider payment is recorded once, however many times it is reported. Money beyond the balance (an online payment that crossed an office payment, say) is recorded and kept as **excess** for a refund. Money in another currency, or an amount that differs from the checkout, is listed under **Payments to check**. Confirmed money is never discarded.
- **Receipts** are numbered per branch and academic year without gaps (`MDP/2026-27/00042`). A number is taken inside the payment's transaction, so a failed payment gives it back, and an issued number is never reused. Every confirmed payment, including excess, gets one. The receipt PDF is emailed to the student's guardians.
- **Reminders:** each day, families of overdue invoices are reminded, at most once a week per invoice.
- **Collection report and CSV** cover payments received between two dates, by method, with amounts applied and held for refund. CSV cells are protected against spreadsheet formulas, and each export is recorded in the activity log.

## Timetable

- Each branch has **periods** (its bell schedule) that never overlap. A class's week has at most one lesson per weekday (Monday to Saturday) and period.
- A lesson is taught by a teacher assigned to that class and subject.
- The database refuses a class booked twice in one period, and a teacher booked twice in one period of the same year ([ADR 0011](adr/0011-timetable-and-htmx.md)). The message names the other class.
- Edits are audited (before and after).

## Importing students

- A CSV of at most 500 rows and 2 MB, saved as UTF-8. The columns are fixed; a misspelt one is refused, not ignored.
- Rows name classes as the school does ("Class 9-A") in a chosen branch and year. Dates are YYYY-MM-DD.
- The check runs every row as a real import would, then undoes it, and lists each row's problems. Confirming imports every row together, or none if anything has changed since the check. A batch is imported once.
- A guardian email already known as a parent in the branch is linked; otherwise a parent account is created.
- New accounts get a "set your password" email; nobody is sent a password ([ADR 0012](adr/0012-import-and-promotion.md)).

## Year-end promotion

- Every student of a class gets a decision: move up into next year's class, repeat the grade (in next year's class of the same grade), or leave. After the branch's last grade, students leave or repeat.
- One transaction: old enrollments close on the year's last day, new ones start on the next year's first day.
- A student already enrolled in a later year is skipped, so running it again changes nothing. Audited with the counts.

## Activity log

Every web request has an id, returned in the `X-Request-ID` response header and stored on each activity-log entry the request writes, so a question about one action can be traced to exactly its entries. Background jobs write entries without one. The log filters by area, person, dates, record and request id.
