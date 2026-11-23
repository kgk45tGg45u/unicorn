"""Exchange rates from the European Central Bank (docs/07 section 11).

This is the only place in the app that talks to the internet (HF-12): it fetches a public file and sends no
personal data. The rates are used to show totals in euros and to convert a payment across currencies. They are
never an exchange rate for UNIQ (HF-4).
"""

import logging
import urllib.request
import xml.etree.ElementTree as ET
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.money import cur

from .models import FxRate

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
log = logging.getLogger(__name__)


class NoRate(ValueError):
    """There is no exchange rate for this currency yet."""


def parse_ecb(xml_text) -> tuple[str, dict[str, Decimal]]:
    """Return (the day as ISO text, {currency: units per 1 EUR}) from the ECB file."""
    root = ET.fromstring(xml_text)  # the ECB file is trusted and small
    day, rates = None, {}
    for node in root.iter():
        if node.tag.endswith("}Cube") or node.tag == "Cube":
            if node.get("time"):
                day = node.get("time")
            elif node.get("currency") and node.get("rate"):
                rates[node.get("currency")] = Decimal(node.get("rate"))
    if day is None or not rates:
        raise ValueError("no rates in the file")
    return day, rates


def store_rates(xml_text) -> int:
    """Save the day's rates. Safe to run twice. Returns how many rows were new."""
    from datetime import date

    day, rates = parse_ecb(xml_text)
    day = date.fromisoformat(day)
    new = 0
    with transaction.atomic():
        rates["EUR"] = Decimal(1)
        for currency, rate in rates.items():
            _row, created = FxRate.objects.get_or_create(date=day, currency=currency, defaults={"per_eur": rate})
            new += int(created)
    return new


def fetch_and_store(opener=urllib.request.urlopen) -> int:
    """Fetch today's file. On a network error, log it and keep the old rates."""
    try:
        with opener(ECB_URL, timeout=20) as response:
            text = response.read().decode("utf-8")
        return store_rates(text)
    except Exception as error:  # noqa: BLE001  any failure here must leave the old rates in place
        log.warning("Could not load exchange rates: %s", error)
        return 0


def rate_on(currency, on=None) -> Decimal:
    """Units of `currency` per 1 EUR: the latest rate on or before the date."""
    if currency == "EUR":
        return Decimal(1)
    on = on or timezone.localdate()
    row = FxRate.objects.filter(currency=currency, date__lte=on).order_by("-date").first()
    if row is None:
        raise NoRate(_("There is no exchange rate for %(currency)s yet.") % {"currency": currency})
    return row.per_eur


def to_eur(amount, currency, on=None) -> Decimal:
    return cur(Decimal(amount) / rate_on(currency, on))


def from_eur(amount, currency, on=None) -> Decimal:
    return cur(Decimal(amount) * rate_on(currency, on))
