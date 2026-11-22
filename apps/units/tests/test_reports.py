from decimal import Decimal

import pytest
from django.urls import reverse

from apps.units import services

from .conftest import make_member, make_unit
from .test_hours_record import today

pytestmark = pytest.mark.django_db


def setup_unit():
    unit = make_unit()
    a, b = make_member("a@x.org", "Ada"), make_member("b@x.org", "Bo")
    services.add_first_worker(unit, a)
    services.decide_join(services.request_to_join(unit, b), a, True)
    services.approve_hours(services.record_hours(a, unit, today(), 150, activity="shift"), b)
    services.approve_hours(services.record_hours(b, unit, today(), 60, activity="project"), a)
    services.record_hours(b, unit, today(), 30, activity="shift")  # still waiting
    return unit, a, b


def test_report_sums_match_the_entries():
    unit, a, b = setup_unit()
    r = services.unit_report(unit, today().year, today().month)
    assert r["total"] == 240
    assert dict(r["by_worker"]) == {"Ada": 150, "Bo": 90}
    assert dict(r["by_activity"]) == {"shift": 180, "project": 60}
    assert dict(r["by_status"]) == {"paid": 210, "waiting for approval": 30}


def test_my_totals_show_gross_tax_and_net():
    unit, a, b = setup_unit()
    by_month, by_unit = services.my_hours_totals(a)
    key, minutes, gross, tax, net = by_month[0]
    assert (minutes, gross) == (150, Decimal("2.5000")) and net == gross - tax
    assert by_unit[0][0] == unit.name


def test_the_public_page_shows_no_names_next_to_hours(client):
    unit, a, b = setup_unit()
    monthly, count = services.public_numbers(unit)
    assert monthly[0][1] == 210 and count == 2
    page = client.get(reverse("units:unit", args=[unit.slug])).content.decode()
    assert "210 min" in page and "Ada" in page  # the workers are listed, but only by display name...
    line = [ln for ln in page.splitlines() if "210 min" in ln][0]
    assert "Ada" not in line and "Bo" not in line  # ...and never next to the hours


def test_report_pages(client):
    unit, a, b = setup_unit()
    client.force_login(a.user)
    assert client.get(reverse("units:report", args=[unit.slug])).status_code == 200
    csv_page = client.get(reverse("units:report", args=[unit.slug]) + "?format=csv")
    assert csv_page["Content-Type"].startswith("text/csv") and b"worker,Ada,150" in csv_page.content
    assert client.get(reverse("units:my_totals")).status_code == 200
    outsider = make_member("o@x.org", "Out")
    client.force_login(outsider.user)
    assert client.get(reverse("units:report", args=[unit.slug])).status_code == 302
