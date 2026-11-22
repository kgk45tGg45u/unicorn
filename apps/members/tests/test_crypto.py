from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.members import crypto, services
from apps.members.models import MemberPrivate, User

pytestmark = pytest.mark.django_db


def make(email="a@example.org"):
    return services.create_applicant(User.objects.create_user(email), "Ada", "DE")


def test_set_and_get_private_data():
    m = make()
    services.set_private(m, legal_name="Ada Lovelace", city="Berlin")
    services.set_private(m, phone="123")
    assert services.get_private(m) == {"legal_name": "Ada Lovelace", "city": "Berlin", "phone": "123"}


def test_unknown_private_field_is_refused():
    with pytest.raises(ValueError):
        services.set_private(make(), shoe_size="42")


def test_hf14_blob_contains_no_plaintext():
    m = make()
    services.set_private(m, legal_name="Ada Lovelace", iban="DE89370400440532013000")
    blob = bytes(MemberPrivate.objects.get(member=m).blob)
    assert b"Ada" not in blob and b"Lovelace" not in blob and b"DE89" not in blob


def test_file_round_trip(settings):
    m = make()
    upload = SimpleUploadedFile("licence.pdf", b"%PDF-1 secret", "application/pdf")
    pf = services.store_private_file(m, upload, "licence")
    stored = (Path(settings.PRIVATE_MEDIA_ROOT) / pf.path).read_bytes()
    assert b"secret" not in stored
    assert services.read_private_file(pf) == ("licence.pdf", b"%PDF-1 secret")


def test_file_type_and_size_limits():
    m = make()
    with pytest.raises(services.FileRejected):
        services.store_private_file(m, SimpleUploadedFile("a.exe", b"x", "application/x-msdownload"), "other")
    with pytest.raises(services.FileRejected):
        services.store_private_file(
            m, SimpleUploadedFile("a.pdf", b"x" * (10 * 1024 * 1024 + 1), "application/pdf"), "other"
        )


def test_after_shred_data_and_files_are_gone():
    m = make()
    services.set_private(m, legal_name="Ada")
    pf = services.store_private_file(m, SimpleUploadedFile("a.pdf", b"x", "application/pdf"), "other")
    services.shred(m)
    assert services.get_private(m) == {"deleted": True}
    with pytest.raises(crypto.KeyDestroyed):
        services.read_private_file(pf)


def test_download_allowed_for_owner_and_403_for_others(client):
    a, b = make("a@example.org"), make("b@example.org")
    pf = services.store_private_file(a, SimpleUploadedFile("a.pdf", b"hello", "application/pdf"), "other")
    url = reverse("members:private_file", args=[pf.pk])
    client.force_login(b.user)
    assert client.get(url).status_code == 403
    client.force_login(a.user)
    response = client.get(url)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"hello"
    assert "attachment" in response["Content-Disposition"]
