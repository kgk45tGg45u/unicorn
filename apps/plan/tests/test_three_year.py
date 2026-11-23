from datetime import date

import pytest

from apps.plan import defaults, group, services
from apps.rules.models import Parameter

from .conftest import drafting_group, new_period

pytestmark = pytest.mark.django_db


def test_with_three_year_plans_the_period_spans_36_months_and_two_groups_share_no_member():
    Parameter.objects.filter(key="plan.period_years").update(value=3)
    assert services.period_end(date(2027, 1, 1)) == date(2029, 12, 31)
    period = new_period(2027, "drafting", years=3)
    assert period.months == 36
    variant = defaults.build_default_variant(period)
    assert len(variant.planned_hours_per_month) == 36
    from apps.tickets.tests.conftest import pool

    pool(40)
    yearly = group.draw_group(period, on=date(2026, 9, 1))
    longterm = group.draw_long_term_group(period, on=date(2026, 9, 1))
    assert longterm.kind == "long_term" and longterm.seats.count() > 0
    assert not set(yearly.seats.values_list("member_id", flat=True)) & set(
        longterm.seats.values_list("member_id", flat=True)
    )


def test_long_term_groups_need_a_longer_period():
    period, g, members = drafting_group(25)
    with pytest.raises(services.PlanError, match="longer than one year"):
        group.draw_long_term_group(period)
