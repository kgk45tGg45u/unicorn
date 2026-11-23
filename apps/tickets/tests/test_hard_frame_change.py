from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.members import services as member_services
from apps.rules.models import ParameterChange
from apps.rules.services import get_param
from apps.tickets import services as ts
from apps.tickets.models import Ticket
from apps.tickets.tests.conftest import CHECK, answer, make_member, open_seats, pool
from apps.votes import services as votes
from apps.votes.models import Referendum

pytestmark = pytest.mark.django_db


def forecast(member):
    return member_services.store_private_file(
        member, SimpleUploadedFile("forecast.pdf", b"%PDF forecast", "application/pdf"), "other"
    )


def proposal(author, with_forecast=True, **kw):
    return ts.create_hard_frame_change(
        author,
        rule="economy.uniq_per_hour",
        new_text="One hour pays 2 UNIQ before tax.",
        why="The simulation says wages are too low.",
        code_change="Change the bound of economy.uniq_per_hour.",
        authors=[{"name": "A. Expert", "expertise": "Labour economist"}],
        forecast=forecast(author) if with_forecast else None,
        check=CHECK,
        **kw,
    )


def test_without_a_forecast_the_ticket_cannot_open():
    members = pool(8)
    with pytest.raises(ts.TicketError, match="forecast"):
        proposal(members[0], with_forecast=False)
    assert not Ticket.objects.exists()


def test_every_field_is_required():
    members = pool(8)
    with pytest.raises(ts.TicketError):
        ts.create_hard_frame_change(
            members[0], rule="", new_text="x", why="y", code_change="z",
            authors=[{"name": "A", "expertise": "B"}], forecast=forecast(members[0]), check=CHECK,
        )  # fmt: skip
    with pytest.raises(ts.TicketError):
        ts.create_hard_frame_change(
            members[0], rule="HF-2", new_text="x", why="y", code_change="z", authors=[], forecast=forecast(members[0]),
            check=CHECK,
        )  # fmt: skip


def test_the_referendum_uses_21_days_25_percent_and_two_thirds():
    members = pool(14)
    ticket = proposal(members[0])
    assert ticket.decision_method == "confirmers" and "complete and understandable" in ticket.decision_question
    for s in open_seats(ticket):
        answer(s, "yes")
    ticket.refresh_from_db()
    r = Referendum.objects.get(ticket=ticket)
    assert ticket.status == "referendum"
    assert r.closes_at - r.opens_at == timedelta(days=21)
    assert r.quorum_share == Decimal("0.25") and r.majority == "two_thirds"
    assert r.forecast_id and "Labour economist" in r.brief_for_md


def test_hf16_hard_change_needs_release():
    members = pool(14)
    ticket = proposal(members[0])
    for s in open_seats(ticket):
        answer(s, "yes")
    r = Referendum.objects.get(ticket=ticket)
    votes.open_due_referendums(now=timezone.now() + timedelta(days=2))
    for m in members[:6]:
        votes.cast(r, m, "yes")
    votes.close_referendums(now=timezone.now() + timedelta(days=40))
    ticket.refresh_from_db()
    assert ticket.status == "in_action" and "release" in ticket.status_note
    assert get_param("economy.uniq_per_hour") == Decimal("1")  # approval alone changes nothing
    assert not ParameterChange.objects.filter(decided_by__startswith="T-").exists()


def test_an_operator_records_the_release_and_the_ticket_is_done():
    members = pool(14)
    ticket = proposal(members[0])
    for s in open_seats(ticket):
        answer(s, "yes")
    r = Referendum.objects.get(ticket=ticket)
    votes.open_due_referendums(now=timezone.now() + timedelta(days=2))
    for m in members[:6]:
        votes.cast(r, m, "yes")
    votes.close_referendums(now=timezone.now() + timedelta(days=40))
    ticket.refresh_from_db()
    plain = make_member("plain@x.org", "Plain")
    with pytest.raises(ts.TicketError):
        ts.record_release(ticket, plain, "v1.2", "abc123")
    op = make_member("op@x.org", "Op")
    op.user.is_staff = True
    op.user.save()
    ts.record_release(ticket, op, "v1.2", "abc123")
    ticket.refresh_from_db()
    assert ticket.status == "done" and ticket.action_result["release"] == {"tag": "v1.2", "commit": "abc123"}


def test_a_forecast_is_readable_by_every_member():
    members = pool(8)
    ticket = proposal(members[0])
    pf = (
        member_services.get_private_file(ticket.action_payload["forecast_id"])
        if hasattr(member_services, "get_private_file")
        else None
    )
    from apps.members.models import PrivateFile

    pf = PrivateFile.objects.get(pk=ticket.action_payload["forecast_id"])
    assert member_services.can_view_file(members[3], pf)
    assert not member_services.can_view_file(None, pf)


def test_the_form_page_works(client):
    members = pool(8)
    client.force_login(members[0].user)
    assert client.get(reverse("tickets:hard_frame_new")).status_code == 200
    assert make_member
