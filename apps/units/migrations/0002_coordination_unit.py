from django.db import migrations
from django.utils import timezone


def create_coordination_unit(apps, schema_editor):
    Unit = apps.get_model("units", "Unit")
    Unit.objects.get_or_create(
        slug="coordination",
        defaults={
            "name": "Unicorn coordination",
            "kind": "coordination",
            "status": "open",
            "description": "Unicorn's own coordination work.",
            "opened_at": timezone.now(),
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("units", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_coordination_unit, migrations.RunPython.noop),
    ]
