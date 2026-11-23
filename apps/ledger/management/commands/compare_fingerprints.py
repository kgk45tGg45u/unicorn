import json

from django.core.management.base import BaseCommand, CommandError

from apps.ledger.models import DailyFingerprint, Transaction


class Command(BaseCommand):
    help = (
        "Compare the chain heads of this database with the daily fingerprints. Every stored fingerprint must match the "
        "transaction it names. With --published FILE (the JSON of /open-books/fingerprints.json), every published "
        "fingerprint up to the last transaction of this database must match too."
    )

    def add_arguments(self, parser):
        parser.add_argument("--published", help="A JSON file of published fingerprints.")

    def handle(self, *args, **options):
        problems = []
        checked = 0
        for fp in DailyFingerprint.objects.filter(chain="uniq"):
            checked += 1
            if fp.seq == 0:  # nothing was booked yet
                if fp.hash != "0" * 64:
                    problems.append(f"The fingerprint of {fp.date} should be empty.")
                continue
            tx = Transaction.objects.filter(seq=fp.seq).first()
            if tx is None or tx.hash != fp.hash:
                problems.append(f"The fingerprint of {fp.date} does not match transaction {fp.seq}.")
        if options["published"]:
            try:
                with open(options["published"]) as f:
                    published = json.load(f)
            except (OSError, ValueError) as e:
                raise CommandError(f"The published fingerprints could not be read: {e}") from None
            last = Transaction.objects.order_by("-seq").values_list("seq", flat=True).first() or 0
            ours = {(str(fp.date), fp.chain): fp.hash for fp in DailyFingerprint.objects.all()}
            for row in published:
                if row["chain"] != "uniq" or row["seq"] > last:
                    continue  # written after the backup was made
                checked += 1
                if ours.get((row["date"], row["chain"])) != row["hash"]:
                    problems.append(f"The published fingerprint of {row['date']} is not in this database or differs.")
        for problem in problems:
            self.stdout.write(problem)
        if problems:
            raise CommandError("The chain heads do not match the fingerprints.")
        self.stdout.write(f"{checked} fingerprints match.")
