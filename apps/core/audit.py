from .models import AuditEvent


def record(actor_ref, verb, obj=None, **data):
    """Record an action. Pass member numbers and ids only, never personal data."""
    return AuditEvent.objects.create(
        actor_ref=str(actor_ref),
        verb=verb,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        data=data,
    )
