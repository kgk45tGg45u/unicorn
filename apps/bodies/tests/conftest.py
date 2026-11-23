from io import StringIO

import pytest
from django.core.management import call_command

from apps.units import services as unit_services
from apps.units.tests.conftest import make_member, make_unit  # noqa: F401


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())


def one_person_unit(slug, email, trade="wood", name=None):
    """A unit with one worker, who is also its responsible. Its decisions take effect at once."""
    unit = make_unit(slug, trade_code=trade)
    member = make_member(email, name or slug.title())
    unit_services.add_first_worker(unit, member)
    return unit, member


def council_unit(slug, emails, trade="wood"):
    """A unit with a working council of several members; the first is the responsible."""
    unit = make_unit(slug, trade_code=trade)
    people = [make_member(e, f"{slug}{i}") for i, e in enumerate(emails)]
    unit_services.add_first_worker(unit, people[0])
    for p in people[1:]:
        unit_services.decide_join(unit_services.request_to_join(unit, p), people[0], True)
    return unit, people


def active_union(name="Woodworkers", trade="wood", council_emails=None):
    """An active union of a three-person council unit and a one-person unit. Returns (union, a, people, b, member_b)."""
    from apps.bodies import services

    b, mb = one_person_unit(f"{name.lower()}-solo", f"{name.lower()}-solo@x.org", trade)
    a, people = council_unit(
        f"{name.lower()}-crew", council_emails or [f"{name.lower()}-{i}@x.org" for i in range(3)], trade
    )
    union = services.form_union(mb, b, name, [trade])
    services.accept_invitation(services.invite_unit(mb, union, a), people[0])
    decision = a.decisions.get()
    for p in people:
        unit_services.vote(decision, p, "yes")
    union.refresh_from_db()
    assert union.status == "active"
    return union, a, people, b, mb
