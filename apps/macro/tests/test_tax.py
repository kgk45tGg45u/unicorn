from decimal import Decimal

import pytest

from apps.ledger.models import Period
from apps.macro import tax
from apps.rules.models import Parameter

pytestmark = pytest.mark.django_db
D = Decimal


def set_param(key, value):
    Parameter.objects.filter(key=key).update(value=value)


def test_the_worked_case():
    assert tax.tax_from_inputs(D(1000), D(700), D(50), D(20)) == D("0.2700")


def test_clipping_at_the_hard_bounds():
    assert tax.tax_from_inputs(D(1000), D(10), D(0), D(0)) == D("0.6800")  # would be 0.99
    assert tax.tax_from_inputs(D(1000), D(2000), D(0), D(0)) == D("0.0000")  # would be negative


def test_hf09_waste_raises_the_tax():
    without = tax.tax_from_inputs(D(1000), D(700), D(50), D(20))
    with_waste = tax.tax_from_inputs(D(1100), D(700), D(50), D(20))  # 100 written-off hours are in H but not in C
    assert with_waste > without


def test_the_fixed_method():
    set_param("economy.flat_tax.method", "fixed")
    period = Period.objects.create(year=2026, month=11, tax_rate=D("0.2"))
    rate, inputs = tax.next_tax_rate(period, {"hours_paid": D(100)})
    assert rate == D("0.35") and inputs["method"] == "fixed"


def test_the_yearly_method_keeps_the_rate_except_in_december():
    set_param("economy.flat_tax.method", "balance_yearly")
    period = Period.objects.create(year=2026, month=5, tax_rate=D("0.2"))
    rate, inputs = tax.next_tax_rate(period, {"hours_paid": D(100)})
    assert rate == D("0.2") and "once a year" in inputs["note"]


def test_no_hours_keeps_the_rate():
    period = Period.objects.create(year=2026, month=5, tax_rate=D("0.2"))
    rate, inputs = tax.next_tax_rate(period, {"hours_paid": D(0)})
    assert rate == D("0.2") and "stays" in inputs["note"]
