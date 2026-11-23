"""What /healthz looks at (P15.T08). It names the checks that failed, and nothing else.

- ``database``  the database answers;
- ``jobs``      the job runner finished a run in the last 5 minutes (cron runs it every minute);
- ``daily``     `daily` ran in the last 26 hours;
- ``audit``     the last audit of the books found nothing wrong;
- ``backup``    the owner's backup wrote ~/run/last_backup less than 26 hours ago (only if ``BACKUP_EXPECTED`` is on).
"""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.mail import mail_admins
from django.db import connection
from django.utils import timezone
from django.utils.translation import gettext as _

JOBS_MAX_AGE = timedelta(minutes=5)
DAILY_MAX_AGE = timedelta(hours=26)
BACKUP_MAX_AGE = timedelta(hours=26)
DISK_WARN_PERCENT = 80


def _recent(moment, limit, now):
    return moment is not None and now - moment <= limit


def backup_time():
    """When the last backup finished: the time the owner's backup job wrote in ~/run/last_backup, or None."""
    path = Path(settings.BACKUP_RUN_DIR) / "last_backup"
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def failed_checks(now=None):
    now = now or timezone.now()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return ["database"]  # nothing else can be asked without it

    from apps.ledger.models import AuditRun
    from apps.members.models import SiteState

    failed = []
    state = SiteState.objects.filter(pk=1).first()
    if not _recent(state and state.last_jobs_run_at, JOBS_MAX_AGE, now):
        failed.append("jobs")
    if not _recent(state and state.last_daily_at, DAILY_MAX_AGE, now):
        failed.append("daily")
    last_audit = AuditRun.objects.exclude(finished_at=None).first()
    if last_audit is not None and not last_audit.ok:
        failed.append("audit")
    if settings.BACKUP_EXPECTED and not _recent(backup_time(), BACKUP_MAX_AGE, now):
        failed.append("backup")
    return failed


def note_jobs_run(now=None):
    from apps.members.models import SiteState

    SiteState.get()
    SiteState.objects.filter(pk=1).update(last_jobs_run_at=now or timezone.now())


def note_daily_run(now=None):
    from apps.members.models import SiteState

    SiteState.get()
    SiteState.objects.filter(pk=1).update(last_daily_at=now or timezone.now())


def disk_percent(path=None):
    path = path or settings.DISK_CHECK_PATH
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    if not usage.total:
        return None
    return round(100 * usage.used / usage.total)


def warn_if_disk_full(path=None):
    """Every day: email the operators when the disk that holds the data is more than 80 % full."""
    percent = disk_percent(path)
    if percent is None or percent <= DISK_WARN_PERCENT:
        return False
    mail_admins(
        _("Unicorn: the disk is %(percent)s%% full") % {"percent": percent},
        _("The disk that holds Unicorn's data is %(percent)s%% full. Free some space before backups or uploads fail.")
        % {"percent": percent},
        fail_silently=True,
    )
    return True
