from django import forms
from django.utils import timezone

from apps.academics.models import Classroom
from apps.academics.selectors import classrooms
from apps.core.forms import DateInput
from apps.students.selectors import students

from .models import Attendance, LeaveRequest
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
            # One tap per student: a button for each status (radio inputs, styled as a group).
            self.fields[key] = forms.ChoiceField(
                choices=Attendance.Status.choices,
                initial=initial_statuses.get(enrollment.pk),
                widget=forms.RadioSelect(attrs={"class": "status-choice"}),
                error_messages={"required": "Choose a status."},
            )
            self.rows.append((enrollment, self[key]))


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["student", "starts_on", "ends_on", "reason"]
        labels = {"student": "Child", "starts_on": "First day", "ends_on": "Last day"}
        widgets = {
            "starts_on": DateInput(),
            "ends_on": DateInput(),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = students(actor)


class LeaveDecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=[("approve", "Approve"), ("reject", "Not approve")])
    note = forms.CharField(max_length=250, required=False)
