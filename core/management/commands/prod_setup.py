"""Prepare a production database from your own machine: migrate, seed_crops, seed_admins.

Serverless hosts cannot run management commands, so these run locally against the production
database. The command shows exactly which database it will change and asks you to type its
host before doing anything. All three steps are safe to repeat.
"""
import os

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from accounts.management.commands.seed_admins import ADMINS


class Command(BaseCommand):
    help = "Run migrate, seed_crops and seed_admins against the configured (production) database."

    def add_arguments(self, parser):
        parser.add_argument("--skip-admins", action="store_true", help="Do not run seed_admins.")
        parser.add_argument(
            "--expect-host", help="Skip the prompt if the database host equals this value (for scripts).",
        )

    def handle(self, *args, skip_admins=False, expect_host=None, **options):
        db = connection.settings_dict
        engine = db["ENGINE"].rsplit(".", 1)[-1]
        host = db.get("HOST") or ""
        if engine == "sqlite3":
            raise CommandError(
                "This is pointing at the local SQLite file, not production. Set AGRADER_ENV_FILE to the file "
                "holding the production settings (see the README)."
            )

        self.stdout.write(f"Database: {engine} on host {host}, database {db['NAME']}, user {db.get('USER')}")
        if not skip_admins:
            missing = [var for _, _, var in ADMINS if not os.environ.get(var)]
            if missing:
                raise CommandError(
                    "Missing " + ", ".join(missing) + ". Add them for this run, or use --skip-admins."
                )

        if expect_host is not None:
            if expect_host != host:
                raise CommandError(f"--expect-host {expect_host} does not match the database host {host}.")
        else:
            answer = input("Type the database host to continue: ").strip()
            if answer != host:
                raise CommandError("Host did not match. Nothing was changed.")

        self.stdout.write(self.style.MIGRATE_HEADING("1/3 migrate"))
        call_command("migrate", interactive=False, stdout=self.stdout)
        self.stdout.write(self.style.MIGRATE_HEADING("2/3 seed_crops"))
        call_command("seed_crops", stdout=self.stdout)
        if skip_admins:
            self.stdout.write("3/3 seed_admins skipped")
        else:
            self.stdout.write(self.style.MIGRATE_HEADING("3/3 seed_admins"))
            call_command("seed_admins", stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Production database is ready."))
