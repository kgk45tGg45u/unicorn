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


# --- The system key, for outside parties (sellers, landlords, donors) who have no account ---


def _system_fernet() -> Fernet:
    """A key derived from the master key with HKDF. It encrypts data of people outside Unicorn (HF-14)."""
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"unicorn-system-v1").derive(
        settings.UNICORN_MASTER_KEY.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def system_encrypt(data: bytes) -> bytes:
    return _system_fernet().encrypt(data)


def system_decrypt(token: bytes) -> bytes:
    return _system_fernet().decrypt(bytes(token))
