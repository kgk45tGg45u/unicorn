from decimal import Decimal

import pytest

from apps.ledger import services as ledger
from apps.ledger.models import Entry
from apps.units import services
from apps.units.models import CouncilRules

from .conftest import make_member, make_unit
from .test_hours_record import today

pytestmark = pytest.mark.django_db
D = Decimal


def council(slug="bakery", n=2, hours_approval=None):
    unit = make_unit(slug)
    people = [make_member(f"{slug}{i}@x.org", f"M{i}") for i in range(n)]
    services.add_first_worker(unit, people[0])
    for p in people[1:]:
        services.decide_join(services.request_to_join(unit, p), people[0], True)
    if hours_approval:
        CouncilRules.objects.filter(unit=unit).update(hours_approval=hours_approval)
    return unit, people


def gross_of(member):
    return sum(
        e.amount for e in Entry.objects.filter(account=ledger.member_account(member), transaction__kind="hours_pay")
    )


def test_a_second_member_approves_and_the_hours_are_paid_with_tax():
    unit, (a, b) = council()
    e = services.record_hours(a, unit, today(), 150)
    assert e.status == "submitted"
    e = services.approve_hours(e, b)
    assert e.status == "paid" and e.transaction.kind == "hours_pay"
    assert gross_of(a) == D("2.5000")
    rate = e.period.tax_rate
    assert ledger.balance(ledger.member_account(a)) == D("2.5") - (D("2.5") * rate).quantize(D("0.0001"))
    assert "2:30" in e.transaction.reason


def test_hf20_own_hours_cannot_be_self_approved():
    unit, (a, b) = council()
    e = services.record_hours(a, unit, today(), 60)
    with pytest.raises(services.UnitError):
        services.approve_hours(e, a)
    with pytest.raises(services.UnitError):
        services.approve_hours(e, None)  # the system does not approve council hours
    with pytest.raises(services.UnitError):
        services.approve_hours(e, make_member("o@x.org", "Out"))  # nor an outsider
    e.refresh_from_db()
    assert e.status == "submitted"


def test_hf20_unapproved_hours_are_not_paid():
    unit, (a, b) = council()
    e = services.record_hours(a, unit, today(), 60)
    with pytest.raises(services.UnitError):
        services.pay_hours(e)
    assert gross_of(a) == 0
    e.status = "approved"
    e.save()
    with pytest.raises(services.UnitError):
        services.pay_hours(e)  # still no approval on record


def test_hf02_same_pay_per_hour_in_every_unit():
    u1, (a, b) = council("one")
    u2, (c, d) = council("two")
    e1 = services.approve_hours(services.record_hours(a, u1, today(), 90), b)
    e2 = services.approve_hours(services.record_hours(c, u2, today(), 90), d)
    assert gross_of(a) == gross_of(c) == D("1.5000")
    assert e1.status == e2.status == "paid"


def test_hf09_tax_is_one_rate_for_everyone():
    u1, (a, b) = council("one")
    u2, (c, d) = council("two")
    services.approve_hours(services.record_hours(a, u1, today(), 120), b)
    services.approve_hours(services.record_hours(c, u2, today(), 120), d)
    net = [ledger.balance(ledger.member_account(m)) for m in (a, c)]
    assert net[0] == net[1]


def test_two_members_rule_needs_two_approvers():
    unit, (a, b, c) = council(n=3, hours_approval="two_members")
    e = services.record_hours(a, unit, today(), 60)
    e = services.approve_hours(e, b)
    assert e.status == "submitted"
    with pytest.raises(services.UnitError):
        services.approve_hours(e, b)  # the same person twice does not count
    assert services.approve_hours(e, c).status == "paid"


def test_responsible_or_other():
    unit, (a, b, c) = council(n=3, hours_approval="responsible_or_other")
    # a is the responsible; b's hours: the responsible alone is enough
    assert services.approve_hours(services.record_hours(b, unit, today(), 60), a).status == "paid"
    # a's hours: b is not the responsible, so two others are needed (only b and c exist)
    e = services.record_hours(a, unit, today(), 60)
    assert services.approve_hours(e, b).status == "submitted"
    assert services.approve_hours(e, c).status == "paid"


def test_extra_approval_needs_two_reasons():
    unit, (a, b, c) = council(n=3)
    services.record_hours(a, unit, today(), 1440)
    services.record_hours(a, unit, today(), 1440)
    e = services.record_hours(a, unit, today(), 60)
    assert e.needs_extra_approval
    with pytest.raises(services.UnitError):
        services.approve_hours(e, b)  # no reason
    assert services.approve_hours(e, b, "Busy week").status == "submitted"
    assert services.approve_hours(e, c, "Agreed").status == "paid"


def test_one_person_units_are_paid_at_once():
    a = make_member()
    unit = make_unit("solo")
    services.add_first_worker(unit, a)
    e = services.record_hours(a, unit, today(), 60)
    assert e.status == "paid"
    assert gross_of(a) == D("1.0000")
    assert e.approvals.get().approver is None


def test_own_initiative_hours_become_pending_sale_without_payment():
    unit, (a, b) = council()
    e = services.record_hours(a, unit, today(), 60, activity="own_initiative")
    e = services.approve_hours(e, b)
    assert e.status == "pending_sale" and e.transaction is None
    assert gross_of(a) == 0


def test_rejecting_needs_a_reason_and_pays_nothing():
    unit, (a, b) = council()
    e = services.record_hours(a, unit, today(), 60)
    with pytest.raises(services.UnitError):
        services.reject_hours(e, b, "")
    with pytest.raises(services.UnitError):
        services.reject_hours(e, a, "no")
    e = services.reject_hours(e, b, "Not on that day")
    assert e.status == "rejected" and gross_of(a) == 0


def test_the_batch_page_asks_for_a_fresh_login(client):
    from django.urls import reverse

    unit, (a, b) = council()
    client.force_login(b.user)
    response = client.get(reverse("units:approve", args=[unit.slug]))
    assert response.status_code in (302, 403)  # sensitive action: never served without a recent login
