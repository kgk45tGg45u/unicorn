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

from .models import InputRequest, Order, OrderLine, ProductionOrder, PurchaseNeed, WeeklyPlan

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
    return need or PurchaseNeed.objects.create(unit=po.offer.unit, item=row.item, month=month, currency=row.currency)


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
