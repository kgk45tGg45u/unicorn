from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from apps.tradefund import fx
from apps.tradefund.models import FxRate

XML = (Path(__file__).parent / "fixtures" / "eurofxref-daily.xml").read_text()


def test_parsing_the_fixture():
    day, rates = fx.parse_ecb(XML)
    assert day == "2026-11-20"
    assert rates["USD"] == Decimal("1.0800")
    assert len(rates) == 3


@pytest.mark.django_db
def test_store_is_safe_to_run_twice():
    assert fx.store_rates(XML) == 4  # three currencies and EUR
    assert fx.store_rates(XML) == 0
    assert FxRate.objects.get(currency="EUR").per_eur == 1


@pytest.mark.django_db
def test_usd_to_eur_and_back():
    fx.store_rates(XML)
    on = date(2026, 11, 20)
    assert fx.to_eur("108.00", "USD", on) == Decimal("100.00")
    assert fx.from_eur("100.00", "USD", on) == Decimal("108.00")
    assert fx.to_eur("5.00", "EUR", on) == Decimal("5.00")


@pytest.mark.django_db
def test_a_missing_day_uses_the_previous_rate():
    fx.store_rates(XML)
    assert fx.to_eur("108.00", "USD", date(2026, 11, 25)) == Decimal("100.00")
    with pytest.raises(fx.NoRate):
        fx.to_eur("1.00", "USD", date(2026, 11, 1))


@pytest.mark.django_db
def test_a_network_error_keeps_old_rates():
    fx.store_rates(XML)

    def broken(*args, **kwargs):
        raise OSError("no network")

    assert fx.fetch_and_store(opener=broken) == 0
    assert FxRate.objects.filter(currency="USD").count() == 1
