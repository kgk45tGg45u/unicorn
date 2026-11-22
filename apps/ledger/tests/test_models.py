from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ledger import services
from apps.ledger.models import ChainHead, Entry, Transaction

pytestmark = pytest.mark.django_db


def make_tx(seq=1):
    return Transaction.objects.create(
        seq=seq,
        period=services.current_period(),
        kind="cancel",
        reason="test",
        actor_ref="system",
        created_at=timezone.now(),
        prev_hash="0" * 64,
        hash="a" * 64,
    )


def test_chain_head_exists_from_migration():
    head = ChainHead.objects.get(name="uniq")
    assert head.last_seq == 0 and head.last_hash == "0" * 64


def test_transaction_can_be_created_once_but_not_changed_or_deleted():
    tx = make_tx()
    tx.reason = "changed"
    with pytest.raises(ValueError):
        tx.save()
    with pytest.raises(ValueError):
        tx.delete()


def test_queryset_update_and_delete_raise():
    tx = make_tx()
    Entry.objects.create(transaction=tx, account=services.fund1(), amount=Decimal("-1"))
    with pytest.raises(ValueError):
        Transaction.objects.all().update(reason="x")
    with pytest.raises(ValueError):
        Transaction.objects.all().delete()
    with pytest.raises(ValueError):
        Entry.objects.all().update(amount=1)
    with pytest.raises(ValueError):
        Entry.objects.all().delete()


def test_other_append_only_models_use_the_same_guard():
    from apps.core import audit
    from apps.core.models import AuditEvent

    audit.record("system", "x")
    with pytest.raises(ValueError):
        AuditEvent.objects.all().update(verb="y")
