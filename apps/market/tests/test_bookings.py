from datetime import UTC, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from freezegun import freeze_time

from apps.core.models import AuditEvent
from apps.ledger import services as ledger
from apps.market import services
from apps.market.models import Booking, StockLot
from apps.market.tests.conftest import ServiceWorld, World
from apps.rules.models import Parameter
from apps.units.models import HoursEntry

pytestmark = pytest.mark.django_db
D = Decimal


def performed(salon, customer=None, days=1):
    """A booked session that has happened and was marked performed."""
    customer = customer or salon.customer()
    slot = salon.slot(days=days)
    booking = services.book(customer, slot)
    with freeze_time(timezone.now() + timedelta(days=days, hours=3)):
        services.mark_performed(slot, salon.provider)
    booking.refresh_from_db()
    return customer, slot, booking


def test_booking_holds_the_price_and_takes_a_seat(salon):
    customer = salon.customer()
    slot = salon.slot()
    booking = services.book(customer, slot)
    slot.refresh_from_db()
    assert booking.price_uniq == D("1.0000") and booking.hold.amount == D("1.0000")
    assert slot.capacity_left == 0 and slot.status == "full"
    assert ledger.available(ledger.member_account(customer)) == D(9)
    with pytest.raises(services.MarketError, match="cannot be booked"):
        services.book(salon.customer("b@x.org"), slot)


def test_confirming_pays_the_provider_once_per_slot():
    room = ServiceWorld(capacity=2, duration=60, travel=0, place="unit")
    slot = room.slot()
    a, b = room.customer("a@x.org"), room.customer("b@x.org")
    first, second = services.book(a, slot), services.book(b, slot)
    with freeze_time(timezone.now() + timedelta(days=1, hours=3)):
        services.mark_performed(slot, room.provider)
    services.confirm_performed(first, a)
    services.confirm_performed(second, b)
    entries = HoursEntry.objects.filter(activity="booking")
    assert entries.count() == 1  # one session, paid once
    entry = entries.get()
    assert entry.minutes == 60 and entry.ref_type == "slot" and entry.ref_id == str(slot.pk) and entry.status == "paid"
    assert Booking.objects.filter(status="confirmed").count() == 2
    slot.refresh_from_db()
    assert slot.hours_entry == entry and slot.idle_minutes == 0
    fund1 = ledger.balance(ledger.fund1())
    assert fund1 == D(2) * room.offer.value_total


def test_a_group_session_with_empty_seats_is_paid_and_the_empty_share_is_idle_time():
    room = ServiceWorld(capacity=4, duration=60, travel=0, place="unit")
    slot = room.slot()
    a = room.customer("a@x.org")
    booking = services.book(a, slot)
    with freeze_time(timezone.now() + timedelta(days=1, hours=3)):
        services.mark_performed(slot, room.provider)
    services.confirm_performed(booking, a)
    slot.refresh_from_db()
    assert HoursEntry.objects.get().minutes == 60  # the whole session is paid
    assert slot.idle_minutes == 45  # 3 of 4 seats were empty


def test_the_haircut_pays_the_hairdresser_an_hour_with_the_trip(salon):
    customer, slot, booking = performed(salon)
    services.confirm_performed(booking, customer)
    entry = HoursEntry.objects.get()
    assert entry.minutes == 60  # 40 minutes and 20 of travel: 1.00 UNIQ gross
    gross = ledger.Entry.objects.filter(
        transaction__kind="hours_pay", amount__gt=0, account=ledger.member_account(salon.provider)
    ).get()
    assert gross.amount == D("1.0000")
    assert ledger.balance(ledger.fund1()) == D("1.0000")
    assert ledger.balance(ledger.member_account(customer)) == D(9)


def test_nothing_is_paid_before_the_customer_confirms(salon):
    customer, slot, booking = performed(salon)
    assert booking.status == "performed" and booking.hold.status == "active"
    assert not HoursEntry.objects.exists() and ledger.balance(ledger.fund1()) == 0


def test_a_no_show_pays_nothing(salon):
    customer = salon.customer()
    slot = salon.slot()
    booking = services.book(customer, slot)
    with freeze_time(timezone.now() + timedelta(days=1, hours=3)):
        services.mark_no_show(booking, salon.provider)
        services.mark_performed(slot, salon.provider)
    booking.refresh_from_db()
    assert booking.status == "no_show" and booking.hold.status == "released"
    assert not HoursEntry.objects.exists() and ledger.balance(ledger.fund1()) == 0
    assert ledger.available(ledger.member_account(customer)) == D(10)
    assert services.no_show_count(customer) == 1


def test_a_no_show_can_be_paid_if_the_members_decide_so(salon):
    Parameter.objects.filter(key="economy.services.no_show_paid").update(value=True)
    customer = salon.customer()
    slot = salon.slot()
    booking = services.book(customer, slot)
    with freeze_time(timezone.now() + timedelta(days=1, hours=3)):
        services.mark_no_show(booking, salon.provider)
    assert HoursEntry.objects.get().minutes == 60


def test_a_social_service_costs_the_customer_nothing_but_pays_the_provider():
    clinic = ServiceWorld(kind="social", email="care@x.org")
    customer = clinic.customer()
    slot = clinic.slot()
    booking = services.book(customer, slot)
    assert booking.hold is None and booking.price_uniq == clinic.offer.value_total
    with freeze_time(timezone.now() + timedelta(days=1, hours=3)):
        services.mark_performed(slot, clinic.provider)
    services.confirm_performed(Booking.objects.get(), customer)
    assert ledger.balance(ledger.member_account(customer)) == D(10)  # nothing was charged
    assert ledger.balance(ledger.fund1()) == 0
    assert HoursEntry.objects.get().status == "paid"  # the provider is paid from the social share


