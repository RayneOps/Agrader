"""New season wizard. Every step saves to the draft Season straight away, so a dropped
connection loses nothing, and "Start new season" resumes an existing draft."""
from datetime import timedelta

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from crops.models import Crop
from readings.forms import ManualReadingForm
from readings.models import SoilReading, implausible_values

from .forms import IntendedCropsForm, SeasonStartForm
from .models import Farm, IntendedCrop, PreviousCrop, Season
from .seasons import dry_season_rain_fed_warning, planting_date_warning

STEPS = [(1, "History"), (2, "Crops"), (3, "Soil"), (4, "Review")]
SENSOR_PICKUP_WINDOW = timedelta(hours=24)


def next_step(season):
    """The first step that still needs input. Step 1 is done once the draft exists."""
    if not season.cropping_method or not season.intended_crops.exists():
        return 2
    if not season.readings.exists():
        return 3
    return 4


def step_url(season, step):
    return redirect("season_step", pk=season.pk, step=step)


def season_start(request, farm_id):
    farm = get_object_or_404(Farm.objects.select_related("farmer"), pk=farm_id)
    draft = farm.seasons.filter(status=Season.Status.DRAFT).first()
    if draft:
        messages.info(request, "This farm already has an open season. Carrying on where it was left.")
        return step_url(draft, next_step(draft))
    return _step_history(request, farm, None)


def season_step(request, pk, step):
    season = get_object_or_404(Season.objects.select_related("farm__farmer"), pk=pk)
    if season.status != Season.Status.DRAFT:
        messages.info(request, "This season is no longer a draft, so it cannot be changed here.")
        return redirect(season.farm)
    reachable = next_step(season)
    if step > reachable:
        return step_url(season, reachable)
    if step == 1:
        return _step_history(request, season.farm, season)
    handler = {2: _step_crops, 3: _step_soil, 4: _step_review}.get(step)
    return handler(request, season) if handler else step_url(season, reachable)


def _render(request, template, season, farm, step, **context):
    reachable = next_step(season) if season else 1
    return render(request, template, {
        "farm": farm, "season": season, "step": step, "reachable": reachable,
        "steps": STEPS, **context,
    })


# --- Step 1: season and history ---

def _slots(earlier):
    """Which past seasons to ask about, as (seasons_ago, heading, must_answer)."""
    if not earlier:
        return [(1, "Last season", False), (2, "2 seasons ago", False), (3, "3 seasons ago", False)]
    slots = [(1, f"What was actually planted last season? ({earlier[0].get_label_display()} {earlier[0].year})", True)]
    for n in (2, 3):
        name = f" ({earlier[n - 1].get_label_display()} {earlier[n - 1].year})" if len(earlier) >= n else ""
        slots.append((n, f"{n} seasons ago{name}, from the farm's records", False))
    return slots


def _initial_history(rows, fields):
    """Form initial data from (seasons_ago, crop_id, free_text) rows."""
    initial, others = {}, {}
    for seasons_ago, crop_id, text in rows:
        p = f"s{seasons_ago}_"
        if crop_id:
            initial.setdefault(p + "crops", []).append(crop_id)
        elif text == PreviousCrop.FALLOW:
            initial[p + "fallow"] = True
        elif text == PreviousCrop.UNKNOWN:
            if p + "unknown" in fields:
                initial[p + "unknown"] = True
        else:
            others.setdefault(p + "other", []).append(text)
    initial.update({k: ", ".join(v) for k, v in others.items()})
    return initial


def _sync(queryset, wanted, key, create):
    """Make the rows in `queryset` match the `wanted` keys, deleting and creating one at a time
    so that every change is audited."""
    existing = {key(row): row for row in queryset}
    for k, row in existing.items():
        if k not in wanted:
            row.delete()
    for k in wanted - existing.keys():
        create(k)


