from decimal import ROUND_HALF_UP, Decimal

from django import forms

from .models import Farm, Farmer, PreviousCrop, Season


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


# --- New season wizard ---

class CropCheckboxes(forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def label_from_instance(self, crop):
        return f"{crop.name} ({crop.also_called})" if crop.also_called else crop.name


class SeasonStartForm(forms.Form):
    """Step 1: which season, and what was actually planted in up to three seasons before it.

    `slots` lists (seasons_ago, heading, must_answer). For a returning farm the last season must be
    answered (crops, other, fallow or "not known"); first-time farms may leave history empty.
    """

    label = forms.ChoiceField(label="Season", choices=Season.Label.choices, widget=forms.RadioSelect)
    planting_date = forms.DateField(
        label="Planned planting date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Can be in the future when planning ahead.",
    )

    def __init__(self, *args, slots, crops, **kwargs):
        super().__init__(*args, **kwargs)
        self.slots = slots
        for seasons_ago, _, must_answer in slots:
            p = f"s{seasons_ago}_"
            self.fields[p + "crops"] = CropCheckboxes(queryset=crops, required=False, label="Crops")
            self.fields[p + "other"] = forms.CharField(
                required=False, max_length=240, label="Other crops not in the list",
                help_text="Separate several with commas.",
            )
            self.fields[p + "fallow"] = forms.BooleanField(required=False, label="Left fallow (nothing planted)")
            if must_answer:
                self.fields[p + "unknown"] = forms.BooleanField(required=False, label="The farmer does not know")

    def slot_fields(self):
        """[(heading, [bound fields])] for the template."""
        groups = []
        for seasons_ago, heading, _ in self.slots:
            names = [n for n in self.fields if n.startswith(f"s{seasons_ago}_")]
            groups.append((heading, [self[n] for n in names]))
        return groups

    def clean(self):
        cleaned = super().clean()
        for seasons_ago, heading, must_answer in self.slots:
            p = f"s{seasons_ago}_"
            crops, other, fallow = cleaned.get(p + "crops"), cleaned.get(p + "other", "").strip(), cleaned.get(p + "fallow")
            answered = bool(crops) or bool(other) or fallow or cleaned.get(p + "unknown")
            if must_answer and not answered:
                self.add_error(p + "crops", "Say what was actually planted, or tick fallow or 'does not know'.")
            if fallow and (crops or other):
                self.add_error(p + "fallow", "A fallow season cannot also have crops.")
        return cleaned

    def previous_crop_rows(self):
        """{(seasons_ago, crop_id, free_text)} to store as PreviousCrop rows."""
        rows = set()
        for seasons_ago, _, _ in self.slots:
            p = f"s{seasons_ago}_"
            for crop in self.cleaned_data.get(p + "crops") or []:
                rows.add((seasons_ago, crop.pk, ""))
            for text in self.cleaned_data.get(p + "other", "").split(","):
                text = " ".join(text.split())[:120]
                if text:
                    rows.add((seasons_ago, None, text))
            if self.cleaned_data.get(p + "fallow"):
                rows.add((seasons_ago, None, PreviousCrop.FALLOW))
            if self.cleaned_data.get(p + "unknown"):
                rows.add((seasons_ago, None, PreviousCrop.UNKNOWN))
        return rows


class IntendedCropsForm(forms.Form):
    """Step 2: the farmer's shortlist and cropping method."""

    cropping_method = forms.ChoiceField(
        label="Cropping method", choices=Season.CroppingMethod.choices, widget=forms.RadioSelect,
        help_text="Mixed cropping ranks combinations of 2 or 3 crops from the shortlist.",
    )
    crops = CropCheckboxes(
        queryset=None, label="Crops the farmer wants to grow",
        error_messages={"required": "Choose at least 1 crop."},
    )

    def __init__(self, *args, crops, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["crops"].queryset = crops

    def clean(self):
        cleaned = super().clean()
        method, crops = cleaned.get("cropping_method"), cleaned.get("crops") or []
        if method == Season.CroppingMethod.MIXED and len(crops) < 2:
            self.add_error("crops", "Mixed cropping needs at least 2 crops on the shortlist.")
        return cleaned
