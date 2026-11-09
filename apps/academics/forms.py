from django import forms

from apps.accounts.selectors import teachers
from apps.core.forms import DateInput
from apps.organization.selectors import branches

from .models import AcademicYear, Classroom, Grade, Subject, TeachingAssignment
from .selectors import classrooms, grades, subjects


class YearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ["name", "starts_on", "ends_on"]
        widgets = {"starts_on": DateInput(), "ends_on": DateInput()}


class TermRowForm(forms.Form):
    """One term in the year's list. A row left empty is ignored; ticking Remove drops a term."""

    id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(max_length=30, required=False)
    starts_on = forms.DateField(required=False, widget=DateInput())
    ends_on = forms.DateField(required=False, widget=DateInput())

    def clean(self):
        data = super().clean()
        filled = [data.get(field) for field in ("name", "starts_on", "ends_on")]
        if any(filled) and not all(filled):
            raise forms.ValidationError("Give the term a name, a start date and an end date.")
        return data

    def row(self):
        """The term as save_terms takes it, or None for an empty row."""
        data = self.cleaned_data
        if not data.get("name") or data.get("DELETE"):
            return None
        return {key: data[key] for key in ("id", "name", "starts_on", "ends_on")}


TermFormSet = forms.formset_factory(TermRowForm, extra=2, can_delete=True)


class GradeForm(forms.ModelForm):
    class Meta:
        model = Grade
        fields = ["branch", "name", "order"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = branches(actor)
        if not actor.system_admin:
            self.fields["branch"].initial = actor.branch_id


class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ["branch", "year", "grade", "section", "homeroom_teacher"]

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = branches(actor)
        self.fields["grade"].queryset = grades(actor)
        self.fields["grade"].help_text = "A grade of the classroom's branch."
        self.fields["homeroom_teacher"].queryset = teachers(actor)
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
        self.fields["teacher"].queryset = teachers(actor)
        self.fields["classroom"].queryset = classrooms(actor)
        self.fields["subject"].queryset = subjects(actor)
