from datetime import timedelta

import pytest
from django.utils import timezone

from apps.plan import defaults, services
from apps.plan.models import PlanPeriod
from apps.rules.models import Parameter
from apps.tickets.tests.conftest import pool
from apps.votes import services as votes

from .conftest import new_period

pytestmark = pytest.mark.django_db


def test_the_default_variant_copies_the_plan_tier_parameters():
    variant = defaults.build_default_variant(new_period())
    plan_params = {p.key: p.value for p in Parameter.objects.filter(tier="plan")}
    assert plan_params and variant.parameters == plan_params
    assert variant.is_default and variant.budget_lines.count() == 14
    assert len(variant.planned_hours_per_month) == 12


def test_the_first_plan_referendum_adopts_the_default_plan():
    members = pool(5)
    period = services.start_first_plan()
    assert period.status == "voting" and period.referendum.method == "yes_no"
    votes.open_due_referendums(now=timezone.now() + timedelta(days=2))
    period.referendum.refresh_from_db()
    for m in members[:4]:
        votes.cast(period.referendum, m, "yes")
    votes.close_referendums(now=timezone.now() + timedelta(days=40))
    period.refresh_from_db()
    assert period.status == "running" and period.adopted_variant.is_default
    assert services.running_period() == period


def test_there_is_only_one_first_plan():
    pool(3)
    services.start_first_plan()
    with pytest.raises(services.PlanError, match="already"):
        services.start_first_plan()
    assert PlanPeriod.objects.count() == 1
