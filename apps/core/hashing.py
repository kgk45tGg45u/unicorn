import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal

from django.conf import settings


def _default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.astimezone(UTC).isoformat()
    raise TypeError(f"cannot serialise {type(obj).__name__}")


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chain_hash(prev_hash: str, payload: dict) -> str:
    return sha256_hex(prev_hash + canonical_json(payload))


def hmac_hex(text: str) -> str:
    key = bytes.fromhex(settings.UNICORN_HMAC_KEY)
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()
