import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.catalogue.models import Offer
from apps.core.decorators import sensitive_action
from apps.units import services as unit_services

from . import needs, services


def _qr_svg(text):
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode()


def _sellable_offers(member):
    """Active products of the units the member works in."""
    unit_ids = [w.unit_id for w in member.unit_memberships.filter(left_at__isnull=True)]
    return Offer.objects.filter(unit_id__in=unit_ids, status="active", item__kind="product").select_related(
        "item", "unit"
    )


@login_required
def sell_in_person(request):
    """The seller's page: choose an offer and a quantity, then show the QR code."""
    offers = _sellable_offers(request.member)
    if request.method == "POST":
        offer = get_object_or_404(offers, pk=request.POST.get("offer") or 0)
        try:
            sale = services.create_sale(request.member, offer, request.POST.get("quantity", ""))
        except services.MarketError as e:
            messages.error(request, str(e))
        else:
            return redirect("market:sale", code=sale.code)
    return render(request, "market/sale_new.html", {"offers": offers})


@login_required
def sale_page(request, code):
    """The seller shows this to the buyer. It refreshes itself until the sale is paid or expired."""
    sale = services.get_sale(code)
    if sale is None or sale.seller_id != request.member.pk:
        raise Http404
    url = request.build_absolute_uri(reverse("market:pay", args=[sale.code]))
    context = {"sale": sale, "qr": _qr_svg(url), "pay_url": url}
    if request.htmx:
        return render(request, "market/_sale_status.html", context)
    return render(request, "market/sale_show.html", context)


def _pay(request, code):
    sale = services.get_sale(code)
    if sale is None:
        raise Http404
    if request.method == "POST":
        try:
            services.pay_sale(sale.code, request.member)
        except services.MarketError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, _("Paid. Thank you!"))
        return redirect("market:pay", code=sale.code)
    return render(request, "market/sale_pay.html", {"sale": sale, "own": sale.seller_id == request.member.pk})


@login_required
def pay(request, code):
    """The buyer's page for a scanned code. Above 10 UNIQ it asks for a recent sign-in first."""
    sale = services.get_sale(code)
    if sale is not None and sale.status == "open" and services.needs_recent_sign_in(sale):
        return sensitive_action(_pay)(request, code)
    return _pay(request, code)


# --- Reviews ---


def _review(request, kind, pk):
    from .models import Booking, OrderLine

    if kind == "line":
        thing = get_object_or_404(OrderLine.objects.select_related("offer__item", "offer__unit", "order"), pk=pk)
        if thing.order.buyer_id != request.member.pk:
            raise Http404
        offer, args = thing.offer, {"order_line": thing}
    else:
        thing = get_object_or_404(Booking.objects.select_related("slot__offer__item", "slot__offer__unit"), pk=pk)
        if thing.customer_id != request.member.pk:
            raise Http404
        offer, args = thing.slot.offer, {"booking": thing}
    if request.method == "POST":
        try:
            services.write_review(
                request.member,
                stars=request.POST.get("stars"),
                text=request.POST.get("text", ""),
                as_thanks=bool(request.POST.get("as_thanks")),
                **args,
            )
        except services.MarketError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, _("Thank you for your review."))
            return redirect("catalogue:offer", pk=offer.pk)
    return render(request, "market/review_form.html", {"offer": offer})


@login_required
def review_line(request, pk):
    return _review(request, "line", pk)


@login_required
def review_booking(request, pk):
    return _review(request, "booking", pk)


@login_required
def unit_reviews(request, slug):
    from apps.units.models import Unit

    unit = get_object_or_404(Unit, slug=slug)
    try:
        reviews = services.reviews_for_council(request.member, unit)
    except services.MarketError:
        raise PermissionDenied from None
    return render(request, "market/unit_reviews.html", {"unit": unit, "reviews": reviews})


# --- The market ---


def _card(offer):
    average, count = services.review_summary(offer)
    return {
        "offer": offer,
        "average": average,
        "count": count,
        "expected": services.expected_date(offer),
    }


def market_index(request):
    """Search and browse offers. Never ordered by price or by stars."""
    q = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "")
    trade = request.GET.get("trade", "")
    town = request.GET.get("town", "")
    offers = services.search_offers(request.member, q, kind, trade, town)
    cards = [_card(o) for o in offers[:60]]
    if q and not offers:
        needs.record_search_miss(request.member, q)  # counted by area; the searcher is never stored
    trades = sorted(
        set(
            Offer.objects.filter(status="active")
            .exclude(unit__trade_code="")
            .values_list("unit__trade_code", flat=True)
        )
    )
    return render(
        request,
        "market/index.html",
        {
            "cards": cards,
            "q": q,
            "kind": kind,
            "trade": trade,
            "town": town,
            "trades": trades,
            "more": len(offers) > 60,
        },
    )


