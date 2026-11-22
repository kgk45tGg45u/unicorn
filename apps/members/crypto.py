"""Per-member encryption (HF-14, docs/08 section 4).

Each member has a data key. It is stored encrypted with the master key from the environment.
Shredding the data key makes all of that member's encrypted data unreadable.
"""

from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone

from .models import DataKey


class KeyDestroyed(Exception):
    pass


def _master() -> Fernet:
    return Fernet(settings.UNICORN_MASTER_KEY.encode())


def create_data_key(member) -> DataKey:
    return DataKey.objects.create(member=member, wrapped=_master().encrypt(Fernet.generate_key()))


def _member_fernet(member) -> Fernet:
    key = DataKey.objects.filter(member=member).first()
    if key is None:
        key = create_data_key(member)
    if key.destroyed_at is not None or not bytes(key.wrapped):
        raise KeyDestroyed(member.number)
    return Fernet(_master().decrypt(bytes(key.wrapped)))


def encrypt_for(member, data: bytes) -> bytes:
    return _member_fernet(member).encrypt(data)


def decrypt_for(member, token: bytes) -> bytes:
    return _member_fernet(member).decrypt(bytes(token))


def shred_key(member) -> None:
    DataKey.objects.filter(member=member).update(wrapped=b"", destroyed_at=timezone.now())
