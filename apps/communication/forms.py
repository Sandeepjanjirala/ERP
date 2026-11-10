from django import forms

from apps.academics.selectors import classrooms
from apps.accounts.models import User
from apps.organization.selectors import branches

from .models import Announcement


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["branch", "audience", "classroom", "title", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classroom"].queryset = classrooms(actor)
        self.fields["classroom"].help_text = "Only for a class announcement."
        if actor.system_admin:
            self.fields["branch"].queryset = branches(actor)
            self.fields["branch"].empty_label = "Every branch"
        else:
            # Everyone else announces in their own branch.
            del self.fields["branch"]
            self.instance.branch_id = actor.branch_id
        if actor.role == User.Role.TEACHER:
            self.fields["audience"].choices = [
                (Announcement.Audience.CLASS, Announcement.Audience.CLASS.label)
            ]
