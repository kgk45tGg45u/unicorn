import pytest
from django.db import DatabaseError, connection

from apps.core.sql import append_only_statements, triggers_present
from apps.ledger import services
from apps.ledger.models import Entry

pytestmark = pytest.mark.django_db

TABLES = ["ledger_transaction", "ledger_entry", "core_auditevent", "rules_parameterchange"]


def test_append_only_statements_are_two_triggers():
    update, delete = append_only_statements("t")
    assert "BEFORE UPDATE ON t" in update and "BEFORE DELETE ON t" in delete


def test_triggers_present_reports():
    result = triggers_present(TABLES + ["no_such_table"])
    assert set(result) == set(TABLES + ["no_such_table"])
    assert result["no_such_table"] is False


def test_hf07_raw_update_refused():
    if not all(triggers_present(["ledger_entry"]).values()):
        pytest.skip("append-only triggers are not installed on this database (no TRIGGER privilege)")
    from decimal import Decimal

    from apps.ledger.services import Leg, post
    from apps.members import services as ms
    from apps.members.models import User

    m = ms.create_applicant(User.objects.create_user("t@x.org"), "t", "DE")
    services.open_member_accounts(m)
    post("hours_pay", "h", [Leg(services.fund2(), Decimal(-1)), Leg(services.member_account(m), Decimal(1))])
    with pytest.raises(DatabaseError):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE ledger_entry SET amount = 0")
    with pytest.raises(DatabaseError):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM ledger_entry")
    assert Entry.objects.count() == 2
