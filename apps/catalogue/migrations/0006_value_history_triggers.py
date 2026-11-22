from django.db import migrations

from apps.core.sql import install_append_only_triggers


def create_triggers(apps, schema_editor):
    install_append_only_triggers(schema_editor, ["catalogue_offervaluehistory"])


class Migration(migrations.Migration):
    dependencies = [("catalogue", "0005_value_history")]
    operations = [migrations.RunPython(create_triggers, migrations.RunPython.noop)]
