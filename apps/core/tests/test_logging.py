import io
import logging

import pytest
from django.conf import settings
from django.http import HttpResponse
from django.urls import path

from apps.core.logging import RedactFilter, RequestContextFilter, redact

pytestmark = pytest.mark.django_db

IBAN = "DE89370400440532013000"


def boom(request):
    raise RuntimeError("something broke for mara@example.org")


def fine(request):
    logging.getLogger("apps.test").warning("hello %s", "world")
    return HttpResponse("fine")


urlpatterns = [path("boom/", boom), path("fine/", fine)]
handler500 = "apps.core.views.server_error"


def stream_logger(name="apps.testlog"):
    """A logger with the same filters and format as the real console handler, writing to a string."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    for key in ("context", "redact"):
        handler.addFilter({"context": RequestContextFilter, "redact": RedactFilter}[key]())
    handler.setFormatter(logging.Formatter(settings.LOGGING["formatters"]["plain"]["format"]))
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger, stream


def test_a_log_message_with_an_email_and_an_iban_comes_out_redacted():
    logger, stream = stream_logger()
    logger.warning("Mara <mara.musterfrau@example.org> paid to %s with token %s", IBAN, "gAAAAAB" + "x" * 60)
    out = stream.getvalue()
    assert "mara.musterfrau@example.org" not in out and IBAN not in out and "gAAAAAB" not in out
    assert out.count("[removed]") == 3


def test_long_secrets_and_a_traceback_are_redacted_too():
    logger, stream = stream_logger("apps.testlog2")
    try:
        raise ValueError("bad value for owner@example.org " + "ab" * 32)
    except ValueError:
        logger.exception("it failed")
    out = stream.getvalue()
    assert "owner@example.org" not in out and "ab" * 32 not in out and "Traceback" in out


def test_ordinary_text_is_left_alone():
    assert (
        redact("Order 12 for 2 loaves, member M-AAAA-BBBB, 3 hours")
        == "Order 12 for 2 loaves, member M-AAAA-BBBB, 3 hours"
    )


def test_every_handler_redacts_and_sql_is_never_logged():
    config = settings.LOGGING
    for name, handler in config["handlers"].items():
        assert "redact" in handler["filters"], name
    sql = config["loggers"]["django.db.backends"]
    assert sql["level"] in ("WARNING", "ERROR") and sql["propagate"] is False
    assert config["loggers"]["django.security"]["level"] == "WARNING"
    assert "mail_admins" in config["loggers"]["django.request"]["handlers"]


@pytest.mark.urls("apps.core.tests.test_logging")
def test_the_response_carries_x_request_id_and_a_good_one_is_kept(client):
    response = client.get("/fine/")
    assert len(response["X-Request-ID"]) == 16
    kept = client.get("/fine/", HTTP_X_REQUEST_ID="abcdef0123456789")
    assert kept["X-Request-ID"] == "abcdef0123456789"
    replaced = client.get("/fine/", HTTP_X_REQUEST_ID="bad id with spaces & <tags>")
    assert replaced["X-Request-ID"] != "bad id with spaces & <tags>" and len(replaced["X-Request-ID"]) == 16


@pytest.mark.urls("apps.core.tests.test_logging")
def test_the_request_id_and_member_number_are_in_the_log_line(client, caplog):
    from apps.units.tests.conftest import make_member

    member = make_member("m@x.org", "M")
    client.force_login(member.user)
    logger, stream = stream_logger("apps.test")
    response = client.get("/fine/", HTTP_X_REQUEST_ID="req-1234567890")
    line = stream.getvalue()
    assert "req-1234567890" in line and member.number in line and "hello world" in line
    assert response["X-Request-ID"] == "req-1234567890"
    assert "m@x.org" not in line and "M " not in line.split("apps.test")[0]


@pytest.mark.urls("apps.core.tests.test_logging")
def test_the_error_page_shows_the_request_id_and_nothing_personal(client):
    client.raise_request_exception = False
    response = client.get("/boom/", HTTP_X_REQUEST_ID="req-abcdef123456")
    body = response.content.decode()
    assert response.status_code == 500 and "req-abcdef123456" in body
    assert "mara@example.org" not in body and "RuntimeError" not in body


def test_audit_events_remember_the_request():
    from apps.core import audit
    from apps.core import logging as unicorn_logging
    from apps.core.models import AuditEvent

    token = unicorn_logging.start_request("req-direct-123456")
    try:
        audit.record("system", "test.event")
    finally:
        unicorn_logging.end_request(token)
    assert AuditEvent.objects.get(verb="test.event").request_id == "req-direct-123456"
