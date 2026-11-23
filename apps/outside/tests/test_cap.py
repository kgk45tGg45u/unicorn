from datetime import date
from decimal import Decimal

import pytest
from freezegun import freeze_time

from apps.ledger.services import current_period
from apps.outside import cap
from apps.tickets.models import Notification

pytestmark = pytest.mark.django_db
D = Decimal
JUNE = "2026-06-10 10:00:00"  # the bread's lead time is 9 days: ready on 19 June, still in June


def _plan(hours):
    p = current_period()
    p.planned_hours = D(hours)
    p.save()


def test_below_the_cap_orders_are_taken_for_this_month(shop):
    with freeze_time(JUNE):
        _plan(100000)
        line = shop.order(1).lines.get()
        assert line.due_date == date(2026, 6, 19)
        assert cap.outside_hours_this_month() == line.value_at_order
        assert cap.cap_hours() == D("100000") * D(str(cap.get_param("economy.outside_sales_cap_share")))


def test_above_the_cap_orders_move_to_next_month_and_the_unit_is_told(shop):
    with freeze_time(JUNE):
        _plan("0.1")  # the cap share of a tenth of an hour is less than one loaf
        line = shop.order(1).lines.get()
        assert line.due_date == date(2026, 7, 1)
        assert Notification.objects.filter(member=shop.baker, text__icontains="cap on outside sales").exists()


def test_no_plan_means_no_cap(shop):
    with freeze_time(JUNE):
        _plan(0)
        assert cap.cap_hours() is None
        assert shop.order(1).lines.get().due_date == date(2026, 6, 19)
