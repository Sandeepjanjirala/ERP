"""Read queries for announcements and notifications, limited to what the user may see."""

from django.db.models import Q

from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.students.models import Student

from .models import Announcement, Notification


def announcements(user):
    """Super admins: everything. Staff: everything sent in their branch. Families: what's for them."""
    qs = Announcement.objects.select_related("branch", "classroom", "author")
    if user.system_admin:
        return qs
    qs = qs.filter(Q(branch__isnull=True) | Q(branch_id=user.branch_id))
    if user.role in User.STAFF:
        return qs
    group = Announcement.Audience.STUDENTS if user.is_student else Announcement.Audience.PARENTS
    return qs.filter(
        Q(audience__in=[Announcement.Audience.EVERYONE, group])
        | Q(audience=Announcement.Audience.CLASS, classroom__in=classrooms(user))
    )


def announcement_audience(announcement):
    """The active accounts an announcement is delivered to (its author excluded)."""
    people = User.objects.filter(is_active=True).exclude(pk=announcement.author_id)
    if announcement.branch_id:
        people = people.filter(branch_id=announcement.branch_id)
    audience = Announcement.Audience
    if announcement.audience == audience.STAFF:
        people = people.filter(role__in=User.STAFF)
    elif announcement.audience == audience.STUDENTS:
        people = people.filter(role=User.Role.STUDENT)
    elif announcement.audience == audience.PARENTS:
        people = people.filter(role=User.Role.PARENT)
    elif announcement.audience == audience.CLASS:
        in_class = Student.objects.filter(
            enrollments__classroom=announcement.classroom, enrollments__left_on__isnull=True
        ).values("pk")
        people = people.filter(
            Q(student_profile__in=in_class) | Q(guardian_profile__child_links__student__in=in_class)
        ).distinct()
    return people


def notifications(user):
    return Notification.objects.filter(recipient=user)


def unread_count(user):
    return notifications(user).filter(read_at__isnull=True).count()
