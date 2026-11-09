from django.core.validators import RegexValidator
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
    receipt_prefix = models.CharField(
        max_length=8,
        blank=True,
        validators=[RegexValidator(r"^[A-Z0-9]+$", "Use capital letters and digits only.")],
        help_text="Starts this branch's receipt numbers, e.g. MDP. Defaults to the branch code.",
    )

    class Meta:
        ordering = ["name"]

    @property
    def receipt_code(self):
        return self.receipt_prefix or self.code.upper().replace("-", "")[:8]

    def __str__(self):
        return f"{self.name} · {self.city}"
