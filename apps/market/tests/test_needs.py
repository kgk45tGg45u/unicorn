from datetime import date, datetime
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse
from freezegun import freeze_time

from apps.catalogue import services as cat
from apps.core import hooks
from apps.core.models import AuditEvent
from apps.market import needs, services
from apps.market.models import (
    DemandSignal,
    Order,
    OrderLine,
    ProductionOrder,
    PurchaseNeed,
    SearchMiss,
    WaitingListEntry,
)
from apps.market.tests.conftest import World, fund, unit_for
from apps.members.models import Skill
from apps.units.models import CouncilDecision, HoursEntry
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db
D = Decimal


def board(client):
    response = client.get(reverse("market:needs"))
    assert response.status_code == 200
    return response.content.decode()


def honey():
    return cat.create_item("Honey", "product", "kg", trade_code="CPA_A01")


def member_with(email, postcode="04109"):
    m = make_member(email, "Neighbour")
    m.postcode = postcode
    m.save()
    fund(m, 5)
    return m


# --- the waiting list ---


def test_a_waiting_list_shows_under_wanted_now(client):
    item = honey()
    a, b = member_with("a@x.org"), member_with("b@x.org")
    needs.join_waiting_list(a, item, 2)
    needs.join_waiting_list(b, item, 3)
    text = board(client)
    assert "Wanted now" in text and "Honey" in text and "2 people want 5 together" in text


def test_joining_twice_changes_the_quantity_and_leaving_removes_it():
    item = honey()
    a = member_with("a@x.org")
    needs.join_waiting_list(a, item, 2)
    needs.join_waiting_list(a, item, 4)
    assert WaitingListEntry.objects.get().quantity == 4
    needs.leave_waiting_list(a, item)
    assert not WaitingListEntry.objects.exists()


def test_the_waiting_list_is_for_items_nobody_can_deliver_within_30_days(world):
    buyer = world.buyer()
    with pytest.raises(services.MarketError, match="order this now"):
        needs.join_waiting_list(buyer, world.bread.item, 1)
    world.bread.cycle_days = 40  # too slow: it takes longer than 30 days
    world.bread.save()
    assert needs.join_waiting_list(buyer, world.bread.item, 1)
    applicant = make_member("app@x.org", "App", verified=False)
    with pytest.raises(services.MarketError, match="Only members"):
        needs.join_waiting_list(applicant, honey(), 1)


def test_the_item_page_offers_the_waiting_list_only_when_needed(world, client):
    client.force_login(world.buyer().user)
    assert (
        "Tell me when it is available"
        not in client.get(reverse("catalogue:item", args=[world.bread.item_id])).content.decode()
    )
    item = honey()
    text = client.get(reverse("catalogue:item", args=[item.pk])).content.decode()
    assert "Tell me when it is available" in text
    client.post(reverse("market:wait", args=[item.pk]), {"quantity": "2"})
    assert WaitingListEntry.objects.get().quantity == 2
    assert "You are on the waiting list for 2" in client.get(reverse("catalogue:item", args=[item.pk])).content.decode()


# --- bought from outside ---


def test_a_purchase_need_shows_under_bought_from_outside_with_its_euros(world, client):
    PurchaseNeed.objects.create(
        unit=world.bakery_unit,
        item=cat.Item.objects.get(name="Salt"),
        month=services.today().replace(day=1),
        quantity=D(100),
        euro_estimate=D(60),
    )
    text = board(client)
    assert "Bought from outside" in text and "Salt" in text
    assert "€20.00 a month" in text and "in 1 unit." in text  # 60 euros over 3 months
    assert "not made in Unicorn" in text  # salt is a placeholder: nobody makes it yet


def test_old_purchase_needs_drop_off_the_board(world, client):
    PurchaseNeed.objects.create(
        unit=world.bakery_unit,
        item=cat.Item.objects.get(name="Salt"),
        month=date(2025, 1, 1),
        quantity=D(1),
        euro_estimate=D(1),
    )
    assert "Unicorn buys nothing from outside" in board(client)


# --- searches that found nothing ---


def test_search_miss_never_stores_a_member():
    assert "member" not in {f.name for f in SearchMiss._meta.get_fields()}
    assert not any(
        f.related_model and f.related_model.__name__ == "Member" for f in SearchMiss._meta.get_fields() if f.is_relation
    )


