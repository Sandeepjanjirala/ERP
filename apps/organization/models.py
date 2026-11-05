from django.db import models
from django.db.models import Q

from apps.core.models import ValidatedModel


class Organization(ValidatedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=120, default="My school")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name="single_organization")]

    def __str__(self):
        return self.name


class Branch(ValidatedModel):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=20, unique=True)
    city = models.CharField(max_length=80)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} · {self.city}"
