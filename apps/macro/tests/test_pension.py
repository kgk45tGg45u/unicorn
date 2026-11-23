from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.ledger import services as ledger
from apps.ledger.models import Transaction
from apps.macro import transfers
from apps.macro.models import ActiveMonth, PensionRecognition
from apps.market.tests.conftest import fund
from apps.members import services as ms
from apps.tickets import actions
from apps.tickets.tests.conftest import CHECK
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal


def old_member(email="old@x.org", name="Old", months=36):
    m = make_member(email, name)
    ms.set_private(m, birth_date="1950-01-01")
    today = timezone.localdate().replace(day=1)
    for i in range(1, months + 1):
        month = (today - timedelta(days=31 * i)).replace(day=1)
        ActiveMonth.objects.get_or_create(member=m, month=month, kind="hours")
    return m


def test_35_active_months_are_not_enough_and_36_are():
    assert ms.has_reached_pension_age(old_member("a@x.org", "A", 35))
    a = old_member("b@x.org", "B", 35)
    assert transfers.active_months(a) == 35 and not transfers.pension_eligible(a)
    ActiveMonth.objects.create(member=a, month=date(2000, 1, 1), kind="care")
    assert transfers.active_months(a) == 36 and transfers.pension_eligible(a)


def test_a_missing_birth_date_means_not_at_pension_age():
    m = make_member("m@x.org", "M")
    assert not ms.has_reached_pension_age(m)
    ms.set_private(m, birth_date=f"{timezone.localdate().year - 30}-01-01")
    assert not ms.has_reached_pension_age(m)


def test_a_young_member_is_eligible_only_after_an_approved_unable_to_work_ticket():
    m = make_member("y@x.org", "Y")
    ms.set_private(m, birth_date="1995-01-01")
    for i in range(1, 37):
        ActiveMonth.objects.create(
            member=m, month=(date(2020, 1, 1) + timedelta(days=31 * i)).replace(day=1), kind="hours"
        )
    assert not transfers.pension_eligible(m)
    from apps.tickets import services as tickets

    ticket = tickets.create_ticket(
        "pension_unable_to_work",
        m,
        "Unable to work",
        brief="A short brief.",
        check=CHECK,
        action_payload={"member": m.number},
    )
    actions.approve(ticket, how="test")
    assert transfers.pension_eligible(m)


def test_the_amount_is_sixty_percent_of_the_median_net_income():
    for i, income in enumerate((10, 20, 30)):
        m = make_member(f"m{i}@x.org", f"M{i}")
        fund(m, income)
        ActiveMonth.objects.create(member=m, month=timezone.localdate().replace(day=1), kind="hours")
    next_month = (timezone.localdate().replace(day=1) + timedelta(days=40)).replace(day=15)
    assert transfers.pension_amount(next_month) == D("12.0000")  # 60% of the median, 20


def test_hf01_transfers_only_from_fund2(monkeypatch):
    pensioner = old_member()
    monkeypatch.setattr(transfers, "pension_amount", lambda today=None: D("12.0000"))
    assert transfers.pay_transfers()["pensions"] == 1
    tx = Transaction.objects.get(kind="transfer")
    assert tx.reason.startswith("Equal pension for") and tx.ref_type == "pension"
    entries = {e.account.kind: e.amount for e in tx.entries.all()}
    assert entries["fund2"] == D("-12.0000") and entries["member"] == D("12.0000")
    assert transfers.pay_transfers() == {"pensions": 0, "plans": 0}  # safe to run twice
    assert Transaction.objects.filter(kind="transfer").count() == 1
    with pytest.raises(ledger.LedgerError):
        ledger.post(
            "transfer",
            "from Fund 1",
            [ledger.Leg(ledger.fund1(), -D(1)), ledger.Leg(ledger.member_account(pensioner), D(1))],
        )


def test_the_evidence_file_is_unreadable_after_30_days():
    m = make_member("m@x.org", "M")
    pf = ms.store_private_file(m, SimpleUploadedFile("note.pdf", b"%PDF-1.4 x", "application/pdf"), "other")
    from apps.tickets import services as tickets

    ticket = tickets.create_ticket(
        "pension_unable_to_work",
        m,
        "Unable to work",
        brief="A short brief.",
        check=CHECK,
        action_payload={"member": m.number, "document_id": pf.pk},
    )
    actions.approve(ticket, how="test")
    rec = PensionRecognition.objects.get()
    assert ms.read_private_file(pf)[1].startswith(b"%PDF")
    assert transfers.shred_evidence(timezone.now() + timedelta(days=29)) == 0
    assert transfers.shred_evidence(timezone.now() + timedelta(days=31)) == 1
    with pytest.raises(FileNotFoundError):
        ms.read_private_file(pf)
    rec.refresh_from_db()
    assert rec.evidence_shredded_at is not None


def test_a_recognised_month_counts():
    m = make_member("m@x.org", "M")
    from apps.tickets import services as tickets

    ticket = tickets.create_ticket(
        "recognised_month",
        m,
        "A month of care",
        brief="A short brief.",
        check=CHECK,
        action_payload={"member": m.number, "month": "2026-03", "kind": "care"},
    )
    actions.approve(ticket, how="test")
    assert ActiveMonth.objects.get(member=m).kind == "care"


def test_active_months_are_recorded_from_approved_hours():
    from apps.units import services as us
    from apps.units.tests.conftest import make_unit

    m = make_member("w@x.org", "W")
    unit = make_unit("shop")
    us.add_first_worker(unit, m)
    for _day in range(10):  # ten hours in the month
        entry = us.record_hours(m, unit, timezone.localdate(), 60)
        entry.status = "approved"
        entry.save()
    year, month = timezone.localdate().year, timezone.localdate().month
    from apps.ledger.models import Period

    transfers.record_active_months(Period(year=year, month=month))
    assert ActiveMonth.objects.filter(member=m, kind="hours").count() == 1
