import pytest

from apps.tickets import confirm

from .conftest import answer, open_seats, pool, ticket_with_brief

pytestmark = pytest.mark.django_db


def into_panel():
    members = pool(40)
    t = ticket_with_brief(members[0])
    first = open_seats(t)
    answer(first[0], "no")
    t.refresh_from_db()
    assert t.status == "panel"
    return t, first


def test_7_of_12_approve():
    t, _first = into_panel()
    panel = open_seats(t, "panel")
    for s in panel[:7]:
        answer(s, "yes")
    t.refresh_from_db()
    assert t.status == "approved"


def test_6_of_12_reject_and_set_the_petition_time():
    t, _first = into_panel()
    panel = open_seats(t, "panel")
    for s in panel[:6]:
        answer(s, "yes")
    for s in panel[6:11]:
        answer(s, "no")
    t.refresh_from_db()
    assert t.status == "panel"  # one seat is still open: 6 yes, 5 no, 1 waiting
    answer(panel[11], "no")
    t.refresh_from_db()
    assert t.status == "rejected" and t.petition_until
    assert "petition" in t.author.notifications.first().text


def test_earlier_confirmers_are_never_on_the_panel():
    t, first = into_panel()
    earlier = {s.member_id for s in first}
    assert not earlier & {s.member_id for s in open_seats(t, "panel")}


def test_the_reasons_of_the_no_votes_are_listed_without_names_unless_shown():
    t, first = into_panel()
    rows = confirm.reasons(t)
    assert rows == [{"reason": "This is a reason that is long enough.", "name": first[0].member.display_name}]
    first[0].refresh_from_db()
    first[0].anonymous = True
    first[0].save()
    assert confirm.reasons(t)[0]["name"] is None


def test_the_panel_pays_45_minutes():
    t, _first = into_panel()
    seat = open_seats(t, "panel")[0]
    answer(seat, "yes")
    seat.refresh_from_db()
    assert seat.paid_entry.minutes == 45


def test_the_ticket_page_shows_names_only_after_the_decision(client):
    from django.urls import reverse

    t, first = into_panel()
    client.force_login(t.author.user)
    html = client.get(reverse("tickets:detail", args=[t.number])).content.decode()
    assert "Panel member 1" in html and "Confirmer 1" not in html  # the first round is decided: names show
    assert first[1].member.display_name in html
    panel = open_seats(t, "panel")
    assert f"<li>{panel[0].member.display_name}\n" not in html
    for s in panel[:7]:
        answer(s, "yes")
    html = client.get(reverse("tickets:detail", args=[t.number])).content.decode()
    assert f"<li>{panel[0].member.display_name}\n" in html
