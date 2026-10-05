from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import MEASUREMENTS, SoilReading


class ManualReadingForm(forms.ModelForm):
    """pH is required; everything else is optional. Out-of-range values are warned about, not refused."""

    taken_at = forms.DateTimeField(
        label="Taken at",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )

    class Meta:
        model = SoilReading
        fields = ["taken_at", *MEASUREMENTS]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get("taken_at"):
            self.initial["taken_at"] = timezone.localtime().replace(second=0, microsecond=0)
        for name, spec in MEASUREMENTS.items():
            field = self.fields[name]
            field.label = spec["label"]
            field.widget = forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"})
            field.unit = spec["unit"]
        self.fields["ph"].required = True

    def clean_taken_at(self):
        taken_at = self.cleaned_data["taken_at"]
        if taken_at > timezone.now() + timedelta(minutes=5):
            raise forms.ValidationError("A reading cannot be taken in the future.")
        return taken_at
