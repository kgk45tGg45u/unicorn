import pytest
from django.db import IntegrityError, transaction

from apps.units.models import Unit
from apps.units.services import coordination_unit


@pytest.mark.django_db
def test_there_is_exactly_one_coordination_unit():
    assert Unit.objects.filter(kind="coordination").count() == 1
    unit = coordination_unit()
    assert unit.slug == "coordination"
    assert unit.status == "open"


@pytest.mark.django_db
def test_slug_is_unique():
    Unit.objects.create(name="Bakery", slug="bakery", kind="production")
    with pytest.raises(IntegrityError), transaction.atomic():
        Unit.objects.create(name="Bakery 2", slug="bakery", kind="production")


@pytest.mark.django_db
def test_cover_radius_defaults_to_the_live_default():
    unit = Unit.objects.create(name="Bikes", slug="bikes", kind="service")
    unit.refresh_from_db()
    assert unit.cover_radius_km == 10
