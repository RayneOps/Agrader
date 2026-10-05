"""The recommendation engine: hard rules, fit scores and mixed-cropping combinations.

Everything here is a pure function over plain data (see `facts.py`), so it can be tested
without a database and re-run later from a stored snapshot. Code decides what is allowed;
the LLM (phase 6) only ranks and explains inside these limits.
"""
from dataclasses import dataclass, field
from itertools import combinations

from .facts import CropFacts, EngineInput, RotationRuleFacts

LEVELS = {"low": 0, "medium": 1, "high": 2}
ROTATION_BASE = 0.60
ROTATION_EFFECTS = {"bonus": 0.40, "small_bonus": 0.20, "penalty": -0.30, "strong_penalty": -0.60}
GOOD_PAIR_BONUS = 5
TOP_OPTIONS = 5
COMPONENTS = [("ph", "pH"), ("nutrient", "Nutrients"), ("rotation", "Rotation"), ("season", "Season"), ("water", "Water")]


@dataclass
class Component:
    key: str
    label: str
    points: float
    max_points: float
    detail: str


@dataclass
class CropScore:
    crop: CropFacts
    components: list[Component]

    @property
    def total(self):
        return round(sum(c.points for c in self.components), 1)


@dataclass
class Removal:
    crop: str
    rule: str
    reason: str


@dataclass
class Option:
    crops: list[str]
    score: float
    components: list[Component]
    good_pairs: list[str] = field(default_factory=list)
    pair_bonus: float = 0
    crop_scores: list[CropScore] = field(default_factory=list)

    @property
    def is_single(self):
        return len(self.crops) == 1


@dataclass
class EngineResult:
    options: list[Option]
    removed: list[Removal]
    notices: list[str]
    mode: str  # "mono", "mixed", or "mixed_fallback"
    total_options: int


# --- Helpers ---

def days_left(inp: EngineInput):
    return (inp.season_end - inp.planting_date).days


def _fmt(value):
    return f"{value:g}"


def rule_matches(rule: RotationRuleFacts, previous: CropFacts, candidate: CropFacts):
    prev_ok = rule.previous_crop_id == previous.id if rule.previous_crop_id else rule.previous_family == previous.family
    next_ok = rule.next_crop_id == candidate.id if rule.next_crop_id else rule.next_family == candidate.family
    return prev_ok and next_ok


def rule_hits(rule: RotationRuleFacts, crop: CropFacts, inp: EngineInput):
    """The previous crop that triggers this rule for `crop`, or None. Rules look only at the season
    just before; the third-season rule (R8) also looks one season further back."""
    previous = inp.previous_crops(1)
    if rule.match == "repeat_third_season":
        same = next((p for p in previous if p.id == crop.id), None)
        return same if same and any(p.id == crop.id for p in inp.previous_crops(2)) else None
    return next((p for p in previous if rule_matches(rule, p, crop)), None)


def _rule_text(rule):
    return f"{rule.code}: {rule.reason}" if rule.reason else f"{rule.code} (no reason recorded)"


# --- Step 2: hard rules ---

def hard_rule_reasons(crop: CropFacts, inp: EngineInput):
    """Every reason this crop must be removed. Empty means it survives."""
    req = crop.requirement
    if req is None:
        return [("no_requirements", f"{crop.name} has no approved requirements yet, so it cannot be assessed.")]
    reasons = []
    if inp.season_label == "dry" and inp.water_source == "rain_fed":
        reasons.append(("dry_rain_fed", "No water source in the dry season: this farm is rain-fed."))
    ph = inp.reading.ph
    if ph < req.ph_min:
        reasons.append(("ph", f"Soil pH {_fmt(ph)} is below the minimum of {_fmt(req.ph_min)} for {crop.name}."))
    elif ph > req.ph_max:
        reasons.append(("ph", f"Soil pH {_fmt(ph)} is above the maximum of {_fmt(req.ph_max)} for {crop.name}."))
    if req.requires_standing_water and inp.water_source == "rain_fed":
        reasons.append(("standing_water", f"{crop.name} needs standing water, but this farm is rain-fed."))
    left = days_left(inp)
    season_waived = req.exempt_from_season_length or inp.water_source in ("irrigated", "fadama")
    if left < req.days_min and not season_waived:
        reasons.append((
            "season_length",
            f"{crop.name} needs at least {req.days_min} days, but only {max(left, 0)} days remain from planting "
            f"({inp.planting_date:%d %b %Y}) to the end of the {inp.season_label} season ({inp.season_end:%d %b %Y}).",
        ))
    for rule in inp.rotation_rules:
        if rule.effect == "block":
            previous = rule_hits(rule, crop, inp)
            if previous:
                reasons.append(("rotation_block", f"{previous.name} last season blocks {crop.name}. {_rule_text(rule)}"))
    return reasons


