"""Orders, production, stock, delivery and bookings (docs/06 sections 4 to 7)."""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalogue import services as catalogue
from apps.core import audit
from apps.core.jobs import enqueue
from apps.core.money import uniq
from apps.ledger import services as ledger
from apps.rules.services import get_param
from apps.units import services as unit_services

from .models import (
    Booking,
    InputRequest,
    Order,
    OrderLine,
    ProductionOrder,
    PurchaseNeed,
    Review,
    Sale,
    ServiceSlot,
    StandingOrder,
    StockLot,
    WasteRecord,
    WeeklyPlan,
)

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
    lot = _lot_for(line.offer, line.quantity)
    if lot is not None:
        line.stock_lot = lot
        line.status = OrderLine.FROM_STOCK
        line.due_date = today()
        line.save(update_fields=["stock_lot", "status", "due_date"])
        return
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
    """Take a line out of its production order."""
    po_id = line.production_order_id
    if po_id is None:
        return
    _release(po_id, line.quantity)
    line.production_order = None
    line.save(update_fields=["production_order"])


def _release(po_id, quantity):
    """Give back `quantity` of a production order. An open batch shrinks; one that has started is made anyway."""
    po = ProductionOrder.objects.select_for_update().get(pk=po_id)
    po.quantity_assigned = max(Decimal("0"), po.quantity_assigned - quantity)
    if po.status == "open" and po.week_start is None and po.origin in SHARED_ORIGINS:
        po.quantity = max(Decimal("0"), po.quantity - quantity)
        if po.quantity <= 0:
            po.status = "cancelled"
    po.save(update_fields=["quantity_assigned", "quantity", "status"])
    if po.status in ("open", "cancelled"):
        _shrink_inputs(po)


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


def assign_quantity(offer, quantity, due_date, origin="orders", _depth=0) -> ProductionOrder:
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
    explode(po, _depth)
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


MAX_CHAIN_DEPTH = 10


def _inputs_needed(po, row) -> Decimal:
    return row.quantity_per_batch * (po.quantity / batch_size(po.offer))


def _live_requests(po, row):
    return po.input_requests.exclude(status="cancelled").filter(offer_input=row)


def _pick_supplier(row, consumer):
    """The preferred supplier; else an active offer in the same town; else the one with the fewest open batches."""
    from django.db.models import Count, Q

    if row.preferred_supplier_id and row.preferred_supplier.status == "active":
        return row.preferred_supplier
    offers = (
        catalogue.Offer.objects.filter(item=row.item, status="active", unit__status__in=["trial", "open"])
        .select_related("unit")
        .annotate(open_batches=Count("production_orders", filter=Q(production_orders__status__in=["open", "started"])))
    )
    town = (consumer.unit.town or "").strip().lower()
    nearby = [o for o in offers if town and (o.unit.town or "").strip().lower() == town]
    pool = nearby or list(offers)
    return min(pool, key=lambda o: (o.open_batches, o.pk), default=None)


def _purchase_need_for(po, row, due):
    month = catalogue.first_of_month(due - timedelta(days=get_param("market.outside_input_days")))
    need = (
        PurchaseNeed.objects.select_for_update()
        .filter(unit=po.offer.unit, item=row.item, month=month, status="open", currency=row.currency)
        .first()
    )
    if need is None:
        need = PurchaseNeed.objects.create(unit=po.offer.unit, item=row.item, month=month, currency=row.currency)
        if month <= catalogue.first_of_month(timezone.localdate()):
            # due sooner than the outside-input days: the trade fund turns it into a request at once (P08.T07)
            from apps.core.jobs import enqueue

            enqueue("tradefund.purchase_lists", {}, dedupe_key=f"purchase-lists-need-{need.pk}")
    return need


def _refresh_need(need):
    from apps.core.money import cur

    live = list(need.requests.exclude(status="cancelled"))
    need.quantity = sum((r.quantity for r in live), Decimal("0"))
    need.euro_estimate = cur(sum((r.quantity * (r.euro_each or 0) for r in live), Decimal("0")))
    need.save(update_fields=["quantity", "euro_estimate"])


def explode(po, _depth=0):
    """Order the inputs a production order needs, down the chain (docs/04 section 8). No UNIQ move (HF-5).

    Runs whenever an order is created or grows; what earlier requests already cover is subtracted.
    """
    if po.status not in ("open", "started"):
        return
    if _depth >= MAX_CHAIN_DEPTH:
        audit.record("system", "input chain too deep", po, depth=_depth)
        return
    for row in po.offer.inputs.select_related("item", "preferred_supplier"):
        covered = sum((r.quantity for r in _live_requests(po, row)), Decimal("0"))
        extra = (_inputs_needed(po, row) - covered).quantize(Decimal("0.0001"))
        if extra <= 0:
            continue
        _request_input(po, row, extra, _depth)


def _request_input(po, row, quantity, depth):
    request = InputRequest(
        production_order=po,
        offer_input=row,
        item=row.item,
        quantity=quantity,
        source=row.source,
        currency=row.currency,
        due_date=po.due_date,
    )
    if row.source == "unicorn":
        supplier = _pick_supplier(row, po.offer)
        if supplier is None:
            audit.record("system", "input.no_supplier", po, item=row.item_id)
            request.due_date = po.due_date
            request.save()
            return
        request.supplier_offer = supplier
        request.due_date = max(today(), po.due_date - timedelta(days=catalogue.lead_time_days(supplier)))
        request.save()
        child = assign_quantity(supplier, quantity, request.due_date, "input_request", depth + 1)
        request.child_production_order = child
        request.save(update_fields=["child_production_order"])
    elif row.source == "own_free":
        request.provided_by = row.provided_by
        request.save()
    else:  # buy_outside: it goes onto the unit's purchase list for the month
        due = max(today(), po.due_date - timedelta(days=get_param("market.outside_input_days")))
        request.due_date = due
        request.euro_each = row.euro_price_estimate
        request.purchase_need = _purchase_need_for(po, row, po.due_date)
        request.save()
        _refresh_need(request.purchase_need)


def _shrink_inputs(po):
    """A batch got smaller or was cancelled: give back the inputs it no longer needs, newest first."""
    for row in po.offer.inputs.all():
        needed = _inputs_needed(po, row) if po.status != "cancelled" else Decimal("0")
        live = list(_live_requests(po, row).order_by("-id"))
        covered = sum((r.quantity for r in live), Decimal("0"))
        for request in live:
            if request.status in ("delivered", "received"):
                continue  # already in the unit's hands
            if covered - request.quantity < needed:
                break
            covered -= request.quantity
            _cancel_request(request)


