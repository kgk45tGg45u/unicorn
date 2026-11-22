from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.market import services as market
from apps.market.models import OrderLine
from apps.market.tests.conftest import World
from apps.plan import check as plan_check
from apps.tickets.models import Ticket
from apps.units import services as us

from .conftest import answer, make_member, open_seats, pool

pytestmark = pytest.mark.django_db


def amber(monkeypatch):
    result = plan_check.CheckResult(
        [plan_check.CheckPoint("amber", "Bakeries are plentiful"), plan_check.CheckPoint("green", "Money is fine")]
    )
    monkeypatch.setattr(plan_check, "check", lambda request: result)


def test_the_amber_path_opens_the_unit_and_creates_a_review_ticket(monkeypatch):
    pool(8)
    amber(monkeypatch)
    unit = us.open_unit(make_member("a@x.org", "Ada"), {"name": "Bakery", "kind": "production", "description": "Bread"})
    ticket = Ticket.objects.get(type="post_check_unit")
    assert unit.status == "trial" and ticket.action_payload["unit_id"] == unit.pk
    assert "Bakeries are plentiful" in ticket.brief_md and "keep working" in ticket.brief_md
    seat = open_seats(ticket)[0]
    assert timedelta(days=13, hours=23) < seat.deadline - timezone.now() <= timedelta(days=14)


def test_a_green_unit_gets_no_review_ticket():
    pool(8)
    us.open_unit(make_member("a@x.org", "Ada"), {"name": "Bakery", "kind": "production", "description": "Bread"})
    assert not Ticket.objects.filter(type="post_check_unit").exists()


def test_approved_means_nothing_changes(monkeypatch):
    pool(8)
    amber(monkeypatch)
    unit = us.open_unit(make_member("a@x.org", "Ada"), {"name": "Bakery", "kind": "production", "description": "Bread"})
    ticket = Ticket.objects.get(type="post_check_unit")
    for s in open_seats(ticket):
        answer(s, "yes")
    unit.refresh_from_db()
    ticket.refresh_from_db()
    assert ticket.status == "approved" and unit.status == "trial"


def test_panel_rejection_pauses_the_unit_releases_its_orders_and_tells_the_workers(monkeypatch):
    from apps.tickets import briefs

    pool(30)
    world = World()
    buyer = world.buyer()
    line = market.place_order(buyer, world.bread, Decimal(2))
    assert line.hold.status == "active"
    result = plan_check.CheckResult([plan_check.CheckPoint("amber", "Many bakeries")])
    ticket = briefs.post_check_unit(world.bakery_unit, world.baker, result)
    answer(open_seats(ticket)[0], "no")
    for s in open_seats(ticket, "panel")[:6]:
        answer(s, "no")
    ticket.refresh_from_db()
    world.bakery_unit.refresh_from_db()
    line.refresh_from_db()
    line.hold.refresh_from_db()
    assert ticket.status == "rejected" and world.bakery_unit.status == "paused"
    assert line.status == OrderLine.CANCELLED and line.hold.status == "released"
    note = world.baker.notifications.get(text__contains="paused")
    assert ticket.number in note.url and "petition" in note.text


def test_a_panel_that_approves_leaves_the_unit_alone():
    from apps.tickets import briefs

    pool(30)
    world = World()
    result = plan_check.CheckResult([plan_check.CheckPoint("amber", "Many bakeries")])
    ticket = briefs.post_check_unit(world.bakery_unit, world.baker, result)
    answer(open_seats(ticket)[0], "no")
    for s in open_seats(ticket, "panel")[:7]:
        answer(s, "yes")
    world.bakery_unit.refresh_from_db()
    assert world.bakery_unit.status == "open"
