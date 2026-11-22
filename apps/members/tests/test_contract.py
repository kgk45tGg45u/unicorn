import hashlib

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.members import services
from apps.members.models import ContractTemplate, Signature, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def member():
    call_command("loaddata", "contracts", verbosity=0)
    return services.create_applicant(User.objects.create_user("a@example.org"), "Ada", "DE")


def test_fixture_hash_matches_body(member):
    t = ContractTemplate.objects.get(kind="membership", version=1)
    assert t.sha256 == hashlib.sha256(t.body_md.encode()).hexdigest()
    assert t.body_md.count("DRAFT — to be written with lawyers") == 5


def test_signature_stores_template_hash(member):
    t = ContractTemplate.objects.get(kind="membership")
    s = services.sign(member, t, "click")
    assert s.text_sha256 == t.sha256


def test_signatures_cannot_be_changed_or_deleted(member):
    s = services.sign(member, ContractTemplate.objects.get(kind="membership"), "click")
    s.method = "code"
    with pytest.raises(ValueError):
        s.save()
    with pytest.raises(ValueError):
        s.delete()


def test_signing_requires_all_tick_boxes(client, member):
    client.force_login(member.user)
    url = reverse("members:contract")
    response = client.post(url, {"accept_0": "1", "accept_1": "1"})
    assert response.status_code == 200
    assert Signature.objects.count() == 0
    response = client.post(url, {f"accept_{i}": "1" for i in range(5)})
    assert response.status_code == 302
    assert Signature.objects.count() == 1