def test_only_searches_with_no_result_are_counted_by_area(world, client):
    me = member_with("me@x.org", "04109")
    client.force_login(me.user)
    client.get(reverse("market:index"), {"q": "bread"})  # found
    assert not SearchMiss.objects.exists()
    client.get(reverse("market:index"), {"q": "  Zebra   Saddle "})
    client.get(reverse("market:index"), {"q": "zebra saddle"})
    row = SearchMiss.objects.get()
    assert (row.area, row.text, row.count) == ("04", "zebra saddle", 2)
    client.logout()
    client.get(reverse("market:index"), {"q": "unicorn horn"})  # nobody is known: not counted
    assert SearchMiss.objects.count() == 1


def test_missing_near_you_shows_the_members_own_area_only(client):
    needs.record_search_miss(member_with("a@x.org", "04109"), "violin repair")
    needs.record_search_miss(member_with("b@x.org", "80331"), "tuba lessons")
    client.force_login(member_with("c@x.org", "04275").user)
    text = board(client)
    assert "violin repair" in text and "tuba lessons" not in text


# --- the monthly signals ---


def order_rows(offer, buyer, quantity, when):
    with freeze_time(when):
        order = Order.objects.create(buyer=buyer)
        OrderLine.objects.create(order=order, offer=offer, quantity=quantity, price_uniq=D(1), total_uniq=D(1))


def made(offer, quantity, when):
    ProductionOrder.objects.create(
        offer=offer, quantity=quantity, status="done", due_date=when.date(), done_at=when, quantity_done=quantity
    )


def test_demand_above_supply_for_two_months_tells_the_council_and_marks_the_item_wanted(world, client):
    buyer = world.buyer()
    for month in (3, 4):
        order_rows(world.bread, buyer, 20, datetime(2026, month, 10, 12))
        made(world.bread, 10, datetime(2026, month, 12, 12, tzinfo=services.BERLIN))
    with freeze_time("2026-05-02 12:00:00"):
        needs.run_demand_signals(date(2026, 3, 1))
        assert not DemandSignal.objects.get(month=date(2026, 3, 1)).flag  # one month is not enough
        mail.outbox.clear()
        needs.run_demand_signals(date(2026, 4, 1))
        needs.run_demand_signals(date(2026, 4, 1))  # safe to run twice
    signal = DemandSignal.objects.get(month=date(2026, 4, 1))
    assert signal.ratio == D("2.0000") and signal.flag == "wanted"
    assert [m.subject for m in mail.outbox if "want more" in m.subject] == ["Members want more Bread"]
    assert "larger batch or weekly plan" in mail.outbox[-1].body
    assert AuditEvent.objects.filter(verb="demand.wanted").count() == 1
    with freeze_time("2026-05-02 12:00:00"):
        text = board(client)
    assert "Wanted now" in text and "Bread" in text and "wanted</span>" in text


def test_demand_below_supply_for_two_months_suggests_making_less(world):
    buyer = world.buyer()
    for month in (3, 4):
        order_rows(world.bread, buyer, 5, datetime(2026, month, 10, 12))
        made(world.bread, 10, datetime(2026, month, 12, 12, tzinfo=services.BERLIN))
    with freeze_time("2026-05-02 12:00:00"):
        needs.run_demand_signals(date(2026, 3, 1))
        needs.run_demand_signals(date(2026, 4, 1))
    assert DemandSignal.objects.get(month=date(2026, 4, 1)).flag == "less"
    assert any("less" in m.subject for m in mail.outbox)


def test_demand_in_balance_makes_no_noise(world):
    buyer = world.buyer()
    for month in (3, 4):
        order_rows(world.bread, buyer, 10, datetime(2026, month, 10, 12))
        made(world.bread, 10, datetime(2026, month, 12, 12, tzinfo=services.BERLIN))
    mail.outbox.clear()
    with freeze_time("2026-05-02 12:00:00"):
        needs.run_demand_signals(date(2026, 3, 1))
        needs.run_demand_signals(date(2026, 4, 1))
    assert not DemandSignal.objects.exclude(flag="").exists() and not mail.outbox


