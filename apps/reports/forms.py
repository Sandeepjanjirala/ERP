from django import forms

from apps.core.forms import DateInput


class ActivityFilterForm(forms.Form):
    """The activity log's filters. Every field is optional; together they narrow the list."""

    area = forms.ChoiceField(required=False, label="Area")
    person = forms.CharField(required=False, max_length=60, label="Who")
    since = forms.DateField(required=False, widget=DateInput(), label="From")
    until = forms.DateField(required=False, widget=DateInput(), label="To")
    text = forms.CharField(required=False, max_length=80, label="Record contains")
    request = forms.CharField(
        required=False,
        max_length=32,
        label="Request ID",
        help_text="From the X-Request-ID of a response, to find what one request did.",
    )

    def __init__(self, *args, areas=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["area"].choices = [("", "Everything"), *[(area, area) for area in areas]]

    def clean(self):
        data = super().clean()
        if data.get("since") and data.get("until") and data["since"] > data["until"]:
            raise forms.ValidationError("The start date must be on or before the end date.")
        return data
