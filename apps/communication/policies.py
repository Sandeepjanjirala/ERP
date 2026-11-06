"""Who may post announcements."""

from apps.academics.selectors import classrooms
from apps.accounts.models import User

from .models import Announcement


def can_announce(user, announcement):
    """Super admins: anywhere. Admins and principals: their branch. Teachers: a class they teach."""
    if user.system_admin:
        return True
    if announcement.branch_id is None or announcement.branch_id != user.branch_id:
        return False
    if user.role in (User.Role.ADMIN, User.Role.PRINCIPAL):
        return True
    return (
        user.role == User.Role.TEACHER
        and announcement.audience == Announcement.Audience.CLASS
        and classrooms(user).filter(pk=announcement.classroom_id).exists()
    )