def _step_history(request, farm, season):
    earlier = list(farm.seasons.exclude(pk=season.pk if season else None).order_by("-planting_date", "-created_at")[:3])
    slots = _slots(earlier)
    if season:
        rows = season.previous_crops.values_list("seasons_ago", "crop_id", "free_text")
        initial = {"label": season.label, "planting_date": season.planting_date}
    else:
        # A returning farm's older seasons come from what was recorded on the last season.
        # Last season itself is always asked: we never assume the recommendation was followed.
        rows = [
            (sa + 1, crop_id, text)
            for sa, crop_id, text in (
                earlier[0].previous_crops.filter(seasons_ago__lte=2).values_list("seasons_ago", "crop_id", "free_text")
                if earlier else []
            )
        ]
        initial = {}
    form = SeasonStartForm(request.POST or None, slots=slots, crops=Crop.objects.all())
    if not request.POST:
        form.initial = {**initial, **_initial_history(rows, form.fields)}

    if request.method == "POST" and form.is_valid():
        label, planting_date = form.cleaned_data["label"], form.cleaned_data["planting_date"]
        try:
            with transaction.atomic():
                if season is None:
                    season = Season.objects.create(
                        farm=farm, label=label, planting_date=planting_date, year=planting_date.year,
                        status=Season.Status.DRAFT, created_by=request.user,
                    )
                elif (season.label, season.planting_date) != (label, planting_date):
                    season.label, season.planting_date, season.year = label, planting_date, planting_date.year
                    season.save()
                _sync(
                    season.previous_crops.all(), form.previous_crop_rows(),
                    key=lambda r: (r.seasons_ago, r.crop_id, r.free_text),
                    create=lambda k: PreviousCrop.objects.create(
                        season=season, seasons_ago=k[0], crop_id=k[1], free_text=k[2], created_by=request.user
                    ),
                )
        except IntegrityError:
            # Someone else opened a draft for this farm at the same moment.
            return season_start(request, farm.pk)
        return step_url(season, 2)

    last_shortlist = list(earlier[0].intended_crops.select_related("crop")) if earlier else []
    return _render(
        request, "farms/wizard/step_history.html", season, farm, 1,
        form=form, returning=bool(earlier), last_season=earlier[0] if earlier else None, last_shortlist=last_shortlist,
    )


# --- Step 2: shortlist and cropping method ---

def _warnings(season):
    return [w for w in (
        planting_date_warning(season.label, season.planting_date),
        dry_season_rain_fed_warning(season.label, season.farm.water_source),
    ) if w]


def _step_crops(request, season):
    form = IntendedCropsForm(
        request.POST or None, crops=Crop.objects.filter(active=True),
        initial={"cropping_method": season.cropping_method or None,
                 "crops": list(season.intended_crops.values_list("crop_id", flat=True))},
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if season.cropping_method != form.cleaned_data["cropping_method"]:
                season.cropping_method = form.cleaned_data["cropping_method"]
                season.save()
            _sync(
                season.intended_crops.all(), {c.pk for c in form.cleaned_data["crops"]},
                key=lambda r: r.crop_id,
                create=lambda crop_id: IntendedCrop.objects.create(season=season, crop_id=crop_id, created_by=request.user),
            )
        return step_url(season, 3)
    return _render(request, "farms/wizard/step_crops.html", season, season.farm, 2, form=form, warnings=_warnings(season))


# --- Step 3: soil reading ---

def _recent_sensor_reading(season):
    return (
        SoilReading.objects
        .filter(farm=season.farm, source=SoilReading.Source.SENSOR, taken_at__gte=timezone.now() - SENSOR_PICKUP_WINDOW)
        .filter(Q(season__isnull=True) | Q(season=season))
        .order_by("-taken_at").first()
    )


def _step_soil(request, season):
    recent = _recent_sensor_reading(season)
    current = season.readings.order_by("-taken_at").first()
    action = request.POST.get("action")

    if request.method == "POST" and action == "use_sensor":
        reading = get_object_or_404(
            SoilReading, pk=request.POST.get("reading"), farm=season.farm, source=SoilReading.Source.SENSOR,
        )
        if reading.season_id not in (None, season.pk):
            messages.error(request, "That reading belongs to another season.")
        elif reading.season_id is None:
            reading.season = season
            reading.save()
        return step_url(season, 4)

    form = ManualReadingForm(request.POST if action == "manual" else None)
    implausible = []
    if action == "manual" and form.is_valid():
        implausible = implausible_values(form.cleaned_data)
        if not implausible or request.POST.get("confirm_implausible"):
            reading = form.save(commit=False)
            reading.farm, reading.season = season.farm, season
            reading.source = SoilReading.Source.MANUAL
            reading.created_by = request.user
            reading.save()
            return step_url(season, 4)
    return _render(
        request, "farms/wizard/step_soil.html", season, season.farm, 3,
        form=form, recent=recent, current=current, implausible=implausible,
    )


# --- Step 4: review ---

def _step_review(request, season):
    previous = {}
    for row in season.previous_crops.select_related("crop"):
        previous.setdefault(row.seasons_ago, []).append(str(row))
    reading = season.readings.order_by("-taken_at").first()
    return _render(
        request, "farms/wizard/step_review.html", season, season.farm, 4,
        warnings=_warnings(season),
        previous=sorted(previous.items()),
        intended=[ic.crop for ic in season.intended_crops.select_related("crop")],
        reading=reading,
        # TODO(phase 5): "Request recommendation" runs the rules and scoring.
    )
