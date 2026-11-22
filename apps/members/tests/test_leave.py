import pytest
from django.urls import reverse

from apps.core.models import AuditEvent
from apps.members import services
from apps.members.models import Member, MemberHash, User

pytestmark = pytest.mark.django_db


def make(email="a@x.org"):
    m = services.create_applicant(User.objects.create_user(email), "Ada", "DE")
    m.status = Member.MEMBER
    m.save()
    return m


@pytest.fixture
def blocker():
    check = lambda member: ["You still hold fund euros."]  # noqa: E731
    services.LEAVE_CHECKS.append(check)
    yield check
    services.LEAVE_CHECKS.remove(check)


def test_blocking_check_stops_leaving(blocker):
    m = make()
    with pytest.raises(services.LeaveBlocked) as e:
        services.leave(m)
    assert "fund euros" in e.value.reasons[0]
    m.refresh_from_db()
    assert m.status == Member.MEMBER


def test_hf08_former_member_keeps_account_and_can_log_in(client):
    m = make()
    services.leave(m)
    m.refresh_from_db()
    assert m.status == Member.FORMER and m.left_at and not m.deleted
    assert AuditEvent.objects.filter(verb="member.left").exists()
    client.force_login(m.user)
    assert client.get(reverse("members:my_account")).status_code == 200


def test_after_deletion_private_data_and_hashes_are_gone():
    m = make()
    services.set_private(m, legal_name="Ada Lovelace", phone="123")
    assert MemberHash.objects.filter(member=m).exists()
    services.delete_account(m)
    m.refresh_from_db()
    assert m.deleted and m.status == Member.FORMER
    assert services.get_private(m) == {"deleted": True}
    assert not MemberHash.objects.filter(member=m).exists()
    assert m.user.email == f"deleted-{m.number}@invalid" and not m.user.is_active
    assert Member.objects.filter(number=m.number).exists()  # the books keep the number


def test_delete_page_warns_and_deletes(client):
    m = make()
    client.force_login(m.user)
    html = client.get(reverse("members:delete")).content.decode()
    assert "can no longer be spent" in html
    client.post(reverse("members:delete"), {"confirm": "1"})
    m.refresh_from_db()
    assert m.deleted


def test_delete_blocked_by_check(client, blocker):
    m = make()
    client.force_login(m.user)
    html = client.post(reverse("members:delete"), {"confirm": "1"}).content.decode()
    assert "fund euros" in html
    m.refresh_from_db()
    assert not m.deleted
