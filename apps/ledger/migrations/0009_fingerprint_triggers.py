from django.db import migrations

from apps.core.sql import install_append_only_triggers


def create_triggers(apps, schema_editor):
    install_append_only_triggers(schema_editor, ["ledger_dailyfingerprint"])


class Migration(migrations.Migration):
    dependencies = [("ledger", "0008_fingerprint")]
    operations = [migrations.RunPython(create_triggers, migrations.RunPython.noop)]
