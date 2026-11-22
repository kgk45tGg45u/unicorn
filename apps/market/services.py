"""Orders, production, stock, delivery and bookings (docs/06 sections 4 to 7)."""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalogue import services as catalogue
from apps.core import audit
from apps.core.money import uniq
from apps.ledger import services as ledger
from apps.rules.services import get_param
from apps.units import services as unit_services

from .models import Order, OrderLine

BERLIN = ZoneInfo("Europe/Berlin")


class MarketError(ValueError):
    """A plain-words reason why something cannot be done."""


def today():
    return timezone.now().astimezone(BERLIN).date()


def _month_start(day):
    return day.replace(day=1)


def _lock_line(line):
    return (
        OrderLine.objects.select_for_update()
        .select_related("offer__unit", "offer__item", "order__buyer")
        .get(pk=line.pk)
    )


# --- Placing and cancelling an order ---


def can_buy(member) -> bool:
    """Members and former members may spend their UNIQ (HF-8); applicants and suspended members may not."""
    return member.status in ("member", "former") and not member.deleted


def _ordered_this_month(member, item):
    from django.db.models import Sum

    first = _month_start(today())
    start = datetime(first.year, first.month, 1, tzinfo=BERLIN)
    total = (
        OrderLine.objects.filter(order__buyer=member, offer__item=item, created_at__gte=start)
        .exclude(status="cancelled")
        .aggregate(t=Sum("quantity"))["t"]
    )
    return total or Decimal("0")


def place_order(member, offer, quantity, note="") -> OrderLine:
    """Order a product: the UNIQ are held at today's price, then the line goes to the shelf or into production."""
    from apps.macro import lights

    try:
        quantity = Decimal(str(quantity))
    except (InvalidOperation, ValueError, TypeError):
        raise MarketError(_("Please enter how many you want.")) from None
    if quantity <= 0 or quantity != quantity.quantize(Decimal("0.0001")):
        raise MarketError(_("Please enter how many you want."))
    if not can_buy(member):
        raise MarketError(_("Only members can order. Please finish joining first."))
    with transaction.atomic():
        offer = type(offer).objects.select_related("item", "unit").get(pk=offer.pk)
        if offer.status != "active" or offer.unit.status not in ("trial", "open"):
            raise MarketError(_("This offer is not available now."))
        if offer.is_service:
            raise MarketError(_("A service is booked, not ordered."))
        if offer.values_computed_at is None or offer.value_total <= 0:
            raise MarketError(_("This offer has no price yet."))
        if lights.item_red(offer.item):
            cap = get_param("market.shortage_cap_per_member")
            if _ordered_this_month(member, offer.item) + quantity > cap:
                raise MarketError(
                    _(
                        "This item is short at the moment, so each member can order at most %(cap)s a month "
                        "to share it fairly."
                    )
                    % {"cap": cap}
                )
        price = offer.value_total  # HF-3: the engine's value, never set by hand
        total = uniq(price * quantity)
        if total <= 0:
            raise MarketError(_("This order is too small to price."))
        order = Order.objects.create(buyer=member, note=note[:300])
        line = OrderLine.objects.create(
            order=order,
            offer=offer,
            quantity=quantity,
            price_uniq=price,
            total_uniq=total,
            due_date=today() + timedelta(days=catalogue.lead_time_days(offer)),
        )
        try:
            line.hold = ledger.place_hold(
                member,
                total,
                _("Order of %(qty)s %(item)s from %(unit)s")
                % {"qty": quantity.normalize(), "item": offer.item.name, "unit": offer.unit.name},
                ref=line,
            )
        except ledger.LedgerError:
            raise MarketError(_("Not enough UNIQ available")) from None
        line.save(update_fields=["hold"])
        audit.record(member.number, "order.placed", line, offer=offer.pk, total=str(total))
        unit_services.touch(offer.unit)
        _fulfil(line)
        line.refresh_from_db()
        return line


def _fulfil(line):
    """Serve a new line from the shelf, or put it into a production order. Filled in by P05.T02 and P05.T04."""


def _free_cancel_allowed(line) -> bool:
    rule = get_param("economy.products.cancel_rule")
    if line.status in (OrderLine.PLACED, OrderLine.FROM_STOCK):
        return True
    if rule == "free_until_delivery":
        return line.status in (OrderLine.IN_PRODUCTION, OrderLine.READY)
    return (
        line.status == OrderLine.IN_PRODUCTION and line.production_order_id and line.production_order.status == "open"
    )


def cancel_line(line, member):
    """Cancel an order line for free while its batch has not started. The hold is released."""
    with transaction.atomic():
        line = _lock_line(line)
        if line.order.buyer_id != member.pk:
            raise MarketError(_("This is not your order."))
        if line.status == OrderLine.CANCELLED:
            return line
        if not _free_cancel_allowed(line):
            raise MarketError(_("This order is already being made"))
        _unassign(line)
        line.status = OrderLine.CANCELLED
        line.save(update_fields=["status"])
        if line.hold_id:
            ledger.release_hold(line.hold, _("Order cancelled by the buyer"))
        audit.record(member.number, "order.cancelled", line)
        return line


def _unassign(line):
    """Take a line out of its production order or off the shelf. Filled in by P05.T02."""
