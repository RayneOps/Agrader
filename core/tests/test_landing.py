from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User


class LandingPageTests(TestCase):
    def test_anonymous_visitors_see_the_landing_page_without_database_queries(self):
        with self.assertNumQueries(0):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/landing.html")
        for text in ("Soil-based crop planning for smallholder farmers in Niger State.",
                     "How it works", "Seasonal Soil Memory", "Prototype. Not yet in use with farmers.",
                     'href="/login"'):
            self.assertContains(response, text)

    def test_signed_in_admins_see_the_overview(self):
        admin = User.objects.create_superuser(email="usman@agrader.hq", password="x" * 12, full_name="Usman")
        self.client.force_login(admin)
        response = self.client.get("/")
        self.assertTemplateUsed(response, "core/overview.html")
        self.assertTemplateNotUsed(response, "core/landing.html")

    def test_other_screens_still_require_login(self):
        for name in ("farmer_list", "crop_list"):
            self.assertRedirects(self.client.get(reverse(name)), reverse("login") + "?next=" + reverse(name))

    def test_page_follows_the_writing_rules(self):
        html = self.client.get("/").content.decode()
        self.assertNotIn("—", html, "no em dashes")
        self.assertNotIn("<img", html, "no images until they exist")

    def test_team_section(self):
        response = self.client.get("/")
        for name, role in (("Ishaq Ishaq Opeyemi", "Founder"), ("Abubakar Usman Damilare", "Developer"),
                           ("Samantha Umar", "Crop Scientist"), ("Apeh Peter", "AI Engineer")):
            self.assertContains(response, f"<li><strong>{name}</strong><span>{role}</span></li>", html=True)

    @override_settings(PRODUCT_NAME="CropCycle")
    def test_product_name_from_settings(self):
        self.assertContains(self.client.get("/"), "<h1>CropCycle</h1>", html=True)

    def test_contact_section_only_when_configured(self):
        self.assertNotContains(self.client.get("/"), "Contact")
        with override_settings(PUBLIC_CONTACT="hello@example.org"):
            self.assertContains(self.client.get("/"), 'href="mailto:hello@example.org"')
        with override_settings(PUBLIC_CONTACT="0803 000 0000"):
            self.assertContains(self.client.get("/"), 'href="tel:08030000000"')
