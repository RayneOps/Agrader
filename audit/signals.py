"""Write an AuditLog row for every create, update and delete on a BaseModel subclass.

Note: QuerySet.update() and bulk_create() bypass model signals, so domain code
must save instances one by one when a change needs to be audited.
"""
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from core.models import BaseModel

from .context import get_current_user
from .models import AuditLog

# updated_at changes on every save and would make every update look different.
ALWAYS_EXCLUDED = {"updated_at"}


def _is_audited(sender):
    return issubclass(sender, BaseModel) and not issubclass(sender, AuditLog)


def snapshot(instance):
    excluded = ALWAYS_EXCLUDED | set(instance.audit_exclude)
    data = {
        field.attname: field.value_from_object(instance)
        for field in instance._meta.concrete_fields
        if field.attname not in excluded and field.name not in excluded
    }
    # Round-trip so UUIDs, dates and Decimals become plain JSON values.
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def _write(action, instance, before, after):
    actor = get_current_user()
    AuditLog.objects.create(
        actor=actor if actor is not None and actor.pk else None,
        action=action,
        model=instance._meta.label,
        object_id=str(instance.pk),
        object_repr=str(instance)[:200],
        before=before,
        after=after,
    )


@receiver(pre_save)
def capture_before(sender, instance, raw=False, **kwargs):
    if raw or not _is_audited(sender):
        return
    instance._audit_before = None
    if not instance._state.adding:
        previous = sender._default_manager.filter(pk=instance.pk).first()
        if previous is not None:
            instance._audit_before = snapshot(previous)


@receiver(post_save)
def log_save(sender, instance, created, raw=False, **kwargs):
    if raw or not _is_audited(sender):
        return
    after = snapshot(instance)
    before = getattr(instance, "_audit_before", None)
    if created or before is None:
        _write(AuditLog.Action.CREATE, instance, None, after)
    elif before != after:
        _write(AuditLog.Action.UPDATE, instance, before, after)


@receiver(post_delete)
def log_delete(sender, instance, **kwargs):
    if not _is_audited(sender):
        return
    _write(AuditLog.Action.DELETE, instance, snapshot(instance), None)
