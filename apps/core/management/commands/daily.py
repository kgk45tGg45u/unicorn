from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.jobs import enqueue, run_due

# Later phases add their daily jobs here, as (kind, payload) pairs.
DAILY_JOBS: list[tuple[str, dict]] = []


class Command(BaseCommand):
    help = "Queue the daily jobs and run them."

    def handle(self, *args, **options):
        today = timezone.localdate().isoformat()
        for kind, payload in DAILY_JOBS:
            enqueue(kind, payload, dedupe_key=f"daily:{kind}:{today}")
        ran = run_due()
        self.stdout.write(f"{ran} job(s) run.")
