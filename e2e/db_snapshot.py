"""Snapshot the rows a migration must not change, as JSON (used by rehearse_migrations.py).

    python e2e/db_snapshot.py sqlite:path/to/db.sqlite3 before.json
    python e2e/db_snapshot.py postgres:postgresql://user:pass@host:5432/name before.json

Works on every schema since Phase 1: a classroom's grade is read as text before Phase 5 and
through the Grade table after it, and tables that don't exist yet are skipped. Large tables are
compared by a hash of their rows.
"""

import hashlib
import json
import sqlite3
import sys

TABLES = [
    "accounts_user", "organization_branch", "academics_academicyear", "academics_classroom",
    "academics_subject", "academics_teachingassignment", "students_student", "students_enrollment",
    "students_guardian", "students_studentguardian", "attendance_attendancesession",
    "attendance_attendance", "attendance_leaverequest", "exams_exam", "exams_mark",
    "communication_announcement", "communication_notification", "audit_auditevent",
    "fees_feehead", "fees_feeplan", "fees_feeplanitem", "fees_invoice", "fees_invoiceline",
    "fees_concession", "fees_paymentorder", "fees_payment", "fees_receipt", "fees_receiptcounter",
    "academics_grade", "academics_term", "academics_period", "academics_timetableslot",
    "exams_gradingscale", "exams_gradeband", "students_importbatch",
]  # fmt: skip

HASHED = {
    "users": ("accounts_user", "select id, username, password, role, branch_id, is_active from accounts_user order by id"),
    "enrollments": ("students_enrollment", "select id, student_id, classroom_id, year_id, joined_on, left_on from students_enrollment order by id"),
    "sessions": ("attendance_attendancesession", "select id, classroom_id, date, version from attendance_attendancesession order by id"),
    "attendance": ("attendance_attendance", "select id, session_id, enrollment_id, status from attendance_attendance order by id"),
    "exams": ("exams_exam", "select id, classroom_id, subject_id, title, date, status, version, published_at from exams_exam order by id"),
    "marks": ("exams_mark", "select id, exam_id, enrollment_id, score, absent from exams_mark order by id"),
    "audit": ("audit_auditevent", "select id, actor_id, action, target from audit_auditevent order by id"),
    "leave": ("attendance_leaverequest", "select id, student_id, starts_on, ends_on, status from attendance_leaverequest order by id"),
    "guardians": ("students_studentguardian", "select id, student_id, guardian_id, relationship, is_primary from students_studentguardian order by id"),
    "invoices": ("fees_invoice", "select id, plan_id, student_id, title, total_paise, paid_paise, status from fees_invoice order by id"),
    "payments": ("fees_payment", "select id, invoice_id, amount_paise, applied_paise, method from fees_payment order by id"),
    "receipts": ("fees_receipt", "select id, payment_id, number from fees_receipt order by id"),
}  # fmt: skip


class Database:
    def __init__(self, target):
        kind, address = target.split(":", 1)
        if kind == "sqlite":
            self.conn = sqlite3.connect(f"file:{address}?mode=ro", uri=True)
            self.tables = {
                r[0] for r in self.conn.execute("select name from sqlite_master where type='table'")
            }
        elif kind == "postgres":
            import psycopg

            self.conn = psycopg.connect(address)
            self.tables = {
                r[0]
                for r in self.conn.execute(
                    "select tablename from pg_tables where schemaname='public'"
                )
            }
        else:
            raise SystemExit("Give sqlite:PATH or postgres:URL")
        self.kind = kind

    def columns(self, table):
        if self.kind == "sqlite":
            return {r[1] for r in self.conn.execute(f"pragma table_info({table})")}
        query = "select column_name from information_schema.columns where table_name=%s"
        return {r[0] for r in self.conn.execute(query, (table,))}

    def rows(self, sql):
        return [list(map(str, row)) for row in self.conn.execute(sql).fetchall()]


def snapshot(target):
    db = Database(target)
    result = {"counts": {}}
    for table in TABLES:
        if table in db.tables:
            result["counts"][table] = db.conn.execute(f"select count(*) from {table}").fetchone()[0]
    if "grade" in db.columns("academics_classroom"):
        result["classrooms"] = db.rows(
            "select id, branch_id, year_id, grade, section, homeroom_teacher_id from academics_classroom order by id"
        )
    else:
        result["classrooms"] = db.rows(
            "select c.id, c.branch_id, c.year_id, g.name, c.section, c.homeroom_teacher_id from academics_classroom c "
            "join academics_grade g on g.id = c.grade_id where g.branch_id = c.branch_id order by c.id"
        )
    if "fees_feeplan" in db.tables:
        if "grade" in db.columns("fees_feeplan"):
            result["fee_plans"] = db.rows(
                "select id, branch_id, year_id, grade from fees_feeplan order by id"
            )
        else:
            result["fee_plans"] = db.rows(
                "select p.id, p.branch_id, p.year_id, g.name from fees_feeplan p join academics_grade g "
                "on g.id = p.grade_id where g.branch_id = p.branch_id order by p.id"
            )
    for key, (table, sql) in HASHED.items():
        if table in db.tables:
            data = db.rows(sql)
            result[key] = {
                "rows": len(data),
                "sha256": hashlib.sha256(json.dumps(data).encode()).hexdigest(),
            }
    if "term_id" in db.columns("exams_exam"):
        result["exams_without_term"] = db.conn.execute(
            "select count(*) from exams_exam where term_id is null"
        ).fetchone()[0]
    return result


if __name__ == "__main__":
    data = snapshot(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as out:
        json.dump(data, out, indent=1)
    print(
        f"{sys.argv[1].split(':')[0]}: {sum(data['counts'].values())} rows in {len(data['counts'])} tables"
    )