# --- what matches my skills, and "I can make this" ---


def test_needs_that_match_my_skills_and_i_can_make_this(world, client):
    item = honey()
    needs.join_waiting_list(member_with("a@x.org"), item, 2)
    me = member_with("me@x.org")
    Skill.objects.create(member=me, trade_name="Beekeeping", trade_code="CPA_A01")
    client.force_login(me.user)
    text = board(client)
    assert "Needs that match your skills" in text
    assert "/units/open/?item=" in text  # no unit yet: open one for it
    client.force_login(world.baker.user)
    text = board(client)
    assert f"/units/bakery/offers/new/?item={item.pk}" in text and "I can make this in Bakery" in text
    assert "Needs that match your skills" not in text  # the baker has no such skill


def test_the_plan_focus_section_is_empty_until_a_plan_has_a_focus(client):
    assert "The yearly plan has no focus yet." in board(client)


def test_the_plan_focus_section_lists_the_running_plans_focus(client):
    from apps.plan.tests.conftest import running_plan

    running_plan(focus=["R-1"])
    assert "Focus" in board(client)


# --- a new offer fills a need ---


def test_publishing_an_offer_for_a_wanted_item_thanks_the_maker_and_tells_the_waiting(client):
    waiting = member_with("a@x.org")
    item = honey()
    needs.join_waiting_list(waiting, item, 2)
    seen = []
    hooks.RECOGNITION_HANDLERS.append(lambda member, kind, obj: seen.append((member, kind, obj)))
    try:
        maker = make_member("bee@x.org", "Bee")
        unit = unit_for(maker, "bees")
        offer = cat.create_offer(maker, unit, item, batch_size=D(10), direct_minutes_per_batch=300)
        mail.outbox.clear()
        cat.publish_offer(offer, maker)
    finally:
        hooks.RECOGNITION_HANDLERS.clear()
    assert seen == [(maker, "filled_need", item)]
    assert WaitingListEntry.objects.get().fulfilled_at is not None
    assert any("is available now" in m.subject for m in mail.outbox)


def test_a_placeholder_made_for_the_first_time_counts_as_a_filled_need(world):
    seen = []
    hooks.RECOGNITION_HANDLERS.append(lambda member, kind, obj: seen.append(kind))
    try:
        salt = cat.Item.objects.get(name="Salt")
        maker = make_member("salt@x.org", "Salter")
        offer = cat.create_offer(
            maker, unit_for(maker, "saltworks"), salt, batch_size=D(10), direct_minutes_per_batch=60
        )
        cat.publish_offer(offer, maker)
    finally:
        hooks.RECOGNITION_HANDLERS.clear()
    assert seen == ["filled_need"]


def test_an_ordinary_offer_is_not_a_filled_need():
    seen = []
    hooks.RECOGNITION_HANDLERS.append(lambda member, kind, obj: seen.append(kind))
    try:
        World()
    finally:
        hooks.RECOGNITION_HANDLERS.clear()
    assert seen == []


# --- HF-10 ---


def test_hf10_needs_board_assigns_nothing(world, client):
    """Looking at the board, joining a waiting list, missing searches and the signals create no work for anyone."""
    tables = (HoursEntry, Order, OrderLine, ProductionOrder, CouncilDecision)
    before = {t: t.objects.count() for t in tables}
    item = honey()
    me = member_with("me@x.org")
    client.force_login(me.user)
    needs.join_waiting_list(me, item, 3)
    needs.record_search_miss(me, "tuba")
    for month in (3, 4):
        order_rows(world.bread, me, 20, datetime(2026, month, 10, 12))
    with freeze_time("2026-05-02 12:00:00"):
        needs.run_demand_signals(date(2026, 3, 1))
        needs.run_demand_signals(date(2026, 4, 1))
        board(client)
    after = {t: t.objects.count() for t in tables}
    assert after[HoursEntry] == before[HoursEntry] and after[ProductionOrder] == before[ProductionOrder]
    assert after[CouncilDecision] == before[CouncilDecision]
    assert after[Order] == before[Order] + 2 and after[OrderLine] == before[OrderLine] + 2  # only my own test rows
    assert DemandSignal.objects.exists()
