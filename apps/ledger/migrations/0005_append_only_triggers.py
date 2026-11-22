from django.db import migrations

from apps.core.sql import install_append_only_triggers

TABLES = [
    "ledger_transaction",
    "ledger_entry",
    "core_auditevent",
    "rules_parameterchange",
    "members_signature",
    "members_vouch",
    "members_inpersoncheck",
]


def create_triggers(apps, schema_editor):
    install_append_only_triggers(schema_editor, TABLES)


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0004_chain_head"),
        ("core", "0002_job"),
        ("rules", "0001_initial"),
        ("members", "0007_availability_licence_skill"),
    ]
    operations = [migrations.RunPython(create_triggers, migrations.RunPython.noop)]
