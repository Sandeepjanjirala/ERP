from django import forms

from .models import Branch, Organization


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name"]


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "code", "city", "receipt_prefix"]
