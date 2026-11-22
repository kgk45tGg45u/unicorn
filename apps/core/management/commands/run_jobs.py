from django.core.management.base import BaseCommand

from apps.core.jobs import run_due


class Command(BaseCommand):
    help = "Run due background jobs once."

    def add_arguments(self, parser):
        parser.add_argument("--max-seconds", type=int, default=55)

    def handle(self, *args, **options):
        ran = run_due(max_seconds=options["max_seconds"])
        self.stdout.write(f"{ran} job(s) run.")
