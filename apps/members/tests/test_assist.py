from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.market.models import Order
from apps.market.tests.conftest import World
from apps.members import assist_services as svc
from apps.members.models import AssistConsent, AssistSummary, Member
from apps.tickets import services as ticket_services
from apps.tickets.models import Comment, Seat, Ticket
from apps.tickets.tests.conftest import pool, ticket_with_brief
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture(autouse=True)
def contracts(db):
    call_command("loaddata", "contracts", verbosity=0)


def signed_consent(helper, member, scopes=("orders", "bookings", "hours_entry", "tickets", "comments"), months=12):
    consent = svc.start(helper, member, list(scopes), months)
    return svc.sign_in_app(consent, member)


def act_for(client, helper, consent):
    client.force_login(helper.user)
    assert client.post(f"/assist/{consent.pk}/act/").status_code == 302


def test_an_order_placed_in_acting_for_mode_belongs_to_the_person_helped_and_shows_the_helper(client):
    world = World()
    helper = make_member("helper@x.org", "Helper")
    helped = world.buyer("helped@x.org", uniq=10)
    consent = signed_consent(helper, helped)
    act_for(client, helper, consent)
    page = client.get("/").content.decode()
    assert "You are acting for" in page and helped.number in page
    response = client.post(f"/offers/{world.bread.pk}/order/", {"quantity": "2"})
    assert response.status_code == 302, response.content.decode()[:500]
    order = Order.objects.get()
    assert order.buyer == helped and order.acted_by == helper
    assert "on your behalf" in client.get("/me/orders/").content.decode()
    event = AuditEvent.objects.filter(verb="order.placed").order_by("-id").first()
    assert event is not None and event.actor_ref == helped.number and event.acted_by == helper.number
    # the person helped sees it under "Done for me"
    client.post("/assist/stop/")
    client.force_login(helped.user)
    done = client.get("/me/done-for-me/").content.decode()
    assert helper.number in done and "order.placed" in done


def test_a_ticket_and_a_comment_store_the_helper(client):
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    consent = signed_consent(helper, helped)
    other = make_member("other@x.org", "Other")
    ticket = ticket_services.create_ticket("question", other, "A question")
    act_for(client, helper, consent)
    assert client.post(f"/tickets/{ticket.number}/comment/", {"body": "Please help me"}).status_code == 302
    comment = Comment.objects.get()
    assert comment.author == helped and comment.acted_by == helper
    page = client.get(f"/tickets/{ticket.number}/").content.decode()
    assert "on their behalf" in page and helper.number in page
    client.post("/tickets/new/idea/", {"title": "An idea", "body_md": "A better bench", "scope": "all"})
    mine = Ticket.objects.filter(author=helped).first()
    assert mine is not None and mine.acted_by == helper


def test_an_action_outside_the_consents_scopes_is_refused(client):
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    consent = signed_consent(helper, helped, scopes=("orders",))
    ticket = ticket_services.create_ticket("question", make_member("o@x.org", "O"), "A question")
    act_for(client, helper, consent)
    response = client.post(f"/tickets/{ticket.number}/comment/", {"body": "Not allowed"})
    assert response.status_code == 403 and "does not allow this" in response.content.decode()
    assert not Comment.objects.exists()


def test_hf13_votes_cannot_be_cast_on_behalf(client):
    members = pool(8)
    ticket = ticket_with_brief(members[0])
    seat = Seat.objects.filter(confirmation__ticket=ticket).first()
    helped = seat.member
    helper = make_member("helper@x.org", "Helper")
    consent = signed_consent(helper, helped)
    act_for(client, helper, consent)
    response = client.post(f"/seat/{seat.pk}/vote/", {"vote": "yes"})
    assert response.status_code == 403
    assert "cannot be done on behalf of someone else" in response.content.decode()
    seat.refresh_from_db()
    assert seat.vote is None
    # the same holds for the other things that are never done for someone else
    for path in ("/leave/", "/delete-account/"):
        assert client.post(path, {"confirm": "1"}).status_code == 403
    assert Member.objects.get(pk=helped.pk).status == "member"


def test_private_pages_are_not_opened_for_a_helper(client):
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    consent = signed_consent(helper, helped)
    act_for(client, helper, consent)
    response = client.get("/delete-account/")
    assert response.status_code == 403 and "private data" in response.content.decode()


def test_the_helper_limit_holds():
    helper = make_member("helper@x.org", "Helper")
    from apps.rules.models import Parameter

    Parameter.objects.filter(key="governance.assist.max_assisted_per_helper").update(value=2)
    for i in range(2):
        svc.start(helper, make_member(f"p{i}@x.org", f"P{i}"), ["orders"])
    with pytest.raises(svc.AssistError, match="limit is full"):
        svc.start(helper, make_member("p3@x.org", "P3"), ["orders"])
    with pytest.raises(svc.AssistError, match="your own helper"):
        svc.start(make_member("solo@x.org", "Solo"), Member.objects.get(user__email="solo@x.org"), ["orders"])


