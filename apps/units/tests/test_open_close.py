from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.members import services as member_services
from apps.members.models import Licence
from apps.plan import check as plan_check
from apps.units import services
from apps.units.models import Unit

from .conftest import make_member

pytestmark = pytest.mark.django_db


def data(**kw):
    base = {"name": "Corner Bakery", "kind": "production", "mode": "continuous", "description": "Bread"}
    base.update(kw)
    return base


def test_a_green_check_opens_the_unit_at_once_as_trial():
    a = make_member()
    unit = services.open_unit(a, data())
    assert unit.status == "trial" and unit.trial_until > timezone.now() + timedelta(days=80)
    assert services.is_worker(a, unit) and services.responsible(unit).member == a
    assert unit.slug == "corner-bakery"
    assert services.open_unit(a, data()).slug == "corner-bakery-2"


def test_hf17_licensed_trade_needs_verified_licence():
    a = make_member()
    with pytest.raises(services.UnitError):
        services.open_unit(a, data(kind="service", licence_kind_required="health_care", insurance_confirmed=True))
    lic = member_services.submit_licence(a, "health_care", SimpleUploadedFile("l.pdf", b"x", "application/pdf"))
    Licence.objects.filter(pk=lic.pk).update(status="verified")
    unit = services.open_unit(a, data(kind="service", licence_kind_required="health_care", insurance_confirmed=True))
    assert unit.status == "trial"


def test_hf17_service_needs_insurance():
    a = make_member()
    with pytest.raises(services.UnitError):
        services.open_unit(a, data(kind="service"))
    with pytest.raises(services.UnitError):
        services.open_unit(a, data(kind="social"))
    assert services.open_unit(a, data(kind="service", insurance_confirmed=True))


def test_hf13_only_verified_members_open_units():
    p = make_member("p@x.org", "Pat", verified=False)
    with pytest.raises(services.UnitError):
        services.open_unit(p, data())


def test_hf15_red_check_does_not_refuse(monkeypatch):
    red = plan_check.CheckResult([plan_check.CheckPoint("red", "Too many bakeries")])
    monkeypatch.setattr(plan_check, "check", lambda request: red)
    unit = services.open_unit(make_member(), data())
    assert unit.status == "paused" and "random confirmers" in unit.status_note


def test_trials_end_and_dormant_units_reopen():
    a = make_member()
    unit = services.open_unit(a, data())
    assert services.end_trials() == 0
    assert services.end_trials(timezone.now() + timedelta(days=100)) == 1
    unit.refresh_from_db()
    assert unit.status == "open"
    assert services.mark_dormant() == 0
    assert services.mark_dormant(timezone.now() + timedelta(days=250)) == 1
    unit.refresh_from_db()
    assert unit.status == "dormant"
    services.reopen_unit(a, unit)
    unit.refresh_from_db()
    assert unit.status == "open"
    assert Unit.objects.get(slug="coordination").status == "open"  # never dormant


def test_a_single_worker_can_close_the_unit_and_checks_can_block():
    a = make_member()
    unit = services.open_unit(a, data())
    block = lambda u: ["There are open production orders."]  # noqa: E731
    services.CLOSE_CHECKS.append(block)
    try:
        assert services.close_unit(unit, "Not needed", member=a) == ["There are open production orders."]
        unit.refresh_from_db()
        assert unit.status == "closing"
    finally:
        services.CLOSE_CHECKS.remove(block)
    assert services.close_unit(unit, "Not needed", member=a) == []
    unit.refresh_from_db()
    assert unit.status == "closed" and unit.closed_at


def test_a_council_unit_closes_only_by_decision():
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    unit = services.open_unit(a, data())
    services.decide_join(services.request_to_join(unit, b), a, True)
    with pytest.raises(services.UnitError):
        services.close_unit(unit, "x", member=a)
    d = services.open_decision(a, unit, "Close us", kind="close_unit")
    services.vote(d, a, "yes")
    services.vote(d, b, "yes")
    unit.refresh_from_db()
    assert unit.status == "closed"


def test_open_page(client):
    a = make_member()
    client.force_login(a.user)
    assert client.get(reverse("units:open")).status_code == 200
    r = client.post(reverse("units:open"), data())
    assert r.status_code == 302 and r["Location"].endswith("/units/corner-bakery/")
    r = client.post(reverse("units:open"), data(name="Clinic", kind="service"))
    assert r.status_code == 200 and "insurance" in r.content.decode()
