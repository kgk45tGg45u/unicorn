from . import acting
from . import logging as unicorn_logging
from .models import AuditEvent


def record(actor_ref, verb, obj=None, **data):
    """Record an action. Pass member numbers and ids only, never personal data.

    While a helper acts for a member, `acted_by` holds the helper's member number.
    """
    helper = acting.current_helper()
    return AuditEvent.objects.create(
        acted_by=helper.number if helper is not None else "",
        request_id=unicorn_logging.current_request_id()[:36],
        actor_ref=str(actor_ref),
        verb=verb,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        data=data,
    )
