from decimal import Decimal

import pytest

from apps.core.money import cur, minutes_to_uniq, uniq


def test_uniq_rounds_to_four_places():
    assert uniq("1.23456") == Decimal("1.2346")


def test_cur_rounds_to_two_places():
    assert cur("1.005") == Decimal("1.00")  # half-even


def test_float_is_refused():
    with pytest.raises(TypeError):
        uniq(0.1)
    with pytest.raises(TypeError):
        cur(0.1)


def test_minutes_to_uniq():
    assert minutes_to_uniq(90) == Decimal("1.5000")