@login_required
@require_POST
def order_offer(request, pk):
    offer = get_object_or_404(Offer, pk=pk)
    try:
        line = services.place_order(request.member, offer, request.POST.get("quantity", ""))
        every = request.POST.get("repeat", "")
        if every in ("week", "month"):
            first = services._next_standing_date(services.today(), every)
            services.create_standing_order(request.member, offer, line.quantity, every, first_date=first)
    except services.MarketError as e:
        messages.error(request, str(e))
        return redirect("catalogue:offer", pk=offer.pk)
    messages.success(request, _("Your order is placed. The UNIQ are held until you receive it."))
    return redirect("market:my_orders")


@login_required
@require_POST
def book_slot(request, pk):
    from .models import ServiceSlot

    slot = get_object_or_404(ServiceSlot, pk=pk)
    try:
        services.book(request.member, slot)
    except services.MarketError as e:
        messages.error(request, str(e))
        return redirect("catalogue:offer", pk=slot.offer_id)
    messages.success(request, _("Booked. The UNIQ are held until the session is done."))
    return redirect("market:my_orders")


# --- My orders ---


@login_required
def my_orders(request):
    from .models import Booking, OrderLine, StandingOrder

    member = request.member
    lines = list(
        OrderLine.objects.filter(order__buyer=member)
        .select_related("offer__item", "offer__unit", "production_order")
        .order_by("-created_at", "-id")[:100]
    )
    for line in lines:
        line.actions = services.line_actions(line)
    bookings = list(
        Booking.objects.filter(customer=member)
        .select_related("slot__offer__item", "slot__offer__unit")
        .order_by("-created_at", "-id")[:100]
    )
    for booking in bookings:
        booking.actions = services.booking_actions(booking)
    standing = StandingOrder.objects.filter(member=member).exclude(status="ended").select_related("offer__item")
    return render(
        request,
        "market/my_orders.html",
        {"lines": lines, "bookings": bookings, "standing": standing, "reasons": services.DISPUTE_REASONS},
    )


@login_required
@require_POST
def my_order_action(request, kind, pk, action):
    from .models import Booking, OrderLine, StandingOrder

    member = request.member
    try:
        if kind == "line":
            line = get_object_or_404(OrderLine, pk=pk, order__buyer=member)
            if action == "cancel":
                services.cancel_line(line, member)
            elif action == "confirm":
                services.confirm_received(line, member)
            elif action == "refuse":
                services.refuse(line, member)
            elif action == "dispute":
                services.dispute(line, member, request.POST.get("reason", ""), request.POST.get("text", ""))
            else:
                raise Http404
        elif kind == "booking":
            booking = get_object_or_404(Booking, pk=pk, customer=member)
            if action == "cancel":
                services.cancel_booking(booking, member)
            elif action == "confirm":
                services.confirm_performed(booking, member)
            elif action == "dispute":
                services.dispute_booking(booking, member, request.POST.get("text", ""))
            else:
                raise Http404
        elif kind == "standing":
            so = get_object_or_404(StandingOrder, pk=pk, member=member)
            if action == "pause":
                services.pause_standing_order(so, member)
            elif action == "resume":
                services.resume_standing_order(so, member)
            elif action == "end":
                services.end_standing_order(so, member)
            else:
                raise Http404
        else:
            raise Http404
    except services.MarketError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, _("Done."))
    return redirect("market:my_orders")


# --- The unit's Work page ---


def _worker_unit(request, slug):
    from apps.units.models import Unit

    unit = get_object_or_404(Unit, slug=slug)
    if not unit_services.is_worker(request.member, unit):
        raise PermissionDenied
    return unit


@login_required
def unit_work(request, slug):
    from .models import InputRequest, OrderLine, ProductionOrder, PurchaseNeed, ServiceSlot

    unit = _worker_unit(request, slug)
    member = request.member
    orders = list(
        ProductionOrder.objects.filter(offer__unit=unit, status__in=["open", "started"])
        .select_related("offer__item")
        .prefetch_related("lines")
        .order_by("due_date", "id")
    )
    needs = (
        InputRequest.objects.filter(production_order__offer__unit=unit)
        .exclude(status__in=["cancelled", "received"])
        .select_related("item", "production_order__offer__item", "supplier_offer__unit", "provided_by")
    )
    to_deliver = (
        InputRequest.objects.filter(supplier_offer__unit=unit, source="unicorn", status__in=["open", "confirmed"])
        .select_related("item", "production_order__offer__unit")
        .order_by("due_date")
    )
    to_confirm = InputRequest.objects.filter(provided_by=member, source="own_free", status="open").select_related(
        "item", "production_order__offer__unit"
    )
    ready = OrderLine.objects.filter(
        offer__unit=unit, status__in=[OrderLine.READY, OrderLine.FROM_STOCK]
    ).select_related("offer__item", "order__buyer")
    now = timezone.now()
    slots = list(
        ServiceSlot.objects.filter(offer__unit=unit, status__in=["open", "full"])
        .select_related("offer__item")
        .prefetch_related("bookings__customer")
        .order_by("starts_at")
    )
    for slot in slots:
        slot.started = slot.starts_at <= now
    offers = list(Offer.objects.filter(unit=unit, status="active").select_related("item"))
    return render(
        request,
        "market/unit_work.html",
        {
            "unit": unit,
            "orders": orders,
            "needs": needs,
            "to_deliver": to_deliver,
            "to_confirm": to_confirm,
            "ready": ready,
            "slots": slots,
            "product_offers": [o for o in offers if not o.is_service],
            "service_offers": [o for o in offers if o.is_service],
            "purchase_needs": PurchaseNeed.objects.filter(unit=unit, status="open").select_related("item"),
            "continuous": unit.mode == "continuous",
        },
    )


