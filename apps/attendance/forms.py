from django import forms
from django.utils import timezone

from apps.academics.models import Classroom
from apps.academics.selectors import classrooms
from apps.core.forms import DateInput

from .models import Attendance
from .services import register_date_error


class RegisterSelection(forms.Form):
    classroom = forms.ModelChoiceField(queryset=Classroom.objects.none())
    date = forms.DateField(widget=DateInput(), initial=timezone.localdate)

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classroom"].queryset = classrooms(actor)

    def clean(self):
        d = super().clean()
        if d.get("date") and d.get("classroom"):
            if problem := register_date_error(d["classroom"], d["date"]):
                self.add_error("date", problem)
        elif d.get("date") and d["date"] > timezone.localdate():
            self.add_error("date", "Future attendance is not allowed.")
        return d


class RegisterForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    reason = forms.CharField(
        required=False, max_length=250, help_text="Required when correcting an existing register."
    )

    def __init__(self, *args, roster, initial_statuses, version, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = version
        self.rows = []
        for enrollment in roster:
            key = f"status_{enrollment.pk}"
            self.fields[key] = forms.ChoiceField(
                choices=[("", "Choose status"), *Attendance.Status.choices],
                initial=initial_statuses.get(enrollment.pk),
            )
            self.rows.append((enrollment, self[key]))
