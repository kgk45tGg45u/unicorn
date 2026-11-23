from datetime import UTC, datetime
from types import SimpleNamespace

from apps.core.rotation import next_in_rotation


def _m(pk):
    return SimpleNamespace(pk=pk)


def _day(n):
    return datetime(2026, 1, n, tzinfo=UTC)


def test_the_member_with_the_fewest_days_is_next():
    a, b = _m(1), _m(2)
    days = {1: 30, 2: 10}
    assert next_in_rotation([(a, _day(1)), (b, _day(2))], lambda m: days[m.pk]) is b


def test_a_tie_goes_to_the_earliest_joined():
    a, b = _m(1), _m(2)
    assert next_in_rotation([(a, _day(5)), (b, _day(2))], lambda m: 0) is b


def test_a_decline_is_skipped_and_nobody_left_gives_none():
    a, b = _m(1), _m(2)
    assert next_in_rotation([(a, _day(1)), (b, _day(2))], lambda m: 0, declined={1}) is b
    assert next_in_rotation([(a, _day(1))], lambda m: 0, declined={1}) is None
