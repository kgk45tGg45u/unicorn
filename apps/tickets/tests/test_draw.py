from datetime import timedelta

import pytest
from django.utils import timezone

from apps.members.models import Member
from apps.rules.models import Parameter
from apps.tickets import confirm, draw, services
from apps.tickets.models import Conflict
from apps.units import services as us

from .conftest import make_unit, pool, ticket_with_brief

pytestmark = pytest.mark.django_db


def numbers(confirmation):
    return [s.member.number for s in confirmation.seats.order_by("drawn_order")]


def test_the_same_inputs_give_the_same_seats():
    members = pool(10)
    t = ticket_with_brief(members[0], open_now=False)
    before = [m.number for m in draw.eligible(t)]
    c1 = draw.draw(t, "confirmers", 4)
    # a second ticket with the same number cannot exist, so repeat the draw by its published inputs instead
    assert draw.reproduce(c1, before) == numbers(c1)
    assert c1.seed and c1.eligible_count == 9


def test_reproduce_refuses_a_list_that_was_not_used():
    members = pool(10)
    t = ticket_with_brief(members[0], open_now=False)
    c = draw.draw(t, "confirmers", 4)
    with pytest.raises(ValueError):
        draw.reproduce(c, ["M-0000-0000"])


def test_the_author_and_the_units_workers_are_never_drawn():
    members = pool(9)
    unit = make_unit("bakery")
    us.add_first_worker(unit, members[1])
    us.decide_join(us.request_to_join(unit, members[2]), members[1], True)
    t = services.create_ticket("close_unit", members[0], "Close", scope="unit", scope_unit=unit, open_now=False)
    pool_numbers = {m.number for m in draw.eligible(t)}
    assert members[0].number not in pool_numbers
    assert members[1].number not in pool_numbers and members[2].number not in pool_numbers
    assert len(pool_numbers) == 6


def test_the_monthly_limit_holds():
    members = pool(6)
    Parameter.objects.filter(key="governance.confirmers.max_draws_per_month").update(value=1)
    first = ticket_with_brief(members[0], open_now=False)
    drawn = draw.draw(first, "confirmers", 2)
    second = services.create_ticket("delegate", members[0], "Other", brief="b", check=ticket_check(), open_now=False)
    again = {m.pk for m in draw.eligible(second)}
    assert not ({s.member_id for s in drawn.seats.all()} & again)


def ticket_check():
    from .conftest import CHECK

    return CHECK


def test_hf13_unverified_never_drawn():
    members = pool(6)
    applicant = pool(1, prefix="app")[0]
    Member.objects.filter(pk=applicant.pk).update(status=Member.APPLICANT)
    t = ticket_with_brief(members[0], open_now=False)
    assert applicant.number not in [m.number for m in draw.eligible(t)]


def test_new_members_are_not_drawn_but_founders_are_exempt_in_the_first_year():
    members = pool(6)
    newbie = pool(1, prefix="new", months=0)[0]
    founder = pool(1, prefix="fo", months=0)[0]
    Member.objects.filter(pk=founder.pk).update(is_founder=True)
    t = ticket_with_brief(members[0], open_now=False)
    found = {m.number for m in draw.eligible(t)}
    assert newbie.number not in found and founder.number in found


def test_a_declared_conflict_and_a_break_keep_a_member_out():
    members = pool(6)
    t = ticket_with_brief(members[0], open_now=False)
    Conflict.objects.create(ticket=t, member=members[1])
    Member.objects.filter(pk=members[2].pk).update(draw_pause_until=timezone.localdate() + timedelta(days=5))
    found = {m.number for m in draw.eligible(t)}
    assert members[1].number not in found and members[2].number not in found


def test_a_local_ticket_draws_only_from_the_area():
    members = pool(6)
    Member.objects.filter(pk__in=[m.pk for m in members[:3]]).update(postcode="10115")
    Member.objects.filter(pk__in=[m.pk for m in members[3:]]).update(postcode="80331")
    t = services.create_ticket("idea", members[0], "Local", scope="local", scope_area="101", open_now=False)
    assert {m.number for m in draw.eligible(t)} == {members[1].number, members[2].number}


def test_fewer_eligible_than_seats_seats_everyone_and_says_so():
    members = pool(3)
    t = ticket_with_brief(members[0])
    t.refresh_from_db()
    assert t.confirmations.get().seats.count() == 2 and "Only 2" in t.status_note
    assert confirm.active_seats(t.confirmations.get())
