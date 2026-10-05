import os
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase


class ProdSetupTests(TestCase):
    def test_refuses_to_run_against_local_sqlite(self):
        # The test database is SQLite, which is exactly the mistake this guards against.
        with self.assertRaisesMessage(CommandError, "local SQLite file"):
            call_command("prod_setup", "--expect-host", "", stdout=StringIO())

    def test_host_must_match_before_anything_runs(self):
        settings = {"ENGINE": "django.db.backends.postgresql", "HOST": "db.example.org", "NAME": "agrader", "USER": "u"}
        with mock.patch("core.management.commands.prod_setup.connection") as conn, \
                mock.patch("core.management.commands.prod_setup.call_command") as run:
            conn.settings_dict = settings
            with self.assertRaisesMessage(CommandError, "does not match"):
                call_command("prod_setup", "--skip-admins", "--expect-host", "other.host", stdout=StringIO())
            run.assert_not_called()

            with mock.patch("builtins.input", return_value="wrong"):
                with self.assertRaisesMessage(CommandError, "Nothing was changed"):
                    call_command("prod_setup", "--skip-admins", stdout=StringIO())
            run.assert_not_called()

            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesMessage(CommandError, "ADMIN_PW_USMAN"):
                    call_command("prod_setup", "--expect-host", "db.example.org", stdout=StringIO())
            run.assert_not_called()

            call_command("prod_setup", "--skip-admins", "--expect-host", "db.example.org", stdout=StringIO())
            self.assertEqual([c.args[0] for c in run.call_args_list], ["migrate", "seed_crops"])
