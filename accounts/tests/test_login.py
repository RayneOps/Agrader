from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            email="usman@agrader.hq", password="kettle-harmattan-41", full_name="Usman"
        )

    def test_every_screen_requires_login(self):
        response = self.client.get(reverse("farmer_list"))
        self.assertRedirects(response, reverse("login") + "?next=/farmers")

    def test_login_page_is_public(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_sign_in_with_email_is_case_insensitive(self):
        response = self.client.post(
            reverse("login"), {"username": " Usman@AGRADER.hq ", "password": "kettle-harmattan-41"}
        )
        self.assertRedirects(response, reverse("overview"))

    def test_wrong_password_shows_error(self):
        response = self.client.post(reverse("login"), {"username": "usman@agrader.hq", "password": "nope"})
        self.assertContains(response, "Email or password is not correct")

    def test_inactive_admin_cannot_sign_in(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            reverse("login"), {"username": "usman@agrader.hq", "password": "kettle-harmattan-41"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))

    @override_settings(PRODUCT_NAME="CropCycle")
    def test_product_name_comes_from_settings(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("overview"))
        self.assertContains(response, "CropCycle")
        self.assertNotContains(response, "AGRADER<")
