"""Who is acting for someone else in this request ("on behalf of", P13.T10).

The members app sets it while a helper uses "Acting for" mode. Everything that records an action reads it, so no
service has to know about it.
"""

from contextvars import ContextVar

_helper: ContextVar = ContextVar("acting_helper", default=None)


def set_helper(member):
    """Remember the helper for this request. Returns a token for `reset`."""
    return _helper.set(member)


def reset(token):
    _helper.reset(token)


def current_helper():
    """The helper's Member while someone acts for another member, else None."""
    return _helper.get()
