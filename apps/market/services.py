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

from .models import Order, OrderLine, ProductionOrder, WeeklyPlan

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
    """Serve a new line from the shelf, or put it into a production order."""
    assign_to_batch(line)


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
    """Take a line out of its production order. An empty open batch made only for orders is cancelled."""
    po_id = line.production_order_id
    if po_id is None:
        return
    po = ProductionOrder.objects.select_for_update().get(pk=po_id)
    po.quantity_assigned = max(Decimal("0"), po.quantity_assigned - line.quantity)
    if po.week_start is None and po.origin in SHARED_ORIGINS:
        po.quantity = max(Decimal("0"), po.quantity - line.quantity)
    if po.status == "open" and po.week_start is None and po.origin in SHARED_ORIGINS and po.quantity <= 0:
        po.status = "cancelled"
    po.save(update_fields=["quantity_assigned", "quantity", "status"])
    line.production_order = None
    line.save(update_fields=["production_order"])


# --- Production orders and batches ---

SHARED_ORIGINS = ("orders", "input_request")  # these share batches; made-ahead and own-initiative batches stand alone
WEEKS_AHEAD = 8


def batch_size(offer) -> Decimal:
    return offer.batch_size or Decimal("1")


def monday_of(day):
    return day - timedelta(days=day.weekday())


def current_weekly_plan(offer, week_start):
    return WeeklyPlan.objects.filter(offer=offer, valid_from__lte=week_start).order_by("-valid_from", "-id").first()


def _weekly_order(offer, quantity, due_date):
    """The week's production order with room for `quantity`, created from the weekly plan if missing."""
    first = monday_of(today())
    for i in range(WEEKS_AHEAD):
        week = first + timedelta(days=7 * i)
        end = week + timedelta(days=6)
        if end < due_date:
            continue
        plan = current_weekly_plan(offer, week)
        if plan is None:
            return None
        po = (
            ProductionOrder.objects.select_for_update()
            .filter(offer=offer, week_start=week, status__in=["open", "started", "done"])
            .first()
        )
        if po is None:
            po = ProductionOrder.objects.create(
                offer=offer, quantity=plan.quantity_per_week, origin="orders", due_date=end, week_start=week
            )
        if po.status == "open" and po.quantity - po.quantity_assigned >= quantity:
            return po
    return None


def _shared_batch(offer, quantity, due_date):
    """An open batch that is only partly filled and is due soon enough, or a new one."""
    b = batch_size(offer)
    candidates = ProductionOrder.objects.select_for_update().filter(
        offer=offer,
        status="open",
        origin__in=SHARED_ORIGINS,
        week_start__isnull=True,
        due_date__lte=due_date + timedelta(days=7),
    )
    for po in candidates.order_by("due_date", "id"):
        if po.quantity % b != 0:
            return po
    return ProductionOrder.objects.create(offer=offer, quantity=0, due_date=due_date)


def assign_quantity(offer, quantity, due_date, origin="orders") -> ProductionOrder:
    """Reserve `quantity` of an offer in a production order and return it. Caller holds the transaction."""
    po = None
    if offer.unit.mode == "continuous":
        po = _weekly_order(offer, quantity, due_date)
    if po is None:
        po = _shared_batch(offer, quantity, due_date)
        po.quantity += quantity
        if po.origin != origin and po.quantity == quantity:
            po.origin = origin
    po.quantity_assigned += quantity
    po.save(update_fields=["quantity", "quantity_assigned", "origin"])
    explode(po)
    return po


def assign_to_batch(line):
    """Put an order line into a batch (this week's order of a continuous unit, or a shared batch)."""
    with transaction.atomic():
        line = _lock_line(line)
        po = assign_quantity(line.offer, line.quantity, line.due_date or today())
        line.production_order = po
        line.status = OrderLine.IN_PRODUCTION
        if line.due_date is None or po.due_date > line.due_date:
            line.due_date = po.due_date  # the member sees the date the batch will really be ready
        line.save(update_fields=["production_order", "status", "due_date"])
        unit_services.touch(line.offer.unit)
        return line


def explode(po):
    """Order the inputs a production order needs down the chain. Built in P05.T03."""


def _need_worker(member, unit):
    if not unit_services.is_worker(member, unit):
        raise MarketError(_("Only people who work in this unit can do this."))


def start_production(po, member):
    with transaction.atomic():
        po = ProductionOrder.objects.select_for_update().select_related("offer__unit").get(pk=po.pk)
        _need_worker(member, po.offer.unit)
        if po.status != "open":
            raise MarketError(_("This batch has already been started."))
        po.status = "started"
        po.started_at = timezone.now()
        po.save(update_fields=["status", "started_at"])
        audit.record(member.number, "production.started", po)
        unit_services.touch(po.offer.unit)
        return po


