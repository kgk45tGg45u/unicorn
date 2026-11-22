from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.members import services
from apps.members.models import Licence, Skill, User

pytestmark = pytest.mark.django_db


def make(email):
    return services.create_applicant(User.objects.create_user(email), email.split("@")[0], "DE")


def test_licence_document_is_private(client):
    a, b = make("a@x.org"), make("b@x.org")
    licence = services.submit_licence(a, "health_care", SimpleUploadedFile("l.pdf", b"%PDF", "application/pdf"))
    assert licence.status == "submitted"
    url = reverse("members:private_file", args=[licence.document_id])
    client.force_login(b.user)
    assert client.get(url).status_code == 403
    client.force_login(a.user)
    assert client.get(url).status_code == 200


def test_has_verified_licence_respects_expiry():
    m = make("a@x.org")
    lic = services.submit_licence(m, "tax_advice", SimpleUploadedFile("l.pdf", b"x", "application/pdf"))
    assert not services.has_verified_licence(m, "tax_advice")  # only submitted
    Licence.objects.filter(pk=lic.pk).update(status="verified", expires_on=date.today() + timedelta(days=1))
    assert services.has_verified_licence(m, "tax_advice")
    assert not services.has_verified_licence(m, "health_care")
    Licence.objects.filter(pk=lic.pk).update(expires_on=date.today() - timedelta(days=1))
    assert not services.has_verified_licence(m, "tax_advice")


def test_portfolio_page_adds_skill_and_public_profile_shows_it(client):
    m = make("a@x.org")
    client.force_login(m.user)
    client.post(reverse("members:portfolio"), {"action": "skill", "trade_name": "Baking", "level": "expert"})
    assert Skill.objects.filter(member=m, trade_name="Baking").exists()
    url = reverse("members:public_profile", args=[m.number])
    assert "Baking" not in client.get(url).content.decode()
    client.post(reverse("members:portfolio"), {"action": "public", "public_profile": "1"})
    assert "Baking" in client.get(url).content.decode()


def test_bad_licence_upload_is_refused_in_plain_words(client):
    m = make("a@x.org")
    client.force_login(m.user)
    response = client.post(
        reverse("members:portfolio"),
        {
            "action": "licence",
            "kind": "health_care",
            "document": SimpleUploadedFile("a.exe", b"x", "application/x-msdownload"),
        },
    )
    assert response.status_code == 200
    assert "Only PDF, JPEG and PNG" in response.content.decode()
