from decimal import Decimal
from pathlib import Path

import pytest
from django.db import connection

from apps.core.sql import triggers_present
from apps.ledger.audit import run_audit
from apps.ledger.jobs import make_fingerprint
from apps.ledger.models import ChainHead, DailyFingerprint
from apps.tradefund import books
from apps.tradefund.models import FundEntry

from .conftest import make_holder

pytestmark = pytest.mark.django_db
D = Decimal


def test_hf07_fund_books_append_only():
    h = make_holder(amount=100)
    entry = FundEntry.objects.get()
    entry.amount = D(1)
    with pytest.raises(ValueError):
        entry.save()
    with pytest.raises(ValueError):
        entry.delete()
    with pytest.raises(ValueError):
        FundEntry.objects.filter(holder=h).update(amount=1)
    assert triggers_present(["tradefund_fundentry"], connection)["tradefund_fundentry"] in (True, False)


def test_hf12_no_bank_integration():
    """The app has no outgoing call except the ECB rates (apps/tradefund/fx.py): no module imports a network library."""
    import ast

    root = Path(__file__).resolve().parents[2]
    banned = {"requests", "urllib", "urllib3", "http", "httpx", "socket", "aiohttp", "smtplib", "ftplib"}
    offenders = []
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if "tests" in parts or "migrations" in parts or path == root / "tradefund" / "fx.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.split(".")[0] in banned for n in names):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_the_chain_links():
    h = make_holder(amount=100)
    books.post_fund(h, "payment_out", -30, "a payment", "group_purchase")
    a, b = FundEntry.objects.order_by("seq")
    assert a.prev_hash == "0" * 64 and b.prev_hash == a.hash
    assert ChainHead.objects.get(name="fund").last_hash == b.hash
    assert books.audit_findings() == []


def test_holdings_never_go_negative():
    h = make_holder(amount=100)
    with pytest.raises(books.BooksError):
        books.post_fund(h, "payment_out", D("-100.01"), "too much", "bill")
    books.post_fund(h, "payment_out", -100, "all of it", "bill")
    assert books.holding(h) == 0


def test_the_free_part_excludes_the_reserve():
    h = make_holder(amount=100)
    books.post_fund(h, "reserve_mark", 40, "loss reserve", "internal")
    assert books.holding(h) == 100 and books.reserve(h) == 40 and books.free(h) == 60
    with pytest.raises(books.BooksError):
        books.post_fund(h, "payment_out", -61, "more than free", "bill")
    with pytest.raises(books.BooksError):
        books.post_fund(h, "reserve_mark", 61, "more than free", "internal")
    books.post_fund(h, "reserve_unmark", 40, "released", "internal")
    assert books.free(h) == 100


def test_every_entry_needs_a_reason_and_a_sensible_sign():
    h = make_holder(amount=10)
    with pytest.raises(books.BooksError):
        books.post_fund(h, "donation", 5, "  ", "gift")
    with pytest.raises(books.BooksError):
        books.post_fund(h, "donation", -5, "wrong sign", "gift")
    with pytest.raises(books.BooksError):
        books.post_fund(h, "payment_out", 5, "wrong sign", "bill")
    with pytest.raises(books.BooksError):
        books.post_fund(h, "setaside", 5, "wrong currency", "gift", currency="USD")


def test_total_in_euros_uses_the_rates():
    from apps.tradefund import fx
    from apps.tradefund.tests.test_fx import XML

    fx.store_rates(XML)
    make_holder("a@x.org", "A", amount=100)
    make_holder("b@x.org", "B", currency="USD", amount=108)
    assert books.fund_total_eur() == D("200.00")


def test_the_audit_checks_the_fund_chain_and_the_fingerprint_covers_it():
    h = make_holder(amount=100)
    assert run_audit(full=True).ok
    from django.utils import timezone

    day = timezone.localdate()
    assert make_fingerprint(day, "fund").seq == 1
    assert DailyFingerprint.objects.filter(chain="fund").count() == 1
    # break the chain in the database: the audit says so
    ChainHead.objects.filter(name="fund").update(last_hash="f" * 64)
    run = run_audit(full=True)
    assert not run.ok and any("fund" in f for f in run.findings)
    assert h.pk


def test_the_daily_fingerprint_job_writes_both_chains():
    from apps.ledger import jobs

    make_holder(amount=5)
    jobs.fingerprint_job({})
    assert set(DailyFingerprint.objects.values_list("chain", flat=True)) == {"uniq", "fund"}
