from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.ledger.models import Transaction
from apps.members import services as member_services
from apps.plan import check as plan_check
from apps.tickets import actions, briefs, services
from apps.tickets.models import Ticket
from apps.units import services as us
from apps.units.models import HoursEntry, Unit

from .conftest import CHECK, answer, make_member, make_unit, open_seats, pool

pytestmark = pytest.mark.django_db


def red(monkeypatch):
    result = plan_check.CheckResult([plan_check.CheckPoint("red", "Too many bakeries")])
    monkeypatch.setattr(plan_check, "check", lambda request: result)


UNIT_DATA = {"name": "Bakery", "kind": "production", "description": "Bread"}


def decide(ticket, votes=("yes",) * 4):
    for seat, v in zip(open_seats(ticket), votes, strict=False):
        answer(seat, v)
    ticket.refresh_from_db()
    return ticket


def test_hf15_checks_route_to_people_a_red_unit(monkeypatch):
    pool(8)
    red(monkeypatch)
    unit = us.open_unit(make_member("a@x.org", "Ada"), UNIT_DATA)
    ticket = Ticket.objects.get(type="open_unit")
    assert unit.status == "paused" and ticket.action_payload["unit_id"] == unit.pk
    assert ticket.status == "confirming" and ticket.plan_check["color"] == "red"


def test_an_approved_open_unit_ticket_opens_the_unit_and_pays_the_seats(monkeypatch):
    pool(8)
    red(monkeypatch)
    unit = us.open_unit(make_member("a@x.org", "Ada"), UNIT_DATA)
    ticket = decide(Ticket.objects.get(type="open_unit"))
    unit.refresh_from_db()
    assert ticket.status == "done" and ticket.action_result["status"] == "trial"
    assert unit.status == "trial" and unit.opened_at and unit.trial_until
    seats = open_seats(ticket)
    assert all(s.paid_entry.minutes == 30 for s in seats)


def test_hf15_checks_route_to_people_a_red_offer(monkeypatch):
    from apps.catalogue import services as cat

    pool(8)
    m = make_member("a@x.org", "Ada")
    unit = make_unit("bakery")
    us.add_first_worker(unit, m)
    offer = cat.create_offer(
        m, unit, cat.create_item("Bread", "product", "pc"), batch_size=Decimal(40), cycle_days=1,
        setup_minutes=30, direct_minutes_per_batch=240,
    )  # fmt: skip
    red(monkeypatch)
    cat.publish_offer(offer, m)
    ticket = Ticket.objects.get(type="offer_red_check")
    assert ticket.action_payload["offer_id"] == offer.pk
    offer.refresh_from_db()
    assert offer.status == "draft"
    monkeypatch.undo()
    decide(ticket)
    offer.refresh_from_db()
    assert offer.status == "active"


def test_hf15_checks_route_to_people_a_possible_duplicate():
    from apps.members.models import User

    pool(8)
    a = make_member("a@x.org", "Ada", verified=False)
    member_services.set_private(a, phone="+49 30 1234")
    b = member_services.create_applicant(User.objects.create_user("b@x.org"), "Bo", "DE")
    member_services.set_private(b, phone="49301234")
    ticket = Ticket.objects.get(type="duplicate_suspected")
    assert ticket.action_payload["newer"] == b.number
    member_services.set_private(b, phone="49301234")  # saving again does not open another ticket
    assert Ticket.objects.filter(type="duplicate_suspected").count() == 1
    decide(ticket)
    b.refresh_from_db()
    assert b.status == "suspended"


def test_hf15_checks_route_to_people_a_dispute(monkeypatch):
    pool(8)
    ticket = briefs.dispute(
        make_member("b@x.org", "Buyer"), "Damaged", "Bread", make_unit("bakery"), {"order_line": 1, "text": "torn"}
    )
    assert ticket.type == "flag" and ticket.status == "confirming"


def test_a_failed_audit_opens_one_ticket(monkeypatch):
    from apps.ledger.models import AuditRun

    pool(8)
    run = AuditRun.objects.create(
        started_at=timezone.now(), finished_at=timezone.now(), ok=False, last_seq=0, last_hash="0", findings=["Bad"]
    )
    assert briefs.audit_failure(run) is not None
    assert briefs.audit_failure(run) is None
    assert Ticket.objects.filter(type="audit_failure").count() == 1


def test_an_approved_hours_correct_posts_a_correction_with_the_ticket_number():
    pool(8)
    a = make_member("a@x.org", "Ada")
    unit = make_unit("bakery")
    us.add_first_worker(unit, a)
    entry = us.record_hours(a, unit, timezone.localdate(), 120)
    assert entry.status == "paid"
    ticket = services.create_ticket(
        "hours_review", None, "Too many hours", brief="b", check=CHECK, action="hours_correct",
        action_payload={"entry_id": entry.pk, "minutes": 60, "units": [unit.pk]},
    )  # fmt: skip
    decide(ticket)
    entry.refresh_from_db()
    assert ticket.status == "done", ticket.action_result
    assert entry.minutes == 60 and entry.status == "paid"
    corrections = Transaction.objects.filter(kind="correction")
    assert corrections.count() == 2 and all(ticket.number in c.reason for c in corrections)