def test_the_consent_cannot_last_longer_than_the_maximum_and_needs_a_scope():
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    consent = svc.start(helper, helped, ["orders"], months=99)
    assert consent.valid_until <= timezone.now() + timedelta(days=370)
    with pytest.raises(svc.AssistError, match="at least one"):
        svc.start(helper, make_member("q@x.org", "Q"), ["voting"])  # voting is not a scope at all


def test_a_revoked_consent_stops_acting_for_mode_at_once(client):
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    consent = signed_consent(helper, helped)
    act_for(client, helper, consent)
    assert "You are acting for" in client.get("/").content.decode()
    svc.revoke(consent, helped)  # the person helped ends it
    page = client.get("/").content.decode()
    assert "You are acting for" not in page
    assert client.post(f"/assist/{consent.pk}/act/").status_code == 302
    assert "You are acting for" not in client.get("/").content.decode()
    with pytest.raises(svc.AssistError, match="Only the person helped or the helper"):
        svc.revoke(consent, make_member("x@x.org", "X"))


def test_an_expired_consent_stops_by_itself(client):
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    consent = signed_consent(helper, helped)
    act_for(client, helper, consent)
    AssistConsent.objects.filter(pk=consent.pk).update(valid_until=timezone.now() - timedelta(minutes=1))
    assert "You are acting for" not in client.get("/").content.decode()


def test_an_unsigned_consent_cannot_be_used(client):
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    consent = svc.start(helper, helped, ["orders"])
    client.force_login(helper.user)
    client.post(f"/assist/{consent.pk}/act/")
    assert "You are acting for" not in client.get("/").content.decode()
    with pytest.raises(svc.AssistError, match="Only the person who is helped"):
        svc.sign_in_app(consent, helper)


def test_a_paper_consent_needs_an_identity_helper_who_is_neither_party():
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    witness = make_member("witness@x.org", "Witness")
    Member.objects.filter(pk=witness.pk).update(is_identity_helper=True)
    witness.refresh_from_db()
    consent = svc.start(helper, helped, ["orders"])
    assert svc.waiting_for_witness(witness) == []  # no scan yet
    scan = SimpleUploadedFile("consent.pdf", b"%PDF-1.4 paper", content_type="application/pdf")
    consent = svc.attach_paper(consent, helper, scan)
    assert svc.consent_for_helper(helper, consent.pk) is None  # a scan alone is not enough
    assert [c.pk for c in svc.waiting_for_witness(witness)] == [consent.pk]
    with pytest.raises(svc.AssistError, match="identity helper"):
        svc.witness_paper(consent, make_member("plain@x.org", "Plain"))
    Member.objects.filter(pk=helper.pk).update(is_identity_helper=True)
    helper.refresh_from_db()
    with pytest.raises(svc.AssistError, match="cannot confirm their own"):
        svc.witness_paper(consent, helper)
    svc.witness_paper(consent, witness)
    assert svc.consent_for_helper(helper, consent.pk) is not None
    assert consent.paper_copy.owner == helped


def test_the_monthly_summary_is_emailed_and_sent_once():
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    from apps.core import acting, audit

    token = acting.set_helper(helper)
    try:
        audit.record(helped.number, "order.placed")
    finally:
        acting.reset(token)
    next_month = (timezone.localdate().replace(day=28) + timedelta(days=5)).replace(day=1)
    mail.outbox.clear()
    assert svc.send_monthly_summaries(next_month) == 1
    assert len(mail.outbox) == 1 and "order.placed" in mail.outbox[0].body
    assert svc.send_monthly_summaries(next_month) == 0
    assert AssistSummary.objects.get().on_paper is False


def test_a_member_without_an_email_gets_a_paper_summary_for_the_helper_to_hand_over():
    helper = make_member("helper@x.org", "Helper")
    helped = make_member("helped@x.org", "Helped")
    signed_consent(helper, helped)
    from apps.core import acting, audit

    token = acting.set_helper(helper)
    try:
        audit.record(helped.number, "order.placed")
    finally:
        acting.reset(token)
    helped.user.email = ""
    helped.user.save()
    next_month = (timezone.localdate().replace(day=28) + timedelta(days=5)).replace(day=1)
    svc.send_monthly_summaries(next_month)
    assert AssistSummary.objects.get().on_paper is True
    ((member, lines),) = svc.paper_summaries_for(helper, next_month)
    assert member == helped and "order.placed" in lines[0]
