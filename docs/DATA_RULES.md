# Attendance, marks, and history

## Academic structure

There is exactly one organisation. Each branch contains its staff, students, subjects, and classrooms. A classroom belongs to an academic year. Each student can have at most one classroom enrollment per academic year.

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

Each exam defines a classroom, subject, title, date, maximum marks, and pass marks. Maximum is at least 1; pass marks must be between 0 and maximum. Scores use decimal arithmetic and two decimal places.

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

A passing result means the student was not absent and their score meets that exam’s configured pass mark. No letter grades, ranks, board-specific formulas, or AI predictions are invented.

The **report card** is a PDF (A4) with the school's name and branch as the letterhead, the student, all published results for the chosen year, and the attendance summary; its footer says it was generated by EduNexa. The report page can also be printed from the browser.

When an exam is published, the students who sat it and their guardians are told, in the app and by email. Publishing again after a reopen tells them again.

CSV exports respect the same scope as the on-screen results. Text cells beginning with spreadsheet formula characters are prefixed with an apostrophe to prevent formula execution.