def test_hf09_services_cannot_be_stored(salon):
    with pytest.raises(services.MarketError, match="cannot be stored"):
        services.make_lot(salon.offer, D(1), "advance")
    with pytest.raises(ValueError):
        StockLot(offer=salon.offer, quantity=1, quantity_left=1, made_at=timezone.now(), origin="advance").save()
    with pytest.raises(services.MarketError):
        services.start_advance(salon.offer, 1, salon.provider, estimate=100)
    assert not StockLot.objects.exists()


def test_the_other_pay_rules_are_not_built_yet(salon):
    Parameter.objects.filter(key="economy.services.pay_rule").update(value="planned_shifts")
    with pytest.raises(NotImplementedError, match="phase_16_later"):
        services.book(salon.customer(), salon.slot())


def test_auto_confirm_after_48_hours(salon):
    customer, slot, booking = performed(salon)
    performed_at = booking.performed_at
    with freeze_time(performed_at + timedelta(hours=47)):
        assert services.auto_confirm_bookings() == 0
    with freeze_time(performed_at + timedelta(hours=49)):
        assert services.auto_confirm_bookings() == 1
        assert services.auto_confirm_bookings() == 0
    booking.refresh_from_db()
    assert booking.status == "confirmed" and HoursEntry.objects.count() == 1
    assert AuditEvent.objects.filter(verb="booking.confirmed", actor_ref="system").exists()


def test_a_dispute_stops_the_auto_confirm_and_keeps_the_hold(salon):
    customer, slot, booking = performed(salon)
    services.dispute_booking(booking, customer, "Nobody came to my door")
    with freeze_time(booking.performed_at + timedelta(hours=60)):
        assert services.auto_confirm_bookings() == 0
    booking.refresh_from_db()
    assert booking.status == "disputed" and booking.hold.status == "active"
    assert not HoursEntry.objects.exists()
    services.confirm_performed(booking, customer)  # an agreement afterwards still pays
    assert HoursEntry.objects.count() == 1


def test_only_the_customer_confirms_and_only_a_worker_marks_performed(salon):
    customer, slot, booking = performed(salon)
    with pytest.raises(services.MarketError, match="not your booking"):
        services.confirm_performed(booking, salon.provider)
    other = salon.slot(days=3)
    with pytest.raises(services.MarketError, match="work in this unit"):
        services.mark_performed(other, customer)
    with pytest.raises(services.MarketError, match="not happened yet"):
        services.mark_performed(other, salon.provider)


def test_the_customer_is_asked_to_confirm(salon):
    mail.outbox.clear()
    performed(salon)
    assert any("confirm your" in m.subject for m in mail.outbox)


def test_cancelling_a_booking_frees_the_seat_and_the_hold(salon):
    customer = salon.customer()
    slot = salon.slot()
    booking = services.book(customer, slot)
    services.cancel_booking(booking, customer)
    slot.refresh_from_db()
    booking.refresh_from_db()
    assert booking.status == "cancelled" and booking.hold.status == "released"
    assert slot.status == "open" and slot.capacity_left == 1
    assert ledger.available(ledger.member_account(customer)) == D(10)


def test_cancelling_a_slot_cancels_every_booking(salon):
    customer = salon.customer()
    slot = salon.slot()
    booking = services.book(customer, slot)
    services.cancel_slot(slot, salon.provider)
    booking.refresh_from_db()
    assert booking.status == "cancelled" and booking.hold.status == "released"


def test_booking_rules(salon):
    slot = salon.slot()
    with pytest.raises(services.MarketError, match="own session"):
        services.book(salon.provider, slot)
    poor = salon.customer("poor@x.org", uniq=D("0.5"))
    with pytest.raises(services.MarketError, match="Not enough UNIQ available"):
        services.book(poor, slot)
    customer = salon.customer()
    services.book(customer, slot)
    with freeze_time(timezone.now() + timedelta(days=2)):
        with pytest.raises(services.MarketError, match="cannot be booked"):
            services.book(salon.customer("late@x.org"), slot)


def test_weekly_slots_keep_their_local_time_across_the_clock_change(salon):
    with freeze_time("2026-03-10 09:00:00"):
        start = timezone.now().astimezone(services.BERLIN).replace(day=17, hour=10, minute=0, second=0, microsecond=0)
        slots = services.create_weekly_slots(salon.provider, salon.offer, start, 8)
    assert len(slots) == 8
    assert {s.starts_at.astimezone(services.BERLIN).hour for s in slots} == {10}
    assert {s.starts_at.astimezone(services.BERLIN).weekday() for s in slots} == {1}  # always a Tuesday
    assert len({s.starts_at.astimezone(UTC).hour for s in slots}) == 2  # the UTC hour changed on 29 March


def test_a_provider_cannot_offer_two_sessions_at_once_or_too_many_a_week(salon):
    slot = salon.slot()
    with pytest.raises(services.MarketError, match="another session"):
        services.create_slot(salon.provider, salon.offer, slot.starts_at + timedelta(minutes=10))
    salon.offer.max_per_week = 1
    salon.offer.save()
    with pytest.raises(services.MarketError, match="at most 1 times a week"):
        services.create_slot(salon.provider, salon.offer, slot.starts_at + timedelta(hours=5))


def test_the_world_of_bread_has_no_service_slots():
    world = World()
    with pytest.raises(services.MarketError, match="active service"):
        services.create_slot(world.baker, world.bread, timezone.now() + timedelta(days=1))
