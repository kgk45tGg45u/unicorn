import io
import json
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from apps.core.jobs import run_due
from apps.ledger import services as ledger
from apps.members import services as member_services
from apps.members.crypto import decrypt_for
from apps.privacy import export
from apps.privacy.models import DataExport
from apps.tickets import services as ticket_services
from apps.tickets.models import Notification

from .conftest import make_member

pytestmark = pytest.mark.django_db


@pytest.fixture
def recent_login(monkeypatch):
    """The member logged in a moment ago, so sensitive pages open (P01.T09 is tested in the members app)."""
    monkeypatch.setattr(
        "allauth.account.internal.flows.reauthentication.is_reauthentication_required", lambda request, **kwargs: False
    )


def fund(member, amount):
    ledger.post(
        "hours_pay",
        "test funding",
        [ledger.Leg(ledger.fund2(), -Decimal(amount)), ledger.Leg(ledger.member_account(member), Decimal(amount))],
    )


def ready_export(member):
    row = DataExport.objects.create(member=member)
    export.create_export(row)
    row.refresh_from_db()
    return row


def open_zip(row):
    return zipfile.ZipFile(io.BytesIO(export.read_export(row)))


def two_members():
    me = make_member("me@x.org", "Mara Mine")
    other = make_member("other@x.org", "Otto Other")
    member_services.set_private(me, legal_name="Mara Musterfrau", city="Berlin", iban="DE89370400440532013000")
    member_services.set_private(other, legal_name="Otto Normal", city="Hamburg", iban="DE02120300000000202051")
    fund(me, 5)
    fund(other, 7)
    return me, other


def test_the_export_contains_my_ledger_entries_and_my_private_data():
    me, other = two_members()
    zf = open_zip(ready_export(me))
    data = json.loads(zf.read("data.json"))
    assert "Secret ballots cannot be exported" in zf.read("README.txt").decode()
    assert any(Decimal(row["amount"]) == Decimal("5.0000") for row in data["entry"])
    assert data["private_data"][0]["legal_name"] == "Mara Musterfrau"
    assert data["login"][0]["email"] == "me@x.org"
    assert "entry.csv" in zf.namelist() and "data.json" in zf.namelist() and "README.txt" in zf.namelist()


def test_the_export_holds_no_other_members_name_or_private_data():
    me, other = two_members()
    ticket = ticket_services.create_ticket("question", other, "Otto asks something")
    ticket_services.add_comment(ticket, me, "I can answer that")
    zf = open_zip(ready_export(me))
    everything = "".join(zf.read(name).decode() for name in zf.namelist())
    for secret in ("Otto Other", "Otto Normal", "Hamburg", "DE02120300000000202051", "other@x.org", "Otto asks"):
        assert secret not in everything, secret
    data = json.loads(zf.read("data.json"))
    assert [c["author"] for c in data["comment"]] == [me.number]
    assert data["ticket"] == []  # the ticket was Otto's


def test_the_file_on_the_server_is_encrypted_and_belongs_to_the_member():
    me, other = two_members()
    row = ready_export(me)
    raw = (
        settings.PRIVATE_MEDIA_ROOT and __import__("pathlib").Path(settings.PRIVATE_MEDIA_ROOT) / row.path
    ).read_bytes()
    assert b"Mara Musterfrau" not in raw and not raw.startswith(b"PK")
    assert export.make_zip(me)[:2] == b"PK"
    assert decrypt_for(me, raw)[:2] == b"PK"
    assert Notification.objects.filter(member=me, text__contains="ready to download").exists()


def test_the_job_builds_the_export_and_the_link_expires_after_seven_days(client, recent_login):
    from apps.core.jobs import enqueue

    me, other = two_members()
    row = DataExport.objects.create(member=me)
    enqueue("privacy.export", {"export": row.pk})
    assert run_due() == 1
    row.refresh_from_db()
    assert row.status == "ready" and row.expires_at > timezone.now() + timedelta(days=6)
    client.force_login(me.user)
    assert client.get(f"/me/data/{row.pk}/download/").status_code == 200
    with freeze_time(timezone.now() + timedelta(days=8)):
        client.force_login(me.user)
        assert client.get(f"/me/data/{row.pk}/download/").status_code == 404
        assert "ended" in client.get(f"/me/data/{row.pk}/").content.decode()
        assert export.delete_files() == 1
    row.refresh_from_db()
    assert row.status == "expired" and row.path == ""


def test_only_the_member_can_download_their_export(client, recent_login):
    me, other = two_members()
    row = ready_export(me)
    client.force_login(other.user)
    assert client.get(f"/me/data/{row.pk}/download/").status_code == 404
    assert client.get(f"/me/data/{row.pk}/").status_code == 404


def test_asking_for_my_data_queues_a_job(client, recent_login):
    from apps.core.models import Job

    me, other = two_members()
    client.force_login(me.user)
    response = client.post("/me/data/export/")
    assert response.status_code == 302
    assert DataExport.objects.filter(member=me).count() == 1
    assert Job.objects.filter(kind="privacy.export").count() == 1
    assert "Download all my data" in client.get("/me/").content.decode()


def test_a_member_who_works_in_a_unit_exports_their_hours():
    from apps.units import services as unit_services
    from apps.units.tests.conftest import make_unit

    me, other = two_members()
    unit = make_unit("bakery")
    unit_services.add_first_worker(unit, me)
    unit_services.record_hours(me, unit, timezone.localdate(), 90)
    data = json.loads(open_zip(ready_export(me)).read("data.json"))
    assert data["hoursentry"][0]["minutes"] == 90 and data["unitmembership"][0]["member"] == me.number


def test_without_a_recent_login_the_download_asks_to_log_in_again(client):
    me, other = two_members()
    row = ready_export(me)
    client.force_login(me.user)
    assert client.get(f"/me/data/{row.pk}/download/").status_code in (302, 403)  # not the file itself
