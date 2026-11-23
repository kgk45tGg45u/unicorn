import json
from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from freezegun import freeze_time

from apps.core import restore
from apps.core.models import RestoreTest
from apps.tickets.models import Ticket

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    call_command("load_defaults", stdout=StringIO())


def run(*args):
    out = StringIO()
    call_command("record_restore_test", *args, stdout=out)
    return out.getvalue()


def test_record_restore_test_stores_a_row():
    run("--ok", "--backup-date", "2027-03-01", "--notes", "all fine", "--operator", "M-AAAA-BBBB")
    row = RestoreTest.objects.get()
    assert row.ok and row.backup_date == date(2027, 3, 1) and row.notes == "all fine"
    assert row.operator_number == "M-AAAA-BBBB"
    run("--failed", "--backup-date", "2027-04-01", "--notes", "the audit found a problem")
    assert RestoreTest.objects.filter(ok=False).count() == 1
    assert restore.last_ok().backup_date == date(2027, 3, 1)  # a failed test is not a success


def test_record_restore_test_refuses_a_bad_date_and_needs_an_outcome():
    with pytest.raises(CommandError, match="YYYY-MM-DD"):
        run("--ok", "--backup-date", "yesterday")
    with pytest.raises(CommandError):
        run("--backup-date", "2027-03-01")


def test_after_35_days_without_a_successful_test_a_warning_ticket_goes_to_the_auditors():
    with freeze_time("2027-01-01 10:00:00"):
        assert restore.overdue()  # nothing was ever tested
        run("--ok", "--backup-date", "2027-01-01")
        assert not restore.overdue() and restore.warn_if_overdue() is None
    with freeze_time("2027-02-04 10:00:00"):  # 34 days later
        assert restore.warn_if_overdue() is None
    with freeze_time("2027-02-07 10:00:00"):  # 37 days later
        ticket = restore.warn_if_overdue()
        assert ticket is not None and ticket.type == "restore_overdue"
        assert "restore test" in ticket.body_md
        assert restore.warn_if_overdue() is None  # one warning at a time
        assert Ticket.objects.filter(type="restore_overdue").count() == 1


def test_the_daily_job_is_registered_and_runs():
    from apps.core.jobs import JOBS
    from apps.core.management.commands import daily

    assert ("core.restore_check", {}) in daily.DAILY_JOBS
    JOBS["core.restore_check"]({})
    assert Ticket.objects.filter(type="restore_overdue").count() == 1


def test_the_open_books_page_shows_the_last_successful_restore_test(client):
    assert "No backup has been restored as a test yet" in client.get("/open-books/").content.decode()
    run("--ok", "--backup-date", "2027-03-01")
    page = client.get("/open-books/").content.decode()
    assert "2027-03-01" in page and "restored successfully" in page


def test_the_fingerprints_are_published_as_data_and_compared_with_a_restored_database(client):
    from apps.ledger import services as ledger
    from apps.ledger.jobs import make_fingerprint
    from apps.units.tests.conftest import make_member

    member = make_member("m@x.org", "M")
    ledger.post(
        "hours_pay",
        "funding",
        [ledger.Leg(ledger.fund2(), -1), ledger.Leg(ledger.member_account(member), 1)],
    )
    make_fingerprint(timezone.localdate())
    published = client.get("/open-books/fingerprints.json").json()
    assert published and set(published[0]) == {"date", "chain", "seq", "hash"}
    out = StringIO()
    call_command("compare_fingerprints", stdout=out)
    assert "fingerprints match" in out.getvalue()


def test_a_wrong_published_fingerprint_is_found(tmp_path):
    from apps.ledger import services as ledger
    from apps.ledger.jobs import make_fingerprint
    from apps.units.tests.conftest import make_member

    member = make_member("m@x.org", "M")
    ledger.post("hours_pay", "funding", [ledger.Leg(ledger.fund2(), -1), ledger.Leg(ledger.member_account(member), 1)])
    make_fingerprint(timezone.localdate())
    from apps.ledger.models import DailyFingerprint

    fp = DailyFingerprint.objects.first()
    wrong = tmp_path / "published.json"
    wrong.write_text(json.dumps([{"date": str(fp.date), "chain": "uniq", "seq": fp.seq, "hash": "0" * 64}]))
    with pytest.raises(CommandError, match="do not match"):
        call_command("compare_fingerprints", "--published", str(wrong), stdout=StringIO())
