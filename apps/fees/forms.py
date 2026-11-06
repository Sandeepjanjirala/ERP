from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.academics.models import AcademicYear, Classroom

from .models import FeeHead, FeePlan, Payment
from .services import COUNTER_METHODS


class RupeesField(forms.DecimalField):
    """Typed in rupees ("12,500.50" is fine); cleaned to whole paise, the unit everything uses."""

    def __init__(self, **kwargs):
        kwargs.setdefault("min_value", Decimal("0.01"))
        super().__init__(max_digits=10, decimal_places=2, **kwargs)
        self.widget.attrs.setdefault("inputmode", "decimal")

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(",", "").replace("₹", "").strip()
        return super().to_python(value)

    def clean(self, value):
        amount = super().clean(value)
        return None if amount is None else int(amount * 100)


class CounterPaymentForm(forms.Form):
    amount = RupeesField(label="Amount received (₹)")
    method = forms.ChoiceField(
        choices=[(m.value, m.label) for m in Payment.Method if m in COUNTER_METHODS]
    )
    reference = forms.CharField(
        max_length=60, required=False, help_text="UPI transaction or cheque number."
    )


class ConcessionForm(forms.Form):
    amount = RupeesField(label="Concession (₹)")
    reason = forms.CharField(max_length=200)


class CancelForm(forms.Form):
    reason = forms.CharField(max_length=250, label="Reason for cancelling")


class FeeHeadForm(forms.ModelForm):
    class Meta:
        model = FeeHead
        fields = ["name", "code"]
        help_texts = {"code": "Short, unique in the branch, e.g. tuition."}


class FeePlanForm(forms.ModelForm):
    """The grade and year, plus one amount field per fee head of the branch."""

    grade = forms.ChoiceField()

    class Meta:
        model = FeePlan
        fields = ["year", "grade"]

    def __init__(self, *args, branch, heads, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.branch = branch
        self.heads = list(heads)
        self.fields["year"].queryset = AcademicYear.objects.all()
        grades = (
            Classroom.objects.filter(branch=branch)
            .order_by("grade")
            .values_list("grade", flat=True)
            .distinct()
        )
        self.fields["grade"].choices = [(grade, grade) for grade in grades]
        current = {}
        if self.instance.pk:
            current = {item.head_id: item.amount_paise for item in self.instance.items.all()}
            # The plan's year and grade are fixed once invoices may have been issued from it.
            self.fields["year"].disabled = self.fields["grade"].disabled = True
        for head in self.heads:
            paise = current.get(head.pk)
            self.fields[f"head_{head.pk}"] = RupeesField(
                label=f"{head.name} (₹)",
                required=False,
                initial=Decimal(paise) / 100 if paise else None,
                help_text="Leave empty if this grade doesn't pay it.",
            )

    def amounts(self):
        return {head: self.cleaned_data.get(f"head_{head.pk}") or 0 for head in self.heads}


class IssueInvoicesForm(forms.Form):
    title = forms.CharField(max_length=80, help_text="For example: Term 1 fees.")
    due_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def clean_due_on(self):
        due_on = self.cleaned_data["due_on"]
        if due_on < timezone.localdate():
            raise forms.ValidationError("The due date can't be before today, the issue date.")
        return due_on
