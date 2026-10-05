from decimal import ROUND_HALF_UP, Decimal

from django import forms

from .models import Farm, Farmer


class FarmerForm(forms.ModelForm):
    class Meta:
        model = Farmer
        fields = ["name", "phone", "language", "village"]
        widgets = {
            "phone": forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "off"}),
        }

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean_village(self):
        return " ".join(self.cleaned_data["village"].split())


def _coordinate_field(label, limit):
    # Phones report GPS with many decimal places; accept any precision and round on save.
    return forms.DecimalField(
        label=label, required=False, min_value=-limit, max_value=limit,
        widget=forms.NumberInput(attrs={"step": "any", "inputmode": "decimal"}),
    )


class FarmForm(forms.ModelForm):
    latitude = _coordinate_field("Latitude", 90)
    longitude = _coordinate_field("Longitude", 180)

    class Meta:
        model = Farm
        fields = ["name", "size_ha", "water_source", "latitude", "longitude"]
        widgets = {
            "size_ha": forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
        }
        help_texts = {
            "water_source": "Fadama means low-lying land that stays wet after the rains.",
        }

    def clean(self):
        cleaned = super().clean()
        lat, lng = cleaned.get("latitude"), cleaned.get("longitude")
        if (lat is None) != (lng is None):
            raise forms.ValidationError("Enter both latitude and longitude, or leave both empty.")
        for key in ("latitude", "longitude"):
            if cleaned.get(key) is not None:
                cleaned[key] = cleaned[key].quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        return cleaned
