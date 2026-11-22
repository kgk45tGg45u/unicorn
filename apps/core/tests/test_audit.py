import pytest

from apps.core import audit
from apps.core.models import AuditEvent


@pytest.mark.django_db
def test_record_creates_event():
    event = audit.record("M0001", "test.verb", answer=42)
    assert event.actor_ref == "M0001"
    assert event.data == {"answer": 42}


@pytest.mark.django_db
def test_audit_event_cannot_be_changed_or_deleted():
    event = audit.record("system", "test.verb")
    event.verb = "other"
    with pytest.raises(ValueError):
        event.save()
    with pytest.raises(ValueError):
        event.delete()
    assert AuditEvent.objects.count() == 1
