from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from farms.models import Season
from farms.wizard import next_step

from . import engine
from .facts import EngineConfigError, gather


def season_ranking(request, pk):
    """Code-only ranking of the farmer's shortlist. Nothing is saved yet (phase 6 adds the
    Recommendation record and the LLM explanation)."""
    season = get_object_or_404(Season.objects.select_related("farm__farmer"), pk=pk)
    if season.status == Season.Status.DRAFT and next_step(season) < 4:
        messages.info(request, "Finish the season details first.")
        return redirect("season_step", pk=season.pk, step=next_step(season))
    try:
        inp = gather(season)
    except EngineConfigError as exc:
        return render(request, "recommendations/ranking.html", {"season": season, "farm": season.farm, "error": str(exc)})
    result = engine.run(inp)
    return render(request, "recommendations/ranking.html", {
        "season": season, "farm": season.farm, "inp": inp, "result": result,
        "component_labels": engine.COMPONENTS,
        "good_pair_bonus": engine.GOOD_PAIR_BONUS, "top_options": engine.TOP_OPTIONS,
    })
