"""Load postcode centres from a GeoNames file (https://download.geonames.org/export/zip/DE.zip, CC BY 4.0).

Run once by the operator; it never runs at request time.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.logistics.models import PostcodePoint


def load(path, country) -> int:
    """Tab-separated: country, postal code, place, admin1-3 (name, code), latitude, longitude, accuracy."""
    seen = {}
    with open(path, encoding="utf-8") as f:
        for raw in f:
            cols = raw.rstrip("\n").split("\t")
            if len(cols) < 11 or cols[0].upper() != country.upper():
                continue
            code = "".join(cols[1].split()).upper()
            try:
                lat, lng = Decimal(cols[9]), Decimal(cols[10])
            except ArithmeticError:
                continue
            seen.setdefault(code, []).append((cols[2], lat, lng))
    count = 0
    for code, places in seen.items():
        town = places[0][0]  # several places: keep the first name, and average different coordinates
        lat = (sum(p[1] for p in places) / len(places)).quantize(Decimal("0.000001"))
        lng = (sum(p[2] for p in places) / len(places)).quantize(Decimal("0.000001"))
        PostcodePoint.objects.update_or_create(
            country=country.upper(), postcode=code, defaults={"town": town[:120], "lat": lat, "lng": lng}
        )
        count += 1
    return count


class Command(BaseCommand):
    help = "Load postcode centres from a GeoNames postal-code file."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--country", default="DE")

    def handle(self, *args, **options):
        try:
            n = load(options["file"], options["country"])
        except OSError as e:
            raise CommandError(f"Cannot read the file: {e}") from None
        self.stdout.write(f"{n} postcodes loaded.")
