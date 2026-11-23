from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.models import AuditEvent
from apps.members import services
from apps.members.models import ContractTemplate, Member, User

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def defaults():
    call_command("load_defaults", stdout=StringIO())
    call_command("loaddata", "contracts", verbosity=0)


def make(email, status=Member.APPLICANT, helper=False):
    m = services.create_applicant(User.objects.create_user(email), email.split("@")[0], "DE")
    m.status = status
    m.is_identity_helper = helper
    m.save()
    return m


def test_two_vouches_plus_in_person_check_verify_the_member():
    v1, v2 = make("v1@x.org", Member.MEMBER), make("v2@x.org", Member.MEMBER)
    helper = make("h@x.org", Member.MEMBER, helper=True)
    new = make("new@x.org")
    services.vouch(v1, new, "I know them")
    services.vouch(v2, new, "Me too")
    new.refresh_from_db()
    assert new.status == Member.APPLICANT  # still no in-person check
    services.record_in_person_check(helper, new, date(2026, 11, 1), "Berlin")
    new.refresh_from_db()
    assert new.status == Member.MEMBER and new.verified_at


def test_verified_hook_is_called():
    seen = []
    services.VERIFIED_HOOKS.append(seen.append)
    try:
        v1, v2 = make("v1@x.org", Member.MEMBER), make("v2@x.org", Member.MEMBER)
        helper = make("h@x.org", Member.MEMBER, helper=True)
        new = make("new@x.org")
        services.vouch(v1, new, "a")
        services.vouch(v2, new, "b")
        services.record_in_person_check(helper, new, date(2026, 11, 1), "Berlin")
    finally:
        services.VERIFIED_HOOKS.remove(seen.append)
    assert [m.pk for m in seen] == [new.pk]


def test_self_vouching_fails():
    m = make("a@x.org", Member.MEMBER)
    with pytest.raises(services.IdentityError):
        services.vouch(m, m, "me")


def test_applicant_cannot_vouch():
    with pytest.raises(services.IdentityError):
        services.vouch(make("a@x.org"), make("b@x.org"), "x")


def test_monthly_vouch_limit_holds():
    voucher = make("v@x.org", Member.MEMBER)
    for i in range(5):
        services.vouch(voucher, make(f"n{i}@x.org"), "ok")
    with pytest.raises(services.IdentityError):
        services.vouch(voucher, make("n9@x.org"), "ok")


def test_helper_who_vouched_cannot_check_and_the_other_way_round():
    helper = make("h@x.org", Member.MEMBER, helper=True)
    a, b = make("a@x.org"), make("b@x.org")
    services.vouch(helper, a, "ok")
    with pytest.raises(services.IdentityError):
        services.record_in_person_check(helper, a, date(2026, 11, 1), "Berlin")
    services.record_in_person_check(helper, b, date(2026, 11, 1), "Berlin")
    with pytest.raises(services.IdentityError):
        services.vouch(helper, b, "ok")


def test_non_helper_cannot_record_check():
    with pytest.raises(services.IdentityError):
        services.record_in_person_check(make("a@x.org", Member.MEMBER), make("b@x.org"), date(2026, 11, 1), "Berlin")


def test_duplicate_email_hash_is_detected():
    a = make("same@x.org")
    services.update_hashes(a)
    other_user = User.objects.create_user("SAME@x.org.other")
    b = services.create_applicant(other_user, "b", "DE")
    other_user.email = "  Same@X.org "
    services.update_hashes(b)
    assert AuditEvent.objects.filter(verb="duplicate_suspected", object_id=str(b.pk)).exists()


def test_duplicate_phone_hash_is_detected():
    a, b = make("a@x.org"), make("b@x.org")
    services.set_private(a, phone="+49 30 1234")
    services.set_private(b, phone="49301234")
    assert AuditEvent.objects.filter(verb="duplicate_suspected").count() == 1


def test_bootstrap_founders_and_refuses_after_target():
    from apps.rules.services import set_param

    a, b = make("a@x.org"), make("b@x.org")
    for m in (a, b):
        services.sign(m, ContractTemplate.objects.get(kind="membership"), "click")
    call_command("bootstrap_founders", "--emails", "a@x.org", "b@x.org", stdout=StringIO())
    a.refresh_from_db()
    assert a.is_founder and a.status == Member.MEMBER
    assert AuditEvent.objects.filter(verb="founders_verified").count() == 1
    set_param("membership.founders_target", 3, decided_by="t", decided_tier="referendum", reason="test")
    for i in range(2):
        make(f"m{i}@x.org", Member.MEMBER)
    with pytest.raises(CommandError):
        call_command("bootstrap_founders", "--emails", "a@x.org", stdout=StringIO())


def test_bootstrap_needs_signed_contract():
    make("a@x.org")
    with pytest.raises(CommandError):
        call_command("bootstrap_founders", "--emails", "a@x.org", stdout=StringIO())
