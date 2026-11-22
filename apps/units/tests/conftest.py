from io import StringIO

import pytest
from django.core.management import call_command

from apps.members import services as ms
from apps.members.models import Member, User
from apps.units.models import Unit


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())


def make_member(email="a@x.org", name="Ada", verified=True):
    from apps.ledger.services import open_member_accounts

    m = ms.create_applicant(User.objects.create_user(email), name, "DE")
    if verified:
        m.status = Member.MEMBER
        m.save()
        open_member_accounts(m)
    return m


def make_unit(slug="bakery", kind="production", **kw):
    return Unit.objects.create(name=slug.title(), slug=slug, kind=kind, status=kw.pop("status", "open"), **kw)


@pytest.fixture
def mk():
    return make_member
