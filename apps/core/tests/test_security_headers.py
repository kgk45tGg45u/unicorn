import re
from pathlib import Path

import pytest
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib import admin
from django.core.management import call_command
from django.urls import reverse
from freezegun import freeze_time

from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def defaults_loaded(db):
    from io import StringIO

    call_command("load_defaults", stdout=StringIO())


def test_the_security_headers_are_on_a_page(client):
    response = client.get("/")
    csp = response["Content-Security-Policy"]
    for directive in (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
    ):
        assert directive in csp, directive
    assert response["X-Frame-Options"] == "DENY"
    assert response["Referrer-Policy"] == "same-origin"
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert 'name="htmx-config"' in response.content.decode() and "includeIndicatorStyles" in response.content.decode()


def test_cookies_are_httponly_and_lax():
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_COOKIE_AGE == 1209600 and settings.SESSION_IDLE_SECONDS == 12 * 3600


def test_in_production_http_is_sent_to_https_and_hsts_is_set(settings, client):
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_HSTS_SECONDS = 3600
    settings.ALLOWED_HOSTS = ["testserver"]
    from django.test import Client

    fresh = Client()
    assert fresh.get("/").status_code == 301
    secure = fresh.get("/", secure=True)
    assert secure.status_code == 200 and secure["Strict-Transport-Security"] == "max-age=3600"
    behind_proxy = fresh.get("/", HTTP_X_FORWARDED_PROTO="https")
    assert behind_proxy.status_code == 200


def test_templates_have_no_inline_script_or_style():
    root = Path(settings.BASE_DIR)
    files = [*root.glob("templates/**/*.html"), *root.glob("apps/*/templates/**/*.html")]
    assert len(files) > 50
    problems = []
    for path in files:
        text = path.read_text()
        for match in re.finditer(r"<script\b[^>]*>", text):
            tag = match.group(0)
            if " src=" not in tag and "application/json" not in tag:
                problems.append(f"{path.relative_to(root)}: inline script")
        if re.search(r"<style\b", text):
            problems.append(f"{path.relative_to(root)}: style element")
        if re.search(r"\sstyle=\"", text):
            problems.append(f"{path.relative_to(root)}: style attribute")
        if re.search(r"<[a-zA-Z][^<>]*\son[a-z]+=\"", text):
            problems.append(f"{path.relative_to(root)}: event attribute")
    assert problems == []


def staff(email="op@x.org"):
    member = make_member(email, "Operator")
    user = member.user
    user.is_staff = True
    user.save()
    return user


def passkey(user):
    return Authenticator.objects.create(user=user, type=Authenticator.Type.WEBAUTHN, data={"name": "key"})


def test_the_admin_is_not_at_admin_and_needs_the_secret_path(client):
    assert client.get("/admin/").status_code == 404
    assert settings.ADMIN_PATH not in ("admin", "")
    response = client.get(f"/{settings.ADMIN_PATH}/")
    assert response.status_code == 302 and response["Location"].startswith("/accounts/login/")


def test_a_staff_user_without_a_passkey_cannot_open_the_admin(client):
    user = staff()
    client.force_login(user)
    response = client.get(f"/{settings.ADMIN_PATH}/")
    assert response.status_code == 403 and "passkey" in response.content.decode()
    passkey(user)
    assert client.get(f"/{settings.ADMIN_PATH}/").status_code == 200


def test_a_normal_member_cannot_open_the_admin(client):
    member = make_member("m@x.org", "M")
    client.force_login(member.user)
    response = client.get(f"/{settings.ADMIN_PATH}/")
    assert response.status_code == 403 and "only for the people who run" in response.content.decode()


def test_the_admins_own_login_page_sends_people_to_the_normal_login(client):
    response = client.get(f"/{settings.ADMIN_PATH}/login/")
    assert response.status_code == 302 and response["Location"].startswith("/accounts/login/")


def test_the_admin_is_read_only_for_everyone(client):
    user = staff()
    user.is_superuser = True
    user.save()
    passkey(user)
    client.force_login(user)
    for model, model_admin in admin.site._registry.items():
        request = type("R", (), {"user": user})()
        assert not model_admin.has_add_permission(request), model
        assert not model_admin.has_change_permission(request), model
        assert not model_admin.has_delete_permission(request), model
    assert client.get(f"/{settings.ADMIN_PATH}/members/member/add/").status_code == 403


def test_an_idle_session_ends_after_12_hours(client):
    member = make_member("m@x.org", "M")
    with freeze_time("2026-11-23 08:00:00") as clock:
        client.force_login(member.user)
        assert client.get("/me/").status_code == 200
        clock.tick(11 * 3600)
        assert client.get("/me/").status_code == 200  # activity resets the clock
        clock.tick(11 * 3600)
        assert client.get("/me/").status_code == 200
        clock.tick(13 * 3600)
        response = client.get("/me/")
        assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_the_admin_path_is_in_the_environment_example():
    assert "ADMIN_PATH" in (Path(settings.BASE_DIR) / ".env.example").read_text()
    assert reverse("admin:index").startswith(f"/{settings.ADMIN_PATH}/")
    call_command("check")


def test_the_deployment_check_has_only_the_two_warnings_we_chose_to_keep(settings):
    """HSTS for subdomains and the preload list stay off on purpose: the owner's server may host other subdomains."""
    from django.core.checks import run_checks

    settings.DEBUG = False
    settings.SECRET_KEY = "x" * 60 + "q7#Zr!f9"
    settings.ALLOWED_HOSTS = ["unicorn.example.org"]
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_HSTS_SECONDS = 31536000
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    ids = {m.id for m in run_checks(include_deployment_checks=True)}
    assert ids <= {"security.W005", "security.W021"}, ids
