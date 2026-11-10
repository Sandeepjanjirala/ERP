from django.db import models


class DemoMarker(models.Model):
    """Written by seed_demo into the empty database it fills: proof, kept inside the database
    itself, that every row here is synthetic. The demo reset refuses any database without it,
    so it can never wipe a real school's data (a real database is never seeded, because
    seeding requires an empty one)."""

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Demo database, seeded {self.created_at:%Y-%m-%d %H:%M}"
