"""Crop knowledge: crops, their requirements, pair rules, rotation rules and score settings.

Every rule here is an unverified draft until the rule approver (the Crop Scientist) approves it.
The recommendation engine only uses approved rules unless ALLOW_UNAPPROVED_RULES is on.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from core.models import BaseModel, CreatedByModel


class Family(models.TextChoices):
    CEREAL = "cereal", "Cereal"
    LEGUME = "legume", "Legume"
    ROOT_TUBER = "root_tuber", "Root and tuber"
    SOLANACEAE = "solanaceae", "Solanaceae (tomato family)"
    MALVACEAE = "malvaceae", "Malvaceae (okro family)"


class Demand(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


def parse_month_day(value):
    """'10-15' -> (10, 15), or None if it is not a real date in the year."""
    match = re.fullmatch(r"(\d{2})-(\d{2})", value or "")
    if not match:
        return None
    try:
        date(2024, int(match[1]), int(match[2]))  # 2024 is a leap year, so 02-29 is allowed
    except ValueError:
        return None
    return int(match[1]), int(match[2])


def approval_block_reason(user, *, already_approved, editor_id):
    """Why `user` may not approve this item, or None if they may."""
    if already_approved:
        return "Already approved."
    if not user.can_approve_rules:
        return "Only the rule approver can approve."
    if editor_id is not None and editor_id == user.pk:
        return "You edited this, so you cannot approve it."
    return None


class Approvable(CreatedByModel):
    """Content that the rule approver signs off. `edited_by` is empty for seed data."""

    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+", editable=False
    )
    approved_at = models.DateTimeField(null=True, blank=True, editable=False)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+", editable=False
    )

    class Meta:
        abstract = True

    def approval_block_reason(self, user):
        return approval_block_reason(user, already_approved=self.approved, editor_id=self.edited_by_id)

    def approve(self, user):
        reason = self.approval_block_reason(user)
        if reason:
            raise PermissionError(reason)
        self.approved = True
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save()

    def mark_edited(self, user):
        """Call before saving a content change: it needs fresh approval."""
        self.edited_by = user
        self.approved = False
        self.approved_by = None
        self.approved_at = None


class Crop(BaseModel):
    name = models.CharField(max_length=60, unique=True)
    also_called = models.CharField(max_length=120, blank=True)
    scientific_name = models.CharField(max_length=120, blank=True)
    family = models.CharField(max_length=20, choices=Family.choices)
    fixes_nitrogen = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def latest_requirement(self):
        return self.requirements.order_by("-version").first()

    def latest_approved_requirement(self):
        return self.requirements.filter(approved=True).order_by("-version").first()


def _ph_field(label):
    return models.DecimalField(
        label, max_digits=3, decimal_places=1, validators=[MinValueValidator(0), MaxValueValidator(14)]
    )


class CropRequirement(Approvable):
    """One version of a crop's growing requirements. Versions are never changed after creation;
    an edit creates the next version, so past recommendations stay reproducible."""

    CONTENT_FIELDS = [
        "ph_min", "ph_ideal_low", "ph_ideal_high", "ph_max",
        "n_demand", "p_demand", "k_demand",
        "water_low_mm", "water_high_mm", "days_min", "days_max", "temp_low_c", "temp_high_c",
        "planting_window", "notes", "requires_standing_water", "exempt_from_season_length",
    ]

    crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="requirements")
    version = models.PositiveIntegerField(editable=False)
    ph_min = _ph_field("pH minimum")
    ph_ideal_low = _ph_field("pH ideal low")
    ph_ideal_high = _ph_field("pH ideal high")
    ph_max = _ph_field("pH maximum")
    n_demand = models.CharField("nitrogen demand", max_length=10, choices=Demand.choices)
    p_demand = models.CharField("phosphorus demand", max_length=10, choices=Demand.choices)
    k_demand = models.CharField("potassium demand", max_length=10, choices=Demand.choices)
    water_low_mm = models.PositiveIntegerField("water need, low (mm)")
    water_high_mm = models.PositiveIntegerField("water need, high (mm)")
    days_min = models.PositiveIntegerField("days to maturity, minimum")
    days_max = models.PositiveIntegerField("days to maturity, maximum")
    temp_low_c = models.DecimalField("temperature low (°C)", max_digits=4, decimal_places=1)
    temp_high_c = models.DecimalField("temperature high (°C)", max_digits=4, decimal_places=1)
    planting_window = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    requires_standing_water = models.BooleanField(default=False)
    exempt_from_season_length = models.BooleanField(default=False)

    class Meta:
        ordering = ["crop__name", "-version"]
        constraints = [models.UniqueConstraint(fields=["crop", "version"], name="unique_requirement_version")]

    def __str__(self):
        return f"{self.crop.name} v{self.version}"

    def clean(self):
        errors = {}
        values = [self.ph_min, self.ph_ideal_low, self.ph_ideal_high, self.ph_max]
        if None not in values and values != sorted(values):
            errors["ph_max"] = "pH values must go up in order: minimum ≤ ideal low ≤ ideal high ≤ maximum."
        if None not in (self.water_low_mm, self.water_high_mm) and self.water_low_mm > self.water_high_mm:
            errors["water_high_mm"] = "High water need must not be below the low water need."
        if None not in (self.days_min, self.days_max) and self.days_min > self.days_max:
            errors["days_max"] = "Maximum days must not be below minimum days."
        if None not in (self.temp_low_c, self.temp_high_c) and self.temp_low_c > self.temp_high_c:
            errors["temp_high_c"] = "High temperature must not be below the low temperature."
        if errors:
            raise ValidationError(errors)

    def content(self):
        return {name: getattr(self, name) for name in self.CONTENT_FIELDS}

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.version is None:
                last = CropRequirement.objects.filter(crop=self.crop_id).aggregate(models.Max("version"))
                self.version = (last["version__max"] or 0) + 1
        else:
            stored = CropRequirement.objects.get(pk=self.pk)
            if stored.content() != self.content() or stored.version != self.version:
                raise ValueError("Crop requirement versions cannot be changed. Create a new version instead.")
        super().save(*args, **kwargs)


class CropPairRule(Approvable):
    """Whether two crops do well together in mixed cropping. Stored once per unordered pair."""

    class Verdict(models.TextChoices):
        GOOD = "good", "Good together"
        AVOID = "avoid", "Avoid together"

    crop_a = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="+")
    crop_b = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="+")
    verdict = models.CharField(max_length=10, choices=Verdict.choices)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["crop_a__name", "crop_b__name"]
        constraints = [
            models.UniqueConstraint(fields=["crop_a", "crop_b"], name="unique_crop_pair"),
            # Always stored in id order, which also rules out pairing a crop with itself.
            models.CheckConstraint(condition=Q(crop_a__lt=F("crop_b")), name="crop_pair_ordered"),
        ]

    def __str__(self):
        return f"{self.crop_a.name} + {self.crop_b.name}: {self.get_verdict_display()}"

    @staticmethod
    def ordered(crop_1, crop_2):
        return (crop_1, crop_2) if crop_1.pk < crop_2.pk else (crop_2, crop_1)

    def save(self, *args, **kwargs):
        if self.crop_a_id and self.crop_b_id and self.crop_a_id > self.crop_b_id:
            self.crop_a, self.crop_b = self.crop_b, self.crop_a
        super().save(*args, **kwargs)

    @classmethod
    def find(cls, crop_1, crop_2):
        a, b = cls.ordered(crop_1, crop_2)
        return cls.objects.filter(crop_a=a, crop_b=b).first()


class RotationRule(Approvable):
    """Effect of the previous season's crop on the next crop.

    A `pattern` rule names one side each as a family or a single crop. The `repeat_third_season`
    rule (R8) has no sides: it applies when the same crop would be grown a third season running.
    """

    class Match(models.TextChoices):
        PATTERN = "pattern", "Previous → next"
        REPEAT_THIRD_SEASON = "repeat_third_season", "Same crop a third season running"

    class Effect(models.TextChoices):
        BONUS = "bonus", "Bonus (+40%)"
        SMALL_BONUS = "small_bonus", "Small bonus (+20%)"
        PENALTY = "penalty", "Penalty (−30%)"
        STRONG_PENALTY = "strong_penalty", "Strong penalty (−60%)"
        BLOCK = "block", "Block (crop removed)"

    code = models.CharField(max_length=10)
    match = models.CharField(max_length=25, choices=Match.choices, default=Match.PATTERN)
    previous_family = models.CharField(max_length=20, choices=Family.choices, blank=True)
    previous_crop = models.ForeignKey(Crop, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    next_family = models.CharField(max_length=20, choices=Family.choices, blank=True)
    next_crop = models.ForeignKey(Crop, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    effect = models.CharField(max_length=20, choices=Effect.choices)
    reason = models.TextField()

    class Meta:
        ordering = ["code", "created_at"]
        indexes = [models.Index(fields=["code"])]
        constraints = [
            models.CheckConstraint(
                name="rotation_rule_sides",
                condition=(
                    Q(match="pattern")
                    & ((~Q(previous_family="") & Q(previous_crop__isnull=True))
                       | (Q(previous_family="") & Q(previous_crop__isnull=False)))
                    & ((~Q(next_family="") & Q(next_crop__isnull=True))
                       | (Q(next_family="") & Q(next_crop__isnull=False)))
                )
                | (
                    Q(match="repeat_third_season", previous_family="", previous_crop__isnull=True,
                      next_family="", next_crop__isnull=True)
                ),
            ),
        ]

    def __str__(self):
        return f"{self.code}: {self.previous_label} → {self.next_label}"

    @property
    def previous_label(self):
        if self.match == self.Match.REPEAT_THIRD_SEASON:
            return "Any crop, two seasons running"
        return self.previous_crop.name if self.previous_crop_id else f"Any {self.get_previous_family_display().lower()}"

    @property
    def next_label(self):
        if self.match == self.Match.REPEAT_THIRD_SEASON:
            return "The same crop again"
        return self.next_crop.name if self.next_crop_id else f"Any {self.get_next_family_display().lower()}"

    def clean(self):
        if self.match == self.Match.REPEAT_THIRD_SEASON:
            if self.previous_family or self.previous_crop_id or self.next_family or self.next_crop_id:
                raise ValidationError("A 'third season running' rule has no previous or next crop.")
            return
        errors = {}
        if bool(self.previous_family) == bool(self.previous_crop_id):
            errors["previous_crop"] = "Choose a previous family or a previous crop, not both."
        if bool(self.next_family) == bool(self.next_crop_id):
            errors["next_crop"] = "Choose a next family or a next crop, not both."
        if errors:
            raise ValidationError(errors)


class ScoreSetting(BaseModel):
    """A number or date the scoring uses. Editable in the app; edits need fresh verification."""

    class Kind(models.TextChoices):
        NUMBER = "number", "Number"
        MONTH_DAY = "month_day", "Date in the year (MM-DD)"

    class Group(models.TextChoices):
        WEIGHTS = "weights", "Score weights"
        CALENDAR = "calendar", "Season calendar"
        WATER = "water", "Water"
        NUTRIENTS = "nutrients", "Nutrient shares"
        THRESHOLDS = "thresholds", "Nutrient thresholds (mg/kg)"

    key = models.SlugField(max_length=60, unique=True)
    group = models.CharField(max_length=20, choices=Group.choices)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.NUMBER)
    value = models.CharField(max_length=40)
    description = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+", editable=False
    )
    verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+", editable=False
    )

    class Meta:
        ordering = ["group", "key"]

    def __str__(self):
        return f"{self.key} = {self.value}"

    def clean(self):
        if self.kind == self.Kind.NUMBER:
            try:
                number = Decimal(self.value)
            except InvalidOperation:
                raise ValidationError({"value": "Enter a number."})
            if not number.is_finite() or number < 0:
                raise ValidationError({"value": "Enter a number that is zero or more."})
        elif self.kind == self.Kind.MONTH_DAY:
            if parse_month_day(self.value) is None:
                raise ValidationError({"value": "Enter a date as MM-DD, for example 10-15 for 15 October."})

    def approval_block_reason(self, user):
        return approval_block_reason(user, already_approved=self.verified, editor_id=self.edited_by_id)

    def verify(self, user):
        reason = self.approval_block_reason(user)
        if reason:
            raise PermissionError(reason)
        self.verified = True
        self.verified_by = user
        self.verified_at = timezone.now()
        self.save()

    def mark_edited(self, user):
        self.edited_by = user
        self.verified = False
        self.verified_by = None
        self.verified_at = None
