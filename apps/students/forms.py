from django import forms
from django.utils import timezone

from apps.academics.models import Classroom
from apps.academics.selectors import classrooms
from apps.accounts.forms import AccountForm
from apps.core.forms import DateInput

from .models import Enrollment, Student
from .selectors import students


class StudentAccountForm(AccountForm):
    """A student's login, admission number and first classroom, created in one step."""

    admission_number = forms.CharField(max_length=30)
    classroom = forms.ModelChoiceField(queryset=Classroom.objects.none())
    joined_on = forms.DateField(widget=DateInput, initial=timezone.localdate)

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, actor=actor, **kwargs)
        self.fields["classroom"].queryset = classrooms(actor)

    def role_choices(self):
        return [("student", "Student")]

    def clean(self):
        data = super().clean()
        if data.get("classroom"):
            c = data["classroom"]
            if data.get("branch") and c.branch_id != data["branch"].pk:
                self.add_error("classroom", "Choose a classroom in the selected branch.")
            if (
                data.get("joined_on")
                and not c.year.starts_on <= data["joined_on"] <= c.year.ends_on
            ):
                self.add_error(
                    "joined_on", "Joining date must fall within the classroom academic year."
                )
            if Student.objects.filter(admission_number=data.get("admission_number")).exists():
                self.add_error("admission_number", "This admission number is already in use.")
        return data


class EnrollmentForm(forms.ModelForm):
    class Meta:
        model = Enrollment
        fields = ["student", "classroom", "joined_on", "left_on"]
        widgets = {"joined_on": DateInput(), "left_on": DateInput()}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = students(actor)
        self.fields["classroom"].queryset = classrooms(actor)

    def clean(self):
        data = super().clean()
        if data.get("classroom"):
            self.instance.year = data["classroom"].year
            if (
                data.get("student")
                and Enrollment.objects.filter(student=data["student"], year=self.instance.year)
                .exclude(pk=self.instance.pk)
                .exists()
            ):
                self.add_error("student", "This student already has an enrollment for that year.")
        return data
