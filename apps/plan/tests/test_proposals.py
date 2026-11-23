from datetime import date

import pytest
from freezegun import freeze_time

from apps.plan import services
from apps.plan.models import PlanProposal
from apps.tickets.models import Ticket
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db


def test_outside_the_window_proposals_are_refused_with_the_dates():
    ada = make_member("a@x.org", "Ada")
    with freeze_time("2026-05-10 10:00:00"):
        with pytest.raises(services.PlanError, match="1 July to 31 August"):
            services.file_proposal(ada, "focus", "Focus on bread", "Why", {"trade_code": "B-10"})
    assert PlanProposal.objects.count() == 0


def test_a_proposal_stores_its_quick_check_and_a_ticket():
    ada = make_member("a@x.org", "Ada")
    with freeze_time("2026-07-15 10:00:00"):
        p = services.file_proposal(
            ada, "invest", "A new oven", "We need it", {"trade_code": "B-10", "eur": "4000", "hours": "20"}
        )
    assert p.period.starts_on == date(2027, 1, 1) and p.status == "open"
    assert p.quick_check["eur"] == "4000" and p.quick_check["hours"] == "20" and p.quick_check["points"]
    assert Ticket.objects.get(plan_proposal=p).type == "plan_proposal"
    assert services.proposals_by_kind(p.period)["invest"] == [p]


def test_only_plan_tier_defaults_can_be_proposed_and_within_bounds():
    ada = make_member("a@x.org", "Ada")
    with freeze_time("2026-07-15 10:00:00"):
        with pytest.raises(services.PlanError, match="plan tier"):
            services.file_proposal(ada, "parameter_change", "t", "", {"key": "plan.group_size", "value": 20})
        with pytest.raises(services.PlanError):
            services.file_proposal(
                ada, "parameter_change", "t", "", {"key": "economy.outside_sales_cap_share", "value": 5}
            )
        ok = services.file_proposal(
            ada, "parameter_change", "Lower the cap", "", {"key": "economy.outside_sales_cap_share", "value": 0.4}
        )
    assert ok.kind == "parameter_change"


def test_unverified_members_cannot_file():
    new = make_member("n@x.org", "New", verified=False)
    with freeze_time("2026-07-15 10:00:00"), pytest.raises(services.PlanError, match="verified"):
        services.file_proposal(new, "focus", "x", "", {})


def test_the_plan_page_shows_the_period_and_the_proposals(client):
    ada = make_member("a@x.org", "Ada")
    with freeze_time("2026-07-15 10:00:00"):
        services.file_proposal(ada, "focus", "Focus on bread", "Why", {"trade_code": "B-10"})
    page = client.get("/plan/")
    assert page.status_code == 200 and b"Focus on bread" in page.content
