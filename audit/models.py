from django.conf import settings
from django.db import models

from core.models import BaseModel


class AuditLog(BaseModel):
    """One row per create, update or delete on a domain model. Never audited itself."""

    class Action(models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Deleted"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_entries",
        help_text="Empty when the change came from a management command or the device API.",
    )
    action = models.CharField(max_length=10, choices=Action.choices)
    model = models.CharField(max_length=100, help_text="app_label.ModelName")
    object_id = models.CharField(max_length=64)
    object_repr = models.CharField(max_length=200, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["model", "object_id"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} {self.model} {self.object_id}"

    @property
    def timestamp(self):
        return self.created_at

    @property
    def changed_fields(self):
        """Field names whose value differs between before and after (updates only)."""
        if not (self.before and self.after):
            return []
        return sorted(k for k in set(self.before) | set(self.after) if self.before.get(k) != self.after.get(k))
