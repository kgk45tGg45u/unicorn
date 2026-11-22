from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalogue import services
from apps.catalogue.models import JoinForcesSuggestion, Offer
from apps.units import services as us
from apps.units.models import CouncilDecision
from apps.units.tests.conftest import make_member, make_unit

pytestmark = pytest.mark.django_db
D = Decimal


def two_woodshops(minutes_b=130, town_b="Oakville"):
    chair = services.create_item("Oak chair", "product", "pc")
    offers, members = [], []
    for slug, minutes, town in (("woodshop", 100, "Oakville"), ("oak-corner", minutes_b, town_b)):
        m = make_member(f"{slug}@x.org", slug)
        unit = make_unit(slug, town=town)
        us.add_first_worker(unit, m)
        o = services.create_offer(m, unit, chair, batch_size=D(1), direct_minutes_per_batch=minutes)
        services.publish_offer(o, m)
        offers.append(o)
        members.append(m)
    services.recompute_values()
    return offers, members


def test_a_30_percent_gap_creates_a_suggestion():
    offers, members = two_woodshops(minutes_b=130)
    assert services.make_join_forces_suggestions() == 1
    s = JoinForcesSuggestion.objects.get()
    assert s.offer_high.unit.slug == "oak-corner" and s.gap == D("0.3000")
    assert services.make_join_forces_suggestions() == 0  # one open suggestion per pair
    text = services.suggestion_text(s)
    assert "Woodshop" in text and "Oak-Corner" in text and "2.2 h" in text and "1.7 h" in text


def test_a_20_percent_gap_does_not():
    two_woodshops(minutes_b=120)
    assert services.make_join_forces_suggestions() == 0


def test_units_far_apart_get_no_suggestion():
    two_woodshops(minutes_b=130, town_b="Elsewhere")
    assert services.make_join_forces_suggestions() == 0


def test_dismissing_stops_repeats_for_six_months():
    offers, members = two_woodshops()
    services.make_join_forces_suggestions()
    s = JoinForcesSuggestion.objects.get()
    with pytest.raises(services.CatalogueError):
        services.dismiss_suggestion(make_member("z@x.org", "Zed"), s)
    services.dismiss_suggestion(members[0], s)
    assert services.make_join_forces_suggestions() == 0
    assert services.make_join_forces_suggestions(timezone.now() + timedelta(days=100)) == 0
    assert services.make_join_forces_suggestions(timezone.now() + timedelta(days=200)) == 1


def test_start_a_conversation_opens_a_decision_in_both_units():
    offers, members = two_woodshops()
    services.make_join_forces_suggestions()
    s = JoinForcesSuggestion.objects.get()
    services.start_conversation(members[1], s)
    s.refresh_from_db()
    assert s.status == "discussed"
    assert CouncilDecision.objects.filter(kind="other").count() == 2
    assert Offer.objects.count() == 2  # nothing was changed automatically (HF-10, HF-15)
