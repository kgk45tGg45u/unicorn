import re
from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.http import HttpResponse
from django.urls import path
from freezegun import freeze_time

from apps.core.decorators import sensitive_action
from apps.members import services
from apps.members.middleware import LastActiveMiddleware
from apps.members.models import Member, User
from unicorn import urls as main_urls

pytestmark = pytest.mark.django_db


@sensitive_action
def secret_view(request):
    return HttpResponse("secret")


urlpatterns = [path("secret/", secret_view), *main_urls.urlpatterns]


def login_by_code(client, email="a@x.org"):
    user = User.objects.create_user(email)
    EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
    client.post("/accounts/login/code/", {"email": email})
    code = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mail.outbox[-1].body).group(1)
    client.post("/accounts/login/code/confirm/", {"code": code})
    return user


def test_login_sends_the_notice_mail(client):
    login_by_code(client)
    assert any("New login" in m.subject for m in mail.outbox)
    notice = [m for m in mail.outbox if "New login" in m.subject][0]
    assert "If this was not you" in notice.body


def reauthenticate_by_code(client, email="a@x.org"):
    client.post("/accounts/reauthenticate/code/", {"recipient": email})
    code = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mail.outbox[-1].body).group(1)
    client.post("/accounts/reauthenticate/code/confirm/", {"code": code})


@pytest.mark.urls("apps.members.tests.test_sensitive")
def test_sensitive_view_needs_recent_authentication(client):
    with freeze_time("2026-01-01 12:00:00") as clock:
        login_by_code(client)
        assert client.get("/secret/").status_code == 302  # allauth counts only an explicit re-authentication
        reauthenticate_by_code(client)
        assert client.get("/secret/").status_code == 200
        clock.tick(timedelta(minutes=14))
        assert client.get("/secret/").status_code == 200
        clock.tick(timedelta(minutes=2))
        response = client.get("/secret/")
        assert response.status_code == 302
        assert "reauthenticate" in response.url


def test_last_active_updates_at_most_once_an_hour(rf):
    user = User.objects.create_user("b@x.org")
    member = services.create_applicant(user, "B", "DE")
    calls = []

    def view(request):
        calls.append(1)
        return HttpResponse("ok")

    middleware = LastActiveMiddleware(view)
    with freeze_time("2026-01-01 12:00:00") as clock:
        request = rf.get("/")
        request.member = member
        middleware(request)
        first = Member.objects.get(pk=member.pk).last_active_at
        clock.tick(timedelta(minutes=30))
        request.member = Member.objects.get(pk=member.pk)
        middleware(request)
        assert Member.objects.get(pk=member.pk).last_active_at == first
        clock.tick(timedelta(minutes=31))
        request.member = Member.objects.get(pk=member.pk)
        middleware(request)
        assert Member.objects.get(pk=member.pk).last_active_at > first
