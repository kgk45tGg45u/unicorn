"""Hooks that let one app call another without importing it.

The recognition app (phase 13) adds its handlers to RECOGNITION_HANDLERS. Until then the list is empty, so a call
does nothing and the market never imports the app that fills it.
"""

from collections.abc import Callable

RECOGNITION_HANDLERS: list[Callable] = []


def RECOGNITION_HOOK(member, kind, obj):  # noqa: N802
    """Tell the recognition app that `member` did something worth recognising: kind is "thanks" or "filled_need"."""
    for handler in RECOGNITION_HANDLERS:
        handler(member, kind, obj)
