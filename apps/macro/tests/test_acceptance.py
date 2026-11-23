"""The acceptance check of phase 09: a month of the phase 05 example, plus one pension, closed."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.ledger import services as ledger
from apps.ledger.models import Period
from apps.macro import close, transfers
from apps.macro.models import ActiveMonth
from apps.members import services as ms
from apps.units.tests.conftest import make_member

from .test_accounts import a_small_month

pytestmark = pytest.mark.django_db
D = Decimal


def test_phase_09_acceptance(client, monkeypatch):
    world, salon = a_small_month()
    pensioner = make_member("pension@x.org", "Pensioner")
    ms.set_private(pensioner, birth_date="1950-01-01")
    for i in range(36):
        ActiveMonth.objects.create(
            member=pensioner,
            month=timezone.localdate().replace(year=2000 + i % 20, month=1 + i % 12, day=1),
            kind="care",
        )
    monkeypatch.setattr(transfers, "pension_amount", lambda today=None: D("5.0000"))
    assert transfers.pay_transfers()["pensions"] == 1

    year, month = timezone.localdate().year, timezone.localdate().month
    snap = close.close_period(year, month)
    # Fund 1 is cancelled, and every identity is exactly zero
    assert ledger.balance(ledger.fund1()) == 0
    assert all(Decimal(v) == 0 for v in snap.identities.values()) and snap.transfers == D("5.0000")
    assert Period.objects.get(year=year, month=month).status == "closed"
    # the next tax rate follows the formula, and the inputs are stored
    assert snap.tax_rate_next == snap.period.next_tax_rate
    assert {"H", "C", "S", "T"} <= set(snap.tax_inputs)
    # the open books show it with its inputs; the lights show and the street light is grey
    page = client.get("/open-books/").content.decode()
    assert str(snap.tax_rate_next) in page and "(H " in page
    assert snap.lights["street_price"]["color"] == "grey"
    # "Are we on track?" compares with the default world's month 1
    response = client.get("/on-track/")
    assert response.status_code == 200 and b"Default world, month 1" in response.content
