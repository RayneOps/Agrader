import os
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from accounts.models import User

PASSWORDS = {
    "ADMIN_PW_USMAN": "kettle-harmattan-41",
    "ADMIN_PW_ISHAQ": "sorghum-lantern-72",
    "ADMIN_PW_SAMANTHA": "fadama-compass-19",
    "ADMIN_PW_APEH": "groundnut-river-55",
}


def run(*args):
    out = StringIO()
    call_command("seed_admins", *args, stdout=out)
    return out.getvalue()


class SeedAdminsTests(TestCase):
    def test_fails_clearly_when_a_password_is_missing(self):
        env = {k: v for k, v in PASSWORDS.items() if k != "ADMIN_PW_APEH"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesMessage(CommandError, "ADMIN_PW_APEH"):
                run()
        self.assertEqual(User.objects.count(), 0)

    def test_rejects_weak_passwords_without_creating_anyone(self):
        env = dict(PASSWORDS, ADMIN_PW_ISHAQ="123")
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesMessage(CommandError, "ADMIN_PW_ISHAQ"):
                run()
        self.assertEqual(User.objects.count(), 0)

    def test_creates_four_super_admins_who_can_sign_in(self):
        with mock.patch.dict(os.environ, PASSWORDS, clear=True):
            run()
        emails = set(User.objects.values_list("email", flat=True))
        self.assertEqual(
            emails,
            {"usman@agrader.hq", "ishaq@agrader.hq", "samantha@agrader.hq", "apeh@agrader.hq"},
        )
        for user in User.objects.all():
            self.assertEqual(user.role, User.Role.SUPER_ADMIN)
        usman = User.objects.get(email="usman@agrader.hq")
        self.assertTrue(usman.check_password(PASSWORDS["ADMIN_PW_USMAN"]))

    def test_rerun_leaves_existing_passwords_alone_unless_reset(self):
        with mock.patch.dict(os.environ, PASSWORDS, clear=True):
            run()
        changed = dict(PASSWORDS, ADMIN_PW_USMAN="new-millet-season-88")
        with mock.patch.dict(os.environ, changed, clear=True):
            run()
            usman = User.objects.get(email="usman@agrader.hq")
            self.assertTrue(usman.check_password(PASSWORDS["ADMIN_PW_USMAN"]))
            run("--reset-passwords")
            usman.refresh_from_db()
            self.assertTrue(usman.check_password("new-millet-season-88"))
        self.assertEqual(User.objects.count(), 4)


class RuleApproverTests(TestCase):
    def approver_emails(self):
        return set(User.objects.filter(can_approve_rules=True).values_list("email", flat=True))

    def test_flag_follows_rule_approver_email(self):
        with mock.patch.dict(os.environ, dict(PASSWORDS, RULE_APPROVER_EMAIL="Samantha@agrader.hq"), clear=True):
            run()
        self.assertEqual(self.approver_emails(), {"samantha@agrader.hq"})
        with mock.patch.dict(os.environ, dict(PASSWORDS, RULE_APPROVER_EMAIL="apeh@agrader.hq"), clear=True):
            run()
        self.assertEqual(self.approver_emails(), {"apeh@agrader.hq"})

    def test_unset_means_nobody_can_approve(self):
        with mock.patch.dict(os.environ, dict(PASSWORDS, RULE_APPROVER_EMAIL="apeh@agrader.hq"), clear=True):
            run()
        with mock.patch.dict(os.environ, PASSWORDS, clear=True):
            output = run()
        self.assertEqual(self.approver_emails(), set())
        self.assertIn("Nobody can approve", output)

    def test_unknown_approver_email_fails(self):
        with mock.patch.dict(os.environ, dict(PASSWORDS, RULE_APPROVER_EMAIL="someone@else.com"), clear=True):
            with self.assertRaisesMessage(CommandError, "not one of the seeded admins"):
                run()
        self.assertEqual(User.objects.count(), 0)
