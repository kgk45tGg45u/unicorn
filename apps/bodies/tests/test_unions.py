import importlib
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.bodies import services
from apps.bodies.models import Union, UnionMembership
from apps.tickets.models import Ticket
from apps.units import services as unit_services

from .conftest import council_unit, one_person_unit

pytestmark = pytest.mark.django_db


def test_a_union_becomes_active_with_the_second_unit():
    a, ma = one_person_unit("woodshop-a", "a@x.org")
    b, mb = one_person_unit("woodshop-b", "b@x.org")
    union = services.form_union(ma, a, "Woodworkers", ["wood"], "People who make things of wood")
    union.refresh_from_db()
    assert union.status == "forming" and services.is_member_unit(union, a)  # a one-person unit decides at once
    ticket = services.invite_unit(ma, union, b)
    assert ticket.status == "draft" and ticket.author_id == mb.pk
    services.accept_invitation(ticket, mb)
    union.refresh_from_db()
    assert union.status == "active" and union.forming_since is None
    assert services.current_rules(union).version == 1


def test_a_units_council_decides_its_own_joining():
    unit, people = council_unit("woodshop-c", ["c0@x.org", "c1@x.org", "c2@x.org"])
    other, other_member = one_person_unit("woodshop-d", "d@x.org")
    union = services.form_union(other_member, other, "Woodworkers", ["wood"])
    ticket = services.invite_unit(other_member, union, unit)
    services.accept_invitation(ticket, people[0])
    ticket.refresh_from_db()
    assert ticket.status == "open" and not services.is_member_unit(union, unit)
    decision = unit.decisions.get()
    for p in people:
        unit_services.vote(decision, p, "yes")
    union.refresh_from_db()
    assert services.is_member_unit(union, unit) and union.status == "active"
    assert Ticket.objects.get(pk=ticket.pk).status in ("approved", "done")


def test_a_council_that_says_no_keeps_the_unit_out():
    unit, people = council_unit("woodshop-e", ["e0@x.org", "e1@x.org", "e2@x.org"])
    other, other_member = one_person_unit("woodshop-f", "f@x.org")
    union = services.form_union(other_member, other, "Woodworkers", ["wood"])
    services.accept_invitation(services.invite_unit(other_member, union, unit), people[0])
    decision = unit.decisions.get()
    for p in people:
        unit_services.vote(decision, p, "no")
    assert not services.is_member_unit(union, unit)


def test_a_union_with_one_unit_left_returns_to_forming_and_is_dissolved_after_90_days():
    a, ma = one_person_unit("woodshop-g", "g@x.org")
    b, mb = one_person_unit("woodshop-h", "h@x.org")
    union = services.form_union(ma, a, "Woodworkers", ["wood"])
    services.accept_invitation(services.invite_unit(ma, union, b), mb)
    union.refresh_from_db()
    assert union.status == "active"
    services.leave_union(mb, union, b)
    union.refresh_from_db()
    assert union.status == "forming" and union.forming_since is not None
    assert services.dissolve_forming(timezone.now() + timedelta(days=89)) == 0
    assert services.dissolve_forming(timezone.now() + timedelta(days=91)) == 1
    union.refresh_from_db()
    assert union.status == "dissolved"
    assert not UnionMembership.objects.filter(union=union, left_at__isnull=True).exists()
    assert services.dissolve_forming(timezone.now() + timedelta(days=200)) == 0  # safe to run twice


def test_only_the_responsible_of_a_unit_can_form_or_invite():
    a, ma = one_person_unit("woodshop-i", "i@x.org")
    stranger = one_person_unit("woodshop-j", "j@x.org")[1]
    with pytest.raises(services.BodyError, match="responsible"):
        services.form_union(stranger, a, "Woodworkers", ["wood"])
    union = services.form_union(ma, a, "Woodworkers", ["wood"])
    with pytest.raises(services.BodyError, match="Only members"):
        services.invite_unit(stranger, union, a)
    with pytest.raises(services.BodyError, match="name"):
        services.form_union(ma, a, " ", ["wood"])
    with pytest.raises(services.BodyError, match="already a union"):
        services.form_union(ma, a, "woodworkers", ["wood"])
    assert Union.objects.count() == 1


def test_the_migration_refuses_to_run_if_a_placeholder_field_holds_a_value():
    for module, _model, field in (
        ("apps.tickets.migrations.0007_remove_ticket_scope_union_id_ticket_scope_union", "Ticket", "scope_union_id"),
        (
            "apps.plan.migrations.0002_remove_expertadviser_nominated_by_union_id_and_more",
            "ExpertAdviser",
            "nominated_by_union_id",
        ),
    ):
        migration = importlib.import_module(module)

        def stub(used):
            qs = SimpleNamespace(filter=lambda **kw: SimpleNamespace(exists=lambda: used))
            return SimpleNamespace(get_model=lambda label, name: SimpleNamespace(objects=qs))

        migration.refuse_if_used(stub(False), None)  # empty: fine
        with pytest.raises(RuntimeError, match=field):
            migration.refuse_if_used(stub(True), None)