def _notify_ready(line):
    unit_services._notify(
        line.order.buyer,
        _("Your %(item)s is ready") % {"item": line.offer.item.name},
        _("%(qty)s %(item)s from %(unit)s is ready. You can collect it now.")
        % {"qty": line.quantity.normalize(), "item": line.offer.item.name, "unit": line.offer.unit.name},
    )


def _input_quantity(po) -> Decimal:
    """What a batch has promised to other units as inputs. Built in P05.T03."""
    return Decimal("0")


def _stock_remainder(po, remainder):
    """The part of a batch nobody ordered goes to the shelf. Built in P05.T04."""


def complete_production(po, member, quantity_done):
    """A batch is done: lines are served in the order placed, the rest goes to the shelf."""
    try:
        quantity_done = Decimal(str(quantity_done))
    except (InvalidOperation, ValueError, TypeError):
        raise MarketError(_("Please enter how many were made.")) from None
    if quantity_done < 0:
        raise MarketError(_("Please enter how many were made."))
    with transaction.atomic():
        po = ProductionOrder.objects.select_for_update().select_related("offer__unit").get(pk=po.pk)
        _need_worker(member, po.offer.unit)
        if po.status != "started":
            raise MarketError(_("Start the batch first."))
        left = quantity_done - _input_quantity(po)
        short = []
        for line in po.lines.select_for_update().filter(status=OrderLine.IN_PRODUCTION).order_by("created_at", "id"):
            if left >= line.quantity:
                left -= line.quantity
                line.status = OrderLine.READY
                line.save(update_fields=["status"])
                _notify_ready(line)
            else:
                short.append(line)
        po.status = "done"
        po.done_at = timezone.now()
        po.quantity_done = quantity_done
        po.save(update_fields=["status", "done_at", "quantity_done"])
        for line in short:  # not enough was made: these lines wait for the next batch
            po.quantity_assigned -= line.quantity
            line.production_order = None
            line.save(update_fields=["production_order"])
            assign_to_batch(line)
        po.save(update_fields=["quantity_assigned"])
        if left > 0:
            _stock_remainder(po, left)
        audit.record(member.number, "production.done", po, made=str(quantity_done))
        unit_services.touch(po.offer.unit)
        return po


def record_production_hours(member, po, date, minutes, note=""):
    """Hours a worker spent on a batch. Own-initiative batches are paid only as they sell (P05.T04)."""
    _need_worker(member, po.offer.unit)
    activity = "own_initiative" if po.origin == "own_initiative" else "order"
    try:
        return unit_services.record_hours(
            member,
            po.offer.unit,
            date,
            minutes,
            activity=activity,
            note=note or _("Production order %(id)s") % {"id": po.pk},
            ref_type="production_order",
            ref_id=po.pk,
        )
    except unit_services.UnitError as e:
        raise MarketError(str(e)) from None


# --- The weekly plan of a continuous unit ---


def set_weekly_plan(member, offer, quantity_per_week, reason):
    """A council decision (at once in a one-person unit) sets how much a continuous unit makes each week."""
    try:
        quantity = Decimal(str(quantity_per_week))
    except (InvalidOperation, ValueError, TypeError):
        raise MarketError(_("Please enter a quantity per week.")) from None
    if quantity <= 0:
        raise MarketError(_("Please enter a quantity per week."))
    if not (reason or "").strip():
        raise MarketError(_("Please write why."))
    if offer.unit.mode != "continuous":
        raise MarketError(_("Only a continuous unit has a weekly plan."))
    try:
        return unit_services.open_decision(
            member,
            offer.unit,
            _("Weekly plan: %(qty)s %(item)s") % {"qty": quantity.normalize(), "item": offer.item.name},
            text=reason.strip(),
            kind="production",
            payload={"weekly_plan": {"offer": offer.pk, "quantity": str(quantity)}},
        )
    except unit_services.UnitError as e:
        raise MarketError(str(e)) from None


_previous_production_action = unit_services.DECISION_ACTIONS.get("production")


def _production_decision_action(decision):
    if _previous_production_action is not None:
        _previous_production_action(decision)
    plan = (decision.payload or {}).get("weekly_plan")
    if plan:
        offer = catalogue.Offer.objects.filter(pk=plan["offer"], unit=decision.unit).first()
        if offer is not None:
            WeeklyPlan.objects.create(
                offer=offer, quantity_per_week=Decimal(plan["quantity"]), set_by=decision, valid_from=today()
            )
            audit.record("system", "production.weekly_plan_set", offer, quantity=plan["quantity"])


unit_services.DECISION_ACTIONS["production"] = _production_decision_action
