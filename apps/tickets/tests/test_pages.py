from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.core.notify import notify
from apps.tickets import services
from apps.tickets.models import HelpfulMark, Notification

from .conftest import CHECK, make_member

pytestmark = pytest.mark.django_db


def test_comments_form_a_thread():
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    t = services.create_ticket("question", a, "How?")
    top = services.add_comment(t, b, "Like this")
    reply = services.add_comment(t, a, "Thanks", parent=top)
    assert reply.parent == top
    assert list(t.comments.all()) == [top, reply]


def test_a_helpful_mark_on_ones_own_comment_is_refused():
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    t = services.create_ticket("question", a, "How?")
    c = services.add_comment(t, b, "Like this")
    with pytest.raises(services.TicketError):
        services.mark_helpful(c, b)
    services.mark_helpful(c, a)
    with pytest.raises(services.TicketError):
        services.mark_helpful(c, a)
    assert HelpfulMark.objects.count() == 1


def test_comments_can_be_edited_for_15_minutes_and_edits_are_audited():
    from apps.core.models import AuditEvent

    a = make_member()
    t = services.create_ticket("question", a, "How?")
    c = services.add_comment(t, a, "first")
    services.edit_comment(c, a, "second")
    assert AuditEvent.objects.filter(verb="ticket.comment_edited").count() == 1
    with pytest.raises(services.TicketError):
        services.edit_comment(c, a, "third", now=timezone.now() + timedelta(minutes=16))


def test_notifications_are_created_for_replies_and_for_the_author():
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    t = services.create_ticket("question", a, "How?")
    services.add_comment(t, b, "Like this")
    assert Notification.objects.filter(member=a).count() == 1
    assert Notification.objects.filter(member=b).count() == 0


def test_notify_sends_an_email_only_when_asked():
    a = make_member()
    notify(a, "Hello", "/tickets/")
    assert mail.outbox == []
    notify(a, "Hello", "/tickets/", email=True)
    assert len(mail.outbox) == 1
    a.email_all_notifications = True
    notify(a, "Again", "/tickets/")
    assert len(mail.outbox) == 2


def test_the_pages_work(client):
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    t = services.create_ticket(
        "benefit_claim", a, "Help", brief="Need help", check=CHECK, action_payload={"claim_id": 1}
    )
    client.force_login(b.user)
    for tab in ("me", "all", "search"):
        assert client.get(reverse("tickets:list"), {"tab": tab, "q": "Help"}).status_code == 200
    page = client.get(reverse("tickets:detail", args=[t.number]))
    assert page.status_code == 200 and "Need help" in page.content.decode()
    client.post(reverse("tickets:comment", args=[t.number]), {"body": "Good luck"})
    assert t.comments.count() == 1
    assert client.get(reverse("tickets:notifications")).status_code == 200
    assert client.get(reverse("tickets:new")).status_code == 200


def test_a_new_ticket_can_be_made_in_the_form(client):
    a = make_member()
    client.force_login(a.user)
    response = client.post(reverse("tickets:new_form", args=["idea"]), {"title": "A bakery", "body": "Let us bake"})
    assert response.status_code == 302 and "/tickets/T-000001/" in response.url


def test_anonymous_visitors_are_sent_to_log_in(client):
    assert client.get(reverse("tickets:list")).status_code == 302
