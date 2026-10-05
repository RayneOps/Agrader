import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User

ADMINS = [
    ("usman@agrader.hq", "Usman", "ADMIN_PW_USMAN"),
    ("ishaq@agrader.hq", "Ishaq", "ADMIN_PW_ISHAQ"),
    ("samantha@agrader.hq", "Samantha", "ADMIN_PW_SAMANTHA"),
    ("apeh@agrader.hq", "Apeh", "ADMIN_PW_APEH"),
]


class Command(BaseCommand):
    help = (
        "Create the four super admins. Initial passwords come from ADMIN_PW_* environment variables. "
        "RULE_APPROVER_EMAIL names the one admin allowed to approve crop rules."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Also reset the password of admins that already exist.",
        )

    def handle(self, *args, reset_passwords=False, **options):
        missing = [var for _, _, var in ADMINS if not os.environ.get(var)]
        if missing:
            raise CommandError(
                "Missing environment variable(s): " + ", ".join(missing)
                + ". Set them in .env (see .env.example). No admins were created."
            )

        approver_email = os.environ.get("RULE_APPROVER_EMAIL", "").strip().lower()
        if approver_email and approver_email not in {email for email, _, _ in ADMINS}:
            raise CommandError(
                f"RULE_APPROVER_EMAIL={approver_email} is not one of the seeded admins. No admins were changed."
            )

        problems = []
        for email, name, var in ADMINS:
            try:
                validate_password(os.environ[var], user=User(email=email, full_name=name))
            except ValidationError as exc:
                problems.append(f"{var}: {' '.join(exc.messages)}")
        if problems:
            raise CommandError("Weak password(s), no admins were created:\n  " + "\n  ".join(problems))

        with transaction.atomic():
            for email, name, var in ADMINS:
                user = User.objects.filter(email=email).first()
                if user is None:
                    User.objects.create_superuser(email=email, password=os.environ[var], full_name=name)
                    self.stdout.write(self.style.SUCCESS(f"Created {email}"))
                elif reset_passwords:
                    user.set_password(os.environ[var])
                    user.save()
                    self.stdout.write(self.style.WARNING(f"Reset password for {email}"))
                else:
                    self.stdout.write(f"{email} already exists, password left unchanged")

            # The flag always follows RULE_APPROVER_EMAIL, so changing the variable moves it.
            for user in User.objects.filter(email__in=[email for email, _, _ in ADMINS]):
                should_approve = user.email == approver_email
                if user.can_approve_rules != should_approve:
                    user.can_approve_rules = should_approve
                    user.save()
        if approver_email:
            self.stdout.write(self.style.SUCCESS(f"Rule approver: {approver_email}"))
        else:
            self.stdout.write(self.style.WARNING("RULE_APPROVER_EMAIL is not set. Nobody can approve crop rules."))
