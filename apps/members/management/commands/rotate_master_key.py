from cryptography.fernet import Fernet
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.members import crypto
from apps.members.models import DataKey

BATCH = 500


class Command(BaseCommand):
    help = (
        "Re-encrypt every data key and every system-encrypted field with the new master key. Put the new key in "
        "UNICORN_MASTER_KEY and the old one in UNICORN_OLD_MASTER_KEYS first. Safe to run twice. "
        "Prints only counts, never keys or data."
    )

    def handle(self, *args, **options):
        if not crypto.old_master_keys():
            raise CommandError("UNICORN_OLD_MASTER_KEYS is empty: there is nothing to rotate from.")
        newest = Fernet(settings.UNICORN_MASTER_KEY.encode())
        system_newest = crypto._derived(settings.UNICORN_MASTER_KEY)
        wrapped = self._data_keys(newest)
        changed = self._system_fields(system_newest)
        left = self._left(newest, system_newest)
        self.stdout.write(f"data keys re-wrapped: {wrapped}")
        self.stdout.write(f"system-encrypted fields re-encrypted: {changed}")
        self.stdout.write(f"left to do: {left}")
        if left == 0:
            self.stdout.write("Done. You can now remove the old key from .env and restart.")

    def _data_keys(self, newest) -> int:
        done = 0
        ids = list(DataKey.objects.filter(destroyed_at__isnull=True).exclude(wrapped=b"").values_list("pk", flat=True))
        for start in range(0, len(ids), BATCH):
            with transaction.atomic():
                for key in DataKey.objects.select_for_update().filter(pk__in=ids[start : start + BATCH]):
                    if not crypto.is_current(key.wrapped, newest):
                        key.wrapped = crypto._master().rotate(bytes(key.wrapped))
                        key.save(update_fields=["wrapped"])
                        done += 1
        return done

    def _system_fields(self, system_newest) -> int:
        done = 0
        for label, field in crypto.SYSTEM_ENCRYPTED_FIELDS:
            model = apps.get_model(label)
            ids = list(model.objects.values_list("pk", flat=True))
            for start in range(0, len(ids), BATCH):
                with transaction.atomic():
                    for row in model.objects.select_for_update().filter(pk__in=ids[start : start + BATCH]):
                        token = getattr(row, field)
                        if token and not crypto.is_current(token, system_newest):
                            setattr(row, field, crypto._system_fernet().rotate(bytes(token)))
                            row.save(update_fields=[field])
                            done += 1
        return done

    def _left(self, newest, system_newest) -> int:
        left = 0
        for key in DataKey.objects.filter(destroyed_at__isnull=True).exclude(wrapped=b""):
            left += 0 if crypto.is_current(key.wrapped, newest) else 1
        for label, field in crypto.SYSTEM_ENCRYPTED_FIELDS:
            for token in apps.get_model(label).objects.values_list(field, flat=True):
                if token and not crypto.is_current(token, system_newest):
                    left += 1
        return left
