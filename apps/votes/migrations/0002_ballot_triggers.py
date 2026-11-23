from django.db import migrations

from apps.core.sql import install_append_only_triggers


def create_triggers(apps, schema_editor):
    install_append_only_triggers(schema_editor, ["votes_ballot", "votes_voterrecord"])


class Migration(migrations.Migration):
    dependencies = [("votes", "0001_initial")]
    operations = [migrations.RunPython(create_triggers, migrations.RunPython.noop)]
