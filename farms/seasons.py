"""Season calendar helpers. The calendar dates are ScoreSettings, so they can be corrected in the app."""
from datetime import date

from crops.models import ScoreSetting

from .models import Farm, Season


def _on(year, month_day):
    month, day = month_day
    if (month, day) == (2, 29):
        try:
            return date(year, 2, 29)
        except ValueError:
            return date(year, 2, 28)
    return date(year, month, day)


def season_window(label, planting_date):
    """(start, end) of the labelled season that the planting date belongs to, or None if the
    calendar settings are missing.

    A dry season runs from November into the next year, so a dry-season date in the first half
    of a year belongs to the dry season that started the previous November.
    """
    if label == Season.Label.RAINY:
        start, end = ScoreSetting.month_day("rainy_season_start"), ScoreSetting.month_day("rainy_season_end")
        if not (start and end):
            return None
        return _on(planting_date.year, start), _on(planting_date.year, end)
    start, end = ScoreSetting.month_day("dry_season_start"), ScoreSetting.month_day("dry_season_end")
    if not (start and end):
        return None
    start_year = planting_date.year - 1 if planting_date.month <= 6 else planting_date.year
    return _on(start_year, start), _on(start_year + 1, end)


def planting_date_warning(label, planting_date):
    window = season_window(label, planting_date)
    if window is None:
        return "The season calendar is missing from Score settings, so the planting date was not checked."
    start, end = window
    if not start <= planting_date <= end:
        name = Season.Label(label).label.lower()
        return (
            f"The planting date {planting_date:%d %b %Y} is outside the {name} "
            f"({start:%d %b %Y} to {end:%d %b %Y}). Check the date and the season."
        )
    return None


def dry_season_rain_fed_warning(label, water_source):
    if label == Season.Label.DRY and water_source == Farm.WaterSource.RAIN_FED:
        return (
            "This is a dry season on a rain-fed farm. With no water source in the dry season, every crop "
            "will be removed. Check the farm's water source before going on."
        )
    return None
