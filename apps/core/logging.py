"""Logs without personal data (docs/08 section 8, P14.T10).

Every log line carries the request id and the member number at most. Anything that looks like an email address, a bank
account number, an encrypted token or a long secret is replaced before it is written.
"""

import logging
import re
from contextvars import ContextVar

_context: ContextVar = ContextVar("log_context", default=None)

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){10,30}\b")
FERNET = re.compile(r"\bgAAAAA[A-Za-z0-9_\-=]{20,}")
LONG_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
REMOVED = "[removed]"


def redact(text: str) -> str:
    for pattern in (FERNET, EMAIL, IBAN, LONG_HEX):
        text = pattern.sub(REMOVED, text)
    return text


def start_request(request_id: str):
    """Called by the request id middleware. Returns a token for `end_request`."""
    return _context.set({"request_id": request_id, "member": ""})


def end_request(token):
    _context.reset(token)


def set_member(number: str):
    """The member number of the person who is logged in (never a name)."""
    context = _context.get()
    if context is not None:
        context["member"] = number


def current_request_id() -> str:
    context = _context.get()
    return context["request_id"] if context else ""


class RequestContextFilter(logging.Filter):
    """Adds `request_id` and `member` to every record, empty outside a request."""

    def filter(self, record):
        context = _context.get() or {"request_id": "", "member": ""}
        record.request_id = context["request_id"] or "-"
        record.member = context["member"] or "-"
        return True


class RedactFilter(logging.Filter):
    """Replaces personal data in the message and in any traceback with [removed]."""

    def filter(self, record):
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True
