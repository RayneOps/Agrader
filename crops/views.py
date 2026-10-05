import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User

from .forms import CropForm, CropRequirementForm, NewCropForm, PairRuleForm, RotationRuleForm, ScoreSettingForm
from .models import Crop, CropPairRule, CropRequirement, RotationRule, ScoreSetting


def knowledge_context(request, tab):
    """Banners and tab state shared by every Crop knowledge page."""
    pending = (
        CropRequirement.objects.filter(approved=False).count()
        + CropPairRule.objects.filter(approved=False).count()
        + RotationRule.objects.filter(approved=False).count()
    )
    return {
        "tab": tab,
        "approver_exists": User.objects.filter(can_approve_rules=True, is_active=True).exists(),
        "allow_unapproved": settings.ALLOW_UNAPPROVED_RULES,
        "pending_count": pending,
        "unverified_thresholds": ScoreSetting.objects.filter(group=ScoreSetting.Group.THRESHOLDS, verified=False).exists(),
        "unverified_settings": ScoreSetting.objects.filter(verified=False).count(),
    }


def _save_edit(request, form, success_url, noun):
    """Save a content edit. It always needs fresh approval, and the editor cannot approve it."""
    if form.instance.pk and not form.has_changed():
        messages.info(request, "No changes to save.")
        return redirect(success_url)
    item = form.save(commit=False)
    if item._state.adding:
        item.created_by = request.user
    item.mark_edited(request.user)
    item.save()
    messages.success(request, f"{noun} saved. It now needs approval by the rule approver.")
    return redirect(success_url)


def _approve(request, item, success_url, verb="approve"):
    done = {"approve": "approved", "verify": "verified"}[verb]
    try:
        getattr(item, verb)(request.user)
    except PermissionError as exc:
        messages.error(request, f"Not {done}: {exc}")
    else:
        messages.success(request, f"{item} {done}.")
    return redirect(success_url)


def _form_page(request, form, title, cancel_url, submit="Save"):
    return render(request, "core/form.html", {"form": form, "title": title, "submit": submit, "cancel_url": cancel_url})


# --- Crops and requirement versions ---

def crop_list(request):
    crops = Crop.objects.prefetch_related(
        Prefetch("requirements", queryset=CropRequirement.objects.order_by("-version"))
    )
    rows = []
    for crop in crops:
        versions = list(crop.requirements.all())
        rows.append({
            "crop": crop,
            "latest": versions[0] if versions else None,
            "approved": next((v for v in versions if v.approved), None),
        })
    return render(request, "crops/crop_list.html", {**knowledge_context(request, "crops"), "rows": rows})


def crop_detail(request, pk):
    crop = get_object_or_404(Crop, pk=pk)
    versions = list(crop.requirements.select_related("created_by", "approved_by"))
    for version in versions:
        version.block_reason = version.approval_block_reason(request.user)
    return render(request, "crops/crop_detail.html", {
        **knowledge_context(request, "crops"),
        "crop": crop,
        "versions": versions,
        "latest": versions[0] if versions else None,
        "in_use": next((v for v in versions if v.approved or settings.ALLOW_UNAPPROVED_RULES), None),
    })


def crop_new(request):
    form = NewCropForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        crop = form.save()
        messages.success(
            request,
            f"{crop.name} added. It cannot be recommended until its requirements are added and approved.",
        )
        return redirect("requirement_new", pk=crop.pk)
    return _form_page(request, form, "Add crop", reverse("crop_list"), submit="Add crop")


def crop_edit(request, pk):
    crop = get_object_or_404(Crop, pk=pk)
    form = CropForm(request.POST or None, instance=crop)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Crop details saved.")
        return redirect("crop_detail", pk=crop.pk)
    return _form_page(request, form, f"Edit {crop.name}", reverse("crop_detail", args=[crop.pk]))


def requirement_new(request, pk):
    crop = get_object_or_404(Crop, pk=pk)
    latest = crop.latest_requirement()
    form = CropRequirementForm(request.POST or None, initial=latest.content() if latest else None)
    if request.method == "POST" and form.is_valid():
        if latest and form.cleaned_data == latest.content():
            messages.info(request, "No changes, so no new version was created.")
            return redirect("crop_detail", pk=crop.pk)
        version = form.save(commit=False)
        version.crop = crop
        version.created_by = request.user
        version.mark_edited(request.user)
        version.save()
        messages.success(request, f"Saved as {version}. It needs approval before the engine uses it.")
        return redirect("crop_detail", pk=crop.pk)
    next_number = (latest.version + 1) if latest else 1
    return _form_page(
        request, form, f"{crop.name}: new requirements version (v{next_number})",
        reverse("crop_detail", args=[crop.pk]), submit=f"Save as v{next_number}",
    )


