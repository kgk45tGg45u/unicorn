import pytest
from django.core.cache import cache
from freezegun import freeze_time

from apps.core import ratelimit
from apps.rules.models import Parameter
from apps.tickets.models import Ticket
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_cache(db):
    from io import StringIO

    from django.core.management import call_command

    call_command("load_defaults", stdout=StringIO())
    cache.clear()


def test_hit_allows_the_limit_and_then_refuses():
    assert all(ratelimit.hit("k", 3, 60, now=1000) for _ in range(3))
    assert ratelimit.hit("k", 3, 60, now=1001) is False
    assert ratelimit.hit("k", 3, 60, now=1000 + 60) is True  # the next window starts fresh
    assert ratelimit.hit("other", 3, 60, now=1000) is True


def test_the_21st_ticket_in_a_day_gets_429_and_the_window_resets_the_next_day(client):
    member = make_member("m@x.org", "M")
    Parameter.objects.filter(key="security.tickets_per_member_per_day").update(value=20)
    client.force_login(member.user)
    with freeze_time("2026-11-23 10:00:00"):
        for i in range(20):
            response = client.post("/tickets/new/idea/", {"title": f"Idea {i}", "body_md": "x", "scope": "all"})
            assert response.status_code == 302, i
        response = client.post("/tickets/new/idea/", {"title": "One too many", "body_md": "x", "scope": "all"})
        assert response.status_code == 429
        assert "Please try again later" in response.content.decode()
        assert Ticket.objects.count() == 20
        assert client.get("/tickets/new/idea/").status_code == 200  # reading is never limited
    with freeze_time("2026-11-24 10:00:00"):
        response = client.post("/tickets/new/idea/", {"title": "A new day", "body_md": "x", "scope": "all"})
        assert response.status_code == 302


def test_comments_are_limited_per_hour(client):
    from apps.tickets import services as ticket_services

    member = make_member("m@x.org", "M")
    ticket = ticket_services.create_ticket("question", make_member("o@x.org", "O"), "A question")
    Parameter.objects.filter(key="security.comments_per_member_per_hour").update(value=3)
    client.force_login(member.user)
    with freeze_time("2026-11-23 10:00:00"):
        codes = [
            client.post(f"/tickets/{ticket.number}/comment/", {"body": f"Comment {i}"}).status_code for i in range(5)
        ]
    assert codes == [302, 302, 302, 429, 429]
    with freeze_time("2026-11-23 11:05:00"):
        assert client.post(f"/tickets/{ticket.number}/comment/", {"body": "Later"}).status_code == 302


def test_ip_keys_are_hashed_and_change_every_day(rf):
    request = rf.post("/", REMOTE_ADDR="203.0.113.7")
    with freeze_time("2026-11-23 10:00:00"):
        today = ratelimit.ip_key(request)
    with freeze_time("2026-11-24 10:00:00"):
        tomorrow = ratelimit.ip_key(request)
    assert "203.0.113.7" not in today and today.startswith("ip-") and today != tomorrow


def test_the_client_address_follows_the_proxy_only_from_localhost(rf):
    behind_apache = rf.post("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="198.51.100.1, 203.0.113.9")
    assert ratelimit.client_ip(behind_apache) == "203.0.113.9"
    spoofed = rf.post("/", REMOTE_ADDR="192.0.2.50", HTTP_X_FORWARDED_FOR="203.0.113.9")
    assert ratelimit.client_ip(spoofed) == "192.0.2.50"


def test_shop_orders_are_limited_per_address(client):
    from django.core.management import call_command

    from apps.outside.tests.conftest import Shop

    call_command("loaddata", "contracts", verbosity=0)
    shop = Shop()
    Parameter.objects.filter(key="security.shop_orders_per_ip_per_hour").update(value=2)
    url = f"/shop/offer/{shop.bread.pk}/"
    codes = [client.post(url, {"quantity": "1"}, REMOTE_ADDR="203.0.113.5").status_code for _i in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429
    assert client.post(url, {"quantity": "1"}, REMOTE_ADDR="203.0.113.6").status_code == 200  # another address
    assert client.get(url, REMOTE_ADDR="203.0.113.5").status_code == 200
