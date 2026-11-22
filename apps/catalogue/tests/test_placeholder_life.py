from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.catalogue import services
from apps.catalogue.models import Item, OfferInput
from apps.units import services as us
from apps.units.models import CouncilDecision
from apps.units.tests.conftest import make_member, make_unit

pytestmark = pytest.mark.django_db
D = Decimal


def bakery(council=False):
    m = make_member("baker@x.org", "Baker")
    unit = make_unit("bakery")
    us.add_first_worker(unit, m)
    others = []
    if council:
        o = make_member("baker2@x.org", "Baker2")
        us.decide_join(us.request_to_join(unit, o), m, True)
        others.append(o)
    bread = services.create_item("Bread", "product", "pc")
    offer = services.create_offer(m, unit, bread, batch_size=D(40), direct_minutes_per_batch=240)
    row = services.add_input(m, offer, "Flour", "kg", D(24), "buy_outside", euro_price_estimate=D("0.8"))
    services.publish_offer(offer, m)
    return m, others, offer, row


def start_mill():
    mm = make_member("miller@x.org", "Miller")
    unit = make_unit("mill")
    us.add_first_worker(unit, mm)
    flour = Item.objects.get(name="Flour")
    o = services.create_offer(mm, unit, flour, batch_size=D(1), direct_minutes_per_batch=3)
    services.publish_offer(o, mm)
    return mm, o


def test_publishing_an_offer_for_a_placeholder_activates_it_and_notifies_its_users():
    m, others, offer, row = bakery()
    assert row.item.status == "placeholder"
    mail.outbox.clear()
    mm, mill_offer = start_mill()
    row.item.refresh_from_db()
    assert row.item.status == "active"
    told = [x for x in mail.outbox if "now makes" in x.subject]
    assert len(told) == 1 and told[0].to == [m.user.email]
    assert "Switch your input to Unicorn?" in told[0].body and "Mill" in told[0].body


def test_a_one_person_unit_switches_at_once():
    m, others, offer, row = bakery()
    start_mill()
    assert services.can_switch(row)
    assert services.switch_input_source(row, "unicorn", m) is None
    row.refresh_from_db()
    assert row.source == "unicorn"


def test_the_switch_goes_through_a_council_decision_in_a_council_unit():
    m, others, offer, row = bakery(council=True)
    start_mill()
    decision = services.switch_input_source(row, "unicorn", m)
    assert isinstance(decision, CouncilDecision) and decision.kind == "production"
    row.refresh_from_db()
    assert row.source == "buy_outside"  # not yet
    for member in [m, *others]:
        us.vote(decision, member, "yes")
    row.refresh_from_db()
    assert row.source == "unicorn"


def test_a_rejected_switch_changes_nothing():
    m, others, offer, row = bakery(council=True)
    start_mill()
    decision = services.switch_input_source(row, "unicorn", m)
    for member in [m, *others]:
        us.vote(decision, member, "no")
    row.refresh_from_db()
    assert row.source == "buy_outside"


def test_unused_placeholders_are_retired_after_a_year():
    m, others, offer, row = bakery()
    OfferInput.objects.filter(pk=row.pk).delete()
    assert services.retire_placeholders() == 0
    assert services.retire_placeholders(timezone.now() + timedelta(days=400)) == 1
    assert Item.objects.get(name="Flour").status == "retired"


def test_a_placeholder_in_a_recipe_is_not_retired():
    m, others, offer, row = bakery()
    assert services.retire_placeholders(timezone.now() + timedelta(days=400)) == 0
