# Access rules

Permissions are enforced in Django views, filtered querysets, and write services. Hiding a navigation link is not the access control.

| Capability | Super admin | Branch admin | Principal | Teacher | Student |
|---|---|---|---|---|---|
| Branch scope | All branches | Own branch | Own branch | Own assigned classes | Own records |
| Create branches / academic years | Yes | No | No | No | No |
| Create principal / admin accounts | Yes | No | No | No | No |
| Create teachers and students | Yes | Own branch | No | No | No |
| Edit user contact details / deactivate | Branch users | Own teachers/students | No | No | No |
| Create classrooms / subjects / assignments | Yes | Own branch | Read only | No | No |
| Record daily attendance | All | Own branch | Read only | Assigned homeroom only | No |
| View student reports | All | Own branch | Own branch | Assigned scope | Self only |
| Create exams | All | Own branch | No | Assigned class+subject | No |
| Enter draft marks | All | No | No | Assigned class+subject | No |
| Submit exams | All | No | No | Assigned class+subject | No |
| Publish / reopen results | All | No | Own branch | No | No |
| CSV reports | All | Own branch | Own branch | Assigned scope | No |
| Activity log | All | Own branch | Own branch | No | No |

A homeroom teacher can view all subject assessments in their homeroom class but can edit only subjects explicitly assigned to them. Other teachers see only assessments for their assigned classroom/subject pairs.

Students can access only their own published results and attendance. Drafts and submitted exams are absent from student queries and aggregates. A student changing a URL to another student’s ID receives a 404. Forbidden actions generally return 403; out-of-scope records return 404.

Branch administrators cannot create or edit principal/super-admin accounts, set system privileges, or choose another branch via a forged request. Contact-detail editing does not accept role, branch, username, or system-permission changes.

Role values are fixed application roles. This pilot does not have a configurable permissions editor. Privilege reassignment and cross-branch transfers require a reviewed migration to keep student, classroom, and historical records consistent.

Accounts are created by an administrator. There is no public signup endpoint. New accounts must change their initial password. Deactivation prevents new login and invalidates access by already-authenticated sessions on their next request. Password reset uses Django’s expiring email-token flow.

After eight login attempts for the same normalized username in a 15-minute window, further attempts are temporarily blocked. A successful login clears that username’s counter. Account-level throttling is not a replacement for hosting-level request-rate controls.

## Implementation references

- `apps/*/selectors.py`: branch, classroom, student, enrollment, exam and attendance scopes.
- `apps/*/policies.py`: `can_attend`, `can_mark`, `can_publish`, `can_manage_account`, `can_change_access`.
- `apps/accounts/decorators.py`: `role_required`, with role groups `User.STAFF`, `User.MANAGERS` and `User.LEADERS`.
- `apps/*/services.py`: check the policy again before changing records; database transactions and row locks.
- `apps/*/forms.py`: only permitted branches and objects are valid choices.
- `apps/*/tests/`: forged requests, scope isolation, the account permission matrix (`apps/accounts/tests/test_policies.py`), locked marks, sessions, and concurrent-write tests on PostgreSQL.
- Django authentication documentation: https://docs.djangoproject.com/en/5.2/topics/auth/default/
