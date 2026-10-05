from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.context import acting_as
from audit.models import AuditLog


class AuditLogTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="ishaq@agrader.hq", password="sorghum-lantern-72", full_name="Ishaq"
        )
        AuditLog.objects.all().delete()

    def test_create_update_delete_are_logged_with_actor_and_values(self):
        with acting_as(self.admin):
            other = User.objects.create_user(email="apeh@agrader.hq", password="x" * 12, full_name="Apeh")
            other.full_name = "Apeh O."
            other.save()
            other_id = str(other.pk)
            other.delete()

        create, update, delete = AuditLog.objects.order_by("created_at")
        self.assertEqual([create.action, update.action, delete.action], ["create", "update", "delete"])
        for entry in (create, update, delete):
            self.assertEqual(entry.actor, self.admin)
            self.assertEqual(entry.model, "accounts.User")
            self.assertEqual(entry.object_id, other_id)

        self.assertIsNone(create.before)
        self.assertEqual(create.after["full_name"], "Apeh")
        self.assertEqual(update.before["full_name"], "Apeh")
        self.assertEqual(update.after["full_name"], "Apeh O.")
        self.assertEqual(update.changed_fields, ["full_name"])
        self.assertEqual(delete.before["full_name"], "Apeh O.")
        self.assertIsNone(delete.after)

    def test_password_hash_is_never_logged(self):
        with acting_as(self.admin):
            self.admin.set_password("a-new-long-password-9")
            self.admin.save()
        # Only the hash changed, and it is excluded, so no update row at all.
        self.assertFalse(AuditLog.objects.exists())
        with acting_as(self.admin):
            User.objects.create_user(email="new@agrader.hq", password="y" * 12, full_name="New")
        self.assertNotIn("password", AuditLog.objects.get().after)

    def test_saving_without_changes_writes_nothing(self):
        self.admin.save()
        self.assertFalse(AuditLog.objects.exists())

    def test_signing_in_does_not_create_noise(self):
        self.client.post(reverse("login"), {"username": "ishaq@agrader.hq", "password": "sorghum-lantern-72"})
        self.assertFalse(AuditLog.objects.exists())

    def test_changes_outside_a_request_have_no_actor(self):
        User.objects.create_user(email="cli@agrader.hq", password="z" * 12, full_name="Cli")
        self.assertIsNone(AuditLog.objects.get().actor)

    def test_request_user_is_recorded_as_actor(self):
        from audit.context import get_current_user
        from audit.middleware import CurrentUserMiddleware

        seen = {}

        def view(request):
            seen["user"] = get_current_user()
            return None

        request = type("R", (), {"user": self.admin})()
        CurrentUserMiddleware(view)(request)
        self.assertEqual(seen["user"], self.admin)
        self.assertIsNone(get_current_user())

    def test_audit_log_rows_are_not_themselves_audited(self):
        with acting_as(self.admin):
            User.objects.create_user(email="one@agrader.hq", password="q" * 12, full_name="One")
        self.assertEqual(AuditLog.objects.count(), 1)
