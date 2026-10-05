from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditLog
from farms.models import Farm, Farmer, Season


def make_farmer(**kw):
    return Farmer.objects.create(**{"name": "Aisha Bello", "phone": "0803 123 4567", "village": "Maikunkele", **kw})


def make_farm(farmer, **kw):
    return Farm.objects.create(
        **{"farmer": farmer, "name": "River plot", "size_ha": "1.50", "water_source": "rain_fed", **kw}
    )


def make_season(farm, **kw):
    return Season.objects.create(
        **{"farm": farm, "year": 2025, "label": "rainy", "cropping_method": "mono",
           "planting_date": date(2025, 5, 20), "status": "closed", **kw}
    )


class FarmScreensTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="usman@agrader.hq", password="x" * 12, full_name="Usman")
        self.client.force_login(self.admin)


class FarmerListTests(FarmScreensTestCase):
    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("farmer_list")).status_code, 302)

    def test_search_by_name_phone_and_village(self):
        make_farmer(name="Aisha Bello", phone="0803 123 4567", village="Maikunkele")
        make_farmer(name="Musa Garba", phone="0706 555 0000", village="Bosso")
        for query, expected in [("aisha", "Aisha Bello"), ("0706", "Musa Garba"), ("bosso", "Musa Garba")]:
            response = self.client.get(reverse("farmer_list"), {"q": query})
            names = [f.name for f in response.context["page"].object_list]
            self.assertEqual(names, [expected], query)

    def test_shows_farm_count_and_last_visit(self):
        farmer = make_farmer()
        farm = make_farm(farmer)
        make_farm(farmer, name="Upland plot")
        season = make_season(farm)
        row = self.client.get(reverse("farmer_list")).context["page"].object_list[0]
        self.assertEqual(row.farm_count, 2)
        self.assertEqual(row.last_visit, season.created_at)


class FarmerCreateTests(FarmScreensTestCase):
    def test_add_farmer_records_creator_and_audit_and_goes_to_add_farm(self):
        response = self.client.post(
            reverse("farmer_create"),
            {"name": "  Halima   Usman ", "phone": "+234 803 000 1111", "language": "nupe", "village": "Chanchaga"},
        )
        farmer = Farmer.objects.get()
        self.assertRedirects(response, reverse("farm_create", args=[farmer.pk]))
        self.assertEqual(farmer.name, "Halima Usman")
        self.assertEqual(farmer.created_by, self.admin)
        entry = AuditLog.objects.get(model="farms.Farmer")
        self.assertEqual((entry.action, entry.actor), ("create", self.admin))

    def test_rejects_bad_phone(self):
        response = self.client.post(
            reverse("farmer_create"), {"name": "A", "phone": "call me", "language": "hausa", "village": "Bosso"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Farmer.objects.exists())

    def test_edit_farmer_is_audited_as_update(self):
        farmer = make_farmer()
        self.client.post(
            reverse("farmer_edit", args=[farmer.pk]),
            {"name": farmer.name, "phone": farmer.phone, "language": "hausa", "village": "Tunga"},
        )
        entry = AuditLog.objects.filter(action="update").get()
        self.assertEqual(entry.changed_fields, ["village"])


class FarmTests(FarmScreensTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = make_farmer()

    def post_farm(self, **overrides):
        data = {"name": "North plot", "size_ha": "2", "water_source": "fadama",
                "latitude": "9.6152341", "longitude": "6.5478912", **overrides}
        return self.client.post(reverse("farm_create", args=[self.farmer.pk]), data)

    def test_add_farm_accepts_phone_gps_precision(self):
        response = self.post_farm()
        farm = Farm.objects.get()
        self.assertRedirects(response, reverse("farm_detail", args=[farm.pk]))
        self.assertEqual(str(farm.latitude), "9.615234")
        self.assertEqual(farm.created_by, self.admin)

    def test_gps_is_optional_but_must_be_complete(self):
        self.post_farm(latitude="", longitude="")
        self.assertEqual(Farm.objects.count(), 1)
        response = self.post_farm(longitude="")
        self.assertContains(response, "Enter both latitude and longitude")
        self.assertEqual(Farm.objects.count(), 1)

    def test_rejects_out_of_range_gps_and_zero_size(self):
        self.post_farm(latitude="95")
        self.post_farm(size_ha="0")
        self.assertFalse(Farm.objects.exists())

    def test_farm_page_lists_seasons_newest_first(self):
        farm = make_farm(self.farmer)
        old = make_season(farm, year=2024, planting_date=date(2024, 5, 1))
        dry = make_season(farm, year=2024, label="dry", planting_date=date(2024, 11, 10))
        new = make_season(farm, year=2025, planting_date=date(2025, 5, 20))
        response = self.client.get(reverse("farm_detail", args=[farm.pk]))
        self.assertEqual(list(response.context["seasons"]), [new, dry, old])
        self.assertContains(response, "Dry season 2024")

    def test_farmer_profile_shows_member_since_and_farms(self):
        make_farm(self.farmer, name="Upland plot")
        response = self.client.get(reverse("farmer_detail", args=[self.farmer.pk]))
        self.assertContains(response, "Member since")
        self.assertContains(response, "Upland plot")
        self.assertContains(response, 'href="tel:08031234567"')

    def test_unknown_ids_are_404(self):
        import uuid
        self.assertEqual(self.client.get(reverse("farm_detail", args=[uuid.uuid4()])).status_code, 404)
        self.assertEqual(self.client.get(reverse("farmer_detail", args=[uuid.uuid4()])).status_code, 404)


class SeasonConstraintTests(TestCase):
    def test_only_one_draft_season_per_farm(self):
        farm = make_farm(make_farmer())
        make_season(farm, status="draft")
        make_season(farm, status="closed")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_season(farm, status="draft", year=2026)
        make_season(make_farm(farm.farmer, name="Other"), status="draft")  # other farms are unaffected


class DuplicateFarmerWarningTests(FarmScreensTestCase):
    def test_warns_then_saves_when_confirmed(self):
        existing = make_farmer(name="Aisha Bello", village="Maikunkele")
        data = {"name": "aisha  bello", "phone": "", "language": "hausa", "village": "MAIKUNKELE"}
        response = self.client.post(reverse("farmer_create"), data)
        self.assertContains(response, "already exists")
        self.assertContains(response, existing.get_absolute_url())
        self.assertEqual(Farmer.objects.count(), 1)

        response = self.client.post(reverse("farmer_create"), {**data, "confirm_duplicate": "1"})
        self.assertEqual(Farmer.objects.count(), 2)
        self.assertEqual(response.status_code, 302)

    def test_same_name_in_another_village_is_not_a_duplicate(self):
        make_farmer(name="Aisha Bello", village="Maikunkele")
        self.client.post(reverse("farmer_create"), {"name": "Aisha Bello", "language": "hausa", "village": "Bosso"})
        self.assertEqual(Farmer.objects.count(), 2)
