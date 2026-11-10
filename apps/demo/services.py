"""Demo mode: one-click role logins and the nightly reset (docs/adr/0014-demo-mode.md)."""

from django.conf import settings
from django.core.management import call_command
from django.db import connection, transaction

from apps.accounts.models import User

from .models import DemoMarker

# The account each one-click login signs in as, from the seeded Madhapur branch.
DEMO_LOGINS = {
    "superadmin": ("Super admin", "superadmin"),
    "admin": ("Branch admin", "admin.madhapur"),
    "principal": ("Principal", "principal.madhapur"),
    "teacher": ("Teacher", "teacher.madhapur"),
    "accountant": ("Accountant", "accountant.madhapur"),
    "student": ("Student", "student1.madhapur"),
    "parent": ("Parent", "parent1.madhapur"),
}


def is_demo_database():
    """Demo mode is on and this database was filled by seed_demo (it holds the marker)."""
    return settings.DEMO_MODE and DemoMarker.objects.exists()


def demo_account(role):
    """The seeded account for a one-click login, or None (unknown role, or not the demo)."""
    if role not in DEMO_LOGINS or not is_demo_database():
        return None
    return User.objects.filter(username=DEMO_LOGINS[role][1]).first()


class NotADemoDatabase(Exception):
    pass


def reset_demo(size=None, stdout=None):
    """Replace all data with a fresh synthetic seed, in one transaction (visitors see the old
    data until the new data is complete). Refused unless DEMO_MODE is on AND the database holds
    the marker seed_demo wrote: two independent checks, one in the settings and one in the
    database, so pointing a demo server at a real school's database can't wipe it."""
    if not settings.DEMO_MODE:
        raise NotADemoDatabase("The demo reset runs only with DEMO_MODE=1.")
    with transaction.atomic():
        if not DemoMarker.objects.select_for_update().exists():
            raise NotADemoDatabase(
                "This database was not created by seed_demo; the demo reset will not touch it."
            )
        if connection.vendor == "postgresql":
            # PostgreSQL won't TRUNCATE tables with foreign-key checks still pending in this
            # transaction (rows written earlier in it); run those checks now.
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        call_command("flush", interactive=False, verbosity=0)
        call_command("seed_demo", size=size or settings.DEMO_SIZE, stdout=stdout)
