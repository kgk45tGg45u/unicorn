"""Per-member encryption (HF-14, docs/08 section 4).

Each member has a data key. It is stored encrypted with the master key from the environment.
Shredding the data key makes all of that member's encrypted data unreadable.
"""

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.utils import timezone

from .models import DataKey


class KeyDestroyed(Exception):
    pass


def old_master_keys() -> list[str]:
    """Keys that were used before the current master key. They are in the setting only while a rotation is running."""
    return [k.strip() for k in getattr(settings, "UNICORN_OLD_MASTER_KEYS", "").split(",") if k.strip()]


def _master() -> MultiFernet:
    """The current master key encrypts; the old ones can still decrypt during a rotation (P14.T05)."""
    return MultiFernet([Fernet(k.encode()) for k in [settings.UNICORN_MASTER_KEY, *old_master_keys()]])


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


def _derived(master_key: str) -> Fernet:
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"unicorn-system-v1").derive(master_key.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _system_fernet() -> MultiFernet:
    """A key derived from each master key with HKDF. It encrypts data of people outside Unicorn (HF-14)."""
    return MultiFernet([_derived(k) for k in [settings.UNICORN_MASTER_KEY, *old_master_keys()]])


# --- Rotation (P14.T05) ---

# Every field encrypted with `system_encrypt`, and every field encrypted with a member's own key. A test checks that
# each column that ends in `_enc` is in one of these lists, so a new encrypted field cannot be forgotten.
SYSTEM_ENCRYPTED_FIELDS = [
    ("outside.OutsideCustomer", "name_enc"),
    ("outside.OutsideCustomer", "address_enc"),
    ("outside.OutsideCustomer", "email_enc"),
    ("outside.Invoice", "customer_snapshot_enc"),
    ("outside.SellerProfile", "trader_address_enc"),
    ("tradefund.Donation", "donor_name_enc"),
    ("tradefund.ExternalPayee", "iban_enc"),
]
MEMBER_ENCRYPTED_FIELDS = [("members.PrivateFile", "name_enc")]  # the member's own data key is not the master key


def is_current(token: bytes, fernet: Fernet) -> bool:
    """Whether the newest key alone can read this token."""
    from cryptography.fernet import InvalidToken

    try:
        fernet.decrypt(bytes(token))
        return True
    except InvalidToken:
        return False


def system_encrypt(data: bytes) -> bytes:
    return _system_fernet().encrypt(data)


def system_decrypt(token: bytes) -> bytes:
    return _system_fernet().decrypt(bytes(token))
