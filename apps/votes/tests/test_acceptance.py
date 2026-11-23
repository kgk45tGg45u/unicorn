"""The acceptance check of phase 07 (plan/phase_07_votes_delegation_tasks.md)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.rules.services import get_param
from apps.tasks import services as task_services
from apps.tasks.models import Mandate
from apps.tickets import services as ticket_services
from apps.tickets.models import Ticket
from apps.votes import services as votes
from apps.votes.models import Referendum

from .conftest import CHECK, answer, make_member, open_seats, pool, rejected_ticket

pytestmark = pytest.mark.django_db


def test_phase_07_acceptance(client):
    members = pool(40)

    # 1. A rejected ticket gets a petition; it reaches its threshold, and a referendum opens and closes.
    ticket = rejected_ticket(members[0])
    petition = votes.open_petition(ticket, members[1], "Should we do this bold idea?")
    for m in members[2:6]:
        petition.refresh_from_db()
        if petition.status == "open":
            votes.sign(petition, m)
    petition.refresh_from_db()
    assert petition.status == "succeeded"
    referendum = Referendum.objects.get(ticket=ticket)
    votes.open_due_referendums(now=timezone.now() + timedelta(days=2))
    receipts = {m.pk: votes.cast(referendum, m, "yes") for m in members[:12]}
    votes.close_referendums(now=timezone.now() + timedelta(days=30))

    # 2. The result decides the ticket, and a member can check their ballot by receipt.
    referendum.refresh_from_db()
    ticket.refresh_from_db()
    assert referendum.result["approved"] and ticket.status == "approved"
    client.force_login(members[3].user)
    page = client.get(reverse("votes:check"), {"code": receipts[members[3].pk]}).content.decode()
    assert "yes" in page and "Counted in" in page

    # 3. A parameter change of tier `confirm` changes the default after 4 yes votes, and the history links the ticket.
    change = ticket_services.create_parameter_change(members[10], "logistics.default_cover_radius_km", 20, "Wider area")
    assert get_param("logistics.default_cover_radius_km") == Decimal("10")
    for s in open_seats(change):
        answer(s, "yes")
    assert get_param("logistics.default_cover_radius_km") == Decimal("20")
    history = client.get(reverse("rules:history", args=["logistics.default_cover_radius_km"])).content.decode()
    assert f"/tickets/{change.number}/" in history

    # 4. A delegate is chosen, reports and is paid.
    author = make_member("author@x.org", "Author")
    need = ticket_services.create_ticket(
        "delegate", author, "Sign the lease", brief="Someone must sign.", check=CHECK,
        action_payload={"needs_delegate": True, "powers": {"spend_limit_eur": 50, "may_sign": True}},
    )  # fmt: skip
    for s in open_seats(need):
        answer(s, "yes")
    task_services.apply(need, members[20], "I can do it")
    task_services.close_applications(now=timezone.now() + timedelta(days=8))
    need.refresh_from_db()
    choice = Ticket.objects.get(number=need.action_payload["delegate_ticket"])
    for s in open_seats(choice):
        answer(s, "yes")
    mandate = Mandate.objects.get()
    assert mandate.delegate == members[20] and mandate.status == "active"
    report = task_services.report(mandate, members[20], "Signed on Monday.", 60)
    answer(open_seats(report)[0], "yes")
    mandate.refresh_from_db()
    assert mandate.status == "done" and mandate.hours_entry.status == "paid"
