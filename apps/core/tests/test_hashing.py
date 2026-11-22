from datetime import UTC, datetime
from decimal import Decimal

from apps.core.hashing import canonical_json, chain_hash, hmac_hex


def test_canonical_json_ignores_key_order():
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


def test_canonical_json_decimal_and_datetime():
    out = canonical_json({"x": Decimal("1.5000"), "t": datetime(2026, 1, 1, tzinfo=UTC)})
    assert out == '{"t":"2026-01-01T00:00:00+00:00","x":"1.5000"}'


def test_chain_hash_is_deterministic():
    assert chain_hash("0", {"a": 1}) == chain_hash("0", {"a": 1})
    assert chain_hash("0", {"a": 1}) != chain_hash("1", {"a": 1})


def test_hmac_hex(settings):
    settings.UNICORN_HMAC_KEY = "ab" * 32
    assert hmac_hex("x") == hmac_hex("x")
    assert len(hmac_hex("x")) == 64
