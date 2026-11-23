"""/healthz (P15.T08): it names the checks that failed, and nothing else."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time

from apps.core import health
from apps.ledger.models import AuditRun
from apps.members.models import SiteState

pytestmark = pytest.mark.django_db


def fresh():
    health.note_jobs_run()
    health.note_daily_run()


def answer(client):
    response = client.get("/healthz")
    return response.status_code, response.json()


def test_a_healthy_system_answers_ok(client):
    fresh()
    assert answer(client) == (200, {"status": "ok"})


def test_healthz_fails_with_jobs_when_no_runner_has_run_for_6_minutes(client):
    with freeze_time("2027-03-01 10:00:00"):
        fresh()
        assert answer(client)[0] == 200
    with freeze_time("2027-03-01 10:04:30"):
        assert answer(client)[0] == 200  # not yet 5 minutes
    with freeze_time("2027-03-01 10:06:00"):
        assert answer(client) == (503, {"status": "fail", "checks": ["jobs"]})


def test_a_system_where_cron_never_ran_fails_both(client):
    assert answer(client) == (503, {"status": "fail", "checks": ["jobs", "daily"]})


def test_healthz_fails_with_daily_after_26_hours(client):
    with freeze_time("2027-03-01 00:05:00"):
        fresh()
    with freeze_time("2027-03-02 02:00:00"):  # 25 h 55 min later
        health.note_jobs_run()
        assert answer(client)[0] == 200
    with freeze_time("2027-03-02 02:10:00"):
        health.note_jobs_run()
        assert answer(client) == (503, {"status": "fail", "checks": ["daily"]})


def test_healthz_fails_with_audit_when_the_last_audit_found_something(client):
    fresh()
    now = timezone.now()
    AuditRun.objects.create(started_at=now - timedelta(hours=2), finished_at=now - timedelta(hours=2), ok=True)
    assert answer(client)[0] == 200
    AuditRun.objects.create(started_at=now - timedelta(hours=1), finished_at=now - timedelta(hours=1), ok=False)
    assert answer(client) == (503, {"status": "fail", "checks": ["audit"]})


def test_the_backup_counts_only_where_it_is_expected(client, settings, tmp_path):
    settings.BACKUP_RUN_DIR = str(tmp_path)
    fresh()
    settings.BACKUP_EXPECTED = False
    assert answer(client)[0] == 200  # staging has no backup, and that is fine
    settings.BACKUP_EXPECTED = True
    assert answer(client) == (503, {"status": "fail", "checks": ["backup"]})  # no file
    stamp = timezone.now() - timedelta(hours=3)
    (tmp_path / "last_backup").write_text(stamp.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
    assert answer(client)[0] == 200
    old = timezone.now() - timedelta(hours=27)
    (tmp_path / "last_backup").write_text(old.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
    assert answer(client) == (503, {"status": "fail", "checks": ["backup"]})
    (tmp_path / "last_backup").write_text("not a time")
    assert answer(client)[1]["checks"] == ["backup"]


def test_healthz_gives_names_only(client, settings):
    settings.BACKUP_EXPECTED = False
    status, body = answer(client)
    assert status == 503 and set(body) == {"status", "checks"}
    assert all(isinstance(name, str) and name.isalpha() for name in body["checks"])


def test_healthz_names_the_database_when_it_does_not_answer(client, monkeypatch):
    from django.db import connection

    class Broken:
        def __enter__(self):
            raise RuntimeError("the database password is hunter2")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(connection, "cursor", lambda: Broken())
    response = client.get("/healthz")
    assert response.status_code == 503 and response.json() == {"status": "fail", "checks": ["database"]}
    assert "hunter2" not in response.content.decode()


def test_the_job_runner_and_daily_leave_their_mark():
    assert SiteState.get().last_jobs_run_at is None
    with freeze_time("2027-03-01 10:00:00"):
        call_command("run_jobs", stdout=StringIO())
        assert SiteState.objects.get().last_jobs_run_at == timezone.now()
        assert SiteState.objects.get().last_daily_at is None
        call_command("daily", stdout=StringIO())
        assert SiteState.objects.get().last_daily_at == timezone.now()


def test_daily_warns_the_operators_when_the_disk_is_over_80_percent(settings, monkeypatch):
    settings.ADMINS = [("Operator", "ops@example.org")]
    monkeypatch.setattr(health, "disk_percent", lambda path=None: 79)
    assert health.warn_if_disk_full() is False and mail.outbox == []
    monkeypatch.setattr(health, "disk_percent", lambda path=None: 85)
    assert health.warn_if_disk_full() is True
    assert len(mail.outbox) == 1 and "85" in mail.outbox[0].body and mail.outbox[0].to == ["ops@example.org"]


def test_the_disk_check_is_one_of_the_daily_jobs():
    from apps.core.management.commands import daily

    assert ("core.disk_check", {}) in daily.DAILY_JOBS


def test_security_txt_shows_the_contact_when_there_is_one(client, settings):
    settings.SECURITY_CONTACT = ""
    assert client.get("/.well-known/security.txt").status_code == 404
    settings.SECURITY_CONTACT = "security@example.org"
    response = client.get("/.well-known/security.txt")
    assert response.status_code == 200 and response["Content-Type"].startswith("text/plain")
    text = response.content.decode()
    assert "Contact: mailto:security@example.org" in text and "Expires: " in text and "Canonical: " in text
