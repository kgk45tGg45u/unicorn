from decimal import Decimal

import pytest

from apps.catalogue import services
from apps.units import services as us
from apps.units.tests.conftest import make_member, make_unit

pytestmark = pytest.mark.django_db
D = Decimal


def setup():
    member = make_member()
    unit = make_unit()
    us.add_first_worker(unit, member)
    return member, unit


def test_bread():
    m, unit = setup()
    bread = services.create_item("Bread", "product", "pc")
    o = services.create_offer(
        m, unit, bread, batch_size=D(40), cycle_days=1, setup_minutes=30, direct_minutes_per_batch=240
    )
    assert o.declared_hours_per_unit == D("0.1125")
    assert o.min_batch == 40 and o.advance_share == D("0.1")
    assert o.status == "draft"


def test_haircut_with_and_without_travel():
    m, unit = setup()
    cut = services.create_item("Haircut", "service", "service")
    o = services.create_offer(m, unit, cut, duration_minutes=40, capacity=1, travel_minutes=20, place="customer")
    assert o.declared_hours_per_unit == D("1.0000")
    assert o.advance_share == 0
    o = services.update_offer(m, o, place="unit")
    assert o.declared_hours_per_unit == D("0.6667")


def test_group_lesson():
    m, unit = setup()
    lesson = services.create_item("Yoga class", "service", "service")
    o = services.create_offer(m, unit, lesson, duration_minutes=90, capacity=10)
    assert o.declared_hours_per_unit == D("0.1500")


def test_a_product_offer_with_service_fields_is_refused():
    m, unit = setup()
    bread = services.create_item("Bread", "product", "pc")
    with pytest.raises(services.CatalogueError):
        services.create_offer(
            m, unit, bread, batch_size=D(40), direct_minutes_per_batch=240, duration_minutes=30, capacity=2
        )
    with pytest.raises(services.CatalogueError):
        services.create_offer(m, unit, bread, batch_size=D(0), direct_minutes_per_batch=240)
    cut = services.create_item("Haircut", "service", "service")
    with pytest.raises(services.CatalogueError):
        services.create_offer(m, unit, cut, duration_minutes=40, capacity=1, batch_size=D(2))


def test_only_the_units_people_can_edit_offers():
    m, unit = setup()
    other = make_member("o@x.org", "Out")
    bread = services.create_item("Bread", "product", "pc")
    with pytest.raises(services.CatalogueError):
        services.create_offer(other, unit, bread, batch_size=D(40), direct_minutes_per_batch=240)
    o = services.create_offer(m, unit, bread, batch_size=D(40), direct_minutes_per_batch=240)
    with pytest.raises(services.CatalogueError):
        services.update_offer(other, o, cycle_days=3)
    with pytest.raises(services.CatalogueError):
        services.update_offer(m, o, value_total=D(1))  # prices come only from the engine (HF-3)