def test_an_hours_review_without_a_correction_just_confirms():
    pool(8)
    ticket = services.create_ticket(
        "hours_review", None, "Look", brief="b", check=CHECK, action_payload={"offer_id": 1, "units": []}
    )
    decide(ticket)
    assert ticket.status == "done" and ticket.action_result == {"confirmed": True}


def test_a_licence_ticket_lets_its_seats_view_the_document_only_while_open():
    pool(8)
    m = make_member("a@x.org", "Ada")
    licence = member_services.submit_licence(m, "health_care", SimpleUploadedFile("l.pdf", b"%PDF", "application/pdf"))
    ticket = Ticket.objects.get(type="verify_licence")
    seats = open_seats(ticket)
    assert len(seats) == 2
    outsider = make_member("z@x.org", "Zed")
    pf = licence.document
    assert member_services.can_view_file(seats[0].member, pf) and not member_services.can_view_file(outsider, pf)
    decide(ticket, ("yes", "yes"))
    licence.refresh_from_db()
    assert ticket.status == "done" and licence.status == "verified" and licence.decided_by == ticket.number
    assert not member_services.can_view_file(seats[0].member, pf)
    assert member_services.can_view_file(m, pf)


def test_a_licence_the_panel_refuses_is_rejected():
    pool(30)
    m = make_member("a@x.org", "Ada")
    licence = member_services.submit_licence(m, "health_care", SimpleUploadedFile("l.pdf", b"%PDF", "application/pdf"))
    ticket = Ticket.objects.get(type="verify_licence")
    answer(open_seats(ticket)[0], "no")
    for s in open_seats(ticket, "panel")[:6]:
        answer(s, "no")
    ticket.refresh_from_db()
    licence.refresh_from_db()
    assert ticket.status == "rejected" and licence.status == "rejected"


def test_a_council_decision_also_has_a_ticket_and_the_tally_updates_it():
    unit = make_unit("bakery")
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    us.add_first_worker(unit, a)
    us.decide_join(us.request_to_join(unit, b), a, True)
    decision = us.open_decision(a, unit, "Bake more")
    ticket = Ticket.objects.get(type="council_decision")
    assert ticket.scope_unit == unit and decision.payload["ticket"] == ticket.number
    us.vote(decision, a, "yes")
    us.vote(decision, b, "yes")
    ticket.refresh_from_db()
    assert ticket.status == "approved"
    d2 = us.open_decision(a, unit, "Bake less")
    us.vote(d2, a, "no")
    us.vote(d2, b, "no")
    t2 = Ticket.objects.get(number=d2.payload["ticket"])
    assert t2.status == "rejected"


def test_a_one_person_units_decision_is_approved_at_once():
    unit = make_unit("solo")
    a = make_member()
    us.add_first_worker(unit, a)
    decision = us.open_decision(a, unit, "Change my hours")
    assert Ticket.objects.get(number=decision.payload["ticket"]).status == "approved"


def test_a_failing_action_leaves_the_ticket_in_action_and_tells_the_operators():
    pool(8)
    op = make_member("op@x.org", "Op")
    op.user.is_staff = True
    op.user.save()
    ticket = services.create_ticket(
        "hours_review", None, "Look", brief="b", check=CHECK, action="hours_correct",
        action_payload={"entry_id": 999999, "minutes": 10, "units": []},
    )  # fmt: skip
    decide(ticket)
    assert ticket.status == "in_action" and ticket.action_result["error"]
    assert op.notifications.filter(text__contains=ticket.number).exists()


def test_an_action_that_nothing_carries_out_yet_stays_approved_with_a_note():
    pool(8)
    ticket = services.create_ticket("benefit_claim", make_member("a@x.org", "Ada"), "Help", brief="b", check=CHECK)
    decide(ticket)
    assert ticket.status == "approved" and "pending" in ticket.action_result


def test_a_ticket_without_a_unit_is_refused_when_the_action_needs_one():
    with pytest.raises(services.TicketError):
        services.create_ticket("close_unit", make_member(), "Close", scope="all")


def test_the_monthly_one_person_checks_sample_the_units_once_a_month():
    from apps.tickets import sampling

    pool(8)
    units = []
    for i in range(10):
        member = make_member(f"solo{i}@x.org", f"Solo{i}")
        unit = make_unit(f"solo-{i}")
        us.add_first_worker(unit, member)
        units.append(unit)
    assert sampling.one_person_checks() == 1  # a tenth of ten
    assert Ticket.objects.filter(type="one_person_check").count() == 1
    assert sampling.one_person_checks() == 0  # safe to run twice
    ticket = Ticket.objects.get(type="one_person_check")
    assert len(open_seats(ticket)) == 1
    answer(open_seats(ticket)[0], "yes")
    seat = open_seats(ticket)[0]
    seat.refresh_from_db()
    assert seat.paid_entry.minutes == 15
    assert AuditEvent.objects.filter(verb="tickets.one_person_checks_done").count() == 1
    assert HoursEntry.objects.filter(unit=Unit.objects.get(slug="coordination")).count() == 1


def test_every_action_a_type_names_is_registered_or_still_to_be_built():
    from apps.tickets.types import TYPES

    for info in TYPES.values():
        for name in (info.action, info.reject_action):
            assert not name or name in actions.ACTIONS or name in PENDING


PENDING = {
    "create_payment_requests",
    "start_benefit",
    "start_guarantee",
    "change_parameter",
    "create_tasks",
    "flag_remove",
    "flag_keep",
    "pause_unit",
}
