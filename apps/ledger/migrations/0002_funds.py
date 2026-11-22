from django.db import migrations


def create_funds(apps, schema_editor):
    Account = apps.get_model("ledger", "Account")
    AccountBalance = apps.get_model("ledger", "AccountBalance")
    for kind in ("fund1", "fund2"):
        account, _ = Account.objects.get_or_create(kind=kind, member=None)
        AccountBalance.objects.get_or_create(account=account)


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial")]
    operations = [migrations.RunPython(create_funds, migrations.RunPython.noop)]
