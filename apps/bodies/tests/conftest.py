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
