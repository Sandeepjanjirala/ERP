# Access rules

Permissions are enforced in Django views, filtered querysets, and write services. Hiding a navigation link is not the access control. The REST API enforces exactly the same rules with the same code; see [The API](#the-api) below.

| Capability | Super admin | Branch admin | Principal | Teacher | Student | Parent | Accountant |
|---|---|---|---|---|---|---|---|
| Branch scope | All branches | Own branch | Own branch | Own assigned classes | Own records | Own children | Own branch (fees only) |
| Create branches / academic years | Yes | No | No | No | No | No | No |
| Create principal / admin accounts | Yes | No | No | No | No | No | No |
| Create teachers, accountants and students | Yes | Own branch | No | No | No | No | No |
| Add parents / set the primary contact | Yes | Own branch | No | No | No | No | No |
| Edit contact details / deactivate | Branch users | Own teachers, accountants, students, parents | No | No | No | No | No |
| Create classrooms / subjects / assignments | Yes | Own branch | Read only | No | No | No | No |
| Grades and periods (bell schedule) | Yes | Own branch | Read only | No | No | No | No |
| A year's terms | Yes | Read only | Read only | Read only | Read only | Read only | No |
| Grading scale (save a new version) | Yes | Read only | Read only | No | No | No | No |
| Edit timetables | All | Own branch | No | No | No | No | No |
| View timetables | All | Own branch | Own branch | Classes they teach, their own week | Own class | Children's classes | No |
| Import students from CSV | All | Own branch | No | No | No | No | No |
| Year-end promotion | All | Own branch | Own branch | No | No | No | No |
| Record that a student has left | All | Own branch | No | No | No | No | No |
| Record daily attendance | All | Own branch | Read only | Assigned homeroom only | No | No | No |
| Apply for leave | No | No | No | No | No | Own children | No |
| Approve / refuse leave | All | Own branch | No | Own homeroom | No | No | No |
| View student reports and report cards | All | Own branch | Own branch | Assigned scope | Self only | Own children | No |
| Download all records (ZIP) | All | Own branch | Own branch | Assigned scope (no fees) | Self only (no fees) | Own children | No |
| Create exams | All | Own branch | No | Assigned class+subject | No | No | No |
| Enter draft marks | All | No | No | Assigned class+subject | No | No | No |
| Submit exams | All | No | No | Assigned class+subject | No | No | No |
| Publish / reopen results | All | No | Own branch | No | No | No | No |
| Post announcements | Any branch, or all | Own branch | Own branch | Classes they teach | No | No | No |
| Read announcements | All | Own branch | Own branch | Own branch | Those for students or their class | Those for parents or their child's class | Those for everyone or staff |
| CSV reports (results) | All | Own branch | Own branch | Assigned scope | No | No | No |
| Activity log | All | Own branch | Own branch | No | No | No | No |
| Fee heads and fee plans | All | Own branch | No | No | No | No | Read only |
| Issue invoices | All | Own branch | No | No | No | No | Own branch |
| Record office payments (cash, UPI, cheque) | All | Own branch | No | No | No | No | Own branch |
| Concessions / cancel an invoice | All | Own branch | No | No | No | No | No |
| View invoices, payments and receipts | All | Own branch | No | No | No | Own children | Own branch |
| Pay online | No | No | No | No | No | Own children | No |
| Fee collections report / payments to check | All | Own branch | No | No | No | No | Own branch |

A homeroom teacher can view all subject assessments in their homeroom class but can edit only subjects explicitly assigned to them. Other teachers see only assessments for their assigned classroom/subject pairs.

Parents see only their own children: their classes, published results, attendance, report cards and leave requests, never a classmate's. A parent account belongs to one branch, and its children must be in that branch. Every selector has an explicit parent rule, and `apps/students/tests/test_parent_scope.py` fails if one is removed.

Accountants handle fees and nothing academic: they see no marks, attendance, exams, leave or student reports, and those selectors return nothing for them (`apps/accounts/tests/test_accountant_scope.py`). Principals and teachers see no fees. Parents see and pay only their own children's invoices; students see no fees.

Students can access only their own published results and attendance. Drafts and submitted exams are absent from student queries and aggregates. A student changing a URL to another student’s ID receives a 404. Forbidden actions generally return 403; out-of-scope records return 404.

Branch administrators cannot create or edit principal/super-admin accounts, set system privileges, or choose another branch via a forged request. Contact-detail editing does not accept role, branch, username, or system-permission changes.

Role values are fixed application roles. This pilot does not have a configurable permissions editor. Privilege reassignment and cross-branch transfers require a reviewed migration to keep student, classroom, and historical records consistent.

Accounts are created by an administrator. There is no public signup endpoint. New accounts must change their initial password. Deactivation prevents new login, deletes the account's web sessions and blacklists its API refresh tokens, so reactivating it never revives them. Students and parents who leave are switched off automatically after a grace period (docs/adr/0013-leaving-and-access.md). Password reset uses Django’s expiring email-token flow.

After eight login attempts for the same normalized username in a 15-minute window, further attempts are temporarily blocked. A successful login clears that username’s counter. Account-level throttling is not a replacement for hosting-level request-rate controls.

## The API

The API applies the same three layers:

1. **Role:** every endpoint requires a signed-in user who has changed their initial password. Role-restricted endpoints use `role_in(...)` (`apps/core/api/permissions.py`), the API's version of `@role_required`.
2. **Scope:** querysets come from the same selectors, so another branch's record is a 404. Ids in a request body are checked against the same selectors, and an out-of-scope id gets the same "does not exist" error as a missing one.
3. **Policy:** writes call the same services, which check the same policies and raise 403.

Every endpoint's access for every role is one table in `apps/core/tests/test_api_permissions.py`. Token rules (expiry, rotation, revocation on password change or deactivation, the shared sign-in limit) are in [API.md](API.md#signing-in).

## Implementation references

- `apps/*/selectors.py`: branch, classroom, subject, assignment, teacher, student, enrollment, exam, attendance and report scopes.
- `apps/*/policies.py`: `can_attend`; `can_create_exam`, `can_mark`, `can_publish` and `exam_actions`; `can_manage_account`, `can_change_access` and `staff_roles_for`; `can_enroll`; `can_manage_setup`; `can_set_up_fees`, `can_collect_fees` and `can_pay_online`.
- `apps/accounts/decorators.py`: `role_required`, with role groups `User.STAFF`, `User.MANAGERS`, `User.LEADERS`, `User.ACADEMIC` (everyone but accountants) and `User.FINANCE` (super admin, branch admin, accountant).
- `apps/*/services.py`: every write checks its policy itself, inside a transaction, with row locks where needed. A caller that skips the web form, such as the API or a script, is still refused.
- `apps/*/forms.py`: only permitted branches and objects are valid choices.
- `apps/*/tests/`: forged requests, scope isolation, the account permission matrix (`apps/accounts/tests/test_policies.py`), the rules shared by web and API (`apps/core/tests/test_shared_rules.py`), the API matrix, locked marks, sessions, and concurrent-write tests on PostgreSQL.
- Django authentication documentation: https://docs.djangoproject.com/en/5.2/topics/auth/default/

## Phase 5 notes

- Terms and the grading scale belong to the whole school group, so only super admins change them. Grades and periods are per branch.
- The grading scale is versioned: saving creates a new version, and results already published keep theirs ([ADR 0010](adr/0010-versioned-grading-scale.md)).
- Timetable edits, imports and promotions are checked again in their services (`can_manage_setup`, `can_import`, `can_promote`), so the API and every other route follow the same rules.
