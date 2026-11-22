import pytest
from django.core import mail
from django.urls import reverse

from apps.tickets import flags, services
from apps.tickets.models import Flag, Hidden, Ticket
from apps.tickets.templatetags import ticket_tags

from .conftest import answer, make_member, open_seats, pool

pytestmark = pytest.mark.django_db


def commented():
    members = pool(30)
    author = make_member("author@x.org", "Author")
    t = services.create_ticket("question", members[0], "How?")
    comment = services.add_comment(t, author, "A rude comment")
    return members, author, comment


def test_the_first_flag_opens_a_ticket_and_later_flags_join_it():
    members, author, comment = commented()
    flags.flag(members[1], "comment", comment.pk, "harassment", "It is rude")
    ticket = Ticket.objects.get(type="flag")
    assert ticket.status == "confirming" and len(open_seats(ticket)) == 4 and ticket.author == members[1]
    flags.flag(members[2], "comment", comment.pk, "harassment")
    assert Ticket.objects.filter(type="flag").count() == 1 and Flag.objects.filter(ticket=ticket).count() == 2
    assert author.number in ticket.action_payload["members"]


def test_three_flags_hide():
    members, author, comment = commented()
    for m in members[1:3]:
        flags.flag(m, "comment", comment.pk, "harassment")
    assert not flags.is_hidden("comment", comment.pk)
    flags.flag(members[3], "comment", comment.pk, "other")
    assert flags.is_hidden("comment", comment.pk) and Hidden.objects.count() == 1
    assert comment.pk in flags.hidden_ids("comment")


def test_one_cannot_flag_twice_or_flag_ones_own_work():
    members, author, comment = commented()
    flags.flag(members[1], "comment", comment.pk, "other")
    with pytest.raises(flags.FlagError):
        flags.flag(members[1], "comment", comment.pk, "other")
    with pytest.raises(flags.FlagError):
        flags.flag(author, "comment", comment.pk, "other")
    with pytest.raises(flags.FlagError):
        flags.flag(members[2], "comment", comment.pk, "nonsense")


def test_removal_sends_the_statement_of_reasons():
    members, author, comment = commented()
    for m in members[1:4]:
        flags.flag(m, "comment", comment.pk, "harassment", "It is rude")
    ticket = Ticket.objects.get(type="flag")
    mail.outbox.clear()
    for s in open_seats(ticket):
        answer(s, "yes")
    ticket.refresh_from_db()
    assert ticket.status == "done" and ticket.action_result["removed"]
    assert (
        "It is rude" in ticket.action_result["statement"]
        and "4 said it should be removed" in ticket.action_result["statement"]
    )
    assert flags.is_hidden("comment", comment.pk)
    assert author.notifications.filter(text__startswith="A statement of reasons").exists()
    assert any(author.user.email in m.to for m in mail.outbox)


def test_keeping_unhides_and_tells_the_flaggers():
    members, author, comment = commented()
    for m in members[1:4]:
        flags.flag(m, "comment", comment.pk, "other")
    ticket = Ticket.objects.get(type="flag")
    answer(open_seats(ticket)[0], "no")
    panel = open_seats(ticket, "panel")
    for s in panel[:6]:
        answer(s, "no")
    ticket.refresh_from_db()
    assert ticket.status == "rejected"
    assert not flags.is_hidden("comment", comment.pk)
    assert members[1].notifications.filter(text__contains="content stays").exists()


def test_the_author_sees_a_hidden_comment_with_the_reasons_and_others_do_not(client):
    members, author, comment = commented()
    for m in members[1:4]:
        flags.flag(m, "comment", comment.pk, "harassment", "It is rude")
    ticket = comment.ticket
    client.force_login(members[5].user)
    html = client.get(reverse("tickets:detail", args=[ticket.number])).content.decode()
    assert "A rude comment" not in html and "Hidden while members review a report" in html
    client.force_login(author.user)
    html = client.get(reverse("tickets:detail", args=[ticket.number])).content.decode()
    assert "A rude comment" in html and "It is rude" in html


def test_the_flag_form_works(client):
    members, author, comment = commented()
    client.force_login(members[1].user)
    response = client.post(
        reverse("tickets:flag"),
        {"target_type": "comment", "target_id": comment.pk, "reason": "other", "text": "hm", "next": "/tickets/"},
    )
    assert response.status_code == 302 and Flag.objects.count() == 1


def test_the_template_filter_knows_hidden_things():
    members, author, comment = commented()
    for m in members[1:4]:
        flags.flag(m, "comment", comment.pk, "other")
    assert ticket_tags.is_hidden(comment) is True
    assert ticket_tags.is_hidden(members[0]) is False


def test_the_author_can_contest_a_removal_before_a_panel_that_never_includes_the_first_deciders():
    members, author, comment = commented()
    for m in members[1:4]:
        flags.flag(m, "comment", comment.pk, "harassment", "It is rude")
    ticket = Ticket.objects.get(type="flag")
    first = open_seats(ticket)
    for s in first:
        answer(s, "yes")
    ticket.refresh_from_db()
    assert flags.can_contest(ticket, author) and not flags.can_contest(ticket, members[5])
    contest = flags.contest(ticket, author)
    assert contest.status == "panel" and not flags.can_contest(ticket, author)
    panel = open_seats(contest, "panel")
    assert not {s.member_id for s in first} & {s.member_id for s in panel}
    for s in panel[:7]:
        answer(s, "yes")
    contest.refresh_from_db()
    assert contest.status == "done" and not flags.is_hidden("comment", comment.pk)
    assert members[1].notifications.filter(text__contains="content stays").exists()


def test_hidden_offers_leave_the_market_search():
    from apps.market import services as market
    from apps.market.tests.conftest import World

    pool(8)
    world = World()
    assert world.bread in market.search_offers(text="bread")
    ticket = services.create_ticket("question", make_member("q@x.org", "Q"), "Q")
    flags.hide("offer", world.bread.pk, ticket)
    assert world.bread not in market.search_offers(text="bread")
    assert flags.owners("offer", world.bread.pk) == [world.baker]
    with pytest.raises(flags.FlagError):
        flags.flag(world.baker, "offer", world.bread.pk, "other")
