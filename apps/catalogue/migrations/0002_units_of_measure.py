from django.db import migrations

UNITS = [
    ("pc", "piece", "count"),
    ("kg", "kilogram", "mass"),
    ("g", "gram", "mass"),
    ("l", "litre", "volume"),
    ("ml", "millilitre", "volume"),
    ("m", "metre", "length"),
    ("m2", "square metre", "area"),
    ("m3", "cubic metre", "volume"),
    ("kwh", "kilowatt hour", "energy"),
    ("h", "hour", "time"),
    ("service", "one service to one customer", "service"),
    ("km", "kilometre", "distance"),
]


def load(apps, schema_editor):
    UnitOfMeasure = apps.get_model("catalogue", "UnitOfMeasure")
    for code, name, dimension in UNITS:
        UnitOfMeasure.objects.get_or_create(code=code, defaults={"name": name, "dimension": dimension})


class Migration(migrations.Migration):

    dependencies = [
        ("catalogue", "0001_initial"),
    ]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
