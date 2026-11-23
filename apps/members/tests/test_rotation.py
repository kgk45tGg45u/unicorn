from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import models
from django.utils import timezone

from apps.members import crypto, services
from apps.members.models import MemberHash
from apps.outside.models import OutsideCustomer
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db


def run(name):
    out = StringIO()
    call_command(name, stdout=out)
    return out.getvalue()


def set_keys(settings, new, old=""):
    settings.UNICORN_MASTER_KEY = new
    settings.UNICORN_OLD_MASTER_KEYS = old


def test_every_encrypted_column_is_in_a_rotation_list():
    registered = {
        f"{label}.{field}" for label, field in crypto.SYSTEM_ENCRYPTED_FIELDS + crypto.MEMBER_ENCRYPTED_FIELDS
    }
    found = set()
    for model in apps.get_models():
        if model.__module__.startswith("apps."):
            for f in model._meta.concrete_fields:
                if f.name.endswith("_enc") or isinstance(f, models.BinaryField):
                    found.add(f"{model._meta.label}.{f.name}")
    # DataKey.wrapped, MemberPrivate.blob and PrivateFile content are wrapped by the master key or by member keys
    known_elsewhere = {"members.DataKey.wrapped", "members.MemberPrivate.blob"}
    assert found - registered - known_elsewhere == set()


def test_after_rotation_everything_decrypts_with_the_new_key_alone(settings):
    old = settings.UNICORN_MASTER_KEY
    member = make_member("m@x.org", "M")
    services.set_private(member, legal_name="Mara Musterfrau", iban="DE89370400440532013000")
    customer = OutsideCustomer.objects.create(
        name_enc=crypto.system_encrypt(b"Cora Customer"),
        email_enc=crypto.system_encrypt(b"cora@example.org"),
        address_enc=crypto.system_encrypt(b"Main Street 1"),
        privacy_consent_at=timezone.now(),
    )
    new = Fernet.generate_key().decode()
    set_keys(settings, new, old)
    assert services.get_private(member)["legal_name"] == "Mara Musterfrau"  # still readable during the change
    out = run("rotate_master_key")
    assert "data keys re-wrapped: 1" in out and "system-encrypted fields re-encrypted: 3" in out
    assert "left to do: 0" in out and "remove the old key" in out
    set_keys(settings, new, "")  # the old key is gone
    assert services.get_private(member)["legal_name"] == "Mara Musterfrau"
    customer.refresh_from_db()
    assert crypto.system_decrypt(customer.name_enc) == b"Cora Customer"
    assert crypto.system_decrypt(customer.email_enc) == b"cora@example.org"
    assert str(old) not in out and str(new) not in out and "Cora" not in out  # counts only


def test_running_the_rotation_twice_changes_nothing_more(settings):
    old = settings.UNICORN_MASTER_KEY
    member = make_member("m@x.org", "M")
    services.set_private(member, legal_name="Mara")
    new = Fernet.generate_key().decode()
    set_keys(settings, new, old)
    run("rotate_master_key")
    before = bytes(member.data_key.__class__.objects.get(member=member).wrapped)
    out = run("rotate_master_key")
    assert "data keys re-wrapped: 0" in out and "system-encrypted fields re-encrypted: 0" in out
    assert bytes(member.data_key.__class__.objects.get(member=member).wrapped) == before


def test_a_rotation_without_an_old_key_is_refused(settings):
    set_keys(settings, settings.UNICORN_MASTER_KEY, "")
    with pytest.raises(CommandError, match="nothing to rotate"):
        run("rotate_master_key")


def test_a_destroyed_key_stays_destroyed_through_a_rotation(settings):
    old = settings.UNICORN_MASTER_KEY
    member = make_member("gone@x.org", "Gone")
    services.set_private(member, legal_name="Gone Person")
    services.delete_account(member)
    set_keys(settings, Fernet.generate_key().decode(), old)
    assert "data keys re-wrapped: 0" in run("rotate_master_key")


def test_the_hmac_rotation_recomputes_hashes_and_still_detects_a_duplicate(settings):
    first = make_member("first@x.org", "First")
    services.set_private(first, iban="DE89 3704 0044 0532 0130 00")
    services.update_hashes(first)
    old_hash = MemberHash.objects.get(member=first, kind="email").value
    settings.UNICORN_HMAC_KEY = "cd" * 32
    assert "recomputed: 1" in run("rotate_hmac_key")
    new_hash = MemberHash.objects.get(member=first, kind="email").value
    assert new_hash != old_hash and new_hash == services.hash_of("email", "first@x.org")
    second = make_member("second@x.org", "Second")
    services.set_private(second, iban="de89370400440532013000")  # the same account number, written differently
    services.update_hashes(second)
    from apps.tickets.models import Ticket

    assert Ticket.objects.filter(type="duplicate_suspected").exists()


def test_generate_keys_prints_two_new_keys_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run("generate_keys").splitlines()
    assert out[0].startswith("UNICORN_MASTER_KEY=") and out[1].startswith("UNICORN_HMAC_KEY=")
    Fernet(out[0].split("=", 1)[1].encode())  # a valid Fernet key
    assert len(bytes.fromhex(out[1].split("=", 1)[1])) == 32
    assert list(tmp_path.iterdir()) == []
