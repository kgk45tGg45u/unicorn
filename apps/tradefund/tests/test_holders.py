import pytest
from allauth.account.models import EmailAddress
from django.core.management import call_command

from apps.members import services as ms
from apps.members.crypto import system_decrypt, system_encrypt
from apps.members.models import MemberPrivate, Signature
from apps.tradefund import services
from apps.tradefund.models import Holder
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db

IBAN = "DE89 3704 0044 0532 0130 00"


@pytest.fixture(autouse=True)
def contracts():
    call_command("loaddata", "contracts", verbosity=0)


def test_an_unverified_member_cannot_become_a_holder():
    applicant = make_member("a@x.org", "Ada", verified=False)
    with pytest.raises(services.FundError):
        services.become_holder(applicant, "EUR", IBAN)
    assert not Holder.objects.exists()


def test_a_verified_member_signs_and_the_iban_is_stored_encrypted():
    m = make_member("a@x.org", "Ada")
    holder = services.become_holder(m, "eur", IBAN, "COBADEFF", "Bank", separate_account=True)
    assert holder.currency == "EUR" and holder.status == "active"
    assert Signature.objects.filter(member=m, template__kind="holder_agreement").count() == 1
    raw = bytes(MemberPrivate.objects.get(member=m).blob)
    assert b"DE89" not in raw
    assert ms.get_private(m)["iban"] == "DE89370400440532013000"


def test_one_cannot_become_a_holder_twice():
    m = make_member("a@x.org", "Ada")
    services.become_holder(m, "EUR", IBAN)
    with pytest.raises(services.FundError):
        services.become_holder(m, "EUR", IBAN)


def test_a_bad_iban_is_refused_in_plain_words():
    m = make_member("a@x.org", "Ada")
    with pytest.raises(services.FundError, match="account number"):
        services.become_holder(m, "EUR", "12")


def test_the_system_key_roundtrips_and_hides_the_text():
    token = system_encrypt(b"DE00 outside payee")
    assert b"outside" not in token
    assert system_decrypt(token) == b"DE00 outside payee"


def test_pages(client):
    m = make_member("a@x.org", "Ada")
    EmailAddress.objects.create(user=m.user, email=m.user.email, verified=True, primary=True)
    client.force_login(m.user)
    assert client.get("/fund/me/").status_code == 200
    assert client.get("/fund/become-a-holder/").status_code == 200
    response = client.post("/fund/become-a-holder/", {"accept": "1", "iban": IBAN})
    assert response.status_code == 302 and "reauthenticate" in response.url
    assert not Holder.objects.exists()
