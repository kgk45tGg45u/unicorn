import time
import traceback
from collections.abc import Callable
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from . import audit
from .models import Job

JOBS: dict[str, Callable[[dict], None]] = {}

STUCK_AFTER = timedelta(minutes=30)


def job(kind: str):
    """Register a job function.

    Every job function must be safe to run twice: a crash can make it run again.
    """

    def decorator(fn):
        JOBS[kind] = fn
        return fn

    return decorator


def enqueue(kind, payload=None, run_after=None, dedupe_key=None):
    """Queue a job. If a job with the same dedupe_key exists, do nothing and return None."""
    if dedupe_key and Job.objects.filter(dedupe_key=dedupe_key).exists():
        return None
    return Job.objects.create(
        kind=kind,
        payload=payload or {},
        run_after=run_after or timezone.now(),
        dedupe_key=dedupe_key,
    )


def _recover_stuck():
    cutoff = timezone.now() - STUCK_AFTER
    for j in Job.objects.filter(status=Job.RUNNING, started_at__lt=cutoff):
        j.attempts += 1
        j.status = Job.FAILED if j.attempts >= j.max_attempts else Job.QUEUED
        j.save(update_fields=["attempts", "status"])


def _claim():
    with transaction.atomic():
        qs = Job.objects.filter(status=Job.QUEUED, run_after__lte=timezone.now()).order_by("run_after", "id")
        if connection.features.has_select_for_update_skip_locked:
            qs = qs.select_for_update(skip_locked=True)  # only the job runner may skip locked rows
        else:
            qs = qs.select_for_update()
        j = qs.first()
        if j is None:
            return None
        j.status = Job.RUNNING
        j.started_at = timezone.now()
        j.save(update_fields=["status", "started_at"])
        return j


def _run_one(j):
    try:
        with transaction.atomic():
            JOBS[j.kind](j.payload)
    except Exception:
        j.attempts += 1
        j.last_error = traceback.format_exc()
        if j.attempts >= j.max_attempts:
            j.status = Job.FAILED
        else:
            j.status = Job.QUEUED
            j.run_after = timezone.now() + timedelta(minutes=2**j.attempts)
        j.save()
    else:
        j.status = Job.DONE
        j.finished_at = timezone.now()
        j.save(update_fields=["status", "finished_at"])


def run_due(max_seconds=55) -> int:
    """Run due jobs one by one until none is due or time is up. Returns how many ran."""
    started = time.monotonic()
    _recover_stuck()
    ran = 0
    while time.monotonic() - started < max_seconds:
        j = _claim()
        if j is None:
            break
        _run_one(j)
        ran += 1
    return ran


@job("core.ping")
def ping(payload):
    audit.record("system", "ping", **payload)


@job("core.disk_check")
def disk_check(payload):
    """Every day: warn the operators by email when the disk is more than 80 % full."""
    from . import health

    health.warn_if_disk_full()


@job("core.restore_check")
def restore_check(payload):
    """Every day: if no restore test has worked for 35 days, the elected auditors get a ticket. Safe to run twice."""
    from . import restore

    restore.warn_if_overdue()
