from django.db import migrations

from apps.core.sql import install_append_only_triggers


def create_head(apps, schema_editor):
    apps.get_model("ledger", "ChainHead").objects.get_or_create(name="fund")


def create_triggers(apps, schema_editor):
    install_append_only_triggers(schema_editor, ["tradefund_fundentry"])


class Migration(migrations.Migration):
    dependencies = [("tradefund", "0003_fund_entry"), ("ledger", "0009_fingerprint_triggers")]
    operations = [
        migrations.RunPython(create_head, migrations.RunPython.noop),
        migrations.RunPython(create_triggers, migrations.RunPython.noop),
    ]
