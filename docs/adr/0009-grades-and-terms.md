# 9. Grades and terms as records; exams placed in terms by their date

**Status:** Accepted, November 2026 (Phase 5)

## Context

Until Phase 5 a classroom's grade was free text ("Class 9"), and fee plans copied that text. Year-end promotion needs to know which grade comes after which, and fee plans need to point at a real grade. Exams also needed terms, so reports could say which term a result belongs to. Real data already existed: classrooms, fee plans with issued invoices, and published exams.

## Decision

**A Grade record per branch** (`name`, `order`), because classrooms and fee plans are per branch already. Classrooms and fee plans point at a Grade.

**The text became records by migration, in three steps per app** (academics 0002-0004, fees 0003-0005):

1. Add the Grade table and a nullable link.
2. Create one Grade per (branch, name) found, ordered by the number in the name, and link every row.
3. Drop the text and make the link required.

Each step is its own migration, because on PostgreSQL a data change followed by a column change in one transaction fails ("pending trigger events"). Old uniqueness rules are removed in step 1, so the migration also runs backwards and restores the text exactly.

**The API keeps `grade` (the name)** in responses and adds `grade_id`. New classrooms are created with `grade_id`.

**Each exam belongs to the term its date falls in.** The term is set on every save from the date; a person never picks it. A date no term covers is refused, with a message naming the year and date. A migration gave every existing year two default terms splitting it in half, then placed every existing exam by its date. A new year gets the same two terms.

**A year's terms are saved as one set** (`save_terms`), with the year row locked. Moving the boundary between Term 1 and Term 2 changes both terms, and saving them one at a time always passes through a gap or an overlap. The whole set is checked: inside the year, no overlaps, unique names. Then every exam moves to the term its date now falls in. If any exam would be outside every term, nothing is saved.

## Consequences

- The migrations were tested with a migration test (forwards and backwards, SQLite and PostgreSQL) and on copies of two Phase 4 PostgreSQL databases: every row compared identical, and every classroom and plan kept its grade name.
- `convert_legacy_data` creates the same grades and terms for exports from the single-app version.
- Schools whose terms aren't two halves adjust them on the terms page; the exams follow.
