from django import forms

from apps.accounts.models import User
from apps.core.forms import DateInput
from apps.organization.selectors import branches

from .models import AcademicYear, Classroom, Subject, TeachingAssignment
from .selectors import classrooms


class YearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ["name", "starts_on", "ends_on"]
        widgets = {"starts_on": DateInput(), "ends_on": DateInput()}


class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ["branch", "year", "grade", "section", "homeroom_teacher"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = branches(actor)
        self.fields["homeroom_teacher"].queryset = User.objects.filter(
            branch__in=branches(actor), role=User.Role.TEACHER, is_active=True
        )
        if not actor.system_admin:
            self.fields["branch"].initial = actor.branch_id


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ["branch", "name", "code"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = branches(actor)
        if not actor.system_admin:
            self.fields["branch"].initial = actor.branch_id


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = TeachingAssignment
        fields = ["teacher", "classroom", "subject"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["teacher"].queryset = User.objects.filter(
            branch__in=branches(actor), role=User.Role.TEACHER, is_active=True
        )
        self.fields["classroom"].queryset = classrooms(actor)
        self.fields["subject"].queryset = Subject.objects.filter(branch__in=branches(actor))
