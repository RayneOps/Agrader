from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from core.models import BaseModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("role", User.Role.SUPER_ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super admin"
        OPERATOR = "operator", "Operator"  # Defined for later; not used in the MVP.

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SUPER_ADMIN)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    can_approve_rules = models.BooleanField(
        default=False,
        help_text="May approve crop requirements, pair rules, rotation rules and verify score settings. "
        "Set from RULE_APPROVER_EMAIL by seed_admins.",
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    # Never write password hashes to the audit log; last_login changes on every sign-in.
    audit_exclude = ("password", "last_login")

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name or self.email

    @property
    def is_super_admin(self):
        return self.role == self.Role.SUPER_ADMIN
