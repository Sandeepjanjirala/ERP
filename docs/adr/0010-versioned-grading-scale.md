# 10. A versioned grading scale that never rewrites published results

**Status:** Accepted, November 2026 (Phase 5)

## Context

Schools grade results in bands (A1 from 91%, A2 from 81%, ...). They also change their bands from time to time, while report cards already given to families must not change afterwards.

## Decision

**A scale is a numbered version that is never edited.** Saving a change creates the next version. The super admin saves it, and the activity log records every band.

**A band is a label and the percentage it starts at**, running up to the next band's start. A scale described this way can't have gaps or overlaps. The lowest band must start at 0%, so every result gets a grade.

**Publishing freezes the version on the exam** (`Exam.grading_scale`). Reopening makes the exam a draft again with no frozen version, and republishing takes the newest one; the publish audit event names the version.

**Which version grades a result:**

- A published exam uses the version it was published with.
- A draft, or an exam awaiting approval, shows the newest version.
- The overall grade on a report uses the version of the most recently published exam among the results. It changes only when results change, never because of a later scale.

**Exams published before any scale existed have no grade.** They were published with no grading rules. Giving them the first scale afterwards would change report cards already in families' hands, which is exactly what this decision forbids.

## Consequences

- A report card printed today matches one printed next year, whatever happens to the scale.
- There is no data migration for a default scale: the super admin saves the first version, starting from the CBSE bands the page offers. The demo seed saves them as version 1.
- Older results that must show grades need a reopen and republish: a deliberate act, recorded in the activity log.
