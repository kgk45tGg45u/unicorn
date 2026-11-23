"""Builders for the plan tests."""

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.plan import defaults, group
from apps.plan.models import BudgetLine, PlanPeriod
from apps.tickets.tests.conftest import make_member, make_unit, pool  # noqa: F401

D = Decimal


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())


def new_period(year=2027, status="proposals", years=1):
    return PlanPeriod.objects.create(starts_on=date(year, 1, 1), ends_on=date(year + years - 1, 12, 31), status=status)


def running_plan(budget=(), closures=(), focus=(), year=2026):
    """A running plan whose default variant has the given budget lines (category, trade, hours, eur)."""
    from apps.plan.models import ClosureItem, FocusItem

    period = new_period(year, "running")
    variant = defaults.build_default_variant(period)
    for category, trade, hours, eur in budget:
        BudgetLine.objects.update_or_create(
            variant=variant, category=category, trade_code=trade, defaults={"hours": D(hours), "eur": D(eur)}
        )
    for trade in closures:
        ClosureItem.objects.create(
            variant=variant,
            trade_code=trade,
            from_date=date.today() + timedelta(days=60),
            hearing_until=date.today() + timedelta(days=30),
        )
    for trade in focus:
        FocusItem.objects.create(variant=variant, trade_code=trade, text="Focus")
    period.adopted_variant = variant
    period.save()
    return period, variant


def drafting_group(n=25, year=2027, on=None):
    """A planning group drawn from n members."""
    members = pool(n)
    period = new_period(year, "drafting")
    defaults.build_default_variant(period)
    return period, group.draw_group(period, on=on or date(year - 1, 9, 1)), members
