import re

import pytest
from django.core import mail

from apps.members.models import User

pytestmark = pytest.mark.django_db


def test_signup_with_only_an_email_creates_user_without_password(client):
    response = client.post("/accounts/signup/", {"email": "new@example.org"})
    assert response.status_code in (200, 302)
    user = User.objects.get(email="new@example.org")
    assert not user.has_usable_password()


def test_login_by_code_works(client):
    User.objects.create_user("a@example.org")
    from allauth.account.models import EmailAddress

    user = User.objects.get(email="a@example.org")
    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
    response = client.post("/accounts/login/code/", {"email": "a@example.org"}, follow=True)
    assert response.status_code == 200
    code = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mail.outbox[-1].body).group(1)
    response = client.post("/accounts/login/code/confirm/", {"code": code}, follow=True)
    assert response.context["user"].is_authenticated


def test_login_page_has_passkey_button(client):
    html = client.get("/accounts/login/").content.decode()
    assert "passkey_login" in html
    assert html.index("passkey") < html.index("login code")
