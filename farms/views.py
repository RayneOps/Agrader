from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import FarmerForm, FarmForm
from .models import Farm, Farmer

FARMERS_PER_PAGE = 25


def farmer_list(request):
    query = request.GET.get("q", "").strip()
    farmers = Farmer.objects.annotate(
        farm_count=Count("farms", distinct=True),
        # TODO(phase 4): also count soil readings as visits.
        last_visit=Max("farms__seasons__created_at"),
    )
    if query:
        farmers = farmers.filter(
            Q(name__icontains=query) | Q(phone__icontains=query) | Q(village__icontains=query)
        )
    page = Paginator(farmers.order_by("name"), FARMERS_PER_PAGE).get_page(request.GET.get("page"))
    return render(request, "farms/farmer_list.html", {"page": page, "query": query})


def farmer_create(request):
    form = FarmerForm(request.POST or None)
    duplicates = []
    if request.method == "POST" and form.is_valid():
        # Warn, but do not block: two different farmers can share a name in one village.
        if not request.POST.get("confirm_duplicate"):
            duplicates = list(Farmer.objects.filter(
                name__iexact=form.cleaned_data["name"], village__iexact=form.cleaned_data["village"]
            ))
        if not duplicates:
            farmer = form.save(commit=False)
            farmer.created_by = request.user
            farmer.save()
            messages.success(request, f"Farmer {farmer.name} added. Now add their first farm.")
            return redirect("farm_create", farmer_id=farmer.pk)
    return render(request, "farms/farmer_form.html", {
        "form": form, "title": "Add farmer", "submit": "Save farmer",
        "cancel_url": reverse("farmer_list"), "duplicates": duplicates,
    })


def farmer_edit(request, pk):
    farmer = get_object_or_404(Farmer, pk=pk)
    form = FarmerForm(request.POST or None, instance=farmer)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Farmer details saved.")
        return redirect(farmer)
    return render(
        request, "core/form.html",
        {"form": form, "title": f"Edit {farmer.name}", "submit": "Save changes", "cancel_url": farmer.get_absolute_url()},
    )


def farmer_detail(request, pk):
    farmer = get_object_or_404(Farmer, pk=pk)
    farms = farmer.farms.annotate(
        season_count=Count("seasons"), last_season=Max("seasons__planting_date")
    ).order_by("name")
    # TODO(phase 4): total soil readings. TODO(phase 6): total recommendations.
    return render(request, "farms/farmer_detail.html", {"farmer": farmer, "farms": farms})


def farm_create(request, farmer_id):
    farmer = get_object_or_404(Farmer, pk=farmer_id)
    form = FarmForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        farm = form.save(commit=False)
        farm.farmer = farmer
        farm.created_by = request.user
        farm.save()
        messages.success(request, f"Farm {farm.name} added.")
        return redirect(farm)
    return render(
        request, "farms/farm_form.html",
        {"form": form, "farmer": farmer, "title": f"Add farm for {farmer.name}", "submit": "Save farm",
         "cancel_url": farmer.get_absolute_url()},
    )


def farm_edit(request, pk):
    farm = get_object_or_404(Farm.objects.select_related("farmer"), pk=pk)
    form = FarmForm(request.POST or None, instance=farm)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Farm details saved.")
        return redirect(farm)
    return render(
        request, "farms/farm_form.html",
        {"form": form, "farmer": farm.farmer, "title": f"Edit {farm.name}", "submit": "Save changes",
         "cancel_url": farm.get_absolute_url()},
    )


def farm_detail(request, pk):
    farm = get_object_or_404(Farm.objects.select_related("farmer"), pk=pk)
    seasons = farm.seasons.order_by("-planting_date", "-created_at")
    # TODO(phase 4): "Start new season" wizard link. TODO(phase 8): soil trend charts.
    return render(request, "farms/farm_detail.html", {"farm": farm, "seasons": seasons})