@require_POST
def requirement_approve(request, pk):
    version = get_object_or_404(CropRequirement.objects.select_related("crop"), pk=pk)
    return _approve(request, version, reverse("crop_detail", args=[version.crop_id]))


# --- Pair rules ---

def pair_list(request):
    crop_id = request.GET.get("crop", "")
    try:
        crop_id = str(uuid.UUID(crop_id)) if crop_id else ""
    except ValueError:
        crop_id = ""
    pairs = CropPairRule.objects.select_related("crop_a", "crop_b", "approved_by", "edited_by")
    if crop_id:
        pairs = pairs.filter(Q(crop_a_id=crop_id) | Q(crop_b_id=crop_id))
    pairs = list(pairs)
    for pair in pairs:
        pair.block_reason = pair.approval_block_reason(request.user)
    return render(request, "crops/pair_list.html", {
        **knowledge_context(request, "pairs"), "pairs": pairs, "crops": Crop.objects.all(), "crop_id": crop_id,
    })


def pair_new(request):
    form = PairRuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        return _save_edit(request, form, reverse("pair_list"), "Pair rule")
    return _form_page(request, form, "New pair rule", reverse("pair_list"))


def pair_edit(request, pk):
    pair = get_object_or_404(CropPairRule, pk=pk)
    form = PairRuleForm(request.POST or None, instance=pair)
    if request.method == "POST" and form.is_valid():
        return _save_edit(request, form, reverse("pair_list"), "Pair rule")
    return _form_page(request, form, f"Edit pair rule: {pair.crop_a} + {pair.crop_b}", reverse("pair_list"))


@require_POST
def pair_approve(request, pk):
    return _approve(request, get_object_or_404(CropPairRule, pk=pk), reverse("pair_list"))


# --- Rotation rules ---

def rotation_list(request):
    rules = list(RotationRule.objects.select_related("previous_crop", "next_crop", "approved_by", "edited_by"))
    for rule in rules:
        rule.block_reason = rule.approval_block_reason(request.user)
    return render(request, "crops/rotation_list.html", {**knowledge_context(request, "rotation"), "rules": rules})


def rotation_new(request):
    form = RotationRuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        return _save_edit(request, form, reverse("rotation_list"), "Rotation rule")
    return _form_page(request, form, "New rotation rule", reverse("rotation_list"))


def rotation_edit(request, pk):
    rule = get_object_or_404(RotationRule, pk=pk)
    form = RotationRuleForm(request.POST or None, instance=rule)
    if request.method == "POST" and form.is_valid():
        return _save_edit(request, form, reverse("rotation_list"), "Rotation rule")
    return _form_page(request, form, f"Edit rotation rule {rule.code}", reverse("rotation_list"))


@require_POST
def rotation_approve(request, pk):
    return _approve(request, get_object_or_404(RotationRule, pk=pk), reverse("rotation_list"))


# --- Score settings ---

WEIGHT_TOTAL = Decimal(100)


def setting_list(request):
    items = list(ScoreSetting.objects.select_related("verified_by", "edited_by"))
    for item in items:
        item.block_reason = item.approval_block_reason(request.user)
    groups = [(label, [i for i in items if i.group == value]) for value, label in ScoreSetting.Group.choices]
    try:
        weight_total = sum(Decimal(i.value) for i in items if i.group == ScoreSetting.Group.WEIGHTS)
    except InvalidOperation:
        weight_total = None
    return render(request, "crops/setting_list.html", {
        **knowledge_context(request, "settings"),
        "groups": [(label, rows) for label, rows in groups if rows],
        "weight_total": weight_total,
        "weights_ok": weight_total == WEIGHT_TOTAL,
    })


def setting_edit(request, pk):
    item = get_object_or_404(ScoreSetting, pk=pk)
    form = ScoreSettingForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        return _save_edit(request, form, reverse("setting_list"), "Setting")
    form.fields["value"].help_text = item.description
    form.fields["value"].label = item.key
    return _form_page(request, form, f"Edit {item.key}", reverse("setting_list"))


@require_POST
def setting_verify(request, pk):
    return _approve(request, get_object_or_404(ScoreSetting, pk=pk), reverse("setting_list"), verb="verify")
