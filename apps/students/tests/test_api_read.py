"""Read endpoints: each role sees only its own scope, the same as the web pages."""

from apps.core.testing import ApiTestCase


def ids(response):
    return sorted(row["id"] for row in response.json()["results"])


class ScopeTests(ApiTestCase):
    def test_lists_are_paginated(self):
        self.as_user(self.root)
        body = self.client.get("/api/v1/branches/").json()
        self.assertEqual(set(body), {"count", "next", "previous", "results"})
        self.assertEqual(body["count"], 2)

    def test_branches(self):
        self.as_user(self.admin)
        self.assertEqual(ids(self.client.get("/api/v1/branches/")), [self.a.pk])
        self.assertEqual(self.client.get(f"/api/v1/branches/{self.b.pk}/").status_code, 404)

    def test_classrooms_follow_the_teacher_and_student_scope(self):
        for user, expected in (
            (self.root, [self.c.pk, self.foreign_class.pk]),
            (self.admin, [self.c.pk]),
            (self.teacher, [self.c.pk]),
            (self.foreign_teacher, [self.foreign_class.pk]),
            (self.e1.student.user, [self.c.pk]),
        ):
            with self.subTest(user=user.username):
                self.as_user(user)
                self.assertEqual(ids(self.client.get("/api/v1/classrooms/")), expected)
        self.as_user(self.teacher)
        self.assertEqual(
            self.client.get(f"/api/v1/classrooms/{self.foreign_class.pk}/").status_code, 404
        )

    def test_a_filter_outside_your_scope_is_rejected(self):
        self.as_user(self.admin)
        response = self.client.get(f"/api/v1/classrooms/?branch={self.b.pk}")
        self.assertEqual(response.status_code, 400)
        self.assertIn("branch", response.json()["fields"])
        self.as_user(self.root)
        self.assertEqual(
            ids(self.client.get(f"/api/v1/classrooms/?branch={self.b.pk}")),
            [self.foreign_class.pk],
        )

    def test_role_restricted_lists(self):
        cases = [
            # (url, user, status)
            ("/api/v1/subjects/", self.teacher, 200),
            ("/api/v1/subjects/", self.e1.student.user, 403),
            ("/api/v1/assignments/", self.principal, 200),
            ("/api/v1/assignments/", self.teacher, 403),
            ("/api/v1/students/", self.teacher, 200),
            ("/api/v1/students/", self.e1.student.user, 403),
            ("/api/v1/years/", self.e1.student.user, 200),
        ]
        for url, user, status in cases:
            with self.subTest(url=url, user=user.username):
                self.as_user(user)
                response = self.client.get(url)
                self.assertEqual(response.status_code, status)
                if status == 403:
                    self.assertEqual(response.json()["code"], "permission_denied")

    def test_forced_password_change_blocks_everything_but_the_profile(self):
        self.teacher.must_change_password = True
        self.teacher.save()
        self.as_user(self.teacher)
        response = self.client.get("/api/v1/classrooms/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "password_change_required")
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 200)


class StudentListTests(ApiTestCase):
    def test_teacher_sees_their_class_with_scoped_enrollments(self):
        self.as_user(self.teacher)
        body = self.client.get("/api/v1/students/").json()
        self.assertEqual([row["admission_number"] for row in body["results"]], ["ALICE", "BOB"])
        enrollment = body["results"][0]["enrollments"][0]
        self.assertEqual(enrollment["classroom"]["label"], "9-A")

    def test_search_and_classroom_filter(self):
        self.as_user(self.root)
        found = self.client.get("/api/v1/students/?search=ali").json()["results"]
        self.assertEqual([row["admission_number"] for row in found], ["ALICE"])
        in_class = self.client.get(f"/api/v1/students/?classroom={self.foreign_class.pk}")
        self.assertEqual(ids(in_class), [self.foreign_enrollment.student.pk])

    def test_other_branch_student_is_not_found(self):
        self.as_user(self.admin)
        url = f"/api/v1/students/{self.foreign_enrollment.student.pk}/"
        self.assertEqual(self.client.get(url).status_code, 404)


class StudentReportTests(ApiTestCase):
    def url(self, enrollment):
        return f"/api/v1/students/{enrollment.student.pk}/report/"

    def test_student_reads_their_own_published_results_only(self):
        self.publish()  # Midterm is published; the science test stays a draft
        student = self.e1.student.user
        self.as_user(student)
        me = self.client.get("/api/v1/me/").json()
        self.assertEqual(me["student_id"], self.e1.student.pk)

        report = self.client.get(self.url(self.e1)).json()
        self.assertEqual([r["exam_title"] for r in report["results"]], ["Midterm"])
        self.assertEqual(report["results"][0]["score"], "80.00")
        self.assertTrue(report["results"][0]["passed"])
        self.assertEqual(report["summary"]["count"], 1)
        self.assertEqual(report["selected_year"]["id"], self.year.pk)
        self.assertEqual(
            set(report["attendance"]),
            {"present", "absent", "late", "excused", "total", "rate", "below_minimum"},
        )

    def test_students_cannot_read_each_other(self):
        self.as_user(self.e1.student.user)
        self.assertEqual(self.client.get(self.url(self.e2)).status_code, 404)

    def test_staff_outside_the_branch_get_404(self):
        self.as_user(self.foreign_teacher)
        self.assertEqual(self.client.get(self.url(self.e1)).status_code, 404)
        self.as_user(self.teacher)
        self.assertEqual(self.client.get(self.url(self.e1)).status_code, 200)

    def test_unknown_year_is_404(self):
        self.as_user(self.admin)
        self.assertEqual(self.client.get(self.url(self.e1) + "?year=999999").status_code, 404)
