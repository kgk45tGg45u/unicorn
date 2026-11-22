from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.core.jobs import job

from .audit import run_audit


@job("ledger.audit")
def audit_job(payload):
    """Safe to run twice. Each Sunday (Europe/Berlin) it checks everything from the start."""
    full = bool(payload.get("full")) or timezone.localdate().weekday() == 6
    run_audit(full=full)


def make_fingerprint(day=None, chain="uniq"):
    """Record the head of the chain at the end of `day` (default: yesterday, Europe/Berlin). Safe to run twice."""
    from .models import DailyFingerprint, Transaction
    from .services import BERLIN

    day = day or (timezone.localdate() - timedelta(days=1))
    if DailyFingerprint.objects.filter(date=day, chain=chain).exists():
        return None
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=BERLIN)
    last = Transaction.objects.filter(created_at__lt=end).order_by("-seq").first()
    if last is not None:
        seq, hash_ = last.seq, last.hash
    else:
        previous = DailyFingerprint.objects.filter(chain=chain, date__lt=day).order_by("-date").first()
        seq, hash_ = (previous.seq, previous.hash) if previous else (0, "0" * 64)
    return DailyFingerprint.objects.create(date=day, chain=chain, seq=seq, hash=hash_)


@job("ledger.fingerprint")
def fingerprint_job(payload):
    make_fingerprint()
