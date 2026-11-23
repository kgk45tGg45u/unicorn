import csv
import io
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.macro import close, forecasts
from apps.macro.models import Forecast
from apps.units.tests.conftest import make_member

from .test_accounts import a_small_month

pytestmark = pytest.mark.django_db
D = Decimal


def closed_month():
    world, salon = a_small_month()
    close.close_period(timezone.localdate().year, timezone.localdate().month)
    return world, salon


def test_open_books_shows_each_closed_month_with_its_inputs_and_the_lights(client):
    closed_month()
    response = client.get("/open-books/")
    text = response.content.decode()
    assert response.status_code == 200
    assert "Each closed month" in text and "Warning lights" in text and "(H " in text
    assert "Download all monthly accounts" in text and "Data for forecasts" in text
    assert "tax = 1 - (C + S - T) / H" in text


def test_the_csvs_have_no_member_numbers(client):
    world, salon = closed_month()
    numbers = [world.baker.number, world.miller.number, salon.provider.number]
    for url in ("/open-books/snapshots.csv", "/open-books/forecast-data.csv"):
        response = client.get(url)
        assert response.status_code == 200
        body = response.content.decode()
        assert not any(n in body for n in numbers)
    rows = list(csv.reader(io.StringIO(client.get("/open-books/forecast-data.csv").content.decode())))
    sections = {r[0] for r in rows}
    assert {"month", "world", "light", "parameter"} <= sections
    assert any(r[0] == "parameter" and r[1] == "economy.flat_tax.method" for r in rows)
    snapshots = list(csv.reader(io.StringIO(client.get("/open-books/snapshots.csv").content.decode())))
    assert snapshots[0][0] == "period" and len(snapshots) == 2


def test_a_forecast_attaches_to_a_ticket_and_is_shown(client):
    from apps.tickets import services as tickets
    from apps.tickets.tests.conftest import CHECK

    author = make_member("e@x.org", "Expert")
    ticket = tickets.create_ticket("question", author, "A plan question")
    forecast = forecasts.attach(
        ticket,
        author,
        {"attractive": True, "growing": True, "independent": False, "stable": True},
        "0.1",
        "0.95",
        "1",
        "Ran seed 3",
    )
    assert Forecast.objects.get() == forecast and forecast.goals["independent"] is False
    client.force_login(author.user)
    page = client.get(f"/tickets/{ticket.number}/").content.decode()
    assert "Forecasts" in page and "0.1000 / 0.9500 / 1.0000" in page and "Ran seed 3" in page
    with pytest.raises(forecasts.ForecastError):
        forecasts.attach(ticket, author, {}, "2")
    assert CHECK


def test_the_home_dashboard_shows_my_month_my_orders_and_the_lights(client):
    world, salon = closed_month()
    client.force_login(world.baker.user)
    page = client.get("/").content.decode()
    assert "My month" in page and "My orders" in page and "Warning lights" in page
    assert "UNIQ" in page
