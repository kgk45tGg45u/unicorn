import pytest

from apps.tickets import services
from apps.units import services as us

from .conftest import make_member, make_unit, pool, ticket_with_brief

pytestmark = pytest.mark.django_db


def test_a_unit_scope_council_ticket_creates_a_council_decision():
    unit = make_unit("bakery")
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    us.add_first_worker(unit, a)
    us.decide_join(us.request_to_join(unit, b), a, True)
    t = services.create_ticket("join_forces", a, "Join forces", "Let us merge", scope="unit", scope_unit=unit)
    from apps.units.models import CouncilDecision

    decision = CouncilDecision.objects.get(pk=t.action_payload["council_decision"])
    assert decision.unit == unit and decision.payload["ticket"] == t.number
    assert t.decision_method == "council" and t.status == "open"


def test_a_question_stays_open():
    t = services.create_ticket("question", make_member(), "How?")
    assert t.status == "open" and t.decision_method == "none" and not t.confirmations.exists()


def test_a_ticket_for_confirmers_draws_them():
    members = pool(8)
    t = ticket_with_brief(members[0])
    t.refresh_from_db()
    assert t.status == "confirming" and t.confirmations.get().seats.count() == 4


def test_an_automatic_ticket_that_is_not_green_goes_to_confirmers():
    members = pool(8)
    unit = make_unit("bakery", status="paused")
    t = services.create_ticket(
        "open_unit",
        members[0],
        "Open a unit",
        brief="The brief.",
        check={"question": "q?", "choices": ["a", "b", "c"], "correct": 0},
        plan_check={"color": "red", "points": []},
        action_payload={"unit_id": unit.pk},
    )
    t.refresh_from_db()
    assert t.decision_method == "confirmers" and t.status == "confirming"


def test_a_ticket_with_nobody_to_draw_waits_and_is_tried_again():
    from apps.tickets import confirm

    author = make_member()
    t = ticket_with_brief(author)
    t.refresh_from_db()
    assert t.status == "open" and "Waiting" in t.status_note
    pool(6)
    confirm.process_deadlines()
    t.refresh_from_db()
    assert t.status == "confirming"
