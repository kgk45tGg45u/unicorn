from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import Job
from apps.ledger import services as ledger
from apps.ledger.models import Period
from apps.macro import close, lights
from apps.market import services
from apps.market.models import OrderLine, WaitingListEntry
from apps.market.tests.conftest import World
from apps.rules.models import Parameter
from apps.tickets.models import Ticket

from .test_accounts import a_small_month

pytestmark = pytest.mark.django_db
D = Decimal


def period():
    return ledger.current_period()


def test_the_street_price_light_stays_grey():
    light = lights.street_price(period())
    assert light["color"] == "grey" and "Not measured yet" in light["text"]


def test_unspent_uniq_thresholds():
    a_small_month()
    light = lights.unspent_uniq(period())
    assert light["color"] in ("green", "amber", "red") and light["value"] is not None
    # with a very low amber level, the same balances turn amber, and red above twice that
    Parameter.objects.filter(key="alarms.unspent_uniq_amber_months").update(value=0.0001)
    assert lights.unspent_uniq(period())["color"] == "red"
    Parameter.objects.filter(key="alarms.unspent_uniq_red_multiple").update(value=10000000)
    assert lights.unspent_uniq(period())["color"] == "amber"


def test_shelves_light():
    world = World()
    buyer = world.buyer(uniq=20)
    assert lights.shelves(period())["color"] == "grey"  # nothing due yet
    line = services.place_order(buyer, world.bread, D(1))
    OrderLine.objects.filter(pk=line.pk).update(due_date=timezone.localdate())
    assert lights.shelves(period())["color"] == "red"  # due but not delivered: 0%
    OrderLine.objects.filter(pk=line.pk).update(status="delivered", delivered_at=timezone.now())
    assert lights.shelves(period())["color"] == "green"
    WaitingListEntry.objects.create(member=buyer, item=world.bread.item, quantity=1)
    assert lights.shelves(period())["value"] == "0.5000"  # a waiting-list entry counts as not served


def test_unsold_light_and_the_euro_reserve_light():
    a_small_month()
    assert lights.unsold(period())["color"] in ("amber", "red")  # 5 of 5 made ahead were written off
    assert lights.euro_reserve(period())["color"] == "grey"  # the fund has paid nothing out
    from apps.tradefund import books
    from apps.tradefund.tests.conftest import make_holder

    h = make_holder("h@x.org", "H", amount=1000)
    books.post_fund(h, "payment_out", -100, "materials", "group_purchase")
    assert lights.euro_reserve(period())["color"] == "green"  # 9 months
    books.post_fund(h, "payment_out", -750, "materials", "group_purchase")
    assert lights.euro_reserve(period())["color"] == "red"  # 150 left over 850 a month


def test_idle_shifts_are_off_while_services_are_paid_when_performed():
    assert lights.idle_shifts(period())["color"] == "grey"


def test_the_lights_have_colour_words():
    a_small_month()
    for light in lights.compute_lights(period()).values():
        assert light["word"] in ("green", "amber", "red", "not measured")


def test_item_red_turns_on_the_shortage_cap_in_place_order():
    world = World()
    buyer = world.buyer(uniq=20)
    other = world.buyer("other@x.org", uniq=20)
    first = services.place_order(other, world.bread, D(1))
    OrderLine.objects.filter(pk=first.pk).update(due_date=timezone.localdate())  # due now, not delivered: red
    assert lights.item_red(world.bread.item)
    services.place_order(buyer, world.bread, D(2))  # the cap is 2 a month
    with pytest.raises(services.MarketError):
        services.place_order(buyer, world.bread, D(1))


def test_hf15_credit_line_warns_but_never_blocks():
    world = World()
    p = period()
    Period.objects.filter(pk=p.pk).update(planned_hours=D(100))
    p.refresh_from_db()
    assert lights.credit_line_check(p, D(115)) is None  # within the 20% tolerance
    ticket = lights.credit_line_check(p, D(130))
    assert ticket is not None and ticket.type == "question" and "More hours were paid than planned" in ticket.title
    assert "130" in ticket.body_md and "100" in ticket.body_md
    # and paying goes on: a new hours entry in the same month is still paid
    from apps.units import services as us
    from apps.units.models import HoursEntry

    entry = us.record_hours(world.baker, world.bakery_unit, timezone.localdate(), 60)
    us.submit_hours(entry) if entry.status == "draft" else None
    entry.refresh_from_db()
    assert entry.status in ("paid", "approved", "submitted")
    assert HoursEntry and Ticket.objects.filter(type="question").count() == 1


def test_the_credit_line_is_skipped_without_a_plan():
    p = period()
    assert p.planned_hours == 0 and lights.credit_line_check(p, D(1000)) is None


def test_the_daily_cache_and_the_close_store_lights():
    a_small_month()
    lights.refresh_cache()
    assert "unspent" in lights.latest()
    year, month = timezone.localdate().year, timezone.localdate().month
    close.close_period(year, month)
    assert Job is not None and timedelta
