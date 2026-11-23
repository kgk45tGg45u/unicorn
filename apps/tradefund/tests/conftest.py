from io import StringIO

import pytest
from django.core.management import call_command

from apps.units.tests.conftest import make_member, make_unit  # noqa: F401


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())
    call_command("loaddata", "contracts", verbosity=0)


IBAN = "DE89 3704 0044 0532 0130 00"


def make_holder(email="h@x.org", name="Holder", currency="EUR", amount=None, **kw):
    """A verified member who is a holder, optionally holding `amount` (as a set-aside, for tests)."""
    from apps.tradefund import books, services

    m = make_member(email, name)
    holder = services.become_holder(m, currency, IBAN, **kw)
    if amount:
        books.post_fund(holder, "setaside", amount, "test funding", "gift")
    return holder


def make_ticket(author=None, title="Buy a thing"):
    """A plain ticket to hang payments on."""
    from apps.tickets.models import Ticket
    from apps.tickets.services import _next_number

    return Ticket.objects.create(
        number=_next_number(),
        type="question",
        title=title,
        author=author,
        decision_method="none",
        status="done",
    )


def set_param(key, value):
    """Change a default directly, for a test (real changes go through tickets, HF-16)."""
    from apps.rules.models import Parameter

    Parameter.objects.filter(key=key).update(value=value)
