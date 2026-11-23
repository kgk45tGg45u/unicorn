from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bodies import local, services
from apps.bodies.models import LocalCouncil, LocalResponsibility
from apps.logistics.models import PickupPoint
from apps.members.models import Member
from apps.tickets.models import Ticket
from apps.tickets.tests.conftest import answer, open_seats, pool

pytestmark = pytest.mark.django_db


def residents(n, postcode="10115", prefix="r", country="DE"):
    people = pool(n, prefix=prefix)
    Member.objects.filter(pk__in=[m.pk for m in people]).update(postcode=postcode, country=country)
    for m in people:
        m.refresh_from_db()
    return people


def open_council(people, prefix="10", name="Berlin Mitte", level="district"):
    ticket = local.propose_council(people[0], name, prefix, level)
    for seat in open_seats(ticket):
        answer(seat, "yes")
    ticket.refresh_from_db()
    assert ticket.status == "done", ticket.status_note
    return LocalCouncil.objects.get(country="DE", postcode_prefix=prefix)


def test_a_council_cannot_open_with_fewer_members_than_the_minimum():
    people = residents(5)
    with pytest.raises(services.BodyError, match="Not enough members live here yet: 5 of the 10"):
        local.propose_council(people[0], "Berlin Mitte", "10", "district")
    assert not Ticket.objects.filter(type="local_council_open").exists()


def test_only_members_of_the_area_are_drawn_and_the_council_opens_when_they_agree():
    people = residents(12)
    elsewhere = residents(6, postcode="80331", prefix="m")
    abroad = residents(6, postcode="10115", prefix="a", country="AT")
    ticket = local.propose_council(people[0], "Berlin Mitte", "10", "district")
    drawn = {s.member_id for s in open_seats(ticket)}
    assert drawn and drawn <= {m.pk for m in people[1:]}
    assert not drawn & {m.pk for m in elsewhere + abroad}
    for seat in open_seats(ticket):
        answer(seat, "yes")
    council = LocalCouncil.objects.get()
    assert council.postcode_prefix == "10" and council.level == "district" and council.ticket == ticket


def test_only_a_member_of_the_area_can_ask_and_an_area_has_one_council():
    people = residents(12)
    outsider = residents(1, postcode="80331", prefix="o")[0]
    with pytest.raises(services.BodyError, match="live in the area"):
        local.propose_council(outsider, "Berlin Mitte", "10", "district")
    open_council(people)
    with pytest.raises(services.BodyError, match="already a council"):
        local.propose_council(people[1], "Again", "10", "district")


def test_moving_to_another_postcode_changes_which_councils_a_member_belongs_to():
    people = residents(12)
    district = open_council(people, "10115", "Mitte")
    town = open_council(people, "10", "Berlin", "town")
    mover = people[3]
    assert {c.pk for c in local.councils_of(mover)} == {district.pk, town.pk}
    Member.objects.filter(pk=mover.pk).update(postcode="10999")
    mover.refresh_from_db()
    assert [c.pk for c in local.councils_of(mover)] == [town.pk]
    Member.objects.filter(pk=mover.pk).update(postcode="80331")
    mover.refresh_from_db()
    assert local.councils_of(mover) == []
    assert not local.belongs(mover, town)


def test_a_pickup_point_is_opened_by_a_local_ticket():
    people = residents(12)
    council = open_council(people)
    point = {"name": "Corner shop", "address": "Main Street 1", "postcode": "10115", "notes": "Open 9 to 5"}
    ticket = local.propose_decision(
        people[1], council, "A pickup point in Mitte", "A shop that will keep parcels.", "open_pickup_point",
        {"point": point},
    )  # fmt: skip
    assert ticket.scope == "local" and ticket.scope_area == "10"
    drawn = {s.member_id for s in open_seats(ticket)}
    assert drawn <= {m.pk for m in people if m.pk != people[1].pk}
    for seat in open_seats(ticket):
        answer(seat, "yes")
    created = PickupPoint.objects.get()
    assert created.managed_by_local_council == council and created.active
    close = local.propose_decision(
        people[2], council, "Close the corner shop", "The shop closed.", "close_pickup_point", {"point_id": created.pk}
    )
    for seat in open_seats(close):
        answer(seat, "yes")
    created.refresh_from_db()
    assert not created.active


def test_a_pickup_point_outside_the_area_is_refused_when_carried_out():
    people = residents(12)
    council = open_council(people)
    point = {"name": "Far shop", "address": "Street 1", "postcode": "80331"}
    ticket = local.propose_decision(
        people[1], council, "A far pickup point", "x", "open_pickup_point", {"point": point}
    )
    for seat in open_seats(ticket):
        answer(seat, "yes")
    ticket.refresh_from_db()
    assert ticket.status == "in_action" and not PickupPoint.objects.exists()
    with pytest.raises(services.BodyError, match="live in the area"):
        local.propose_decision(residents(1, "80331", "q")[0], council, "x", "x")


def test_the_responsible_rotates_among_volunteers_and_stays_empty_without_any():
    people = residents(12)
    council = open_council(people)
    assert local.current_responsible(council) is None
    first = local.volunteer(people[0], council)
    assert local.current_responsible(council).member == people[0] and first.withdrawn_at is None
    local.volunteer(people[1], council)
    local.volunteer(people[2], council)
    assert local.rotate_local(timezone.now() + timedelta(days=100)) == 0
    assert local.rotate_local(timezone.now() + timedelta(days=200)) == 1
    assert local.current_responsible(council).member != people[0]
    assert LocalResponsibility.objects.filter(council=council, ends_at__isnull=False).count() == 1
    for m in people[:3]:
        local.withdraw(m, council)
    assert local.current_responsible(council) is None  # the page says so


def test_a_responsible_who_moves_away_hands_the_role_over():
    people = residents(12)
    council = open_council(people)
    local.volunteer(people[0], council)
    local.volunteer(people[1], council)
    Member.objects.filter(pk=people[0].pk).update(postcode="80331")
    assert local.rotate_local() == 1
    assert local.current_responsible(council).member == people[1]
    with pytest.raises(services.BodyError, match="live in the area"):
        local.volunteer(Member.objects.get(pk=people[0].pk), council)


def test_the_responsible_can_decline_a_turn():
    people = residents(12)
    council = open_council(people)
    local.volunteer(people[0], council)
    local.volunteer(people[1], council)
    row = local.decline_turn(people[0], council)
    assert row.member == people[1]
    with pytest.raises(services.BodyError, match="not the responsible"):
        local.decline_turn(people[0], council)


def test_the_pickup_point_migration_refuses_to_run_if_the_placeholder_holds_a_value():
    import importlib
    from types import SimpleNamespace

    migration = importlib.import_module(
        "apps.logistics.migrations.0003_remove_pickuppoint_managed_by_local_council_id_and_more"
    )

    def stub(used):
        qs = SimpleNamespace(filter=lambda **kw: SimpleNamespace(exists=lambda: used))
        return SimpleNamespace(get_model=lambda label, name: SimpleNamespace(objects=qs))

    migration.refuse_if_used(stub(False), None)
    with pytest.raises(RuntimeError, match="managed_by_local_council_id"):
        migration.refuse_if_used(stub(True), None)


def test_the_council_page_lists_the_helpers_of_the_area():
    from apps.members import assist_services

    people = residents(12)
    council = open_council(people)
    assert local.area_helpers(council) == []
    assist_services.start(people[0], people[1], ["orders"])
    assert local.area_helpers(council) == [people[0]]
