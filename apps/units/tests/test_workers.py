import pytest
from django.urls import reverse

from apps.units import services
from apps.units.models import JoinRequest

from .conftest import make_member, make_unit

pytestmark = pytest.mark.django_db


def two_workers():
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    unit = make_unit()
    services.add_first_worker(unit, a)
    req = services.request_to_join(unit, b)
    return unit, a, b, req


def test_has_council_turns_true_with_the_second_worker():
    unit, a, b, req = two_workers()
    assert not services.has_council(unit)
    services.decide_join(req, a, True)
    assert services.has_council(unit)
    assert {m.member for m in services.council_members(unit)} == {a, b}


def test_a_non_member_cannot_decide_a_join_request():
    unit, a, b, req = two_workers()
    c = make_member("c@x.org", "Cy")
    with pytest.raises(services.UnitError):
        services.decide_join(req, c, True)
    with pytest.raises(services.UnitError):
        services.decide_join(req, b, True)  # the person asking cannot decide it either
    assert JoinRequest.objects.get(pk=req.pk).status == "open"


def test_hf13_only_verified_members_join_units():
    unit = make_unit()
    applicant = make_member("p@x.org", "Pat", verified=False)
    with pytest.raises(services.UnitError):
        services.request_to_join(unit, applicant)


def test_a_member_can_work_in_two_units_at_once():
    a = make_member()
    u1, u2 = make_unit("one"), make_unit("two")
    services.add_first_worker(u1, a)
    services.add_first_worker(u2, a)
    assert services.is_worker(a, u1) and services.is_worker(a, u2)


def test_leaving_ends_the_membership_and_allows_rejoining():
    unit, a, b, req = two_workers()
    services.decide_join(req, a, True)
    services.leave_unit(b, unit)
    assert not services.is_worker(b, unit)
    services.add_first_worker(unit, b)
    assert services.is_worker(b, unit)


def test_second_worker_runs_the_hook():
    seen = []
    services.SECOND_WORKER_HOOKS.append(seen.append)
    try:
        unit, a, b, req = two_workers()
        services.decide_join(req, a, True)
    finally:
        services.SECOND_WORKER_HOOKS.remove(seen.append)
    assert seen == [unit]


def test_pages(client):
    unit, a, b, req = two_workers()
    client.force_login(a.user)
    page = client.get(reverse("units:unit", args=[unit.slug]))
    assert page.status_code == 200
    assert "Bo" in page.content.decode()  # the open join request is shown to the council
    assert client.get(reverse("units:list")).status_code == 200
