import sys

from django.core.management.base import BaseCommand

from apps.core import launch


class Command(BaseCommand):
    help = "Before the founders launch: print OK, WARN or FAIL for every condition. Exits with 1 if anything FAILs."

    def handle(self, *args, **options):
        lines = launch.run_all()
        width = max(len(line.name) for line in lines)
        for line in lines:
            self.stdout.write(f"{line.status:<5} {line.name:<{width}}  {line.detail}")
        fails = sum(1 for line in lines if line.status == launch.FAIL)
        warns = sum(1 for line in lines if line.status == launch.WARN)
        self.stdout.write(f"\n{fails} to fix, {warns} to look at, {len(lines) - fails - warns} in order.")
        if fails:
            sys.exit(1)
