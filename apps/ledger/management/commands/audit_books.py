from django.core.management.base import BaseCommand

from apps.ledger.audit import run_audit


class Command(BaseCommand):
    help = "Check the UNIQ books: hash chain, sums, balances."

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", help="Check from the first transaction.")

    def handle(self, *args, **options):
        run = run_audit(full=options["full"])
        for finding in run.findings:
            self.stdout.write(finding)
        self.stdout.write("The books are in order." if run.ok else "The audit found problems.")
