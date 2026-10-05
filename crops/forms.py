from django import forms

from .models import Crop, CropPairRule, CropRequirement, RotationRule, ScoreSetting


class NewCropForm(forms.ModelForm):
    """Family and nitrogen fixing feed the scoring. They are set here once and locked afterwards."""

    class Meta:
        model = Crop
        fields = ["name", "also_called", "scientific_name", "family", "fixes_nitrogen", "active"]
        help_texts = {
            "family": "Cannot be changed after the crop is created. Rotation rules use it.",
            "fixes_nitrogen": "Cannot be changed after the crop is created. Nitrogen-fixing crops get full marks for nitrogen.",
        }

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if Crop.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("A crop with this name already exists.")
        return name


class CropForm(forms.ModelForm):
    """Display details only. Family and nitrogen fixing are locked after creation."""

    class Meta:
        model = Crop
        fields = ["name", "also_called", "scientific_name", "active"]
        help_texts = {"active": "Inactive crops cannot be added to a farmer's shortlist."}


class CropRequirementForm(forms.ModelForm):
    class Meta:
        model = CropRequirement
        fields = CropRequirement.CONTENT_FIELDS
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            **{name: forms.NumberInput(attrs={"step": "0.1", "inputmode": "decimal"})
               for name in ["ph_min", "ph_ideal_low", "ph_ideal_high", "ph_max", "temp_low_c", "temp_high_c"]},
        }
        help_texts = {
            "requires_standing_water": "Removed on rain-fed farms.",
            "exempt_from_season_length": "Not removed when the season is shorter than its minimum days.",
        }


class PairRuleForm(forms.ModelForm):
    class Meta:
        model = CropPairRule
        fields = ["crop_a", "crop_b", "verdict", "reason"]
        labels = {"crop_a": "First crop", "crop_b": "Second crop"}
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned = super().clean()
        first, second = cleaned.get("crop_a"), cleaned.get("crop_b")
        if first and second:
            if first == second:
                raise forms.ValidationError("Choose two different crops.")
            # Pairs are stored in a fixed order, so A + B and B + A are the same rule.
            cleaned["crop_a"], cleaned["crop_b"] = CropPairRule.ordered(first, second)
            existing = CropPairRule.find(first, second)
            if existing and existing.pk != self.instance.pk:
                raise forms.ValidationError(f"There is already a rule for {first} + {second}. Edit that one instead.")
        return cleaned

    def validate_unique(self):
        pass  # handled in clean(), with a clearer message


class RotationRuleForm(forms.ModelForm):
    class Meta:
        model = RotationRule
        fields = ["code", "match", "previous_family", "previous_crop", "next_family", "next_crop", "effect", "reason"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "match": "Use 'same crop a third season running' only for the R8 safeguard. It has no previous or next crop.",
            "previous_crop": "Choose a family or a single crop for each side, not both.",
        }


class ScoreSettingForm(forms.ModelForm):
    class Meta:
        model = ScoreSetting
        fields = ["value"]
