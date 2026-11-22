import re

import pytest
from django.urls import reverse

from apps.members import services
from apps.members.models import Member, User

pytestmark = pytest.mark.django_db


def make(email="a@example.org", name="Ada", status=Member.APPLICANT):
    user = User.objects.create_user(email)
    member = services.create_applicant(user, name, "DE", "EUR", "10115")
    member.status = status
    member.save()
    return member


def test_number_format_and_uniqueness():
    numbers = {make(f"u{i}@example.org").number for i in range(20)}
    assert len(numbers) == 20
    assert all(re.fullmatch(r"M-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}", n) for n in numbers)


def test_hf13_is_verified_false_for_applicant_and_former():
    assert not services.is_verified(make("a@example.org", status=Member.APPLICANT))
    assert not services.is_verified(make("b@example.org", status=Member.FORMER))
    assert not services.is_verified(make("c@example.org", status=Member.SUSPENDED))
    assert services.is_verified(make("d@example.org", status=Member.MEMBER))
    assert not services.is_verified(None)


def test_active_members_only_status_member():
    make("a@example.org")
    m = make("b@example.org", status=Member.MEMBER)
    assert list(services.active_members()) == [m]


def test_middleware_sets_request_member(client):
    m = make()
    assert client.get("/").wsgi_request.member is None
    client.force_login(m.user)
    assert client.get("/").wsgi_request.member == m


def test_my_account_shows_own_data_only(client):
    a = make("a@example.org", "Ada")
    b = make("b@example.org", "Bob")
    client.force_login(a.user)
    html = client.get(reverse("members:my_account")).content.decode()
    assert a.number in html and "a@example.org" in html
    assert b.number not in html and "b@example.org" not in html


def test_my_account_needs_login(client):
    assert client.get(reverse("members:my_account")).status_code == 302


def test_public_profile_hides_private_details(client):
    a = make()
    html = client.get(reverse("members:public_profile", args=[a.number])).content.decode()
    assert "Ada" in html and "a@example.org" not in html
