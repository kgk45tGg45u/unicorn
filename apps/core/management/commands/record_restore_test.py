from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.core import audit
from apps.core.models import RestoreTest


class Command(BaseCommand):
    help = (
        "Record the result of a restore test: record_restore_test --ok|--failed --backup-date 2027-03-01 --notes '...'"
    )

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--ok", action="store_true")
        group.add_argument("--failed", action="store_true")
        parser.add_argument(
            "--backup-date", required=True, help="The day of the backup that was restored (YYYY-MM-DD)."
        )
        parser.add_argument("--notes", default="")
        parser.add_argument("--operator", default="", help="The operator's member number.")

    def handle(self, *args, **options):
        try:
            backup_date = date.fromisoformat(options["backup_date"])
        except ValueError:
            raise CommandError("Please write the backup date as YYYY-MM-DD.") from None
        row = RestoreTest.objects.create(
            backup_date=backup_date,
            ok=bool(options["ok"]),
            notes=options["notes"],
            operator_number=options["operator"],
        )
        audit.record(options["operator"] or "system", "restore_test.recorded", row, ok=row.ok)
        self.stdout.write(f"Recorded: {row}")
