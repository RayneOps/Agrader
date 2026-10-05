"""Plain data the engine works on, and `gather()`, which loads it from the database.

Only approved crop requirements, pair rules and rotation rules are used, unless
ALLOW_UNAPPROVED_RULES is on, in which case `used_unapproved` is set so the screen shows the
draft-rules banner.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings as django_settings


class EngineConfigError(Exception):
    """Settings the engine needs are missing or invalid."""


@dataclass(frozen=True)
class RequirementFacts:
    version: int
    approved: bool
    ph_min: float
    ph_ideal_low: float
    ph_ideal_high: float
    ph_max: float
    n_demand: str
    p_demand: str
    k_demand: str
    water_low_mm: int
    water_high_mm: int
    days_min: int
    days_max: int
    requires_standing_water: bool
    exempt_from_season_length: bool


@dataclass(frozen=True)
class CropFacts:
    id: str
    name: str
    family: str
    fixes_nitrogen: bool
    requirement: RequirementFacts | None


@dataclass(frozen=True)
class ReadingFacts:
    ph: float
    nitrogen: float | None = None
    phosphorus: float | None = None
    potassium: float | None = None
    moisture_pct: float | None = None  # context for the LLM only, never scored
    temperature_c: float | None = None
    ec: float | None = None


@dataclass(frozen=True)
class RotationRuleFacts:
    code: str
    match: str
    effect: str
    reason: str
    previous_family: str = ""
    previous_crop_id: str | None = None
    next_family: str = ""
    next_crop_id: str | None = None
    approved: bool = True


@dataclass(frozen=True)
class PairRuleFacts:
    crop_ids: frozenset
    verdict: str
    reason: str
    approved: bool = True


@dataclass(frozen=True)
class SettingsFacts:
    weights: dict
    nutrient_shares: dict
    thresholds: dict  # {"n": (medium_min, high_min), ...}
    seasonal_rainfall_mm: float
    unverified: tuple = ()


@dataclass
class EngineInput:
    season_label: str
    planting_date: date
    season_start: date
    season_end: date
    cropping_method: str
    water_source: str
    reading: ReadingFacts
    intended: list[CropFacts]
    previous: dict  # {seasons_ago: [CropFacts]} for previous crops linked to a crop
    previous_free_text: dict  # {seasons_ago: [str]} context for the LLM
    rotation_rules: list[RotationRuleFacts]
    pair_rules: list[PairRuleFacts]
    settings: SettingsFacts
    has_history: bool = True
    used_unapproved: bool = False
    notices: list[str] = field(default_factory=list)

    @property
    def season_length(self):
        return (self.season_end - self.season_start).days

    def previous_crops(self, seasons_ago):
        return self.previous.get(seasons_ago, [])

    def pair_verdict(self, a: CropFacts, b: CropFacts):
        key = frozenset((a.id, b.id))
        return next((p.verdict for p in self.pair_rules if p.crop_ids == key), None)


# --- Loading from the database ---

def _number(values, key):
    try:
        return float(Decimal(values[key]))
    except KeyError:
        raise EngineConfigError(f"Score setting '{key}' is missing. Run seed_crops or add it on the Score settings screen.")
    except InvalidOperation:
        raise EngineConfigError(f"Score setting '{key}' is not a number.")


def load_settings():
    from crops.models import ScoreSetting

    rows = {s.key: s for s in ScoreSetting.objects.all()}
    values = {k: s.value for k, s in rows.items()}
    weights = {k: _number(values, f"weight_{k}") for k in ("ph", "nutrient", "rotation", "season", "water")}
    if sum(weights.values()) <= 0:
        raise EngineConfigError("The score weights add up to zero.")
    thresholds = {}
    for k in ("n", "p", "k"):
        medium, high = _number(values, f"{k}_medium_min_mg_kg"), _number(values, f"{k}_high_min_mg_kg")
        if medium > high:
            raise EngineConfigError(f"The {k.upper()} medium threshold is above the high threshold.")
        thresholds[k] = (medium, high)
    return SettingsFacts(
        weights=weights,
        nutrient_shares={k: _number(values, f"nutrient_share_{k}") for k in ("n", "p", "k")},
        thresholds=thresholds,
        seasonal_rainfall_mm=_number(values, "seasonal_rainfall_mm"),
        unverified=tuple(sorted(k for k, s in rows.items() if not s.verified)),
    )


def crop_facts(crop, allow_unapproved):
    versions = crop.requirements.order_by("-version")
    if not allow_unapproved:
        versions = versions.filter(approved=True)
    req = versions.first()
    return CropFacts(
        id=str(crop.pk), name=crop.name, family=crop.family, fixes_nitrogen=crop.fixes_nitrogen,
        requirement=None if req is None else RequirementFacts(
            version=req.version, approved=req.approved,
            ph_min=float(req.ph_min), ph_ideal_low=float(req.ph_ideal_low),
            ph_ideal_high=float(req.ph_ideal_high), ph_max=float(req.ph_max),
            n_demand=req.n_demand, p_demand=req.p_demand, k_demand=req.k_demand,
            water_low_mm=req.water_low_mm, water_high_mm=req.water_high_mm,
            days_min=req.days_min, days_max=req.days_max,
            requires_standing_water=req.requires_standing_water,
            exempt_from_season_length=req.exempt_from_season_length,
        ),
    )


def gather(season):
    """Build the engine input for a draft season. Raises EngineConfigError if something it
    needs is missing."""
    from crops.models import CropPairRule, RotationRule
    from farms.models import PreviousCrop
    from farms.seasons import season_window

    allow = django_settings.ALLOW_UNAPPROVED_RULES
    reading = season.readings.order_by("-taken_at").first()
    if reading is None:
        raise EngineConfigError("This season has no soil reading yet.")
    if not season.cropping_method or not season.intended_crops.exists():
        raise EngineConfigError("This season has no shortlist yet.")
    window = season_window(season.label, season.planting_date)
    if window is None:
        raise EngineConfigError("The season calendar is missing from Score settings.")

    notices = []
    intended = [crop_facts(ic.crop, allow) for ic in season.intended_crops.select_related("crop")]

    previous, free_text, any_history = {}, {}, False
    for row in season.previous_crops.select_related("crop"):
        if row.free_text == PreviousCrop.UNKNOWN:
            continue
        any_history = True
        if row.crop_id:
            previous.setdefault(row.seasons_ago, []).append(crop_facts(row.crop, allow))
        else:
            free_text.setdefault(row.seasons_ago, []).append(row.free_text)

    rotation_qs = RotationRule.objects.all()
    pair_qs = CropPairRule.objects.all()
    if not allow:
        skipped_rotation = rotation_qs.filter(approved=False).count()
        skipped_pairs = pair_qs.filter(approved=False).count()
        rotation_qs, pair_qs = rotation_qs.filter(approved=True), pair_qs.filter(approved=True)
        if skipped_rotation:
            notices.append(f"{skipped_rotation} rotation rule(s) are not approved yet and were not used.")
        if skipped_pairs and season.cropping_method == "mixed":
            notices.append(f"{skipped_pairs} pair rule(s) are not approved yet and were not used.")

    rotation = [
        RotationRuleFacts(
            code=r.code, match=r.match, effect=r.effect, reason=r.reason,
            previous_family=r.previous_family, previous_crop_id=str(r.previous_crop_id) if r.previous_crop_id else None,
            next_family=r.next_family, next_crop_id=str(r.next_crop_id) if r.next_crop_id else None,
            approved=r.approved,
        )
        for r in rotation_qs
    ]
    pairs = [
        PairRuleFacts(frozenset((str(p.crop_a_id), str(p.crop_b_id))), p.verdict, p.reason, p.approved)
        for p in pair_qs
    ]

    settings = load_settings()
    if any(k.endswith("_mg_kg") for k in settings.unverified):
        notices.append("Nutrient thresholds are placeholders and not verified, so nutrient scores are not reliable yet.")

    used_unapproved = allow and (
        any(c.requirement and not c.requirement.approved for c in intended)
        or any(not r.approved for r in rotation) or any(not p.approved for p in pairs)
    )

    return EngineInput(
        season_label=season.label, planting_date=season.planting_date,
        season_start=window[0], season_end=window[1],
        cropping_method=season.cropping_method, water_source=season.farm.water_source,
        reading=ReadingFacts(
            ph=reading.ph, nitrogen=reading.nitrogen, phosphorus=reading.phosphorus, potassium=reading.potassium,
            moisture_pct=reading.moisture_pct, temperature_c=reading.temperature_c, ec=reading.ec,
        ),
        intended=intended, previous=previous, previous_free_text=free_text,
        rotation_rules=rotation, pair_rules=pairs, settings=settings,
        has_history=any_history, used_unapproved=used_unapproved, notices=notices,
    )
