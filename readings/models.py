from django.db import models

from core.models import CreatedByModel

# Plausible range and unit for each measured value. Outside the range the reading is flagged
# (never refused): sensor faults happen, but so do unusual soils. EC unit is assumed to be µS/cm;
# the sensor's units are not confirmed yet.
MEASUREMENTS = {
    "ph": {"label": "pH", "unit": "", "min": 3, "max": 10},
    "nitrogen": {"label": "Nitrogen (N)", "unit": "mg/kg", "min": 0, "max": 1000},
    "phosphorus": {"label": "Phosphorus (P)", "unit": "mg/kg", "min": 0, "max": 1000},
    "potassium": {"label": "Potassium (K)", "unit": "mg/kg", "min": 0, "max": 2000},
    "moisture_pct": {"label": "Moisture", "unit": "%", "min": 0, "max": 100},
    "temperature_c": {"label": "Soil temperature", "unit": "°C", "min": 5, "max": 60},
    "ec": {"label": "Electrical conductivity (EC)", "unit": "µS/cm", "min": 0, "max": 10000},
}


def implausible_values(values):
    """Return a list of plain-English warnings for values outside their plausible range."""
    warnings = []
    for field, spec in MEASUREMENTS.items():
        value = values.get(field)
        if value is None:
            continue
        if not spec["min"] <= value <= spec["max"]:
            unit = f" {spec['unit']}" if spec["unit"] else ""
            warnings.append(
                f"{spec['label']} {value:g}{unit} is outside the usual range "
                f"({spec['min']:g} to {spec['max']:g}{unit})."
            )
    return warnings


class SoilReading(CreatedByModel):
    """One soil measurement, stored exactly as received. N, P and K are in mg/kg."""

    class Source(models.TextChoices):
        SENSOR = "sensor", "Sensor"
        MANUAL = "manual", "Typed in"

    farm = models.ForeignKey("farms.Farm", on_delete=models.PROTECT, related_name="readings")
    # Empty when a device reading arrived while the farm had no open season.
    season = models.ForeignKey(
        "farms.Season", on_delete=models.PROTECT, null=True, blank=True, related_name="readings"
    )
    # TODO(phase 7): device = ForeignKey(Device, null=True)
    taken_at = models.DateTimeField()
    ph = models.FloatField("pH")
    nitrogen = models.FloatField(null=True, blank=True)
    phosphorus = models.FloatField(null=True, blank=True)
    potassium = models.FloatField(null=True, blank=True)
    moisture_pct = models.FloatField(null=True, blank=True)
    temperature_c = models.FloatField(null=True, blank=True)
    ec = models.FloatField("EC", null=True, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices)

    class Meta:
        ordering = ["-taken_at"]
        indexes = [models.Index(fields=["farm", "-taken_at"])]

    def __str__(self):
        return f"pH {self.ph:g} on {self.taken_at:%d %b %Y %H:%M}"

    def values(self):
        return {field: getattr(self, field) for field in MEASUREMENTS}

    @property
    def warnings(self):
        return implausible_values(self.values())

    @property
    def missing_nutrients(self):
        return [MEASUREMENTS[f]["label"] for f in ("nitrogen", "phosphorus", "potassium") if getattr(self, f) is None]
