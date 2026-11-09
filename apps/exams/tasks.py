from celery import shared_task
from django.urls import reverse

from apps.communication.models import Notification
from apps.communication.services import notify
from apps.students.models import Student
from apps.students.selectors import family

from .models import Exam


@shared_task
def announce_results(exam_id, version):
    """Tell the students who sat a published exam, and their guardians. Safe to run twice.

    The key includes the exam's version, so results published again after a reopen are
    announced again; an exam reopened before this ran is skipped.
    """
    exam = Exam.objects.select_related("subject", "classroom__grade").get(pk=exam_id)
    if exam.status != Exam.Status.PUBLISHED or exam.version != version:
        return 0
    sat = Student.objects.filter(enrollments__marks__exam=exam)
    return notify(
        family(sat),
        Notification.Kind.RESULTS,
        f"results:{exam.pk}:{version}",
        f"Results published: {exam.title}",
        f"{exam.subject.name}, class {exam.classroom.grade}-{exam.classroom.section}.",
        url=reverse("exams"),
        email=True,
    )
