from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.ledger import services
from apps.ledger.audit import run_audit
from apps.ledger.jobs import make_fingerprint
from apps.ledger.models import DailyFingerprint
from apps.ledger.services import Leg, post
from apps.members import services as ms
from apps.members.models import User

pytestmark = pytest.mark.django_db
D = Decimal


def book():
    m = ms.create_applicant(User.objects.create_user("secret-person@x.org"), "Secret Name", "DE")
    services.open_member_accounts(m)
    post("hours_pay", "h", [Leg(services.fund2(), D(-5)), Leg(services.member_account(m), D(5))])
    return m


def test_a_fingerprint_is_made_once_per_day_and_chain():
    book()
    yesterday = timezone.localdate() - timedelta(days=1)
    first = make_fingerprint(timezone.localdate())
    assert first is not None and first.seq == 1
    assert make_fingerprint(timezone.localdate()) is None
    assert DailyFingerprint.objects.filter(chain="uniq").count() == 1
    repeat = make_fingerprint(yesterday)
    assert repeat.seq == 0 and repeat.hash == "0" * 64


def test_an_empty_day_repeats_the_previous_fingerprint():
    book()
    today = timezone.localdate()
    make_fingerprint(today)
    nxt = make_fingerprint(today + timedelta(days=1))
    assert (nxt.seq, nxt.date) == (1, today + timedelta(days=1))


def test_the_page_shows_the_last_audit_result_and_no_member_numbers(client):
    m = book()
    run_audit()
    make_fingerprint(timezone.localdate())
    html = client.get(reverse("ledger:open_books")).content.decode()
    assert "Books checked on" in html
    assert m.number not in html and "Secret Name" not in html and "secret-person" not in html
    assert "UNIQ outstanding" in html


def test_a_failed_audit_lights_a_red_banner(client):
    book()
    from apps.ledger.models import ChainHead

    ChainHead.objects.filter(name="uniq").update(last_hash="f" * 64)
    run_audit(full=True)
    assert "found problems" in client.get(reverse("ledger:open_books")).content.decode()


def test_period_csv(client):
    book()
    text = client.get(reverse("ledger:open_books_csv")).content.decode()
    assert text.splitlines()[0] == "period,status,tax_rate,issued,tax,spent"
    assert ",5.0000," in text


def test_fingerprints_cannot_be_changed():
    book()
    f = make_fingerprint(date(2026, 1, 1))
    f.seq = 99
    with pytest.raises(ValueError):
        f.save()
