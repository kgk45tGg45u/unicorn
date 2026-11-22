from django.utils import timezone

from apps.core.jobs import job

from .audit import run_audit


@job("ledger.audit")
def audit_job(payload):
    """Safe to run twice. Each Sunday (Europe/Berlin) it checks everything from the start."""
    full = bool(payload.get("full")) or timezone.localdate().weekday() == 6
    run_audit(full=full)
