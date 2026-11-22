from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.ledger.models import Period
from apps.units import services
from apps.units.models import HoursEntry, TimerSession

from .conftest import make_member, make_unit

pytestmark = pytest.mark.django_db


def worker():
    a = make_member()
    unit = make_unit()
    services.add_first_worker(unit, a)
    return a, unit


def today():
    return timezone.now().astimezone(services.BERLIN).date()


def test_hours_are_submitted_with_the_period():
    a, unit = worker()
    e = services.record_hours(a, unit, today(), 150, activity="shift")
    assert e.status == "submitted" and e.period.status == "open" and e.submitted_at
    assert not e.needs_extra_approval


def test_hours_in_a_closed_period_are_refused():
    a, unit = worker()
    p = services.period_for_date(today())
    Period.objects.filter(pk=p.pk).update(status="closed")
    with pytest.raises(services.UnitError):
        services.record_hours(a, unit, today(), 60)


def test_future_days_and_bad_minutes_are_refused():
    a, unit = worker()
    with pytest.raises(services.UnitError):
        services.record_hours(a, unit, today() + timedelta(days=1), 60)
    for bad in (0, 1441):
        with pytest.raises(services.UnitError):
            services.create_draft(a, unit, today(), bad)


def test_the_weekly_limit_sets_needs_extra_approval():
    a, unit = worker()
    other = make_unit("second")
    services.add_first_worker(other, a)
    day = today()
    services.record_hours(a, unit, day, 1440)
    services.record_hours(a, other, day, 1440)  # 48 h so far: exactly at the limit
    assert not HoursEntry.objects.filter(needs_extra_approval=True).exists()
    e = services.record_hours(a, unit, day, 1)
    assert e.needs_extra_approval


def test_a_non_worker_cannot_record_hours_for_the_unit():
    a, unit = worker()
    outsider = make_member("o@x.org", "Out")
    with pytest.raises(services.UnitError):
        services.record_hours(outsider, unit, today(), 60)
    with pytest.raises(services.UnitError):
        services.start_timer(outsider, unit)


def test_the_timer_makes_a_rounded_draft():
    a, unit = worker()
    t = services.start_timer(a, unit)
    with pytest.raises(services.UnitError):
        services.start_timer(a, unit)
    e = services.stop_timer(a, now=t.started_at + timedelta(minutes=90, seconds=40))
    assert (e.minutes, e.status) == (91, "draft")
    assert not TimerSession.objects.exists()
    with pytest.raises(services.UnitError):
        services.stop_timer(a)
    services.submit_hours(e)
    with pytest.raises(services.UnitError):
        services.submit_hours(e)  # only once


def test_pages(client):
    a, unit = worker()
    client.force_login(a.user)
    r = client.post(
        reverse("units:my_hours"),
        {"unit": unit.pk, "date": today().isoformat(), "hours": 2, "minutes": 30, "activity": "shift"},
    )
    assert r.status_code == 302
    assert HoursEntry.objects.get().minutes == 150
    assert "150 min" in client.get(reverse("units:my_hours")).content.decode()
    assert client.get(reverse("units:unit_hours", args=[unit.slug])).status_code == 200
