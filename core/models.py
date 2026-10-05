import uuid

from django.conf import settings
from django.db import models


class BaseModel(models.Model):
    """UUID primary key and timestamps on every model, so offline sync can be added later.

    Every concrete subclass is audited automatically (see `audit.signals`).
    Set `audit_exclude` on a subclass to keep sensitive fields out of the log.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    audit_exclude = ()

    class Meta:
        abstract = True


class CreatedByModel(BaseModel):
    """BaseModel plus the admin who created the record."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        abstract = True
