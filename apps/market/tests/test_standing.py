from datetime import date
from decimal import Decimal

import pytest
from django.core import mail
from freezegun import freeze_time

from apps.catalogue import services as cat
from apps.market import services
from apps.market.models import OrderLine
from apps.market.tests.conftest import fund
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal


@freeze_time("2026-06-10 08:00:00")
def test_a_weekly_order_creates_a_line_every_week_at_that_days_price(world):
    buyer = world.buyer(uniq=20)
    so = services.create_standing_order(buyer, world.bread, 4, "week")
    assert services.run_standing_orders() == 1
    first = OrderLine.objects.get()
    assert first.price_uniq == D("0.1425") and first.order.note == "Standing order"
    so.refresh_from_db()
    assert so.next_date == date(2026, 6, 17)
    assert services.run_standing_orders() == 0  # safe to run twice

    cat.update_offer(world.baker, world.bread, direct_minutes_per_batch=120)  # the recipe changes, the price follows
    cat.recompute_values()
    world.bread.refresh_from_db()
    with freeze_time("2026-06-17 08:00:00"):
        assert services.run_standing_orders() == 1
    second = OrderLine.objects.order_by("-id").first()
    assert second.price_uniq == world.bread.value_total < first.price_uniq
    assert OrderLine.objects.count() == 2 and first.price_uniq == D("0.1425")  # the first line keeps its price


@freeze_time("2026-06-10 08:00:00")
def test_not_enough_uniq_skips_and_notifies(world):
    poor = world.buyer("poor@x.org", uniq=D("0.1"))
    so = services.create_standing_order(poor, world.bread, 4, "week")
    mail.outbox.clear()
    assert services.run_standing_orders() == 0
    so.refresh_from_db()
    assert not OrderLine.objects.exists()
    assert so.next_date == date(2026, 6, 17) and "Not enough UNIQ" in so.last_result and so.status == "active"
    assert any("was skipped" in m.subject for m in mail.outbox)
    fund(poor, 10)
    with freeze_time("2026-06-17 08:00:00"):
        assert services.run_standing_orders() == 1


@freeze_time("2026-06-10 08:00:00")
def test_a_paused_or_ended_standing_order_does_not_run(world):
    buyer = world.buyer(uniq=20)
    so = services.create_standing_order(buyer, world.bread, 2, "week")
    services.pause_standing_order(so, buyer)
    assert services.run_standing_orders() == 0
    with freeze_time("2026-06-30 08:00:00"):
        services.resume_standing_order(so, buyer)
        so.refresh_from_db()
        assert so.next_date >= date(2026, 6, 30)  # no catching up on the weeks that were paused
    services.end_standing_order(so, buyer)
    with freeze_time("2026-07-30 08:00:00"):
        assert services.run_standing_orders() == 0
    assert not OrderLine.objects.exists()


def test_only_the_owner_changes_a_standing_order(world):
    buyer, other = world.buyer(), world.buyer("o@x.org")
    so = services.create_standing_order(buyer, world.bread, 2, "month")
    with pytest.raises(services.MarketError, match="not your"):
        services.pause_standing_order(so, other)
    with pytest.raises(services.MarketError, match="not your"):
        services.end_standing_order(so, other)


def test_a_monthly_order_keeps_to_the_end_of_short_months():
    assert services._next_standing_date(date(2026, 1, 31), "month") == date(2026, 2, 28)
    assert services._next_standing_date(date(2026, 12, 15), "month") == date(2027, 1, 15)


def test_an_applicant_or_a_service_cannot_be_subscribed(world):
    applicant = make_member("app@x.org", "App", verified=False)
    with pytest.raises(services.MarketError, match="Only members"):
        services.create_standing_order(applicant, world.bread, 1, "week")
    with pytest.raises(services.MarketError):
        services.create_standing_order(world.buyer(), world.bread, 0, "week")
