from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.core import jobs
from apps.core.models import AuditEvent, Job


@pytest.fixture
def boom():
    @jobs.job("test.boom")
    def _boom(payload):
        raise RuntimeError("boom")

    yield
    jobs.JOBS.pop("test.boom")


@pytest.mark.django_db
def test_enqueue_and_run_ping():
    jobs.enqueue("core.ping", {"n": 1})
    assert jobs.run_due() == 1
    assert Job.objects.get().status == Job.DONE
    assert AuditEvent.objects.filter(verb="ping").count() == 1


@pytest.mark.django_db
def test_failing_job_is_retried_then_failed(boom):
    with freeze_time("2026-01-01 12:00:00") as clock:
        j = jobs.enqueue("test.boom")
        j.max_attempts = 2
        j.save()
        jobs.run_due()
        j.refresh_from_db()
        assert j.status == Job.QUEUED and j.attempts == 1
        assert j.run_after > timezone.now()
        assert "boom" in j.last_error
        assert jobs.run_due() == 0  # not due yet
        clock.tick(timedelta(minutes=3))
        jobs.run_due()
        j.refresh_from_db()
        assert j.status == Job.FAILED and j.attempts == 2


@pytest.mark.django_db
def test_dedupe_key_prevents_doubles():
    assert jobs.enqueue("core.ping", dedupe_key="x") is not None
    assert jobs.enqueue("core.ping", dedupe_key="x") is None
    assert Job.objects.count() == 1


@pytest.mark.django_db
def test_running_job_is_not_picked_again():
    j = jobs.enqueue("core.ping")
    j.status = Job.RUNNING
    j.started_at = timezone.now()
    j.save()
    assert jobs.run_due() == 0


@pytest.mark.django_db
def test_stuck_job_is_queued_again():
    with freeze_time("2026-01-01 12:00:00") as clock:
        j = jobs.enqueue("core.ping")
        j.status = Job.RUNNING
        j.started_at = timezone.now()
        j.save()
        clock.tick(timedelta(minutes=31))
        jobs.run_due()  # recovers it, then runs it
        j.refresh_from_db()
        assert j.attempts == 1
        assert j.status == Job.DONE