def apply_hard_rules(inp: EngineInput):
    survivors, removed = [], []
    for crop in inp.intended:
        reasons = hard_rule_reasons(crop, inp)
        if reasons:
            removed.extend(Removal(crop.name, rule, reason) for rule, reason in reasons)
        else:
            survivors.append(crop)
    return survivors, removed


# --- Step 3: fit score ---

def ph_fraction(ph, req):
    if req.ph_ideal_low <= ph <= req.ph_ideal_high:
        return 1.0
    if ph < req.ph_ideal_low:
        span = req.ph_ideal_low - req.ph_min
        return max(0.0, (ph - req.ph_min) / span) if span > 0 else (1.0 if ph >= req.ph_min else 0.0)
    span = req.ph_max - req.ph_ideal_high
    return max(0.0, (req.ph_max - ph) / span) if span > 0 else (1.0 if ph <= req.ph_max else 0.0)


def bucket(value, medium_min, high_min):
    if value < medium_min:
        return "low"
    return "medium" if value < high_min else "high"


def nutrient_fraction(crop: CropFacts, inp: EngineInput):
    """(fraction or None if nothing could be scored, detail text)."""
    parts, notes = [], []
    for key, name, measured in (
        ("n", "N", inp.reading.nitrogen), ("p", "P", inp.reading.phosphorus), ("k", "K", inp.reading.potassium),
    ):
        demand = getattr(crop.requirement, f"{key}_demand")
        share = inp.settings.nutrient_shares[key]
        if key == "n" and crop.fixes_nitrogen:
            parts.append((share, 1.0))
            notes.append("N full marks (fixes nitrogen)")
            continue
        if measured is None:
            notes.append(f"{name} not measured, left out")
            continue
        medium_min, high_min = inp.settings.thresholds[key]
        level = bucket(measured, medium_min, high_min)
        short = LEVELS[demand] - LEVELS[level]
        fraction = 1.0 if short <= 0 else 0.5 if short == 1 else 0.0
        parts.append((share, fraction))
        notes.append(f"{name} {level} vs {demand} demand")
    total_share = sum(share for share, _ in parts)
    if not parts or total_share <= 0:
        return None, "; ".join(notes)
    return sum(share * f for share, f in parts) / total_share, "; ".join(notes)


def rotation_fraction(crop: CropFacts, inp: EngineInput):
    applied = []
    fraction = ROTATION_BASE
    for rule in inp.rotation_rules:
        # Each matching rule counts once, however many previous crops match it.
        if rule.effect in ROTATION_EFFECTS and rule_hits(rule, crop, inp):
            fraction += ROTATION_EFFECTS[rule.effect]
            applied.append(f"{rule.code} {rule.effect.replace('_', ' ')}")
    fraction = min(1.0, max(0.0, fraction))
    if not inp.has_history:
        detail = "No history recorded: base score"
    elif applied:
        detail = "Base 60%, " + ", ".join(applied)
    else:
        detail = "Base 60%, no rotation rule applies"
    return fraction, detail


def season_fraction(crop: CropFacts, inp: EngineInput):
    left, req = days_left(inp), crop.requirement
    if left >= req.days_max:
        return 1.0, f"{left} days left, needs up to {req.days_max}"
    if left >= req.days_min:
        return 0.5, f"{left} days left, fits the shortest variety ({req.days_min} days)"
    return 0.0, f"{max(left, 0)} days left, needs at least {req.days_min}"


def water_fraction(crop: CropFacts, inp: EngineInput):
    if inp.water_source in ("irrigated", "fadama"):
        return 1.0, f"{inp.water_source.replace('_', ' ').capitalize()} farm"
    need = crop.requirement.water_low_mm
    ratio = min(1.0, max(0.0, days_left(inp) / inp.season_length)) if inp.season_length > 0 else 0.0
    available = inp.settings.seasonal_rainfall_mm * ratio
    detail = f"About {available:.0f} mm of rain expected after planting, needs {need} mm"
    if available >= need:
        return 1.0, detail
    if available >= 0.75 * need:
        return 0.5, detail
    return 0.0, detail


