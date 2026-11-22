"""Money helpers. UNIQ and euros are Decimal, never float (CLAUDE.md)."""

from decimal import ROUND_HALF_EVEN, Decimal

UNIQ_Q = Decimal("0.0001")
CUR_Q = Decimal("0.01")


def _to_decimal(x) -> Decimal:
    if isinstance(x, float):
        raise TypeError("float is not allowed for UNIQ or money; use int, str or Decimal")
    if isinstance(x, bool) or not isinstance(x, int | str | Decimal):
        raise TypeError(f"cannot convert {type(x).__name__} to Decimal")
    return Decimal(x)


def uniq(x) -> Decimal:
    return _to_decimal(x).quantize(UNIQ_Q, rounding=ROUND_HALF_EVEN)


def cur(x) -> Decimal:
    return _to_decimal(x).quantize(CUR_Q, rounding=ROUND_HALF_EVEN)


def minutes_to_uniq(minutes: int) -> Decimal:
    return uniq(Decimal(minutes) / 60)
