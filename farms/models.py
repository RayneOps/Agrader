from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.urls import reverse

from core.models import CreatedByModel

phone_validator = RegexValidator(
    r"^\+?[0-9][0-9 \-]{6,18}[0-9]$",
    "Enter a phone number using digits, spaces or dashes, e.g. 0803 123 4567.",
)


class Farmer(CreatedByModel):
    class Language(models.TextChoices):
        HAUSA = "hausa", "Hausa"
        NUPE = "nupe", "Nupe"
        GBAGYI = "gbagyi", "Gbagyi (Gwari)"
        ENGLISH = "english", "English"
        YORUBA = "yoruba", "Yoruba"
        IGBO = "igbo", "Igbo"
        OTHER = "other", "Other"

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    language = models.CharField(max_length=20, choices=Language.choices, default=Language.HAUSA)
    village = models.CharField(max_length=120)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["village"]), models.Index(fields=["phone"])]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("farmer_detail", args=[self.pk])

    @property
    def member_since(self):
        return self.created_at


class Farm(CreatedByModel):
    class WaterSource(models.TextChoices):
        RAIN_FED = "rain_fed", "Rain-fed"
        IRRIGATED = "irrigated", "Irrigated"
        FADAMA = "fadama", "Fadama"

    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="farms")
    name = models.CharField(max_length=120)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal("-90")), MaxValueValidator(Decimal("90"))],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal("-180")), MaxValueValidator(Decimal("180"))],
    )
    size_ha = models.DecimalField(
        "size (hectares)", max_digits=8, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    water_source = models.CharField(max_length=20, choices=WaterSource.choices)

    class Meta:
        ordering = ["farmer__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.farmer.name})"

    def get_absolute_url(self):
        return reverse("farm_detail", args=[self.pk])

    @property
    def has_gps(self):
        return self.latitude is not None and self.longitude is not None


class Season(CreatedByModel):
    """One growing season on a farm. A farm's seasons in date order are its Seasonal Soil Memory."""

    class Label(models.TextChoices):
        RAINY = "rainy", "Rainy season"
        DRY = "dry", "Dry season"

    class CroppingMethod(models.TextChoices):
        MONO = "mono", "Mono cropping"
        MIXED = "mixed", "Mixed cropping"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RECOMMENDED = "recommended", "Recommended"
        CLOSED = "closed", "Closed"

    farm = models.ForeignKey(Farm, on_delete=models.PROTECT, related_name="seasons")
    year = models.PositiveSmallIntegerField(validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    label = models.CharField(max_length=10, choices=Label.choices)
    # Blank only on a draft that has not reached wizard step 2 yet.
    cropping_method = models.CharField(max_length=10, choices=CroppingMethod.choices, blank=True)
    planting_date = models.DateField()
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        ordering = ["farm", "planting_date", "created_at"]
        constraints = [
            # The device API attaches readings to "the" open season, so there can be only one.
            models.UniqueConstraint(
                fields=["farm"],
                condition=models.Q(status="draft"),
                name="one_draft_season_per_farm",
                violation_error_message="This farm already has an open (draft) season.",
            ),
        ]

    def __str__(self):
        return f"{self.get_label_display()} {self.year}, {self.farm.name}"


class PreviousCrop(CreatedByModel):
    """What was actually planted on the farm before this season, as told to the operator.

    Rules use only rows with a crop. Free-text rows (unlisted crops, "fallow") are context for the LLM.
    """

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="previous_crops")
    crop = models.ForeignKey("crops.Crop", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    free_text = models.CharField(max_length=120, blank=True)
    seasons_ago = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(3)])

    FALLOW = "Fallow (nothing planted)"
    UNKNOWN = "Not known"

    class Meta:
        ordering = ["seasons_ago", "crop__name", "free_text"]
        constraints = [
            models.CheckConstraint(
                name="previous_crop_has_crop_or_text",
                condition=models.Q(crop__isnull=False) | ~models.Q(free_text=""),
            ),
            models.CheckConstraint(name="previous_crop_seasons_ago_1_to_3", condition=models.Q(seasons_ago__gte=1, seasons_ago__lte=3)),
        ]

    def __str__(self):
        return self.crop.name if self.crop_id else self.free_text


class IntendedCrop(CreatedByModel):
    """A crop on the farmer's shortlist for this season. Ranking never leaves this list."""

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="intended_crops")
    crop = models.ForeignKey("crops.Crop", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["crop__name"]
        constraints = [models.UniqueConstraint(fields=["season", "crop"], name="unique_intended_crop")]

    def __str__(self):
        return self.crop.name