def _cancel_request(request):
    request.status = "cancelled"
    request.save(update_fields=["status"])
    if request.child_production_order_id:
        _release(request.child_production_order_id, request.quantity)
    if request.purchase_need_id:
        _refresh_need(request.purchase_need)


# --- Handing inputs between units ---


def _lock_request(request):
    return InputRequest.objects.select_for_update().select_related("production_order__offer__unit").get(pk=request.pk)


def confirm_input(request, member):
    """The member who provides an input free confirms they will bring it."""
    with transaction.atomic():
        request = _lock_request(request)
        if request.source != "own_free" or request.provided_by_id != member.pk:
            raise MarketError(_("Only the member who provides this input can confirm it."))
        if request.status != "open":
            raise MarketError(_("This input was already answered."))
        request.status = "confirmed"
        request.save(update_fields=["status"])
        audit.record(member.number, "input.confirmed", request)
        return request


def mark_delivered(request, member):
    """The supplying unit says it has handed the input over."""
    with transaction.atomic():
        request = _lock_request(request)
        if request.source != "unicorn" or request.child_production_order_id is None:
            raise MarketError(_("This input is not made by another unit."))
        _need_worker(member, request.supplier_offer.unit)
        if request.status not in ("open", "confirmed"):
            raise MarketError(_("This input was already handed over or cancelled."))
        request.status = "delivered"
        request.delivered_at = timezone.now()
        request.save(update_fields=["status", "delivered_at"])
        audit.record(member.number, "input.delivered", request)
        unit_services.touch(request.supplier_offer.unit)
        return request


def mark_received(request, member):
    """The unit that needs the input says it arrived."""
    with transaction.atomic():
        request = _lock_request(request)
        _need_worker(member, request.production_order.offer.unit)
        ready = request.status == "delivered" or (request.source == "own_free" and request.status == "confirmed")
        if not ready:
            raise MarketError(_("This input has not been handed over yet."))
        request.status = "received"
        request.received_at = timezone.now()
        request.save(update_fields=["status", "received_at"])
        audit.record(member.number, "input.received", request)
        return request


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
    """What a batch has promised to other units as inputs."""
    from django.db.models import Sum

    total = po.serves_requests.exclude(status="cancelled").aggregate(t=Sum("quantity"))["t"]
    return total or Decimal("0")


def _stock_remainder(po, remainder):
    """The part of a batch nobody ordered goes to the shelf."""
    origin = "own_initiative" if po.origin == "own_initiative" else "advance"
    make_lot(po.offer, remainder, origin, po)


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


# --- Stock, made ahead, own initiative, written off (docs/06 section 5) ---

STOCK_RESERVING = ("from_stock", "handed_over")  # lines that have claimed a lot but not drawn it yet


def make_lot(offer, quantity, origin, po=None) -> StockLot:
    if offer.is_service:  # HF-9: a service is gone when its time has passed
        raise MarketError(_("A service cannot be stored."))
    now = timezone.now()
    days = offer.item.shelf_life_days
    lot = StockLot.objects.create(
        offer=offer,
        quantity=quantity,
        quantity_left=quantity,
        made_at=now,
        expires_at=now + timedelta(days=days) if days else None,
        origin=origin,
        production_order=po,
    )
    audit.record("system", "stock.lot_made", lot, quantity=str(quantity), origin=origin)
    return lot


def reserved(lot) -> Decimal:
    from django.db.models import Sum

    total = OrderLine.objects.filter(stock_lot=lot, status__in=STOCK_RESERVING).aggregate(t=Sum("quantity"))["t"]
    return total or Decimal("0")


def free_quantity(lot) -> Decimal:
    return lot.quantity_left - reserved(lot)


def _lot_for(offer, quantity):
    """The lot that will serve a line: first to expire first, and big enough for the whole line."""
    now = timezone.now()
    lots = StockLot.objects.select_for_update().filter(offer=offer, status="available", quantity_left__gt=0)
    lots = [lot for lot in lots if lot.expires_at is None or lot.expires_at > now]
    lots.sort(key=lambda lot: (lot.expires_at is None, lot.expires_at or lot.made_at, lot.pk))
    return next((lot for lot in lots if free_quantity(lot) >= quantity), None)


def draw_stock(lot, quantity):
    """A sale takes `quantity` off the shelf. Own-initiative lots then pay out their pending hours."""
    lot = StockLot.objects.select_for_update().get(pk=lot.pk)
    if quantity > lot.quantity_left:
        raise MarketError(_("There is not enough on the shelf."))
    lot.quantity_left -= quantity
    if lot.quantity_left <= 0:
        lot.status = "sold_out"
    lot.save(update_fields=["quantity_left", "status"])
    if lot.origin == "own_initiative":
        pay_pending_sale(lot, quantity)
    return lot


def pay_pending_sale(lot, units_sold):
    """Pay own-initiative hours pro rata as the products sell (HF-9: the mixed rule).

    Each pending entry has been paid `paid_fraction` of its hours; it is now owed the sold share of the lot.
    When the lot is sold out, the rounding remainder is paid too.
    """
    from django.db.models import Sum

    from apps.core.money import minutes_to_uniq
    from apps.ledger.models import Entry
    from apps.units.models import HoursEntry

    if lot.production_order_id is None:
        return
    sold_share = (lot.quantity - lot.quantity_left) / lot.quantity
    period = ledger.current_period()
    entries = HoursEntry.objects.select_for_update().filter(
        ref_type="production_order", ref_id=str(lot.production_order_id), status="pending_sale"
    )
    for entry in entries:
        total = minutes_to_uniq(entry.minutes)
        account = ledger.member_account(entry.member)
        paid = Entry.objects.filter(
            transaction__kind="hours_pay",
            transaction__ref_type="hoursentry",
            transaction__ref_id=str(entry.pk),
            account=account,
        ).aggregate(t=Sum("amount"))["t"] or Decimal("0")
        due = total if lot.status == "sold_out" else uniq(total * sold_share)
        gross = min(due, total) - paid
        if gross <= 0:
            continue
        tx = ledger.post(
            "hours_pay",
            _("Paid for %(time)s at %(unit)s as the products sold")
            % {"time": f"{entry.minutes // 60}:{entry.minutes % 60:02d}", "unit": entry.unit.name},
            [ledger.Leg(ledger.fund2(), -gross), ledger.Leg(account, gross)],
            ref=entry,
            period=period,
        )
        tax = uniq(gross * period.tax_rate)
        if tax:
            ledger.post(
                "tax",
                _("Flat tax %(rate)s%%") % {"rate": (period.tax_rate * 100).normalize()},
                [ledger.Leg(account, -tax), ledger.Leg(ledger.fund2(), tax)],
                ref=entry,
                period=period,
            )
        entry.paid_fraction = ((paid + gross) / total).quantize(Decimal("0.000001"))
        entry.transaction = tx
        if paid + gross >= total:
            entry.status = "paid"
        entry.save(update_fields=["paid_fraction", "transaction", "status"])
        audit.record("system", "hours.paid_as_sold", entry, gross=str(gross), units_sold=str(units_sold))


