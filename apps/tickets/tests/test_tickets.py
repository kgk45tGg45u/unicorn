import pytest

from apps.tickets import services, types
from apps.tickets.models import Ticket

from .conftest import CHECK, make_member

pytestmark = pytest.mark.django_db


def test_numbers_are_consecutive():
    m = make_member()
    a = services.create_ticket("question", m, "One")
    b = services.create_ticket("idea", m, "Two")
    assert (a.number, b.number) == ("T-000001", "T-000002")
    assert Ticket.objects.count() == 2


def test_every_type_of_the_docs_exists():
    for key in ("open_unit", "close_unit", "purchase", "flag", "mediation", "hard_frame_change", "audit_failure"):
        assert key in types.TYPES
    assert types.TYPES["verify_licence"].confirmers == 2
    assert types.TYPES["one_person_check"].confirmers == 1


CLAIM = {"claim_id": 1}  # the benefit action needs to know its claim


def test_a_type_that_needs_a_check_question_refuses_without_one():
    m = make_member()
    with pytest.raises(services.TicketError):
        services.create_ticket("benefit_claim", m, "Help", brief="I need help", action_payload=CLAIM)
    with pytest.raises(services.TicketError):
        services.create_ticket(
            "benefit_claim", m, "Help", brief="I need help", check={"question": "x?"}, action_payload=CLAIM
        )
    t = services.create_ticket("benefit_claim", m, "Help", brief="I need help", check=CHECK, action_payload=CLAIM)
    assert t.check_correct == 1 and t.decision_method == "confirmers" and t.action == "start_benefit"


def test_a_brief_over_500_words_is_refused():
    m = make_member()
    with pytest.raises(services.TicketError):
        services.create_ticket("question", m, "Long", brief="word " * 501)
    services.create_ticket("question", m, "Fine", brief="word " * 500)


def test_a_ticket_is_recorded_in_the_audit_log():
    from apps.core.models import AuditEvent

    m = make_member()
    t = services.create_ticket("question", m, "One")
    assert AuditEvent.objects.filter(verb="ticket.created", object_id=str(t.pk)).exists()
