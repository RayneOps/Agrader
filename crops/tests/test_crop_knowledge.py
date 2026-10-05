from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from crops.models import Crop, CropPairRule, CropRequirement, RotationRule, ScoreSetting


def seed():
    call_command("seed_crops", stdout=StringIO())


def make_user(email, approver=False):
    return User.objects.create_superuser(
        email=email, password="x" * 12, full_name=email.split("@")[0].title(), can_approve_rules=approver
    )


class SeedCropsTests(TestCase):
    def test_loads_everything_as_unapproved_drafts(self):
        seed()
        self.assertEqual(Crop.objects.count(), 12)
        self.assertEqual(CropRequirement.objects.count(), 12)
        self.assertEqual(CropPairRule.objects.filter(verdict="good").count(), 17)
        self.assertEqual(CropPairRule.objects.filter(verdict="avoid").count(), 10 + 11)
        self.assertFalse(CropRequirement.objects.filter(approved=True).exists())
        self.assertFalse(CropPairRule.objects.filter(approved=True).exists())
        self.assertFalse(RotationRule.objects.filter(approved=True).exists())
        self.assertFalse(ScoreSetting.objects.filter(verified=True).exists())

    def test_flags_and_values(self):
        seed()
        lowland = Crop.objects.get(name="Rice (lowland)").latest_requirement()
        self.assertTrue(lowland.requires_standing_water)
        self.assertTrue(Crop.objects.get(name="Yam").latest_requirement().exempt_from_season_length)
        self.assertEqual(CropRequirement.objects.filter(requires_standing_water=True).count(), 1)
        self.assertEqual(CropRequirement.objects.filter(exempt_from_season_length=True).count(), 1)
        cowpea = Crop.objects.get(name="Beans (cowpea)")
        self.assertTrue(cowpea.fixes_nitrogen)
        self.assertEqual(cowpea.family, "legume")
        soya = Crop.objects.get(name="Soya beans").latest_requirement()
        self.assertEqual((str(soya.ph_min), soya.p_demand, soya.days_max), ("5.5", "high", 120))
        self.assertEqual(ScoreSetting.objects.get(key="seasonal_rainfall_mm").value, "1200")
        self.assertEqual(ScoreSetting.objects.get(key="rainy_season_end").value, "10-15")
        self.assertEqual(ScoreSetting.objects.get(key="dry_season_end").value, "03-31")

    def test_rotation_rules_shape(self):
        seed()
        self.assertEqual(RotationRule.objects.filter(code="R2").count(), 3)
        r6 = RotationRule.objects.filter(code="R6")
        self.assertEqual(r6.count(), 2)
        okro = Crop.objects.get(name="Okro")
        self.assertTrue(r6.filter(previous_crop=okro, next_family="solanaceae").exists())
        self.assertTrue(r6.filter(previous_family="solanaceae", next_crop=okro).exists())
        r8 = RotationRule.objects.get(code="R8")
        self.assertEqual((r8.match, r8.effect), ("repeat_third_season", "strong_penalty"))
        self.assertEqual(RotationRule.objects.get(code="R5").effect, "block")

    def test_rice_lowland_avoids_every_other_crop(self):
        seed()
        lowland = Crop.objects.get(name="Rice (lowland)")
        for crop in Crop.objects.exclude(pk=lowland.pk):
            self.assertEqual(CropPairRule.find(lowland, crop).verdict, "avoid", crop.name)

    def test_rerun_never_overwrites_edited_or_approved(self):
        seed()
        approver = make_user("samantha@agrader.hq", approver=True)
        editor = make_user("ishaq@agrader.hq")
        maize, beans = Crop.objects.get(name="Maize"), Crop.objects.get(name="Beans (cowpea)")
        pair = CropPairRule.find(maize, beans)
        pair.mark_edited(editor)
        pair.reason = "Checked in the field."
        pair.save()
        rule = RotationRule.objects.get(code="R1")
        rule.approve(approver)
        setting = ScoreSetting.objects.get(key="seasonal_rainfall_mm")
        setting.mark_edited(editor)
        setting.value = "1100"
        setting.save()
        CropRequirement.objects.create(
            crop=maize, created_by=editor, edited_by=editor,
            **{**maize.latest_requirement().content(), "days_max": 110},
        )
        okro = Crop.objects.get(name="Okro")
        CropPairRule.find(maize, okro).delete()  # a deleted seed record is restored

        seed()
        pair = CropPairRule.find(maize, beans)
        self.assertEqual((pair.reason, pair.edited_by), ("Checked in the field.", editor))
        self.assertEqual(CropPairRule.find(maize, okro).verdict, "good")
        self.assertEqual(CropPairRule.objects.count(), 38)
        rule.refresh_from_db()
        self.assertTrue(rule.approved)
        setting.refresh_from_db()
        self.assertEqual(setting.value, "1100")
        self.assertEqual(maize.requirements.count(), 2)
        self.assertEqual(maize.latest_requirement().days_max, 110)


class ModelRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed()

    def setUp(self):
        self.maize = Crop.objects.get(name="Maize")

    def test_requirement_versions_are_immutable_and_numbered(self):
        v1 = self.maize.latest_requirement()
        v1.days_max = 999
        with self.assertRaises(ValueError):
            v1.save()
        v2 = CropRequirement.objects.create(crop=self.maize, **{**v1.content(), "days_max": 100})
        self.assertEqual(v2.version, 2)

    def test_pair_is_stored_once_per_unordered_pair(self):
        okro, yam = Crop.objects.get(name="Okro"), Crop.objects.get(name="Yam")
        CropPairRule.find(okro, yam).delete()
        pair = CropPairRule.objects.create(crop_a=okro, crop_b=yam, verdict="good")
        self.assertLess(pair.crop_a_id, pair.crop_b_id)
        self.assertEqual(CropPairRule.find(yam, okro), pair)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CropPairRule.objects.create(crop_a=yam, crop_b=okro, verdict="avoid")

    def test_rotation_rule_needs_exactly_one_side_each(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            RotationRule.objects.create(
                code="X", previous_family="cereal", previous_crop=self.maize, next_family="legume",
                effect="bonus", reason="x",
            )

    def test_month_day_setting_validation(self):
        from django.core.exceptions import ValidationError
        setting = ScoreSetting.objects.get(key="rainy_season_end")
        for bad in ["10/15", "13-01", "02-30", "1015"]:
            setting.value = bad
            with self.assertRaises(ValidationError, msg=bad):
                setting.full_clean()
        setting.value = "02-29"
        setting.full_clean()


class ApprovalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed()

    def setUp(self):
        self.approver = make_user("samantha@agrader.hq", approver=True)
        self.editor = make_user("ishaq@agrader.hq")

    def test_only_the_approver_can_approve(self):
        pair = CropPairRule.objects.first()
        with self.assertRaises(PermissionError):
            pair.approve(self.editor)
        pair.approve(self.approver)
        pair.refresh_from_db()
        self.assertEqual((pair.approved, pair.approved_by), (True, self.approver))
        self.assertIsNotNone(pair.approved_at)

    def test_approver_may_approve_own_edit_as_a_separate_step(self):
        rule = RotationRule.objects.get(code="R3")
        rule.mark_edited(self.approver)
        rule.save()
        self.assertFalse(rule.approved, "editing never approves")
        rule.approve(self.approver)
        rule.refresh_from_db()
        self.assertEqual((rule.approved, rule.approved_by), (True, self.approver))

    def test_editor_without_flag_cannot_approve_own_edit(self):
        rule = RotationRule.objects.get(code="R3")
        rule.mark_edited(self.editor)
        rule.save()
        with self.assertRaises(PermissionError):
            rule.approve(self.editor)

    def test_editing_resets_approval(self):
        self.client.force_login(self.editor)
        pair = CropPairRule.objects.filter(verdict="good").first()
        pair.approve(self.approver)
        self.client.post(reverse("pair_edit", args=[pair.pk]), {
            "crop_a": pair.crop_a_id, "crop_b": pair.crop_b_id, "verdict": "good", "reason": "Shade for the legume.",
        })
        pair.refresh_from_db()
        self.assertFalse(pair.approved)
        self.assertIsNone(pair.approved_by)
        self.assertEqual(pair.edited_by, self.editor)

    def test_new_version_via_screen_then_approval(self):
        maize = Crop.objects.get(name="Maize")
        v1 = maize.latest_requirement()
        data = {k: ("on" if v is True else "" if v is False else v) for k, v in v1.content().items()}
        data = {k: v for k, v in data.items() if v != ""}

        self.client.force_login(self.approver)
        self.client.post(reverse("requirement_new", args=[maize.pk]), data)
        self.assertEqual(maize.requirements.count(), 1, "unchanged form must not create a version")

        self.client.post(reverse("requirement_new", args=[maize.pk]), {**data, "days_max": 115})
        v2 = maize.latest_requirement()
        self.assertEqual((v2.version, v2.days_max, v2.approved), (2, 115, False))
        self.assertEqual(v2.edited_by, self.approver)
        v1.refresh_from_db()
        self.assertEqual(v1.days_max, 120)

        self.client.post(reverse("requirement_approve", args=[v2.pk]))
        v2.refresh_from_db()
        self.assertTrue(v2.approved, "the approver may approve their own version with a separate click")

        self.client.force_login(self.editor)
        self.client.post(reverse("requirement_approve", args=[v1.pk]))
        v1.refresh_from_db()
        self.assertFalse(v1.approved, "non-approver cannot approve")

        self.client.force_login(self.approver)
        self.client.post(reverse("requirement_approve", args=[v1.pk]))
        v1.refresh_from_db()
        self.assertTrue(v1.approved)
        self.assertEqual(maize.latest_approved_requirement(), v2)

    def test_approve_requires_post(self):
        self.client.force_login(self.approver)
        pair = CropPairRule.objects.first()
        self.assertEqual(self.client.get(reverse("pair_approve", args=[pair.pk])).status_code, 405)

    def test_verify_setting_and_edit_resets_it(self):
        setting = ScoreSetting.objects.get(key="weight_ph")
        self.client.force_login(self.approver)
        self.client.post(reverse("setting_verify", args=[setting.pk]))
        setting.refresh_from_db()
        self.assertTrue(setting.verified)
        self.client.force_login(self.editor)
        self.client.post(reverse("setting_edit", args=[setting.pk]), {"value": "abc"})
        setting.refresh_from_db()
        self.assertEqual(setting.value, "30")
        self.client.post(reverse("setting_edit", args=[setting.pk]), {"value": "35"})
        setting.refresh_from_db()
        self.assertEqual((setting.value, setting.verified, setting.edited_by), ("35", False, self.editor))

    def test_pair_form_rejects_same_pair_in_reverse(self):
        self.client.force_login(self.editor)
        pair = CropPairRule.objects.first()
        response = self.client.post(reverse("pair_new"), {
            "crop_a": pair.crop_b_id, "crop_b": pair.crop_a_id, "verdict": "good", "reason": "",
        })
        self.assertContains(response, "There is already a rule for")
        self.assertEqual(CropPairRule.objects.count(), 38)


class CropKnowledgeScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed()

    def setUp(self):
        self.admin = make_user("usman@agrader.hq")
        self.client.force_login(self.admin)

    def test_all_pages_render(self):
        crop = Crop.objects.first()
        for url in [
            reverse("crop_list"), reverse("crop_detail", args=[crop.pk]), reverse("crop_edit", args=[crop.pk]),
            reverse("requirement_new", args=[crop.pk]), reverse("pair_list"), reverse("pair_new"),
            reverse("pair_list") + f"?crop={crop.pk}", reverse("pair_list") + "?crop=bad",
            reverse("rotation_list"), reverse("rotation_new"), reverse("setting_list"),
            reverse("pair_edit", args=[CropPairRule.objects.first().pk]),
            reverse("rotation_edit", args=[RotationRule.objects.first().pk]),
            reverse("setting_edit", args=[ScoreSetting.objects.first().pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_says_when_nobody_can_approve(self):
        response = self.client.get(reverse("crop_list"))
        self.assertContains(response, "Nobody can approve rules yet")
        make_user("samantha@agrader.hq", approver=True)
        self.assertNotContains(self.client.get(reverse("crop_list")), "Nobody can approve rules yet")

    def test_warns_about_unverified_thresholds_and_bad_weight_total(self):
        response = self.client.get(reverse("setting_list"))
        self.assertContains(response, "Nutrient thresholds are placeholders")
        self.assertNotContains(response, "not 100")
        weight = ScoreSetting.objects.get(key="weight_ph")
        weight.value = "40"
        weight.save()
        self.assertContains(self.client.get(reverse("setting_list")), "add up to 110")

    def test_non_approver_sees_no_approve_buttons(self):
        self.assertNotContains(self.client.get(reverse("rotation_list")), ">Approve</button>")

    @override_settings(ALLOW_UNAPPROVED_RULES=True)
    def test_engine_version_shown_with_unapproved_allowed(self):
        crop = Crop.objects.get(name="Maize")
        self.assertContains(self.client.get(reverse("crop_detail", args=[crop.pk])), "v1 (draft)")


class AddCropTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed()

    def setUp(self):
        self.client.force_login(make_user("usman@agrader.hq"))

    def test_add_crop_sets_family_once_and_has_no_approved_requirement(self):
        response = self.client.post(reverse("crop_new"), {
            "name": "Sesame", "also_called": "Ridi", "scientific_name": "Sesamum indicum",
            "family": "cereal", "fixes_nitrogen": "", "active": "on",
        })
        crop = Crop.objects.get(name="Sesame")
        self.assertRedirects(response, reverse("requirement_new", args=[crop.pk]))
        self.assertIsNone(crop.latest_approved_requirement())
        self.assertContains(self.client.get(reverse("crop_detail", args=[crop.pk])), "cannot be recommended")

        # The edit form ignores family and fixes_nitrogen.
        self.client.post(reverse("crop_edit", args=[crop.pk]), {
            "name": "Sesame", "also_called": "Ridi", "scientific_name": "Sesamum indicum",
            "family": "legume", "fixes_nitrogen": "on", "active": "on",
        })
        crop.refresh_from_db()
        self.assertEqual((crop.family, crop.fixes_nitrogen), ("cereal", False))

    def test_duplicate_crop_name_rejected(self):
        response = self.client.post(reverse("crop_new"), {"name": "maize", "family": "cereal", "active": "on"})
        self.assertContains(response, "already exists")
        self.assertEqual(Crop.objects.count(), 12)
