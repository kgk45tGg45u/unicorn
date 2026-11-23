"""Builders for the outside-shop tests: the bakery world, its baker as a holder and outside seller."""

from decimal import Decimal
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command

from apps.market.tests.conftest import World
from apps.outside import services
from apps.tradefund import services as fund

D = Decimal
IBAN = "DE89 3704 0044 0532 0130 00"


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())
    call_command("loaddata", "contracts", verbosity=0)
    mail.outbox.clear()


class Shop(World):
    """The bakery, with the baker as a holder and an outside seller selling bread for 5.00 euros."""

    def __init__(self, small_business=True, price="5.00"):
        super().__init__()
        fund.become_holder(self.baker, "EUR", IBAN)
        self.profile = services.activate_seller(
            self.baker, "Baker Bakery", "Mill Road 1\n12345 Town", small_business=small_business
        )
        services.apply_outside_offer(self.bread, price, "EUR", self.baker)
        self.bread.refresh_from_db()

    def order(self, quantity=2, email="c@example.org"):
        return services.place_outside_order(
            self.bread, quantity, "Cora Customer", email, "Street 5\n99999 City", "DE", True, True
        )

    def pay(self, order, amount=None):
        line = order.lines.get()
        amount = amount if amount is not None else services.total_of(line)
        return services.confirm_customer_payment(order, self.baker, amount)


@pytest.fixture
def shop():
    return Shop()


@pytest.fixture
def world():
    return World()
