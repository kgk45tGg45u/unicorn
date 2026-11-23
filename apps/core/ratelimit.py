"""Limits against spam and overload (docs/08 section 1, P14.T02).

The counts live in the shared cache (a database table), so every gunicorn worker sees the same numbers. They are never
used for anything but limits, and no raw IP address is stored.
"""

import hashlib
import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render
from django.utils import timezone

from apps.rules.services import get_param


def hit(key, limit, window_seconds, now=None) -> bool:
    """Count one use of `key`. Returns False once more than `limit` uses fall in the same window."""
    now = int(now if now is not None else time.time())
    start = now - now % window_seconds
    full = f"rl:{key}:{start}"
    cache.add(full, 0, timeout=window_seconds * 2)
    try:
        count = cache.incr(full)
    except ValueError:  # the entry expired between the two calls
        cache.set(full, 1, timeout=window_seconds * 2)
        count = 1
    return count <= limit


def client_ip(request) -> str:
    """Behind Apache the last address of X-Forwarded-For is the client's, but only when Apache itself called us."""
    remote = request.META.get("REMOTE_ADDR", "")
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if remote == "127.0.0.1" and forwarded:
        return forwarded.split(",")[-1].strip()
    return remote


def ip_key(request) -> str:
    """A hash of the address with a salt that changes every day, so no address is stored and none can be followed."""
    day = timezone.localdate().isoformat()
    raw = f"{settings.SECRET_KEY}:{day}:{client_ip(request)}"
    return "ip-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def rate_limited(name, param, window_seconds, per="member"):
    """Limit a view that changes something. Only unsafe requests (POST and the like) are counted.

    `param` names the democratic default that holds the limit, for example `security.comments_per_member_per_hour`.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method in ("GET", "HEAD", "OPTIONS"):
                return view(request, *args, **kwargs)
            who = None
            if per == "member":
                member = getattr(request, "real_member", None) or getattr(request, "member", None)
                who = f"m-{member.number}" if member is not None else None
            if who is None:
                who = ip_key(request)
            if not hit(f"{name}:{who}", get_param(param), window_seconds):
                return render(request, "429.html", status=429)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
