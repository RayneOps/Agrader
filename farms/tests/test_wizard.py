from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from crops.models import Crop, ScoreSetting
from farms.models import Farm, Farmer, IntendedCrop, PreviousCrop, Season
from farms.seasons import planting_date_warning, season_window
from farms.wizard import next_step
from readings.models import SoilReading, implausible_values


def crop(name):
    return Crop.objects.get(name=name)


class WizardTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_crops", stdout=StringIO())

    def setUp(self):
        self.admin = User.objects.create_superuser(email="apeh@agrader.hq", password="x" * 12, full_name="Apeh")
        self.client.force_login(self.admin)
        self.farmer = Farmer.objects.create(name="Musa Garba", village="Bosso")
        self.farm = Farm.objects.create(farmer=self.farmer, name="Upland", size_ha="2", water_source="rain_fed")

    def start(self, **data):
        payload = {"label": "rainy", "planting_date": "2027-05-20", **data}
        return self.client.post(reverse("season_start", args=[self.farm.pk]), payload)

    def step_url(self, season, step):
        return reverse("season_step", args=[season.pk, step])

    def draft(self):
        return self.farm.seasons.get(status="draft")

    def reading_data(self, **data):
        return {"action": "manual", "taken_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "ph": "6.2", **data}


class FirstTimeFarmTests(WizardTestCase):
    def test_full_flow_saves_after_every_step(self):
        response = self.start(s1_crops=[crop("Maize").pk], s1_other="Sesame", s2_fallow="on")
        season = self.draft()
        self.assertRedirects(response, self.step_url(season, 2))
        self.assertEqual((season.year, season.label, season.cropping_method), (2027, "rainy", ""))
        self.assertEqual(
            set(season.previous_crops.values_list("seasons_ago", "crop__name", "free_text")),
            {(1, "Maize", ""), (1, None, "Sesame"), (2, None, PreviousCrop.FALLOW)},
        )
        self.assertEqual(next_step(season), 2)

        response = self.client.post(self.step_url(season, 2), {
            "cropping_method": "mixed", "crops": [crop("Maize").pk, crop("Beans (cowpea)").pk],
        })
        self.assertRedirects(response, self.step_url(season, 3))
        season.refresh_from_db()
        self.assertEqual(season.cropping_method, "mixed")
        self.assertEqual(season.intended_crops.count(), 2)

        response = self.client.post(self.step_url(season, 3), self.reading_data(nitrogen="40"))
        self.assertRedirects(response, self.step_url(season, 4))
        reading = season.readings.get()
        self.assertEqual((reading.ph, reading.nitrogen, reading.phosphorus, reading.source), (6.2, 40, None, "manual"))
        self.assertEqual(reading.farm, self.farm)

        review = self.client.get(self.step_url(season, 4))
        self.assertContains(review, "Not measured: Phosphorus (P), Potassium (K)")
        self.assertContains(review, "Sesame")

    def test_history_is_optional_for_a_first_time_farm(self):
        self.start()
        self.assertFalse(self.draft().previous_crops.exists())

    def test_fallow_cannot_have_crops(self):
        response = self.start(s1_crops=[crop("Maize").pk], s1_fallow="on")
        self.assertContains(response, "cannot also have crops")
        self.assertFalse(Season.objects.exists())

    def test_cannot_skip_ahead(self):
        self.start()
        season = self.draft()
        self.assertRedirects(self.client.get(self.step_url(season, 4)), self.step_url(season, 2))


class ResumeTests(WizardTestCase):
    def test_start_new_season_resumes_the_draft(self):
        self.start()
        season = self.draft()
        self.assertRedirects(self.client.get(reverse("season_start", args=[self.farm.pk])), self.step_url(season, 2))
        self.start()  # posting step 1 again must not create a second draft
        self.assertEqual(self.farm.seasons.count(), 1)

    def test_going_back_updates_rather_than_duplicates(self):
        self.start(s1_crops=[crop("Maize").pk])
        season = self.draft()
        self.client.post(self.step_url(season, 1), {
            "label": "rainy", "planting_date": "2027-06-01", "s1_crops": [crop("Millet").pk],
        })
        season.refresh_from_db()
        self.assertEqual(season.planting_date, date(2027, 6, 1))
        self.assertEqual(list(season.previous_crops.values_list("crop__name", flat=True)), ["Millet"])

    def test_closed_season_cannot_be_edited(self):
        season = Season.objects.create(
            farm=self.farm, year=2025, label="rainy", cropping_method="mono",
            planting_date=date(2025, 5, 1), status="closed",
        )
        self.assertRedirects(self.client.get(self.step_url(season, 1)), self.farm.get_absolute_url())


class ReturningFarmTests(WizardTestCase):
    def setUp(self):
        super().setUp()
        self.last = Season.objects.create(
            farm=self.farm, year=2026, label="rainy", cropping_method="mono",
            planting_date=date(2026, 5, 15), status="closed",
        )
        IntendedCrop.objects.create(season=self.last, crop=crop("Groundnut"))
        PreviousCrop.objects.create(season=self.last, crop=crop("Millet"), seasons_ago=1)
        PreviousCrop.objects.create(season=self.last, crop=crop("Maize"), seasons_ago=2)

    def test_asks_what_was_actually_planted_and_prefills_older_seasons(self):
        response = self.client.get(reverse("season_start", args=[self.farm.pk]))
        self.assertContains(response, "What was actually planted last season?")
        self.assertContains(response, "shortlist was: Groundnut")
        form = response.context["form"]
        self.assertNotIn("s1_crops", form.initial, "last season must not be assumed")
        self.assertEqual(form.initial["s2_crops"], [crop("Millet").pk])
        self.assertEqual(form.initial["s3_crops"], [crop("Maize").pk])

    def test_last_season_must_be_answered(self):
        response = self.start()
        self.assertContains(response, "Say what was actually planted")
        self.assertEqual(self.farm.seasons.count(), 1)
        self.start(s1_unknown="on")
        self.assertEqual(self.draft().previous_crops.get().free_text, PreviousCrop.UNKNOWN)

    def test_answer_is_stored_as_previous_crop(self):
        self.start(s1_crops=[crop("Beans (cowpea)").pk], s2_crops=[crop("Millet").pk], s3_crops=[crop("Maize").pk])
        rows = set(self.draft().previous_crops.values_list("seasons_ago", "crop__name"))
        self.assertEqual(rows, {(1, "Beans (cowpea)"), (2, "Millet"), (3, "Maize")})


class CropsStepTests(WizardTestCase):
    def setUp(self):
        super().setUp()
        self.start()
        self.season = self.draft()

    def test_mixed_needs_two_mono_needs_one(self):
        url = self.step_url(self.season, 2)
        self.assertContains(self.client.post(url, {"cropping_method": "mixed", "crops": [crop("Maize").pk]}),
                            "at least 2 crops")
        self.assertContains(self.client.post(url, {"cropping_method": "mono"}), "Choose at least 1 crop")
        self.assertRedirects(self.client.post(url, {"cropping_method": "mono", "crops": [crop("Maize").pk]}),
                             self.step_url(self.season, 3))

    def test_only_active_crops_offered(self):
        okro = crop("Okro")
        okro.active = False
        okro.save()
        response = self.client.get(self.step_url(self.season, 2))
        self.assertNotIn(okro, response.context["form"].fields["crops"].queryset)
        response = self.client.post(self.step_url(self.season, 2), {"cropping_method": "mono", "crops": [okro.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.season.intended_crops.exists())

    def test_dry_season_on_rain_fed_farm_warns_before_soil_step(self):
        self.client.post(self.step_url(self.season, 1), {"label": "dry", "planting_date": "2027-11-15"})
        response = self.client.get(self.step_url(self.season, 2))
        self.assertContains(response, "dry season on a rain-fed farm")
        self.farm.water_source = "irrigated"
        self.farm.save()
        self.assertNotContains(self.client.get(self.step_url(self.season, 2)), "dry season on a rain-fed farm")

    def test_planting_date_outside_season_warns(self):
        self.client.post(self.step_url(self.season, 1), {"label": "rainy", "planting_date": "2027-12-01"})
        self.assertContains(self.client.get(self.step_url(self.season, 2)), "outside the rainy season")


class SoilStepTests(WizardTestCase):
    def setUp(self):
        super().setUp()
        self.start()
        self.season = self.draft()
        self.client.post(self.step_url(self.season, 2), {"cropping_method": "mono", "crops": [crop("Maize").pk]})
        self.url = self.step_url(self.season, 3)

    def test_ph_required_others_optional(self):
        response = self.client.post(self.url, self.reading_data(ph=""))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SoilReading.objects.exists())
        self.client.post(self.url, self.reading_data())
        self.assertEqual(SoilReading.objects.get().ph, 6.2)

    def test_units_shown_beside_fields(self):
        response = self.client.get(self.url)
        for unit in ("mg/kg", "%", "°C", "µS/cm"):
            self.assertContains(response, f"<span>{unit}</span>")

    def test_implausible_values_warn_then_save_anyway(self):
        response = self.client.post(self.url, self.reading_data(ph="2.1", moisture_pct="140"))
        self.assertContains(response, "Save anyway")
        self.assertContains(response, "pH 2.1 is outside the usual range")
        self.assertFalse(SoilReading.objects.exists())
        response = self.client.post(self.url, self.reading_data(ph="2.1", moisture_pct="140", confirm_implausible="1"))
        self.assertRedirects(response, self.step_url(self.season, 4))
        self.assertEqual(SoilReading.objects.get().ph, 2.1)
        self.assertContains(self.client.get(self.step_url(self.season, 4)), "outside the usual range")

    def test_recent_sensor_reading_can_be_used(self):
        sensor = SoilReading.objects.create(
            farm=self.farm, taken_at=timezone.now() - timedelta(hours=2), ph=5.9, source="sensor",
        )
        old = SoilReading.objects.create(
            farm=self.farm, taken_at=timezone.now() - timedelta(hours=30), ph=5.0, source="sensor",
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["recent"], sensor)
        self.client.post(self.url, {"action": "use_sensor", "reading": sensor.pk})
        sensor.refresh_from_db()
        old.refresh_from_db()
        self.assertEqual(sensor.season, self.season)
        self.assertIsNone(old.season)


class FarmPageTests(WizardTestCase):
    def test_button_says_start_or_resume_and_counts_readings(self):
        page = self.client.get(self.farm.get_absolute_url())
        self.assertContains(page, "Start new season")
        self.start()
        self.assertContains(self.client.get(self.farm.get_absolute_url()), "Resume open season")
        SoilReading.objects.create(farm=self.farm, taken_at=timezone.now(), ph=6, source="sensor")
        self.assertContains(self.client.get(self.farmer.get_absolute_url()), "<dd>1</dd>")


class CalendarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_crops", stdout=StringIO())

    def test_windows(self):
        self.assertEqual(season_window("rainy", date(2027, 6, 1)), (date(2027, 4, 25), date(2027, 10, 15)))
        self.assertEqual(season_window("dry", date(2027, 11, 20)), (date(2027, 11, 1), date(2028, 3, 31)))
        self.assertEqual(season_window("dry", date(2028, 1, 10)), (date(2027, 11, 1), date(2028, 3, 31)))

    def test_planting_warning(self):
        self.assertIsNone(planting_date_warning("rainy", date(2027, 5, 1)))
        self.assertIsNotNone(planting_date_warning("rainy", date(2027, 4, 1)))
        self.assertIsNotNone(planting_date_warning("dry", date(2027, 8, 1)))

    def test_calendar_comes_from_settings(self):
        setting = ScoreSetting.objects.get(key="rainy_season_end")
        setting.value = "10-31"
        setting.save()
        self.assertEqual(season_window("rainy", date(2027, 6, 1))[1], date(2027, 10, 31))


class PlausibilityTests(TestCase):
    def test_ranges(self):
        self.assertEqual(implausible_values({"ph": 6.5, "nitrogen": None, "moisture_pct": 30}), [])
        warnings = implausible_values({"ph": 10.5, "nitrogen": -1, "ec": 50000})
        self.assertEqual(len(warnings), 3)
