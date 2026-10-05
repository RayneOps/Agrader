from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from crops.models import Crop, CropPairRule, CropRequirement, RotationRule
from farms.models import Farm, Farmer, IntendedCrop, PreviousCrop, Season
from readings.models import SoilReading
from recommendations import engine
from recommendations.facts import EngineConfigError, gather


class RankingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_crops", stdout=StringIO())
        cls.admin = User.objects.create_superuser(email="usman@agrader.hq", password="x" * 12, full_name="Usman")
        farm = Farm.objects.create(
            farmer=Farmer.objects.create(name="Aisha", village="Bosso"), name="Plot", size_ha="1", water_source="rain_fed",
        )
        cls.last = Season.objects.create(farm=farm, year=2026, label="rainy", cropping_method="mono",
                                         planting_date=date(2026, 5, 20), status="closed")
        cls.season = Season.objects.create(farm=farm, year=2027, label="rainy", cropping_method="mixed",
                                           planting_date=date(2027, 5, 20), status="draft")
        for name in ("Maize", "Beans (cowpea)", "Guinea corn"):
            IntendedCrop.objects.create(season=cls.season, crop=Crop.objects.get(name=name))
        PreviousCrop.objects.create(season=cls.season, crop=Crop.objects.get(name="Groundnut"), seasons_ago=1)
        PreviousCrop.objects.create(season=cls.season, free_text="Sesame", seasons_ago=1)
        SoilReading.objects.create(farm=farm, season=cls.season, taken_at=timezone.now(), ph=6.3,
                                   nitrogen=25, phosphorus=None, potassium=120, source="manual")

    def setUp(self):
        self.client.force_login(self.admin)

    def url(self):
        return reverse("season_ranking", args=[self.season.pk])


class GatherTests(RankingTestCase):
    def test_unapproved_rules_are_not_used(self):
        inp = gather(self.season)
        self.assertTrue(all(c.requirement is None for c in inp.intended))
        self.assertEqual(inp.rotation_rules, [])
        self.assertEqual(inp.pair_rules, [])
        self.assertFalse(inp.used_unapproved)
        result = engine.run(inp)
        self.assertEqual(result.options, [])
        self.assertEqual({r.rule for r in result.removed}, {"no_requirements"})

    @override_settings(ALLOW_UNAPPROVED_RULES=True)
    def test_unapproved_allowed_sets_the_draft_flag(self):
        inp = gather(self.season)
        self.assertTrue(inp.used_unapproved)
        self.assertEqual(len(inp.rotation_rules), RotationRule.objects.count())

    def test_newest_approved_version_is_used(self):
        approver = User.objects.create_superuser(email="s@agrader.hq", password="x" * 12, full_name="S", can_approve_rules=True)
        maize = Crop.objects.get(name="Maize")
        v1 = maize.latest_requirement()
        v1.approve(approver)
        CropRequirement.objects.create(crop=maize, **{**v1.content(), "days_max": 99})  # v2, unapproved
        facts = next(c for c in gather(self.season).intended if c.name == "Maize")
        self.assertEqual((facts.requirement.version, facts.requirement.days_max), (1, 120))

    def test_history_and_free_text(self):
        inp = gather(self.season)
        self.assertEqual([c.name for c in inp.previous_crops(1)], ["Groundnut"])
        self.assertEqual(inp.previous_free_text, {1: ["Sesame"]})
        self.assertTrue(inp.has_history)
        self.assertEqual(inp.season_end, date(2027, 10, 15))

    def test_missing_reading_is_a_clear_error(self):
        empty = Season.objects.create(farm=self.last.farm, year=2028, label="rainy", cropping_method="mono",
                                      planting_date=date(2028, 5, 1), status="closed")
        IntendedCrop.objects.create(season=empty, crop=Crop.objects.get(name="Maize"))
        with self.assertRaisesMessage(EngineConfigError, "no soil reading"):
            gather(empty)


@override_settings(ALLOW_UNAPPROVED_RULES=True)
class RankingScreenTests(RankingTestCase):
    def test_shows_ranked_combinations_with_breakdown(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        result = response.context["result"]
        self.assertEqual(result.mode, "mixed")
        # Maize + Guinea corn is an avoid pair, so it never appears.
        self.assertNotIn({"Maize", "Guinea corn"}, [set(o.crops) for o in result.options])
        for label in ("pH", "Nutrients", "Rotation", "Season", "Water", "Good pairs", "Score of each crop"):
            self.assertContains(response, label)
        self.assertContains(response, "Draft rules, not approved by Crop Scientist")
        self.assertContains(response, "Not measured: phosphorus")

    def test_rotation_bonus_from_last_season_legume(self):
        # Groundnut last season: R1 gives the cereals a bonus, R4 penalises cowpea.
        result = self.client.get(self.url()).context["result"]
        scores = {cs.crop.name: cs for o in result.options for cs in o.crop_scores}
        rotation = {name: next(c for c in s.components if c.key == "rotation").points for name, s in scores.items()}
        self.assertEqual(rotation["Maize"], 25)
        self.assertEqual(rotation["Beans (cowpea)"], 7.5)

    def test_removed_crops_listed_with_reason(self):
        lowland = Crop.objects.get(name="Rice (lowland)")
        IntendedCrop.objects.create(season=self.season, crop=lowland)
        response = self.client.get(self.url())
        self.assertContains(response, "Removed from the shortlist")
        self.assertContains(response, "needs standing water, but this farm is rain-fed")

    def test_unfinished_season_goes_back_to_the_wizard(self):
        self.season.readings.all().delete()
        self.assertRedirects(self.client.get(self.url()), reverse("season_step", args=[self.season.pk, 3]))

    def test_review_step_links_to_ranking(self):
        self.assertContains(self.client.get(reverse("season_step", args=[self.season.pk, 4])), self.url())


class NoApprovedRulesScreenTests(RankingTestCase):
    def test_explains_why_nothing_is_ranked(self):
        response = self.client.get(self.url())
        self.assertContains(response, "No crop on the shortlist passed the rules")
        self.assertContains(response, "has no approved requirements yet")
        self.assertNotContains(response, "Draft rules, not approved")

    def test_pair_rule_approval_matters_for_mixed(self):
        approver = User.objects.create_superuser(email="s@agrader.hq", password="x" * 12, full_name="S", can_approve_rules=True)
        for c in Crop.objects.filter(name__in=["Maize", "Beans (cowpea)", "Guinea corn"]):
            c.latest_requirement().approve(approver)
        avoid = CropPairRule.find(Crop.objects.get(name="Maize"), Crop.objects.get(name="Guinea corn"))
        combos = lambda: [set(o.crops) for o in self.client.get(self.url()).context["result"].options]
        self.assertIn({"Maize", "Guinea corn"}, combos(), "unapproved avoid rule is not applied")
        avoid.approve(approver)
        self.assertNotIn({"Maize", "Guinea corn"}, combos())
