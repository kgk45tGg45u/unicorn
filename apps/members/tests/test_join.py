from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.members import services
from apps.members.models import Member, Signature, SiteState, User, Waitlist

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def defaults():
    call_command("load_defaults", stdout=StringIO())
    call_command("loaddata", "contracts", verbosity=0)


def about(**over):
    data = {
        "display_name": "Ada",
        "country": "de",
        "currency": "eur",
        "postcode": "10115",
        "legal_name": "Ada Lovelace",
        "birth_date": "1990-05-05",
        "phone": "",
    }
    data.update(over)
    return data


def test_full_signup_creates_applicant_with_encrypted_data_and_signature(client):
    user = User.objects.create_user("ada@example.org")
    client.force_login(user)
    response = client.post(reverse("members:join_about"), about())
    assert response.status_code == 302 and response.url == reverse("members:contract")
    member = Member.objects.get(user=user)
    assert member.status == Member.APPLICANT and member.country == "DE"
    assert services.get_private(member)["legal_name"] == "Ada Lovelace"
    response = client.post(reverse("members:contract"), {f"accept_{i}": "1" for i in range(5)})
    assert response.url == reverse("members:join_next")
    assert Signature.objects.filter(member=member).count() == 1
    member.refresh_from_db()
    assert member.joined_at is not None
    assert member.hashes.filter(kind="email").exists()


def test_under_18_is_refused(client):
    user = User.objects.create_user("kid@example.org")
    client.force_login(user)
    year = timezone.localdate().year - 15
    response = client.post(reverse("members:join_about"), about(birth_date=f"{year}-01-01"))
    assert response.status_code == 200
    assert "18 or older" in response.content.decode()
    assert not Member.objects.exists()


def test_waitlist_is_used_during_the_trial_year(client):
    SiteState.objects.create(pk=1, launched_at=timezone.now())
    user = User.objects.create_user("late@example.org")
    client.force_login(user)
    html = client.get(reverse("members:join_about")).content.decode()
    assert "trial year" in html
    client.post(reverse("members:join_about"), {"waitlist": "1"})
    assert Waitlist.objects.filter(email="late@example.org").exists()
    assert not Member.objects.exists()


def test_after_the_trial_year_joining_is_open(client):
    SiteState.objects.create(pk=1, launched_at=timezone.now().replace(year=timezone.now().year - 2))
    client.force_login(User.objects.create_user("x@example.org"))
    assert "About you" in client.get(reverse("members:join_about")).content.decode()


def test_non_german_notice_and_benefits_warning_are_shown(client):
    user = User.objects.create_user("fr@example.org")
    client.force_login(user)
    client.post(reverse("members:join_about"), about(country="FR", receives_benefits="on"))
    html = client.get(reverse("members:join_next")).content.decode()
    assert "laws of your country" in html
    assert "means-tested benefits" in html


def test_waitlist_purge_deletes_invited_and_old():
    a = Waitlist.objects.create(email="a@x.org", invited_at=timezone.now())
    Waitlist.objects.create(email="b@x.org")
    assert services.purge_waitlist() == 1
    assert not Waitlist.objects.filter(pk=a.pk).exists()
    assert services.purge_waitlist(now=timezone.now().replace(year=timezone.now().year + 3)) == 1


def test_launch_when_every_founder_has_clicked():
    from apps.rules.services import set_param

    set_param("membership.founders_target", 3, decided_by="t", decided_tier="referendum", reason="test")
    founders = []
    for i in range(3):
        m = services.create_applicant(User.objects.create_user(f"f{i}@x.org"), f"f{i}", "DE")
        m.status, m.is_founder = Member.MEMBER, True
        m.save()
        founders.append(m)
    for m in founders[:2]:
        services.record_launch_click(m)
    assert SiteState.get().launched_at is None
    services.record_launch_click(founders[2])
    assert SiteState.get().launched_at is not None
    assert age_ok()


def age_ok():
    return services.age_on(date(2000, 2, 29), date(2018, 2, 28)) == 17
