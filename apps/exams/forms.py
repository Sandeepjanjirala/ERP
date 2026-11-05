from django import forms
from django.core.exceptions import ValidationError

from apps.academics.models import Subject, TeachingAssignment
from apps.academics.selectors import classrooms
from apps.core.forms import DateInput
from apps.organization.selectors import branches

from .models import Exam


class ExamForm(forms.ModelForm):
    class Meta:
        model = Exam
        fields = ["classroom", "subject", "title", "date", "max_marks", "pass_marks"]
        widgets = {"date": DateInput()}

    def __init__(self, *args, actor, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        self.fields["classroom"].queryset = classrooms(actor)
        subjects = Subject.objects.filter(branch__in=branches(actor))
        if actor.role == "teacher":
            subjects = subjects.filter(
                pk__in=TeachingAssignment.objects.filter(teacher=actor).values("subject_id")
            )
        self.fields["subject"].queryset = subjects

    def clean(self):
        data = super().clean()
        if (
            self.actor.role == "teacher"
            and data.get("classroom")
            and data.get("subject")
            and not TeachingAssignment.objects.filter(
                teacher=self.actor, classroom=data["classroom"], subject=data["subject"]
            ).exists()
        ):
            raise ValidationError("You can create exams only for your assigned class and subject.")
        return data


class MarkSheetForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput, min_value=1)

    def __init__(self, *args, roster, marks, exam, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = exam.version
        self.rows = []
        for enrollment in roster:
            mark = marks.get(enrollment.pk)
            score_key, absent_key = f"score_{enrollment.pk}", f"absent_{enrollment.pk}"
            self.fields[score_key] = forms.DecimalField(
                required=False,
                min_value=0,
                max_value=exam.max_marks,
                decimal_places=2,
                max_digits=6,
                initial=mark.score if mark else None,
            )
            self.fields[absent_key] = forms.BooleanField(
                required=False, initial=mark.absent if mark else False
            )
            self.rows.append((enrollment, self[score_key], self[absent_key]))

    def clean(self):
        d = super().clean()
        for enrollment, score, absent in self.rows:
            if d.get(absent.name) and d.get(score.name) is not None:
                self.add_error(score.name, "Use either a score or absent, not both.")
        return d
