from django import forms
from django.utils import timezone

from apps.academics.models import AcademicYear, Classroom
from apps.academics.selectors import classrooms
from apps.accounts.forms import AccountForm, NewAccountForm, choices_for
from apps.accounts.models import User
from apps.core.forms import DateInput
from apps.organization.models import Branch
from apps.organization.selectors import branches

from .models import Enrollment, Student, StudentGuardian
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
        return choices_for(User.Role.STUDENT)

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


class GuardianChoices(forms.Form):
    relationship = forms.ChoiceField(choices=StudentGuardian.Relationship.choices)
    make_primary = forms.BooleanField(
        required=False,
        label="Make this the primary contact",
        help_text="A student's first guardian is always the primary contact.",
    )


class GuardianAccountForm(NewAccountForm, GuardianChoices):
    """A new parent login for this student's family."""

    field_order = [*NewAccountForm.Meta.fields, "password", "relationship", "make_primary"]


class LinkGuardianForm(GuardianChoices):
    """An existing parent account, for a brother or sister of a student already at the school."""

    parent = forms.ModelChoiceField(queryset=User.objects.none(), label="Parent account")

    def __init__(self, *args, student, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = (
            User.objects.filter(role=User.Role.PARENT, branch=student.user.branch, is_active=True)
            .exclude(guardian_profile__child_links__student=student)
            .order_by("first_name", "username")
        )
        self.order_fields(["parent", "relationship", "make_primary"])


class ImportForm(forms.Form):
    """Which branch and year the classes in the file belong to, and the file."""

    branch = forms.ModelChoiceField(queryset=Branch.objects.none())
    year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.all(), help_text="The year of the classes in the file."
    )
    file = forms.FileField(
        help_text="A CSV saved as UTF-8: at most 500 rows and 2 MB.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = branches(actor)
        if not actor.system_admin:
            self.fields["branch"].initial = actor.branch_id
        current = AcademicYear.objects.filter(
            starts_on__lte=timezone.localdate(), ends_on__gte=timezone.localdate()
        ).first()
        self.fields["year"].initial = current.pk if current else None
