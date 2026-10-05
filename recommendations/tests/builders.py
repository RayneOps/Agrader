"""Small builders for engine tests, so each test states only what matters to it."""
from dataclasses import replace
from datetime import date

from recommendations.facts import (
    CropFacts, EngineInput, PairRuleFacts, ReadingFacts, RequirementFacts, RotationRuleFacts, SettingsFacts,
)

DEFAULT_REQ = dict(
    version=1, approved=True, ph_min=5.0, ph_ideal_low=5.8, ph_ideal_high=7.0, ph_max=8.0,
    n_demand="medium", p_demand="medium", k_demand="medium", water_low_mm=500, water_high_mm=800,
    days_min=90, days_max=120, requires_standing_water=False, exempt_from_season_length=False,
)


def crop(name, family="cereal", fixes_nitrogen=False, requirement=True, **req):
    return CropFacts(
        id=name.lower().replace(" ", "-"), name=name, family=family, fixes_nitrogen=fixes_nitrogen,
        requirement=RequirementFacts(**{**DEFAULT_REQ, **req}) if requirement else None,
    )


def settings(**overrides):
    base = dict(
        weights={"ph": 30, "nutrient": 25, "rotation": 25, "season": 10, "water": 10},
        nutrient_shares={"n": 1, "p": 1, "k": 1},
        thresholds={"n": (20, 40), "p": (10, 25), "k": (80, 150)},
        seasonal_rainfall_mm=1200,
    )
    return SettingsFacts(**{**base, **overrides})


def rule(code, previous, following, effect, reason="", match="pattern"):
    """`previous`/`following` are a family name or a CropFacts."""
    kw = {"code": code, "match": match, "effect": effect, "reason": reason}
    for side, value in (("previous", previous), ("next", following)):
        if isinstance(value, CropFacts):
            kw[f"{side}_crop_id"] = value.id
        elif value:
            kw[f"{side}_family"] = value
    return RotationRuleFacts(**kw)


def pair(a, b, verdict, reason=""):
    return PairRuleFacts(frozenset((a.id, b.id)), verdict, reason)


def make_input(intended, **overrides):
    """A rainy season planted 20 May 2027 on a rain-fed farm: 148 days left of a 173-day season."""
    base = dict(
        season_label="rainy", planting_date=date(2027, 5, 20),
        season_start=date(2027, 4, 25), season_end=date(2027, 10, 15),
        cropping_method="mono", water_source="rain_fed",
        reading=ReadingFacts(ph=6.5, nitrogen=30, phosphorus=15, potassium=100),
        intended=list(intended), previous={}, previous_free_text={},
        rotation_rules=[], pair_rules=[], settings=settings(), has_history=False,
    )
    return EngineInput(**{**base, **overrides})


def reading(**values):
    return replace(ReadingFacts(ph=6.5, nitrogen=30, phosphorus=15, potassium=100), **values)
