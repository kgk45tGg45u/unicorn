from django.core.management.base import BaseCommand

from apps.macro import close


class Command(BaseCommand):
    help = "Close a month: cancel Fund 1, store the macro accounts and set the next flat tax (default: last month)."

    def add_arguments(self, parser):
        parser.add_argument("--period", help="YYYY-MM")

    def handle(self, *args, **options):
        if options["period"]:
            year, month = (int(x) for x in options["period"].split("-"))
        else:
            year, month = close.previous_month()
        snapshot = close.close_period(year, month)
        if snapshot is None:
            self.stdout.write(f"Nothing happened in {year}-{month:02d}.")
        else:
            self.stdout.write(f"{year}-{month:02d} closed. Next flat tax: {snapshot.tax_rate_next}.")
