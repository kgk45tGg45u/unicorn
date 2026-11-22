from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.catalogue import services
from apps.catalogue.models import Item, OwnFreeConfirmation
from apps.core.models import Job
from apps.plan import check as plan_check
from apps.units import services as us
from apps.units.tests.conftest import make_member, make_unit

pytestmark = pytest.mark.django_db
D = Decimal


def setup(kind="production"):
    member = make_member()
    unit = make_unit(kind=kind)
    us.add_first_worker(unit, member)
    bread = services.create_item("Bread", "product", "pc")
    offer = services.create_offer(
        member, unit, bread, batch_size=D(40), cycle_days=1, setup_minutes=30, direct_minutes_per_batch=240
    )
    return member, unit, offer


def test_a_unicorn_input_without_an_active_offer_is_refused():
    m, unit, offer = setup()
    services.add_input(m, offer, "Flour", "kg", D(24), "unicorn")
    msgs = services.validate_recipe(offer)
    assert "not made in Unicorn yet" in msgs[0]  # the new name became a placeholder
    flour = Item.objects.get(name="Flour")
    flour.status = "active"
    flour.save()
    assert "Nobody in Unicorn makes Flour yet" in services.validate_recipe(offer)[0]


def test_a_placeholder_may_only_be_own_free_or_bought():
    m, unit, offer = setup()
    services.add_input(m, offer, "Salt", "kg", D("0.5"), "buy_outside", euro_price_estimate=D("0.6"))
    assert services.validate_recipe(offer) == []


def test_buy_outside_needs_a_price_and_own_free_needs_a_worker():
    m, unit, offer = setup()
    services.add_input(m, offer, "Salt", "kg", D("0.5"), "buy_outside")
    services.add_input(m, offer, "Oven power", "kwh", D(3), "own_free")
    other = make_member("o@x.org", "Out")
    services.add_input(m, offer, "Eggs", "pc", D(10), "own_free", provided_by=other)
    msgs = services.validate_recipe(offer)
    assert any("estimate the price" in x for x in msgs)
    assert sum("which worker" in x for x in msgs) == 2


def test_a_to_buy_tool_blocks_publishing():
    m, unit, offer = setup()
    services.add_tool(m, offer, "Big oven", "to_buy", D(1), D(1000))
    with pytest.raises(services.RecipeBlocked) as e:
        services.publish_offer(offer, m)
    assert "Buy the tool first: ask the trade fund" in e.value.messages[0]
    offer.refresh_from_db()
    assert offer.status == "draft"


def test_publishing_activates_and_queues_one_recompute():
    m, unit, offer = setup()
    services.add_input(m, offer, "Salt", "kg", D("0.5"), "buy_outside", euro_price_estimate=D("0.6"))
    services.add_tool(m, offer, "My oven", "own_free", D(1), D(1000), provided_by=m)
    offer = services.publish_offer(offer, m)
    assert offer.status == "active"
    assert Job.objects.filter(kind="catalogue.recompute").count() == 1
    services.request_recompute()
    assert Job.objects.filter(kind="catalogue.recompute").count() == 1  # same minute: one run


def test_hf15_a_red_plan_check_keeps_the_offer_a_draft(monkeypatch):
    m, unit, offer = setup()
    red = plan_check.CheckResult([plan_check.CheckPoint("red", "too much")])
    monkeypatch.setattr(plan_check, "check", lambda request: red)
    offer = services.publish_offer(offer, m)
    assert offer.status == "draft" and "random confirmers" in offer.status_note


def test_hf17_service_offers_need_insurance():
    m = make_member()
    unit = make_unit("cuts", kind="service")
    us.add_first_worker(unit, m)
    cut = services.create_item("Haircut", "service", "service")
    offer = services.create_offer(m, unit, cut, duration_minutes=40, capacity=1)
    with pytest.raises(services.RecipeBlocked):
        services.publish_offer(offer, m)
    unit.insurance_confirmed = True
    unit.save()
    assert services.publish_offer(offer, m).status == "active"


def test_an_unconfirmed_own_free_input_pauses_the_offer_after_two_months():
    m, unit, offer = setup()
    services.add_input(m, offer, "Eggs", "pc", D(10), "own_free", provided_by=m)
    offer = services.publish_offer(offer, m)
    assert services.ask_own_free(date(2026, 1, 15)) == 0
    assert services.ask_own_free(date(2026, 2, 15)) == 0
    assert services.ask_own_free(date(2026, 2, 16)) == 0  # safe to run twice
    assert services.ask_own_free(date(2026, 3, 15)) == 1
    offer.refresh_from_db()
    assert offer.status == "paused"


def test_a_confirmed_input_keeps_the_offer_active():
    m, unit, offer = setup()
    row = services.add_input(m, offer, "Eggs", "pc", D(10), "own_free", provided_by=m)
    offer = services.publish_offer(offer, m)
    services.ask_own_free(date(2026, 1, 15))
    OwnFreeConfirmation.objects.filter(input=row).update(confirmed_at="2026-01-20T10:00:00Z")
    services.ask_own_free(date(2026, 2, 15))
    assert services.ask_own_free(date(2026, 3, 15)) == 0
    other = make_member("o@x.org", "Out")
    with pytest.raises(services.CatalogueError):
        services.confirm_own_free(other, row)


def test_the_editor_page(client):
    m, unit, offer = setup()
    client.force_login(m.user)
    assert client.get(reverse("catalogue:recipe", args=[offer.pk])).status_code == 200
    r = client.post(
        reverse("catalogue:add_input", args=[offer.pk]),
        {"name": "Salt", "quantity": "0.5", "uom": "kg", "source": "buy_outside", "euro_price_estimate": "0.6"},
    )
    assert r.status_code == 302 and offer.inputs.count() == 1
    client.force_login(make_member("z@x.org", "Zed").user)
    assert client.get(reverse("catalogue:recipe", args=[offer.pk])).status_code == 403