def _int(request, name="id"):
    try:
        return int(request.POST.get(name, ""))
    except ValueError:
        raise Http404 from None


def _when(text):
    """A date and time typed as 2026-12-01 10:00 (Europe/Berlin)."""
    from datetime import datetime

    try:
        return datetime.strptime(text.strip().replace("T", " "), "%Y-%m-%d %H:%M").replace(tzinfo=services.BERLIN)
    except ValueError:
        raise services.MarketError(_("Please enter the date and time like 2026-12-01 10:00.")) from None


@login_required
@require_POST
def unit_work_action(request, slug, action):
    from datetime import date

    from .models import Booking, InputRequest, OrderLine, ProductionOrder, ServiceSlot

    unit = _worker_unit(request, slug)
    member, p = request.member, request.POST
    try:
        if action in ("start", "complete", "hours"):
            po = get_object_or_404(ProductionOrder, pk=_int(request), offer__unit=unit)
            if action == "start":
                services.start_production(po, member)
            elif action == "complete":
                services.complete_production(po, member, p.get("quantity_done", ""))
            else:
                try:
                    day = date.fromisoformat(p.get("date") or services.today().isoformat())
                    minutes = int(p.get("minutes", ""))
                except ValueError:
                    raise services.MarketError(_("Please enter the date and the minutes.")) from None
                services.record_production_hours(member, po, day, minutes)
        elif action == "hand_over":
            services.hand_over(get_object_or_404(OrderLine, pk=_int(request), offer__unit=unit), member)
        elif action in ("confirm_input", "deliver_input", "receive_input"):
            req = get_object_or_404(InputRequest, pk=_int(request))
            if action == "confirm_input":
                services.confirm_input(req, member)
            elif action == "deliver_input":
                services.mark_delivered(req, member)
            else:
                services.mark_received(req, member)
        elif action in ("performed", "cancel_slot", "no_show"):
            if action == "no_show":
                services.mark_no_show(get_object_or_404(Booking, pk=_int(request), slot__offer__unit=unit), member)
            else:
                slot = get_object_or_404(ServiceSlot, pk=_int(request), offer__unit=unit)
                (services.mark_performed if action == "performed" else services.cancel_slot)(slot, member)
        elif action == "new_slots":
            offer = get_object_or_404(Offer, pk=_int(request, "offer"), unit=unit)
            services.create_weekly_slots(member, offer, _when(p.get("starts_at", "")), int(p.get("weeks") or 1))
        elif action in ("advance", "own_initiative"):
            offer = get_object_or_404(Offer, pk=_int(request, "offer"), unit=unit)
            if action == "advance":
                services.start_advance(offer, p.get("quantity", ""), member, estimate=p.get("estimate") or None)
            else:
                services.start_own_initiative(offer, p.get("quantity", ""), member)
        elif action == "weekly_plan":
            offer = get_object_or_404(Offer, pk=_int(request, "offer"), unit=unit)
            services.set_weekly_plan(member, offer, p.get("quantity", ""), p.get("reason", ""))
        else:
            raise Http404
    except (services.MarketError, unit_services.UnitError) as e:
        messages.error(request, str(e))
    else:
        messages.success(request, _("Done."))
    return redirect("market:work", slug=unit.slug)


# --- The needs board ---


def needs_board(request):
    board = needs.needs_board(request.member)
    return render(
        request,
        "market/needs.html",
        {**board, "my_units": needs.my_units(request.member), "member": request.member},
    )


@login_required
@require_POST
def join_waiting_list(request, pk):
    from apps.catalogue.models import Item

    item = get_object_or_404(Item, pk=pk)
    try:
        if request.POST.get("leave"):
            needs.leave_waiting_list(request.member, item)
            messages.success(request, _("You are off the waiting list."))
        else:
            needs.join_waiting_list(request.member, item, request.POST.get("quantity") or 1)
            messages.success(request, _("We will tell you when it is available."))
    except services.MarketError as e:
        messages.error(request, str(e))
    return redirect("catalogue:item", pk=item.pk)
