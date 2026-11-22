import pytest
from django.urls import reverse

from apps.catalogue import services
from apps.catalogue.models import Item, UnitOfMeasure
from apps.units.models import Unit

pytestmark = pytest.mark.django_db


def test_units_of_measure_are_loaded():
    assert set(UnitOfMeasure.objects.values_list("code", flat=True)) >= {"pc", "kg", "g", "l", "h", "service", "km"}


def test_a_placeholder_is_created_once_per_name_and_uom():
    unit = Unit.objects.get(slug="coordination")
    a = services.get_or_create_placeholder("Salt", "kg", unit)
    b = services.get_or_create_placeholder("salt", "kg", unit)
    c = services.get_or_create_placeholder("Salt", "g", unit)
    assert a == b and a != c
    assert a.status == "placeholder"


def test_a_service_item_with_uom_kg_is_refused():
    with pytest.raises(services.CatalogueError):
        services.create_item("Haircut", "service", "kg")
    assert services.create_item("Haircut", "service", "service").kind == "service"
    assert services.create_item("Tutoring", "service", "h")


def test_duplicate_items_are_refused_and_search_works():
    services.create_item("Rye bread", "product", "pc")
    with pytest.raises(services.CatalogueError):
        services.create_item("Rye bread", "product", "pc")
    assert [i.name for i in services.find_items("BREAD")] == ["Rye bread"]
    assert list(services.find_items("")) == []


def test_pages(client):
    item = services.create_item("Rye bread", "product", "pc")
    assert client.get(reverse("catalogue:item", args=[item.pk])).status_code == 200
    r = client.get(reverse("catalogue:item_search"), {"q": "rye"})
    assert "Rye bread" in r.content.decode()
    assert Item.objects.count() == 1