def _months_ago(months):
    moment = timezone.now().astimezone(BERLIN)
    total = moment.year * 12 + moment.month - 1 - months
    return moment.replace(year=total // 12, month=total % 12 + 1, day=min(moment.day, 28))


def average_monthly_orders(offer) -> Decimal:
    from django.db.models import Sum

    total = (
        OrderLine.objects.filter(offer=offer, created_at__gte=_months_ago(3))
        .exclude(status="cancelled")
        .aggregate(t=Sum("quantity"))["t"]
    )
    return (total or Decimal("0")) / 3


def allowed_advance(offer, estimate=None) -> Decimal:
    """What a unit may make ahead this month: its advance share of the expected orders.

    The expectation is the average of the last 3 months of orders; in the offer's first 3 months it is the
    council's own estimate (`estimate`, orders a month).
    """
    from django.db.models import Sum

    young = offer.created_at > _months_ago(3)
    base = Decimal(str(estimate or 0)) if young else average_monthly_orders(offer)
    allowed = uniq(offer.advance_share * base)
    first = today().replace(day=1)
    already = ProductionOrder.objects.filter(offer=offer, origin="advance", created_at__gte=_start_of(first)).exclude(
        status="cancelled"
    ).aggregate(t=Sum("quantity"))["t"] or Decimal("0")
    return max(Decimal("0"), allowed - already)


def _start_of(day):
    return datetime(day.year, day.month, day.day, tzinfo=BERLIN)


def _new_batch(offer, quantity, member, origin):
    try:
        quantity = Decimal(str(quantity))
    except (InvalidOperation, ValueError, TypeError):
        raise MarketError(_("Please enter how many you want to make.")) from None
    if quantity <= 0:
        raise MarketError(_("Please enter how many you want to make."))
    _need_worker(member, offer.unit)
    if offer.status != "active" or offer.is_service:
        raise MarketError(_("Only an active product can be made for the shelf."))
    po = ProductionOrder.objects.create(
        offer=offer,
        quantity=quantity,
        origin=origin,
        due_date=today() + timedelta(days=catalogue.lead_time_days(offer)),
    )
    explode(po)
    audit.record(member.number, f"production.{origin}", po, quantity=str(quantity))
    unit_services.touch(offer.unit)
    return po


def start_advance(offer, quantity, member, estimate=None) -> ProductionOrder:
    """Make products ahead for the shelf, up to the unit's advance share (more: own initiative only)."""
    with transaction.atomic():
        offer = type(offer).objects.select_related("item", "unit").get(pk=offer.pk)
        _need_worker(member, offer.unit)
        left = allowed_advance(offer, estimate)
        if Decimal(str(quantity)) > left:
            raise MarketError(
                _(
                    "That is more than the %(share)s of expected orders a unit may make ahead. "
                    "You can still make up to %(left)s ahead this month, or make more on your own initiative."
                )
                % {"share": f"{offer.advance_share:.0%}", "left": left.normalize()}
            )
        return _new_batch(offer, quantity, member, "advance")


def start_own_initiative(offer, quantity, member) -> ProductionOrder:
    """Make products beyond the orders and the advance share. The hours are paid only as the products sell."""
    with transaction.atomic():
        offer = type(offer).objects.select_related("item", "unit").get(pk=offer.pk)
        return _new_batch(offer, quantity, member, "own_initiative")


def write_off_lots(now=None):
    """Unsold lots whose shelf life ended, or that sat longer than `economy.products.unsold_after_days`."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=get_param("economy.products.unsold_after_days"))
    count = 0
    candidates = StockLot.objects.filter(status="available", quantity_left__gt=0).select_related("offer__unit")
    for lot in candidates:
        if not ((lot.expires_at and lot.expires_at <= now) or lot.made_at <= cutoff):
            continue
        with transaction.atomic():
            lot = StockLot.objects.select_for_update().select_related("offer__unit", "offer__item").get(pk=lot.pk)
            if lot.status != "available" or lot.quantity_left <= 0 or reserved(lot) > 0:
                continue
            left = lot.quantity_left
            lot.status = "written_off"
            lot.quantity_left = Decimal("0")
            lot.save(update_fields=["status", "quantity_left"])
            hours = uniq(left * lot.offer.value_total)
            WasteRecord.objects.create(lot=lot, quantity=left, hours=hours, period=ledger.current_period(now))
            audit.record("system", "stock.written_off", lot, quantity=str(left), hours=str(hours))
            _notify_written_off(lot, left)
            count += 1
    return count


def _notify_written_off(lot, left):
    if lot.origin == "own_initiative":
        body = _(
            "%(qty)s %(item)s from your own initiative were not sold and are written off. "
            "The hours still waiting for these sales stay unpaid."
        )
    else:
        body = _("%(qty)s %(item)s were not sold and are written off. Their hours are taken back through the flat tax.")
    for w in unit_services.workers(lot.offer.unit):
        unit_services._notify(
            w.member,
            _("Unsold %(item)s written off") % {"item": lot.offer.item.name},
            body % {"qty": left.normalize(), "item": lot.offer.item.name},
        )


# --- Handing over and paying (docs/06 section 5, items 4 and 5) ---

DISPUTE_REASONS = {"not_received": _("Not received"), "damaged": _("Damaged")}  # a booking: "Not performed"


def hand_over(line, worker):
    """A worker of the unit gives the product to the buyer (pickup in this phase)."""
    with transaction.atomic():
        line = _lock_line(line)
        _need_worker(worker, line.offer.unit)
        if line.status not in (OrderLine.READY, OrderLine.FROM_STOCK):
            raise MarketError(_("This order is not ready to be handed over."))
        line.status = OrderLine.HANDED_OVER
        line.handed_over_at = timezone.now()
        line.save(update_fields=["status", "handed_over_at"])
        audit.record(worker.number, "order.handed_over", line)
        hours = get_param("market.delivery_confirm_hours")
        enqueue(
            "market.auto_confirm_line",
            {"line": line.pk},
            run_after=line.handed_over_at + timedelta(hours=hours),
            dedupe_key=f"market.auto_confirm_line:{line.pk}",
        )
        unit_services._notify(
            line.order.buyer,
            _("Please confirm you received your %(item)s") % {"item": line.offer.item.name},
            _(
                "%(unit)s says it handed over %(qty)s %(item)s to you. Please confirm that you got it. "
                "If you do not answer within %(hours)s hours, it counts as received."
            )
            % {
                "unit": line.offer.unit.name,
                "qty": line.quantity.normalize(),
                "item": line.offer.item.name,
                "hours": hours,
            },
        )
        return line


def _deliver(line, actor_ref):
    """The held UNIQ go to Fund 1, and a line served from the shelf draws its stock. Caller holds the lock."""
    ledger.capture_hold(
        line.hold,
        _("Bought %(qty)s %(item)s from %(unit)s")
        % {"qty": line.quantity.normalize(), "item": line.offer.item.name, "unit": line.offer.unit.name},
    )
    if line.stock_lot_id:
        draw_stock(line.stock_lot, line.quantity)
    line.status = OrderLine.DELIVERED
    line.delivered_at = timezone.now()
    line.save(update_fields=["status", "delivered_at"])
    audit.record(actor_ref, "order.delivered", line, total=str(line.total_uniq))
    unit_services.touch(line.offer.unit)
    return line


def confirm_received(line, buyer):
    with transaction.atomic():
        line = _lock_line(line)
        if line.order.buyer_id != buyer.pk:
            raise MarketError(_("This is not your order."))
        if line.status == OrderLine.DELIVERED:
            return line
        if line.status not in (OrderLine.READY, OrderLine.FROM_STOCK, OrderLine.HANDED_OVER):
            raise MarketError(_("This order is not ready yet."))
        return _deliver(line, buyer.number)


def auto_confirm_deliveries(now=None):
    """Handed-over lines with no answer after `market.delivery_confirm_hours` count as received."""
    cutoff = (now or timezone.now()) - timedelta(hours=get_param("market.delivery_confirm_hours"))
    count = 0
    for line in OrderLine.objects.filter(
        status=OrderLine.HANDED_OVER, disputed_at__isnull=True, handed_over_at__lte=cutoff
    ):
        with transaction.atomic():
            line = _lock_line(line)
            if line.status == OrderLine.HANDED_OVER and line.disputed_at is None:
                _deliver(line, "system")
                count += 1
    return count


def refuse(line, buyer):
    """The buyer does not want the product. After the batch started the order was binding: the buyer still pays."""
    with transaction.atomic():
        line = _lock_line(line)
        if line.order.buyer_id != buyer.pk:
            raise MarketError(_("This is not your order."))
        po = line.production_order
        binding = (
            line.status in (OrderLine.READY, OrderLine.HANDED_OVER)
            and po is not None
            and po.status in ("started", "done")
        )
        if not binding:
            return cancel_line(line, buyer)  # nothing was made for this order alone: it can simply be cancelled
        ledger.capture_hold(
            line.hold,
            _("Refused after production started: %(qty)s %(item)s from %(unit)s")
            % {"qty": line.quantity.normalize(), "item": line.offer.item.name, "unit": line.offer.unit.name},
        )
        line.status = OrderLine.REFUSED
        line.save(update_fields=["status"])
        make_lot(line.offer, line.quantity, "refused", po)
        audit.record(buyer.number, "order.refused", line, total=str(line.total_uniq))
        unit_services._notify(
            buyer,
            _("You refused your %(item)s") % {"item": line.offer.item.name},
            _(
                "The batch had already been started when you refused, so the order was binding and the %(total)s UNIQ "
                "were charged. The %(item)s goes on the unit's shelf for other members to buy."
            )
            % {"total": line.total_uniq.normalize(), "item": line.offer.item.name},
        )
        return line


def dispute(line, buyer, reason, text=""):
    """'Not received' or 'damaged'. The UNIQ stay held, and a ticket asks random confirmers."""
    if reason not in DISPUTE_REASONS:
        raise MarketError(_("Please say what went wrong."))
    with transaction.atomic():
        line = _lock_line(line)
        if line.order.buyer_id != buyer.pk:
            raise MarketError(_("This is not your order."))
        if line.status not in (OrderLine.READY, OrderLine.FROM_STOCK, OrderLine.HANDED_OVER):
            raise MarketError(_("There is nothing to report about this order now."))
        line.disputed_at = timezone.now()
        line.dispute_text = f"{reason}: {text}".strip()[:300]
        line.save(update_fields=["disputed_at", "dispute_text"])
        audit.record(buyer.number, "order.disputed", line, reason=reason)
        from apps.tickets import briefs

        briefs.dispute(
            buyer, DISPUTE_REASONS[reason], line.offer.item.name, line.offer.unit, {"order_line": line.pk, "text": text}
        )
        return line


# --- Services: slots, bookings, performed, confirmed, paid (docs/06 section 4) ---


def _need_pay_rule():
    if get_param("economy.services.pay_rule") != "when_performed":
        raise NotImplementedError("see plan/phase_16_later.md")


def _local(moment):
    return moment.astimezone(BERLIN)


def _day(moment) -> str:
    return f"{_local(moment):%Y-%m-%d}"


def _week_start(moment):
    local = _local(moment)
    return (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def create_slot(provider, offer, starts_at) -> ServiceSlot:
    """A worker of the unit offers one session at `starts_at`."""
    with transaction.atomic():
        offer = type(offer).objects.select_related("item", "unit").get(pk=offer.pk)
        _need_worker(provider, offer.unit)
        if not offer.is_service or offer.status != "active":
            raise MarketError(_("Sessions can only be offered for an active service."))
        if starts_at <= timezone.now():
            raise MarketError(_("A session must be in the future."))
        ends_at = starts_at + timedelta(minutes=offer.duration_minutes)
        busy = ServiceSlot.objects.filter(
            provider=provider, status__in=["open", "full"], starts_at__lt=ends_at, ends_at__gt=starts_at
        )
        if busy.exists():
            raise MarketError(_("You already offer another session at this time."))
        if offer.max_per_week:
            monday = _week_start(starts_at)
            this_week = ServiceSlot.objects.filter(
                offer=offer, status__in=["open", "full", "done"], starts_at__gte=monday
            ).filter(starts_at__lt=monday + timedelta(days=7))
            count = this_week.count()
            if count >= offer.max_per_week:
                raise MarketError(_("This service is offered at most %(n)s times a week.") % {"n": offer.max_per_week})
        slot = ServiceSlot.objects.create(
            offer=offer, provider=provider, starts_at=starts_at, ends_at=ends_at, capacity_left=offer.capacity
        )
        audit.record(provider.number, "slot.created", slot)
        unit_services.touch(offer.unit)
        return slot


def create_weekly_slots(provider, offer, first_start, weeks) -> list:
    """'Every Tuesday 10:00 for 8 weeks': the same local time each week, also across the clock change."""
    if not 1 <= weeks <= 52:
        raise MarketError(_("Please choose between 1 and 52 weeks."))
    local = _local(first_start)
    with transaction.atomic():
        return [create_slot(provider, offer, local + timedelta(weeks=i)) for i in range(weeks)]


def book(customer, slot) -> Booking:
    """Book a seat. The price is held, unless the unit is a social one, whose services are free."""
    _need_pay_rule()
    if not can_buy(customer):
        raise MarketError(_("Only members can book. Please finish joining first."))
    with transaction.atomic():
        slot = ServiceSlot.objects.select_for_update().select_related("offer__item", "offer__unit").get(pk=slot.pk)
        offer = slot.offer
        if slot.status != "open" or slot.starts_at <= timezone.now() or offer.status != "active":
            raise MarketError(_("This session cannot be booked any more."))
        if offer.unit.status not in ("trial", "open"):
            raise MarketError(_("This offer is not available now."))
        if slot.provider_id == customer.pk:
            raise MarketError(_("You cannot book your own session."))
        if slot.bookings.filter(customer=customer).exclude(status="cancelled").exists():
            raise MarketError(_("You have already booked this session."))
        if offer.values_computed_at is None:
            raise MarketError(_("This offer has no price yet."))
        booking = Booking.objects.create(slot=slot, customer=customer, price_uniq=offer.value_total)
        if offer.unit.kind != "social" and offer.value_total > 0:
            try:
                booking.hold = ledger.place_hold(
                    customer,
                    offer.value_total,
                    _("Booking of %(item)s with %(unit)s on %(date)s")
                    % {"item": offer.item.name, "unit": offer.unit.name, "date": _day(slot.starts_at)},
                    ref=booking,
                )
            except ledger.LedgerError:
                raise MarketError(_("Not enough UNIQ available")) from None
            booking.save(update_fields=["hold"])
        slot.capacity_left -= 1
        if slot.capacity_left == 0:
            slot.status = "full"
        slot.save(update_fields=["capacity_left", "status"])
        audit.record(customer.number, "booking.made", booking, slot=slot.pk, price=str(booking.price_uniq))
        unit_services.touch(offer.unit)
        return booking


def _lock_booking(booking):
    return (
        Booking.objects.select_for_update()
        .select_related("slot__offer__unit", "slot__offer__item", "customer")
        .get(pk=booking.pk)
    )


def _give_seat_back(booking):
    slot = ServiceSlot.objects.select_for_update().get(pk=booking.slot_id)
    if slot.status in ("open", "full"):
        slot.capacity_left += 1
        slot.status = "open"
        slot.save(update_fields=["capacity_left", "status"])


def cancel_booking(booking, customer):
    """The customer cancels before the session. The hold is released and the seat is free again."""
    with transaction.atomic():
        booking = _lock_booking(booking)
        if booking.customer_id != customer.pk:
            raise MarketError(_("This is not your booking."))
        if booking.status != "booked" or booking.slot.starts_at <= timezone.now():
            raise MarketError(_("This booking can no longer be cancelled."))
        booking.status = "cancelled"
        booking.save(update_fields=["status"])
        _give_seat_back(booking)
        if booking.hold_id:
            ledger.release_hold(booking.hold, _("Booking cancelled by the customer"))
        audit.record(customer.number, "booking.cancelled", booking)
        return booking


def cancel_slot(slot, provider):
    """The provider cancels a session: every booking is cancelled and every hold released."""
    with transaction.atomic():
        slot = ServiceSlot.objects.select_for_update().select_related("offer__unit").get(pk=slot.pk)
        _need_worker(provider, slot.offer.unit)
        if slot.status not in ("open", "full") or slot.starts_at <= timezone.now():
            raise MarketError(_("This session can no longer be cancelled."))
        slot.status = "cancelled"
        slot.save(update_fields=["status"])
        for booking in slot.bookings.select_for_update().filter(status="booked"):
            booking.status = "cancelled"
            booking.save(update_fields=["status"])
            if booking.hold_id:
                ledger.release_hold(booking.hold, _("The provider cancelled the session"))
            unit_services._notify(
                booking.customer,
                _("Your session was cancelled"),
                _("%(unit)s cancelled the %(item)s on %(date)s. Your UNIQ are free again.")
                % {"unit": slot.offer.unit.name, "item": slot.offer.item.name, "date": _day(slot.starts_at)},
            )
        audit.record(provider.number, "slot.cancelled", slot)
        return slot


def mark_performed(slot, provider):
    """After the session: every booking that is still `booked` becomes `performed`; the customers must confirm."""
    _need_pay_rule()
    with transaction.atomic():
        slot = ServiceSlot.objects.select_for_update().select_related("offer__unit", "offer__item").get(pk=slot.pk)
        _need_worker(provider, slot.offer.unit)
        if slot.status not in ("open", "full"):
            raise MarketError(_("This session is already closed."))
        if slot.starts_at > timezone.now():
            raise MarketError(_("This session has not happened yet."))
        now = timezone.now()
        hours = get_param("economy.services.customer_confirm_hours")
        for booking in slot.bookings.select_for_update().select_related("customer").filter(status="booked"):
            booking.status = "performed"
            booking.performed_at = now
            booking.save(update_fields=["status", "performed_at"])
            enqueue(
                "market.auto_confirm_booking",
                {"booking": booking.pk},
                run_after=now + timedelta(hours=hours),
                dedupe_key=f"market.auto_confirm_booking:{booking.pk}",
            )
            unit_services._notify(
                booking.customer,
                _("Please confirm your %(item)s") % {"item": slot.offer.item.name},
                _(
                    "%(unit)s says it performed the %(item)s on %(date)s. Please confirm that it took place. "
                    "If you do not answer within %(hours)s hours, it counts as confirmed."
                )
                % {
                    "unit": slot.offer.unit.name,
                    "item": slot.offer.item.name,
                    "date": _day(slot.starts_at),
                    "hours": hours,
                },
            )
        slot.status = "done"
        slot.save(update_fields=["status"])
        audit.record(provider.number, "slot.performed", slot)
        unit_services.touch(slot.offer.unit)
        return slot


def mark_no_show(booking, provider):
    """The customer did not come: nothing is paid (unless `economy.services.no_show_paid`), the hold is released."""
    _need_pay_rule()
    with transaction.atomic():
        booking = _lock_booking(booking)
        slot = booking.slot
        _need_worker(provider, slot.offer.unit)
        if booking.status not in ("booked", "performed") or slot.starts_at > timezone.now():
            raise MarketError(_("This booking cannot be marked as a no-show."))
        booking.status = "no_show"
        booking.save(update_fields=["status"])
        if booking.hold_id:
            ledger.release_hold(booking.hold, _("The customer did not come"))
        audit.record(provider.number, "booking.no_show", booking)
        if get_param("economy.services.no_show_paid"):
            _ensure_slot_hours(slot)
        _record_idle(slot)
        return booking


def no_show_count(customer) -> int:
    """For providers only: how often a customer did not come."""
    return Booking.objects.filter(customer=customer, status="no_show").count()


def _ensure_slot_hours(slot):
    """The provider's hours for the session, made once, from the first confirmed booking."""
    _need_pay_rule()
    slot = ServiceSlot.objects.select_for_update().select_related("offer__unit", "provider").get(pk=slot.pk)
    if slot.hours_entry_id:
        return slot.hours_entry
    offer = slot.offer
    minutes = offer.duration_minutes + (offer.travel_minutes if offer.place == "customer" else 0)
    day = min(_local(slot.starts_at).date(), today())
    kwargs = {"activity": "booking", "ref_type": "slot", "ref_id": slot.pk, "note": offer.item.name}
    try:
        entry = unit_services.record_hours(slot.provider, offer.unit, day, minutes, **kwargs)
    except unit_services.UnitError:
        # that month is closed: the hours count from today
        entry = unit_services.record_hours(slot.provider, offer.unit, today(), minutes, **kwargs)
    slot.hours_entry = entry
    slot.save(update_fields=["hours_entry"])
    return entry


def _record_idle(slot):
    """The empty seats' share of the session is idle time (for the warning light, P09)."""
    slot = ServiceSlot.objects.select_for_update().select_related("offer").get(pk=slot.pk)
    offer = slot.offer
    if offer.capacity and offer.capacity > 1:
        used = slot.bookings.filter(status="confirmed").count()
        slot.idle_minutes = round(offer.duration_minutes * (offer.capacity - used) / offer.capacity)
        slot.save(update_fields=["idle_minutes"])


def _finish_confirmation(booking, actor_ref):
    _need_pay_rule()
    if booking.hold_id:
        ledger.capture_hold(
            booking.hold,
            _("Booked %(item)s with %(unit)s")
            % {"item": booking.slot.offer.item.name, "unit": booking.slot.offer.unit.name},
        )
    booking.status = "confirmed"
    booking.confirmed_at = timezone.now()
    booking.save(update_fields=["status", "confirmed_at"])
    _ensure_slot_hours(booking.slot)
    _record_idle(booking.slot)
    audit.record(actor_ref, "booking.confirmed", booking)
    unit_services.touch(booking.slot.offer.unit)
    return booking


def confirm_performed(booking, customer):
    with transaction.atomic():
        booking = _lock_booking(booking)
        if booking.customer_id != customer.pk:
            raise MarketError(_("This is not your booking."))
        if booking.status == "confirmed":
            return booking
        if booking.status not in ("performed", "disputed"):
            raise MarketError(_("This session has not been marked as performed yet."))
        return _finish_confirmation(booking, customer.number)


def auto_confirm_bookings(now=None):
    """Performed bookings with no answer after `economy.services.customer_confirm_hours` count as confirmed."""
    cutoff = (now or timezone.now()) - timedelta(hours=get_param("economy.services.customer_confirm_hours"))
    count = 0
    for booking in Booking.objects.filter(status="performed", performed_at__lte=cutoff):
        with transaction.atomic():
            booking = _lock_booking(booking)
            if booking.status == "performed":
                _finish_confirmation(booking, "system")
                count += 1
    return count


def dispute_booking(booking, customer, text=""):
    """The customer says the session did not take place as it should. The hold stays; nothing is paid yet."""
    with transaction.atomic():
        booking = _lock_booking(booking)
        if booking.customer_id != customer.pk:
            raise MarketError(_("This is not your booking."))
        if booking.status != "performed":
            raise MarketError(_("There is nothing to report about this booking now."))
        booking.status = "disputed"
        booking.dispute_text = text.strip()[:300]
        booking.save(update_fields=["status", "dispute_text"])
        audit.record(customer.number, "booking.disputed", booking)
        from apps.tickets import briefs

        offer = booking.slot.offer
        briefs.dispute(customer, _("Not performed"), offer.item.name, offer.unit, {"booking": booking.pk, "text": text})
        return booking


# --- Standing orders (docs/06 section 5) ---


def _next_standing_date(day, every):
    if every == "week":
        return day + timedelta(days=7)
    year, month = (day.year, day.month + 1) if day.month < 12 else (day.year + 1, 1)
    for d in range(day.day, 0, -1):  # 31 January goes to 28 February
        try:
            return day.replace(year=year, month=month, day=d)
        except ValueError:
            continue


def create_standing_order(member, offer, quantity, every, first_date=None) -> StandingOrder:
    try:
        quantity = Decimal(str(quantity))
    except (InvalidOperation, ValueError, TypeError):
        raise MarketError(_("Please enter how many you want.")) from None
    if quantity <= 0 or every not in dict(StandingOrder.EVERY):
        raise MarketError(_("Please enter how many you want, and how often."))
    if not can_buy(member):
        raise MarketError(_("Only members can order. Please finish joining first."))
    if offer.status != "active" or offer.is_service:
        raise MarketError(_("This offer is not available now."))
    first_date = first_date or today()
    if first_date < today():
        raise MarketError(_("The first delivery cannot be in the past."))
    with transaction.atomic():
        so = StandingOrder.objects.create(
            member=member, offer=offer, quantity=quantity, every=every, next_date=first_date
        )
        audit.record(member.number, "standing_order.created", so)
        return so


def _own_standing_order(so, member):
    so = StandingOrder.objects.select_for_update().get(pk=so.pk)
    if so.member_id != member.pk:
        raise MarketError(_("This is not your standing order."))
    return so


def pause_standing_order(so, member):
    with transaction.atomic():
        so = _own_standing_order(so, member)
        if so.status != "active":
            raise MarketError(_("This standing order is not running."))
        so.status = "paused"
        so.save(update_fields=["status"])
        audit.record(member.number, "standing_order.paused", so)
        return so


def resume_standing_order(so, member):
    with transaction.atomic():
        so = _own_standing_order(so, member)
        if so.status != "paused":
            raise MarketError(_("This standing order is not paused."))
        so.status = "active"
        while so.next_date < today():
            so.next_date = _next_standing_date(so.next_date, so.every)
        so.save(update_fields=["status", "next_date"])
        audit.record(member.number, "standing_order.resumed", so)
        return so


def end_standing_order(so, member):
    with transaction.atomic():
        so = _own_standing_order(so, member)
        so.status = "ended"
        so.save(update_fields=["status"])
        audit.record(member.number, "standing_order.ended", so)
        return so


def run_standing_orders(day=None):
    """Place the order of every active standing order that is due, at today's price. Safe to run twice.

    If the UNIQ are not there, this time is skipped and the member is told; the next date is set in any case.
    """
    day = day or today()
    count = 0
    due = StandingOrder.objects.filter(status="active", next_date__lte=day).select_related("member", "offer")
    for so in due:
        with transaction.atomic():
            so = (
                StandingOrder.objects.select_for_update()
                .select_related("member", "offer__item", "offer__unit")
                .get(pk=so.pk)
            )
            if so.status != "active" or so.next_date > day:
                continue
            try:
                with transaction.atomic():
                    place_order(so.member, so.offer, so.quantity, note=_("Standing order"))
                so.last_result = _("Ordered on %(date)s") % {"date": day.isoformat()}
                count += 1
            except MarketError as e:
                so.last_result = _("Skipped on %(date)s: %(why)s") % {"date": day.isoformat(), "why": e}
                audit.record(so.member.number, "standing_order.skipped", so, why=str(e))
                unit_services._notify(
                    so.member,
                    _("Your standing order for %(item)s was skipped") % {"item": so.offer.item.name},
                    _("This time your standing order could not be placed: %(why)s. The next one is on %(date)s.")
                    % {"why": e, "date": _next_standing_date(so.next_date, so.every).isoformat()},
                )
            while so.next_date <= day:
                so.next_date = _next_standing_date(so.next_date, so.every)
            so.save(update_fields=["next_date", "last_result"])
    return count


# --- Paying in person with a QR code (docs/06 section 6) ---

SALE_MINUTES = 10
SALE_CODE_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
REAUTH_ABOVE_UNIQ = Decimal("10")  # a payment above this needs a recent sign-in


def _new_sale_code():
    import secrets

    while True:
        code = "".join(secrets.choice(SALE_CODE_CHARS) for _ in range(10))
        if not Sale.objects.filter(code=code).exists():
            return code


def create_sale(seller, offer, quantity) -> Sale:
    """A worker of the unit sells products from its shelf in person. The buyer pays by scanning the code."""
    try:
        quantity = Decimal(str(quantity))
    except (InvalidOperation, ValueError, TypeError):
        raise MarketError(_("Please enter how many.")) from None
    if quantity <= 0:
        raise MarketError(_("Please enter how many."))
    with transaction.atomic():
        offer = type(offer).objects.select_related("item", "unit").get(pk=offer.pk)
        _need_worker(seller, offer.unit)
        if offer.status != "active":
            raise MarketError(_("This offer is not available now."))
        # OWNER-CHECK: selling a service in person (how are the provider's hours recorded?) is not built; products only.
        if offer.is_service:
            raise MarketError(_("Services are booked in the market. In-person payment is for products on the shelf."))
        if offer.values_computed_at is None or offer.value_total <= 0:
            raise MarketError(_("This offer has no price yet."))
        if _lot_for(offer, quantity) is None:
            raise MarketError(_("There is not enough of this on the shelf."))
        sale = Sale.objects.create(
            offer=offer,
            quantity=quantity,
            seller=seller,
            code=_new_sale_code(),
            amount_uniq=uniq(offer.value_total * quantity),
            expires_at=timezone.now() + timedelta(minutes=SALE_MINUTES),
        )
        audit.record(seller.number, "sale.created", sale, amount=str(sale.amount_uniq))
        return sale


def get_sale(code):
    """The sale for a code, marked expired if its time is over. None if there is no such code."""
    sale = Sale.objects.select_related("offer__item", "offer__unit", "seller").filter(code=(code or "").upper()).first()
    if sale is not None and sale.status == "open" and sale.expires_at <= timezone.now():
        Sale.objects.filter(pk=sale.pk, status="open").update(status="expired")
        sale.status = "expired"
    return sale


def needs_recent_sign_in(sale) -> bool:
    return sale.amount_uniq > REAUTH_ABOVE_UNIQ


def pay_sale(code, buyer) -> Sale:
    """The buyer confirms: the UNIQ go straight to Fund 1 and the shelf is drawn. Works once per code."""
    if not can_buy(buyer):
        raise MarketError(_("Only members can pay. Please finish joining first."))
    with transaction.atomic():
        sale = (
            Sale.objects.select_for_update()
            .select_related("offer__item", "offer__unit")
            .filter(code=(code or "").upper())
            .first()
        )
        if sale is None:
            raise MarketError(_("This payment code does not exist."))
        if sale.status == "paid":
            raise MarketError(_("This sale has already been paid."))
        if sale.status == "expired" or sale.expires_at <= timezone.now():
            if sale.status == "open":
                sale.status = "expired"
                sale.save(update_fields=["status"])
            raise MarketError(_("This payment code has expired. Please ask the seller for a new one."))
        if sale.seller_id == buyer.pk:
            raise MarketError(_("You cannot pay your own sale."))
        lot = _lot_for(sale.offer, sale.quantity)
        if lot is None:
            raise MarketError(_("There is not enough of this on the shelf any more."))
        try:
            ledger.post(
                "purchase",
                _("Bought %(qty)s %(item)s from %(unit)s in person")
                % {"qty": sale.quantity.normalize(), "item": sale.offer.item.name, "unit": sale.offer.unit.name},
                [
                    ledger.Leg(ledger.member_account(buyer), -sale.amount_uniq),
                    ledger.Leg(ledger.fund1(), sale.amount_uniq),
                ],
                ref=sale,
                actor_ref=buyer.number,
            )
        except ledger.LedgerError:
            raise MarketError(_("Not enough UNIQ available")) from None
        draw_stock(lot, sale.quantity)
        sale.status = "paid"
        sale.buyer = buyer
        sale.stock_lot = lot
        sale.paid_at = timezone.now()
        sale.save(update_fields=["status", "buyer", "stock_lot", "paid_at"])
        audit.record(buyer.number, "sale.paid", sale, amount=str(sale.amount_uniq))
        unit_services.touch(sale.offer.unit)
        return sale


def expire_sales():
    return Sale.objects.filter(status="open", expires_at__lte=timezone.now()).update(status="expired")


# --- Reviews (docs/06 section 6) ---


def write_review(member, *, order_line=None, booking=None, stars, text="", as_thanks=False) -> Review:
    """One review per delivered order line or confirmed booking, by the buyer or customer."""
    from apps.core.hooks import RECOGNITION_HOOK

    if (order_line is None) == (booking is None):
        raise MarketError(_("Please choose one order or one booking to review."))
    try:
        stars = int(stars)
    except (TypeError, ValueError):
        stars = 0
    if not 1 <= stars <= 5:
        raise MarketError(_("Please give between 1 and 5 stars."))
    with transaction.atomic():
        if order_line is not None:
            thing = OrderLine.objects.select_related("order", "offer").get(pk=order_line.pk)
            owner_id, done, offer = thing.order.buyer_id, thing.status == OrderLine.DELIVERED, thing.offer
        else:
            thing = Booking.objects.select_related("slot__offer").get(pk=booking.pk)
            owner_id, done, offer = thing.customer_id, thing.status == "confirmed", thing.slot.offer
        if owner_id != member.pk:
            raise MarketError(_("You can only review what you bought yourself."))
        if not done:
            raise MarketError(_("You can review it once you have received it."))
        if Review.objects.filter(**({"order_line": thing} if order_line is not None else {"booking": thing})).exists():
            raise MarketError(_("You have already reviewed this."))
        review = Review.objects.create(
            offer=offer,
            order_line=thing if order_line is not None else None,
            booking=thing if booking is not None else None,
            author=member,
            stars=stars,
            text=text.strip()[:2000],
            as_thanks=bool(as_thanks and text.strip()),
        )
        audit.record(member.number, "review.written", review, stars=stars)
    if review.as_thanks:
        RECOGNITION_HOOK(member, "thanks", review)
    return review


def review_summary(offer):
    """The average stars (or None) and the number of reviews."""
    from django.db.models import Avg, Count

    row = Review.objects.filter(offer=offer).aggregate(avg=Avg("stars"), n=Count("id"))
    return row["avg"], row["n"]


def latest_reviews(offer, limit=10):
    return list(Review.objects.filter(offer=offer).select_related("author")[:limit])


def reviews_for_council(member, unit):
    """Every review of a unit's offers, for its council. Others see the latest 10 on each offer page."""
    if not unit_services.is_council_member(member, unit):
        raise MarketError(_("Only the unit's council can read all its reviews."))
    return Review.objects.filter(offer__unit=unit).select_related("author", "offer__item")


# --- Finding offers (docs/06 section 6) ---


def search_offers(member=None, text="", kind="", trade="", town=""):
    """Active offers, filtered by text, kind, trade and town.

    Order: the member's own area first, then alphabetical. Never by price, by stars or by anything else a
    score could change (HF-3, HF-10). Distance replaces the area in phase 12.
    """
    from django.db.models import Q

    from apps.tickets.flags import hidden_ids

    offers = (
        catalogue.Offer.objects.filter(status="active", unit__status__in=["trial", "open"])
        .exclude(pk__in=hidden_ids("offer"))  # hidden while members review a report (P06.T08)
        .select_related("item", "item__uom", "unit")
    )
    text = (text or "").strip()
    if text:
        offers = offers.filter(Q(item__name__icontains=text) | Q(unit__name__icontains=text))
    if kind in ("product", "service"):
        offers = offers.filter(item__kind=kind)
    if trade:
        offers = offers.filter(Q(unit__trade_code=trade) | Q(item__trade_code=trade))
    town = (town or "").strip()
    if town:
        offers = offers.filter(unit__town__iexact=town)
    postcode = (getattr(member, "postcode", "") or "").strip()

    def rank(offer):
        if town and (offer.unit.town or "").lower() == town.lower():
            return 0
        if postcode and offer.unit.postcode and offer.unit.postcode == postcode:
            return 0
        if postcode and offer.unit.postcode and offer.unit.postcode[:2] == postcode[:2]:
            return 1
        return 2

    return sorted(offers, key=lambda o: (rank(o), o.item.name.lower(), o.unit.name.lower(), o.pk))


# --- What the pages show (docs/06 section 6) ---


def expected_date(offer):
    """Products: today plus the lead time. Services: the start of the next open session, if any."""
    if offer.is_service:
        slot = (
            ServiceSlot.objects.filter(offer=offer, status="open", starts_at__gt=timezone.now())
            .order_by("starts_at")
            .first()
        )
        return _local(slot.starts_at) if slot else None
    return today() + timedelta(days=catalogue.lead_time_days(offer))


def open_slots(offer, weeks=4):
    """The open sessions of the next 4 weeks, for the booking calendar."""
    now = timezone.now()
    return list(
        ServiceSlot.objects.filter(
            offer=offer, status="open", starts_at__gt=now, starts_at__lte=now + timedelta(weeks=weeks)
        ).order_by("starts_at")
    )


def line_actions(line) -> set:
    """The buttons a buyer gets on an order line."""
    actions = set()
    if line.status in (OrderLine.DELIVERED, OrderLine.REFUSED, OrderLine.CANCELLED):
        if line.status == OrderLine.DELIVERED and not hasattr(line, "review"):
            actions.add("review")
        return actions
    if _free_cancel_allowed(line):
        actions.add("cancel")
    if line.status in (OrderLine.READY, OrderLine.FROM_STOCK, OrderLine.HANDED_OVER):
        actions.add("confirm")
        if line.disputed_at is None:
            actions.add("dispute")
    if line.status in (OrderLine.READY, OrderLine.HANDED_OVER):
        actions.add("refuse")
    return actions


def booking_actions(booking) -> set:
    actions = set()
    if booking.status == "booked" and booking.slot.starts_at > timezone.now():
        actions.add("cancel")
    if booking.status in ("performed", "disputed"):
        actions.add("confirm")
    if booking.status == "performed":
        actions.add("dispute")
    if booking.status == "confirmed" and not hasattr(booking, "review"):
        actions.add("review")
    return actions


def release_unit_orders(unit):
    """A unit was paused: orders not yet being made and coming sessions are cancelled, and their UNIQ released."""
    with transaction.atomic():
        lines = OrderLine.objects.filter(
            offer__unit=unit, status__in=[OrderLine.PLACED, OrderLine.FROM_STOCK, OrderLine.IN_PRODUCTION]
        )
        for line in lines:
            line = _lock_line(line)
            started = (
                line.status == OrderLine.IN_PRODUCTION
                and line.production_order_id
                and line.production_order.status != "open"
            )
            if started or line.status == OrderLine.CANCELLED:
                continue  # a batch that has started is made anyway
            _unassign(line)
            line.status = OrderLine.CANCELLED
            line.save(update_fields=["status"])
            if line.hold_id:
                ledger.release_hold(line.hold, _("The unit was paused"))
            audit.record("system", "order.released", line, unit=unit.pk)
            unit_services._notify(
                line.order.buyer,
                _("Your order from %(unit)s was cancelled") % {"unit": unit.name},
                _("The unit was paused while members review it. Your UNIQ are free again."),
            )
        for booking in Booking.objects.filter(
            slot__offer__unit=unit, status="booked", slot__starts_at__gt=timezone.now()
        ):
            booking = _lock_booking(booking)
            if booking.status != "booked":
                continue
            booking.status = "cancelled"
            booking.save(update_fields=["status"])
            _give_seat_back(booking)
            if booking.hold_id:
                ledger.release_hold(booking.hold, _("The unit was paused"))
            audit.record("system", "booking.released", booking, unit=unit.pk)


if release_unit_orders not in unit_services.PAUSE_HOOKS:
    unit_services.PAUSE_HOOKS.append(release_unit_orders)
