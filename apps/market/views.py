import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.catalogue.models import Offer
from apps.core.decorators import sensitive_action

from . import services


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
