from datetime import timedelta

import pytest
from django.utils import timezone

from apps.members import services as member_services
from apps.tasks import services
from apps.tasks.models import Mandate
from apps.tickets import confirm
from apps.tickets import services as ticket_services
from apps.tickets.models import Ticket

from .conftest import CHECK, answer, make_member, open_seats, pool

pytestmark = pytest.mark.django_db


def approved_need(powers=None):
    members = pool(40)
    author = make_member("author@x.org", "Author")
    ticket = ticket_services.create_ticket(
        "delegate",
        author,
        "Sign the lease",
        brief="We need someone to sign the lease for the workshop.",
        check=CHECK,
        action_payload={"needs_delegate": True, "powers": powers or {"spend_limit_eur": 100, "may_sign": True}},
    )
    for s in open_seats(ticket):
        answer(s, "yes")
    ticket.refresh_from_db()
    assert ticket.status == "approved" and ticket.action_payload["applications_until"]
    return members, author, ticket


def choose(ticket, applicants):
    for m, text in applicants:
        services.apply(ticket, m, text)
    services.close_applications(now=timezone.now() + timedelta(days=8))
    ticket.refresh_from_db()
    return Ticket.objects.get(number=ticket.action_payload["delegate_ticket"])


def rank(seat, ranking):
    seat.refresh_from_db()
    if not seat.check_passed:
        confirm.answer_check(seat, seat.confirmation.ticket.check_correct)
    return confirm.cast(seat, "yes", ranking=ranking)


def test_a_single_applicant_is_approved_by_four_yes_votes():
    members, author, ticket = approved_need()
    delegate_ticket = choose(ticket, [(members[1], "I know the landlord")])
    assert "Yes means this person" in delegate_ticket.brief_md
    for s in open_seats(delegate_ticket):
        answer(s, "yes")
    delegate_ticket.refresh_from_db()
    mandate = Mandate.objects.get()
    assert delegate_ticket.status == "done" and mandate.delegate == members[1] and mandate.status == "active"
    assert mandate.powers["spend_limit_eur"] == 100 and mandate.scope_md.startswith("We need someone")
    assert mandate.ends_at - mandate.starts_at == timedelta(days=90)


def test_applicants_are_never_seats_and_nobody_can_apply_late():
    members, author, ticket = approved_need()
    delegate_ticket = choose(ticket, [(members[1], "me"), (members[2], "me too")])
    seated = {s.member_id for s in open_seats(delegate_ticket)}
    assert not seated & {members[1].pk, members[2].pk, author.pk}
    with pytest.raises(services.TaskError):
        services.apply(ticket, members[3], "late")


def test_three_applicants_are_ranked_and_the_instant_runoff_picks_the_delegate():
    members, author, ticket = approved_need()
    a, b, c = members[1:4]
    delegate_ticket = choose(ticket, [(a, "A"), (b, "B"), (c, "C")])
    seats = open_seats(delegate_ticket)
    rank(seats[0], [a.pk, b.pk])
    rank(seats[1], [a.pk, c.pk])
    rank(seats[2], [b.pk, a.pk])
    rank(seats[3], [a.pk])
    delegate_ticket.refresh_from_db()
    assert delegate_ticket.status == "done"
    assert Mandate.objects.get().delegate == a


def test_none_of_them_counts_as_no_and_goes_to_a_panel():
    members, author, ticket = approved_need()
    delegate_ticket = choose(ticket, [(members[1], "A"), (members[2], "B")])
    seats = open_seats(delegate_ticket)
    rank(seats[0], [members[1].pk])
    answer(seats[1], "no")
    delegate_ticket.refresh_from_db()
    assert delegate_ticket.status == "panel"


def test_a_ranking_must_name_applicants():
    members, author, ticket = approved_need()
    delegate_ticket = choose(ticket, [(members[1], "A"), (members[2], "B")])
    seat = open_seats(delegate_ticket)[0]
    confirm.answer_check(seat, delegate_ticket.check_correct)
    with pytest.raises(confirm.SeatError):
        confirm.cast(seat, "yes", ranking=[members[9].pk])
    with pytest.raises(confirm.SeatError):
        confirm.cast(seat, "yes")


def test_nobody_applying_is_recorded_and_the_author_told():
    members, author, ticket = approved_need()
    services.close_applications(now=timezone.now() + timedelta(days=8))
    ticket.refresh_from_db()
    assert ticket.action_payload["delegate_status"] == "no_applicants"
    assert author.notifications.filter(text__contains="Nobody applied").exists()


def delegate_with_mandate(powers=None):
    members, author, ticket = approved_need(powers)
    delegate_ticket = choose(ticket, [(members[1], "me")])
    for s in open_seats(delegate_ticket):
        answer(s, "yes")
    return members[1], Mandate.objects.get()


def test_a_mandates_spending_above_its_limit_is_refused():
    delegate, mandate = delegate_with_mandate()
    assert services.spend(mandate, 80)["amount"] == "80"
    with pytest.raises(services.TaskError, match="more than the mandate allows"):
        services.spend(mandate, 100.5)


def test_an_expired_mandate_cannot_report_new_hours_or_spend():
    delegate, mandate = delegate_with_mandate()
    assert services.expire_mandates(now=timezone.now() + timedelta(days=91)) == 1
    mandate.refresh_from_db()
    assert mandate.status == "expired"
    with pytest.raises(services.TaskError):
        services.report(mandate, delegate, "Done", 60)
    with pytest.raises(services.TaskError):
        services.spend(mandate, 1)


def test_the_report_is_checked_by_one_seat_and_then_the_hours_are_paid():
    delegate, mandate = delegate_with_mandate()
    with pytest.raises(services.TaskError):
        services.report(mandate, make_member("other@x.org", "Other"), "Done", 60)
    ticket = services.report(mandate, delegate, "I signed the lease on Monday.", 90)
    mandate.refresh_from_db()
    assert mandate.hours_entry.status == "draft"  # not paid before the check
    seats = open_seats(ticket)
    assert len(seats) == 1 and seats[0].member != delegate
    answer(seats[0], "yes")
    mandate.refresh_from_db()
    ticket.refresh_from_db()
    assert mandate.status == "done" and mandate.hours_entry.status == "paid" and mandate.hours_entry.minutes == 90
    assert ticket.status == "done"


def test_a_report_the_seat_refuses_can_be_written_again():
    delegate, mandate = delegate_with_mandate()
    ticket = services.report(mandate, delegate, "Done.", 90)
    answer(open_seats(ticket)[0], "no")
    for s in open_seats(ticket, "panel")[:6]:
        answer(s, "no")
    mandate.refresh_from_db()
    assert mandate.status == "active" and mandate.report_at is None
    services.report(mandate, delegate, "Done, with proof.", 90)


def test_a_mandate_can_be_taken_back_by_random_confirmers():
    delegate, mandate = delegate_with_mandate()
    asker = make_member("asker@x.org", "Asker")
    ticket = services.open_revocation(asker, mandate, "They did nothing")
    for s in open_seats(ticket):
        answer(s, "yes")
    mandate.refresh_from_db()
    assert mandate.status == "revoked"
    assert delegate.notifications.filter(text__contains="taken back").exists()


def test_leaving_is_blocked_while_a_mandate_is_active():
    delegate, mandate = delegate_with_mandate()
    assert "active mandate" in " ".join(member_services.leave_blockers(delegate))
    services.expire_mandates(now=timezone.now() + timedelta(days=91))
    assert "active mandate" not in " ".join(member_services.leave_blockers(delegate))
