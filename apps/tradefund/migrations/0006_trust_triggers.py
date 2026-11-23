from django.db import migrations

from apps.core.sql import install_append_only_triggers


def create_triggers(apps, schema_editor):
    install_append_only_triggers(schema_editor, ["tradefund_trustevent"])


class Migration(migrations.Migration):
    dependencies = [("tradefund", "0005_payments_trust")]
    operations = [migrations.RunPython(create_triggers, migrations.RunPython.noop)]