def score_crop(crop: CropFacts, inp: EngineInput, weights):
    """Score one surviving crop. `weights` are already scaled to add up to 100."""
    nutrient, nutrient_detail = nutrient_fraction(crop, inp)
    fractions = {
        "ph": (ph_fraction(inp.reading.ph, crop.requirement),
               f"pH {_fmt(inp.reading.ph)}, ideal {_fmt(crop.requirement.ph_ideal_low)}–{_fmt(crop.requirement.ph_ideal_high)}"),
        "nutrient": (nutrient, nutrient_detail),
        "rotation": rotation_fraction(crop, inp),
        "season": season_fraction(crop, inp),
        "water": water_fraction(crop, inp),
    }
    return CropScore(crop, [
        Component(key, label, round(weights[key] * fractions[key][0], 1), round(weights[key], 1), fractions[key][1])
        for key, label in COMPONENTS if key in weights
    ])


def effective_weights(inp: EngineInput):
    """Weights scaled to add up to 100. If the reading has no N, P or K at all, nutrient fit is
    left out for every crop and the other weights are scaled up instead (the same rule as a
    single missing nutrient, one level up)."""
    weights = dict(inp.settings.weights)
    r = inp.reading
    drop_nutrient = r.nitrogen is None and r.phosphorus is None and r.potassium is None
    if drop_nutrient:
        weights.pop("nutrient")
    total = sum(weights.values())
    return {k: v * 100 / total for k, v in weights.items()}, drop_nutrient


# --- Step 4: options ---

def _single(score: CropScore):
    return Option([score.crop.name], score.total, score.components, crop_scores=[score])


def _combination(scores: list[CropScore], inp: EngineInput):
    names = [s.crop.name for s in scores]
    good = []
    for a, b in combinations(scores, 2):
        if inp.pair_verdict(a.crop, b.crop) == "avoid":
            return None
        if inp.pair_verdict(a.crop, b.crop) == "good":
            good.append(f"{a.crop.name} + {b.crop.name}")
    mean = sum(s.total for s in scores) / len(scores)
    bonus = GOOD_PAIR_BONUS * len(good)
    components = [
        Component(
            first.key, first.label,
            round(sum(s.components[i].points for s in scores) / len(scores), 1),
            first.max_points, "Average of the crops",
        )
        for i, first in enumerate(scores[0].components)
    ]
    return Option(names, round(min(100.0, mean + bonus), 1), components, good, bonus, list(scores))


def build_options(scores: list[CropScore], inp: EngineInput):
    """(options, mode, notices). Mixed cropping ranks combinations only, falling back to single
    crops with a notice when no valid combination exists."""
    if inp.cropping_method != "mixed":
        return [_single(s) for s in scores], "mono", []
    combos = []
    for size in (2, 3):
        for group in combinations(scores, size):
            option = _combination(list(group), inp)
            if option:
                combos.append(option)
    if combos:
        return combos, "mixed", []
    if len(scores) == 1:
        why = f"Only {scores[0].crop.name} passed the rules, so there is nothing to combine it with."
    else:
        why = "Every pair of the remaining crops is listed as a pairing to avoid."
    return [_single(s) for s in scores], "mixed_fallback", [f"No mixed-cropping combination is possible. {why} Single crops are ranked instead."]


def run(inp: EngineInput) -> EngineResult:
    notices = list(inp.notices)
    survivors, removed = apply_hard_rules(inp)
    if not survivors:
        return EngineResult([], removed, notices + ["No crop on the shortlist passed the rules."], inp.cropping_method, 0)

    weights, dropped_nutrient = effective_weights(inp)
    if dropped_nutrient:
        notices.append("No nitrogen, phosphorus or potassium was measured, so nutrient fit is left out and the "
                       "other scores are scaled up to 100.")
    else:
        missing = [n for n, v in (("nitrogen", inp.reading.nitrogen), ("phosphorus", inp.reading.phosphorus),
                                  ("potassium", inp.reading.potassium)) if v is None]
        if missing:
            notices.append(f"Not measured: {', '.join(missing)}. Nutrient fit uses only what was measured.")

    scores = [score_crop(c, inp, weights) for c in survivors]
    options, mode, option_notices = build_options(scores, inp)
    notices += option_notices
    options.sort(key=lambda o: (-o.score, len(o.crops), o.crops))
    return EngineResult(options[:TOP_OPTIONS], removed, notices, mode, len(options))
