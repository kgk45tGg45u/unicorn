from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.catalogue.models import Offer
from apps.core.decorators import sensitive_action
from apps.market.models import Order, OrderLine
from apps.units import services as unit_services

from . import invoices, services
from .models import Invoice


def shop(request):
    return render(request, "outside/shop.html", {"offers": services.shop_offers()})


def consumer_info(request):
    return render(request, "outside/consumer_info.html", {})


def checkout(request, pk):
    offer = next((o for o in services.shop_offers() if o.pk == pk), None)
    if offer is None:
        raise Http404
    profile = services.active_seller(offer.outside_seller)
    if request.method == "POST":
        p = request.POST
        try:
            order = services.place_outside_order(
                offer, p.get("quantity", ""), p.get("name", ""), p.get("email", ""), p.get("address", ""),
                p.get("country", ""), bool(p.get("read_info")), bool(p.get("consent")),
                delivery=_delivery(p),
            )  # fmt: skip
            return redirect("outside:order", token=order.public_token)
        except services.OutsideError as e:
            messages.error(request, str(e))
    return render(request, "outside/checkout.html", {"offer": offer, "profile": profile})


def _delivery(p):
    if p.get("delivery") != "deliver":
        return None
    return {"mode": "deliver", "postcode": p.get("postcode", ""), "country": p.get("country", "DE") or "DE"}


def received(request, token):
    order = _order_by_token(token)
    if request.method == "POST":
        try:
            services.customer_received(order)
            messages.success(request, _("Thank you. We are glad it arrived."))
        except services.OutsideError as e:
            messages.error(request, str(e))
    return redirect("outside:order", token=token)


def _order_by_token(token):
    return get_object_or_404(Order, public_token=token, kind="outside")


def order_page(request, token):
    order = _order_by_token(token)
    line = order.lines.select_related("offer__item", "offer__unit", "seller").get()
    profile = services.active_seller(line.seller) or getattr(line.seller, "seller_profile", None)
    return render(
        request,
        "outside/order.html",
        {
            "order": order,
            "line": line,
            "profile": profile,
            "reference": services.reference_of(order),
            "total": services.total_of(line),
            "iban": services.seller_iban(profile) if profile else "",
            "can_withdraw": services.withdrawal_open(order),
            "invoice": getattr(order, "invoice", None),
            "shipment": order.shipments.first(),
        },
    )


def withdraw(request, token):
    order = _order_by_token(token)
    if request.method == "POST":
        try:
            services.request_withdrawal(order)
            messages.success(request, _("Thank you. The seller was told and will refund you."))
        except services.OutsideError as e:
            messages.error(request, str(e))
        return redirect("outside:order", token=token)
    return render(request, "outside/withdrawal.html", {"order": order, "open": services.withdrawal_open(order)})


def _invoice_response(request, invoice):
    return render(
        request,
        "outside/invoice.html",
        {
            "invoice": invoice,
            "customer": invoices.customer_of(invoice),
            "seller": invoice.seller.seller_profile,
            "address": __import__("apps.members.crypto", fromlist=["x"])
            .system_decrypt(invoice.seller.seller_profile.trader_address_enc)
            .decode(),
        },
    )


def customer_invoice(request, token):
    order = _order_by_token(token)
    invoice = getattr(order, "invoice", None)
    if invoice is None:
        raise Http404
    return _invoice_response(request, invoice)


@login_required
def seller_invoice(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, seller=request.member)
    return _invoice_response(request, invoice)


@login_required
@sensitive_action(allow_get=True)
def seller_area(request):
    member = request.member
    profile = services.active_seller(member)
    if request.method == "POST":
        p = request.POST
        try:
            do = p.get("do")
            if do == "activate":
                services.activate_seller(
                    member, p.get("trader_name", ""), p.get("address", ""), bool(p.get("small_business")),
                    p.get("vat_id", ""), None, bool(p.get("show_iban")),
                )  # fmt: skip
                messages.success(request, _("Outside sales are switched on."))
            elif do == "tax":
                services.change_tax_reserve(member, p.get("share", ""), p.get("reason", ""))
                messages.success(request, _("Your tax reserve share is changed."))
            elif do == "paid":
                order = get_object_or_404(Order, pk=p.get("order"), kind="outside")
                services.confirm_customer_payment(order, member, p.get("amount", ""))
                messages.success(request, _("Thank you. The order goes into production."))
            elif do == "deliver":
                services.deliver(get_object_or_404(OrderLine, pk=p.get("line")), member)
                messages.success(request, _("Handed over."))
            elif do == "refund":
                services.refund_order(get_object_or_404(Order, pk=p.get("order")), member, p.get("reason", ""))
                messages.success(request, _("The order is refunded."))
            elif do == "offer":
                offer = get_object_or_404(Offer, pk=p.get("offer"))
                result = services.propose_outside_offer(
                    member, offer, p.get("price", ""), p.get("currency", "EUR"), member
                )
                messages.success(
                    request,
                    _("Done.") if isinstance(result, Offer) else _("Your unit's council will decide."),
                )
        except (services.OutsideError, unit_services.UnitError) as e:
            messages.error(request, str(e))
        return redirect("outside:seller")
    lines = (
        OrderLine.objects.filter(seller=member, order__kind="outside")
        .select_related("offer__item", "order")
        .order_by("-id")[:30]
    )
    unit_ids = unit_services.UnitMembership.objects.filter(member=member, left_at__isnull=True).values("unit_id")
    return render(
        request,
        "outside/seller.html",
        {
            "profile": profile,
            "lines": [(line, services.total_of(line), services.reference_of(line.order)) for line in lines],
            "offers": Offer.objects.filter(unit_id__in=unit_ids, status="active", item__kind="product"),
        },
    )
