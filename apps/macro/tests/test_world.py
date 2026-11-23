from decimal import Decimal

import pytest
from django.utils import timezone

from apps.macro import services as macro
from apps.macro import world
from apps.members import services as ms
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal


def test_the_planning_rate_falls_back_and_then_uses_the_measured_rate(monkeypatch):
    assert macro.planning_rate() == D("17.35")

    class Outside:
        @staticmethod
        def sales_after_tax_and_hours(months):
            return D("2000.00"), D("100"), 4

    monkeypatch.setattr(world, "_outside", lambda: Outside)
    assert macro.planning_rate() == D("20.00")  # euros per outside-sales hour after the sellers' tax reserves

    class TooLittle(Outside):
        @staticmethod
        def sales_after_tax_and_hours(months):
            return D("2000.00"), D("100"), 2  # only 2 months of data

    monkeypatch.setattr(world, "_outside", lambda: TooLittle)
    assert macro.planning_rate() == D("17.35")


def test_attractiveness_is_none_with_too_few_data():
    assert macro.attractiveness() is None
    m = make_member("m@x.org", "M")
    ms.set_private(m, net_hourly_wage_eur="15.00")
    assert world.attractiveness_estimate() is None  # no offers with an outside price, one member with a wage


def test_attractiveness_is_the_median_of_the_ratios(monkeypatch):
    for i in range(10):
        m = make_member(f"m{i}@x.org", f"M{i}")
        ms.set_private(m, net_hourly_wage_eur=str(10 + i))
    monkeypatch.setattr(world, "uniq_value_eur", lambda: D("20"))
    value = world.attractiveness_estimate()
    assert value is not None and value > 0
    from apps.ledger.services import current_period

    net = 1 - D(str(current_period().tax_rate))
    expected = sorted(net * D(20) / D(10 + i) for i in range(10))
    assert value == ((expected[4] + expected[5]) / 2).quantize(D("0.0001"))


def test_the_world_page_reads_the_benchmark_csv_and_shows_the_month_values(client):
    rows = world.benchmark_rows()
    assert len(rows) == 360 and rows[0]["month"] == "1"
    real = {"outside_sales_per_member_eur": "82.00", "can_live_without_job_share": "0.0000", "reserve_months": "0.17"}
    table, row, _year = world.on_track(real, 1)
    assert row["export_revenue_per_member"] == rows[0]["export_revenue_per_member"]
    by_label = {r["label"]: r for r in table}
    sales = by_label["Outside sales per member and month (euros)"]
    assert sales["verdict"] == "on_track"  # 82 against the default world's 82.8
    response = client.get("/on-track/")
    assert response.status_code == 200
    assert b"Are we on track?" in response.content and b"82.82" in response.content


def test_verdict_words():
    assert world.verdict(80, 100) == "on_track"
    assert world.verdict(60, 100) == "behind"
    assert world.verdict(30, 100) == "far_behind"
    assert world.verdict(None, 100) == "unknown"


def test_a_member_can_state_the_job_and_the_wage_and_it_is_private(client):
    m = make_member("m@x.org", "M")
    client.force_login(m.user)
    assert client.get("/me/world/").status_code == 200
    assert client.post("/me/world/", {"has_job": "no", "wage": "16,50"}).status_code == 302
    m.refresh_from_db()
    assert m.has_capitalist_job is False
    assert ms.get_private(m)["net_hourly_wage_eur"] == "16.50"
    assert world.can_live_without_job_share() == D("1.0000")
    assert "16.50" not in str(world.world_metrics(__import__("apps.ledger.services", fromlist=["x"]).current_period()))


def test_world_metrics_at_a_close():
    from apps.ledger.services import current_period

    data = world.world_metrics(current_period())
    assert data["planning_rate_eur_per_hour"] == "17.35" and data["attractiveness_estimate"] is None
    assert timezone.now()
