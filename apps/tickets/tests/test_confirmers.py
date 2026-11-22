from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tickets import confirm
from apps.units.models import HoursEntry

from .conftest import CHECK, answer, open_seats, pool, ticket_with_brief

pytestmark = pytest.mark.django_db


def setup_ticket(n=40):
    members = pool(n)
    t = ticket_with_brief(members[0])
    t.refresh_from_db()
    return members, t


def test_four_yes_votes_approve():
    members, t = setup_ticket()
    seats = open_seats(t)
    assert len(seats) == 4
    for s in seats:
        answer(s, "yes")
    t.refresh_from_db()
    assert t.status == "approved" and t.decided_at


def test_one_no_starts_a_panel():
    members, t = setup_ticket()
    seats = open_seats(t)
    answer(seats[0], "yes")
    answer(seats[1], "no")
    t.refresh_from_db()
    assert t.status == "panel"
    assert len(open_seats(t, "panel")) == 12


def test_a_no_needs_a_reason_of_20_characters():
    members, t = setup_ticket()
    seat = open_seats(t)[0]
    assert confirm.answer_check(seat, CHECK["correct"])
    with pytest.raises(confirm.SeatError):
        confirm.cast(seat, "no", "too short")


def test_a_vote_needs_the_check_first():
    members, t = setup_ticket()
    seat = open_seats(t)[0]
    with pytest.raises(confirm.SeatError):
        confirm.cast(seat, "yes")


def test_a_wrong_check_answer_twice_replaces_the_seat():
    members, t = setup_ticket()
    seat = open_seats(t)[0]
    assert confirm.answer_check(seat, 0) is False
    seat.refresh_from_db()
    assert not seat.replaced
    assert confirm.answer_check(seat, 2) is False
    seat.refresh_from_db()
    assert seat.replaced
    assert len(open_seats(t)) == 4  # a new member took the seat
    assert seat.replaced_by.get().member != seat.member


def test_a_silent_seat_is_redrawn_then_counts_as_no():
    members, t = setup_ticket()
    for s in open_seats(t)[1:]:
        answer(s, "yes")
    later = timezone.now() + timedelta(days=4)
    for round_ in range(1, 4):
        confirm.process_deadlines(now=later + timedelta(days=4 * round_))
        t.refresh_from_db()
        if round_ < 3:
            assert t.status == "confirming"
    assert t.status == "panel"  # the silence counted as no
    silent = [s for s in confirm.active_seats(t.confirmations.first()) if s.vote == "no"]
    assert len(silent) == 1 and not silent[0].answered and silent[0].paid_entry is None


def test_reminders_go_out_24_hours_before_the_deadline():
    from apps.tickets.models import Notification

    members, t = setup_ticket()
    soon = timezone.now() + timedelta(hours=60)
    confirm.process_deadlines(now=soon)
    assert Notification.objects.filter(text__startswith="Reminder").count() == 4
    confirm.process_deadlines(now=soon)
    assert Notification.objects.filter(text__startswith="Reminder").count() == 4


def test_each_vote_creates_a_paid_30_minute_coordination_entry():
    members, t = setup_ticket()
    seat = open_seats(t)[0]
    answer(seat, "yes")
    seat.refresh_from_db()
    entry = HoursEntry.objects.get(pk=seat.paid_entry_id)
    assert entry.minutes == 30 and entry.unit.kind == "coordination" and entry.status == "paid"
    assert entry.ref_type == "seat" and entry.activity == "coordination"


def test_a_conflict_of_interest_replaces_the_seat():
    members, t = setup_ticket()
    seat = open_seats(t)[0]
    confirm.declare_conflict(seat)
    seat.refresh_from_db()
    assert seat.replaced and len(open_seats(t)) == 4
    from apps.tickets import draw

    assert seat.member.number not in [m.number for m in draw.eligible(t)]


def test_the_seat_pages_work(client):
    from django.urls import reverse

    members, t = setup_ticket()
    seat = open_seats(t)[0]
    client.force_login(seat.member.user)
    page = client.get(reverse("tickets:seat", args=[seat.pk]))
    assert page.status_code == 200 and "The brief." in page.content.decode()
    client.post(reverse("tickets:seat", args=[seat.pk]), {"choice": CHECK["correct"]})
    seat.refresh_from_db()
    assert seat.check_passed and seat.opened_at
    other = open_seats(t)[1]
    assert client.get(reverse("tickets:seat", args=[other.pk])).status_code == 404  # only the seated member
