from django.db import migrations


def create_head(apps, schema_editor):
    ChainHead = apps.get_model("ledger", "ChainHead")
    ChainHead.objects.get_or_create(name="uniq")


class Migration(migrations.Migration):
    dependencies = [("ledger", "0003_transactions")]
    operations = [migrations.RunPython(create_head, migrations.RunPython.noop)]
