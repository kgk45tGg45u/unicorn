"""Shared builders for the market tests: a mill, a bakery, a hairdresser, and members with UNIQ."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.catalogue import services as cat
from apps.ledger import services as ledger
from apps.units import services as us
from apps.units.tests.conftest import make_member, make_unit

D = Decimal


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())


def fund(member, amount):
    """Give a member UNIQ the only legal way: as pay for hours (Fund 2 to the member)."""
    ledger.post(
        "hours_pay",
        "test funding",
        [ledger.Leg(ledger.fund2(), -D(amount)), ledger.Leg(ledger.member_account(member), D(amount))],
    )


def unit_for(member, slug, **kw):
    unit = make_unit(slug, **kw)
    us.add_first_worker(unit, member)
    return unit


class World:
    """The bakery example of docs/04: bread (0.1425 UNIQ) needs flour from the mill and salt from outside."""

    def __init__(self, with_bread=True, mode="on_order"):
        self.baker = make_member("baker@x.org", "Baker")
        self.miller = make_member("miller@x.org", "Miller")
        self.mill_unit = unit_for(self.miller, "mill", mode="continuous")
        self.bakery_unit = unit_for(self.baker, "bakery", mode=mode)
        flour_item = cat.create_item("Flour", "product", "kg")
        self.mill = cat.create_offer(
            self.miller, self.mill_unit, flour_item, batch_size=D(100), cycle_days=1, direct_minutes_per_batch=300
        )
        cat.publish_offer(self.mill, self.miller)
        bread_item = cat.create_item("Bread", "product", "pc", shelf_life_days=5)
        self.bread = cat.create_offer(
            self.baker,
            self.bakery_unit,
            bread_item,
            batch_size=D(40),
            cycle_days=1,
            setup_minutes=30,
            direct_minutes_per_batch=240,
        )
        cat.add_input(self.baker, self.bread, "Flour", "kg", D(24), "unicorn")
        cat.add_input(self.baker, self.bread, "Salt", "kg", D("0.5"), "buy_outside", euro_price_estimate=D("0.6"))
        cat.publish_offer(self.bread, self.baker)
        cat.recompute_values()
        self.bread.refresh_from_db()
        self.mill.refresh_from_db()

    def buyer(self, email="buyer@x.org", uniq=10):
        m = make_member(email, "Buyer")
        fund(m, uniq)
        return m


@pytest.fixture
def world():
    return World()
