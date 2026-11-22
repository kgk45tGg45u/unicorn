from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.units import council_rules, services
from apps.units.models import CouncilDecision

from .conftest import make_member, make_unit

pytestmark = pytest.mark.django_db


def council():
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    unit = make_unit()
    services.add_first_worker(unit, a)
    services.decide_join(services.request_to_join(unit, b), a, True)
    return unit, a, b


def test_default_rules_come_from_the_parameters():
    unit, a, b = council()
    r = council_rules.current(unit)
    assert (r.version, r.decision_rule, r.vote_days, r.rotation_months) == (1, "majority", 3, 6)
    assert r.quorum == Decimal("0.5")
    assert r.hours_approval == "any_other_member" and r.admission == "council_approves"
    assert council_rules.create_default(unit) == r  # safe to call twice


def test_hf02_clause_cannot_change_pay():
    assert council_rules.validate_clauses("Ada gets a bonus on top of her pay each hour")
    assert council_rules.validate_clauses("We pay extra UNIQ to the cook")
    assert not council_rules.validate_clauses("We meet on Mondays")


def make_decision(unit, status):
    now = timezone.now()
    return CouncilDecision.objects.create(
        unit=unit, title="t", kind="rules_change", status=status, opens_at=now, closes_at=now + timedelta(days=3)
    )


def test_a_new_version_needs_an_approved_council_decision():
    unit, a, b = council()
    with pytest.raises(council_rules.RulesError):
        council_rules.new_version(unit, {"vote_days": 5}, None)
    with pytest.raises(council_rules.RulesError):
        council_rules.new_version(unit, {"vote_days": 5}, make_decision(unit, "open"))
    d = make_decision(unit, "approved")
    r = council_rules.new_version(unit, {"vote_days": 5}, d)
    assert (r.version, r.vote_days, r.adopted_by) == (2, 5, d)
    assert r.decision_rule == "majority"  # unchanged values carry over
    with pytest.raises(council_rules.RulesError):
        council_rules.new_version(unit, {"clauses_md": "pay a bonus per hour"}, make_decision(unit, "approved"))


def test_workers_sign_the_current_version(client):
    unit, a, b = council()
    signed, unsigned = council_rules.signers(unit)
    assert signed == [] and set(unsigned) == {a, b}
    council_rules.sign_current(a, unit)
    assert council_rules.sign_current(a, unit) is None  # once is enough
    signed, unsigned = council_rules.signers(unit)
    assert signed == [a] and unsigned == [b]
    client.force_login(b.user)
    page = client.get(reverse("units:rules", args=[unit.slug]))
    assert page.status_code == 200 and "Still to sign" in page.content.decode()
    outsider = make_member("c@x.org", "Cy")
    with pytest.raises(council_rules.RulesError):
        council_rules.sign_current(outsider, unit)
