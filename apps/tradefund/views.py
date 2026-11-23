from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import sensitive_action

from . import payments, purchases, services, trust
from .models import Holder, PaymentRequest, PurchaseRequest, TrustEvent
from .services import FundError


@login_required
@sensitive_action(allow_get=True)
def become_holder(request):
    member = request.member
    if services.is_holder(member):
        return redirect("tradefund:mine")
    template = services.agreement()
    if request.method == "POST":
        if not request.POST.get("accept"):
            messages.error(request, _("Please tick the box to accept the holder agreement."))
        else:
            try:
                services.become_holder(
                    member,
                    request.POST.get("currency") or member.currency,
                    request.POST.get("iban", ""),
                    request.POST.get("bic", ""),
                    request.POST.get("bank_name", ""),
                    separate_account=bool(request.POST.get("separate_account")),
                    iban_shown_to_donors=bool(request.POST.get("iban_shown_to_donors")),
                )
                messages.success(request, _("Thank you. You are now a holder."))
                return redirect("tradefund:mine")
            except services.FundError as e:
                messages.error(request, str(e))
    return render(request, "tradefund/become_holder.html", {"template": template, "currency": member.currency})


@login_required
def my_holding(request):
    holder = Holder.objects.filter(member=request.member).first()
    return render(request, "tradefund/mine.html", {"holder": holder})


def _mine(pr, member):
    """The payer, the receiver and (for an outside payee) the buyer may open a payment."""
    return member is not None and (member.pk == pr.payer.member_id or payments.can_confirm_receipt(pr, member))


@login_required
def pay_list(request):
    member = request.member
    to_pay = PaymentRequest.objects.filter(payer__member=member, status__in=PaymentRequest.OPEN)
    candidates = PaymentRequest.objects.filter(status__in=PaymentRequest.OPEN).select_related(
        "payer__member", "payee_holder__member", "payee_member", "confirmer", "ticket"
    )
    to_confirm = [p for p in candidates if p.payer.member_id != member.pk and payments.can_confirm_receipt(p, member)]
    done = PaymentRequest.objects.filter(payer__member=member).exclude(status__in=PaymentRequest.OPEN)[:20]
    return render(request, "tradefund/pay_list.html", {"to_pay": to_pay, "to_confirm": to_confirm, "done": done})


@login_required
@sensitive_action(allow_get=True)
def pay_detail(request, pk):
    pr = get_object_or_404(PaymentRequest.objects.select_related("payer__member"), pk=pk)
    member = request.member
    if not _mine(pr, member):
        raise Http404
    if request.method == "POST":
        try:
            if request.POST.get("do") == "sent":
                payments.confirm_sent(pr, member, request.POST.get("amount", ""))
                messages.success(request, _("Thank you. You said that you sent it."))
            elif request.POST.get("do") == "received":
                payments.confirm_received(pr, member, request.POST.get("amount", ""))
                messages.success(request, _("Thank you. You said that it arrived."))
        except payments.FundError as e:
            messages.error(request, str(e))
        return redirect("tradefund:pay_detail", pk=pk)
    pr.refresh_from_db()
    is_payer = member.pk == pr.payer.member_id
    return render(
        request,
        "tradefund/pay_detail.html",
        {
            "pr": pr,
            "info": payments.instructions(pr, member),
            "is_payer": is_payer,
            "can_send": is_payer and pr.sent_amount is None and pr.status in ("requested", "overdue", "received"),
            "can_receive": payments.can_confirm_receipt(pr, member)
            and pr.received_amount is None
            and pr.status in ("requested", "overdue", "sent"),
        },
    )


@login_required
def trust_page(request):
    holder = Holder.objects.filter(member=request.member).first()
    if holder is None:
        return redirect("tradefund:become_holder")
    annulled = set(TrustEvent.objects.filter(kind="annulled").values_list("ref", flat=True))
    events = [
        {"event": e, "annulled": f"event:{e.pk}" in annulled, "can_contest": trust.can_contest(e)}
        for e in holder.trust_events.all().order_by("-id")
    ]
    return render(
        request,
        "tradefund/trust.html",
        {"holder": holder, "score": trust.score(holder), "cap": trust.cap_eur(holder), "events": events},
    )


@login_required
@require_POST
def trust_contest(request, pk):
    holder = get_object_or_404(Holder, member=request.member)
    event = get_object_or_404(TrustEvent, pk=pk, holder=holder)
    try:
        ticket = trust.contest(event, request.member, request.POST.get("why", ""))
        messages.success(request, _("Thank you. Members elected to review ratings will look at it."))
        return redirect("tickets:detail", number=ticket.number)
    except (trust.TrustError, FundError) as e:
        messages.error(request, str(e))
    return redirect("tradefund:trust")


# --- Purchases from outside (P08.T07) ---


@login_required
def purchase_list(request):
    mine = PurchaseRequest.objects.filter(requester=request.member)
    to_buy = PurchaseRequest.objects.filter(buyer__member=request.member, status="approved")
    open_for_buyers = PurchaseRequest.objects.filter(
        status="approved", pay_method="pooled_to_buyer", buyer__isnull=True
    )
    return render(
        request,
        "tradefund/purchase_list.html",
        {
            "mine": mine[:30],
            "to_buy": to_buy,
            "open_for_buyers": open_for_buyers,
            "is_holder": services.is_holder(request.member),
        },
    )


@login_required
def purchase_new(request):
    member = request.member
    if request.method == "POST":
        p = request.POST
        try:
            pr = purchases.create_purchase(
                member,
                p.get("description", ""),
                p.get("est_price", "0").replace(",", "."),
                currency=(p.get("currency") or "EUR").upper()[:3],
                seller=p.get("seller", ""),
                seller_iban=p.get("seller_iban", ""),
                why=p.get("why", ""),
            )
            messages.success(request, _("Thank you. Your request is with the people who decide."))
            return redirect("tradefund:purchase_detail", pk=pr.pk)
        except (FundError, ArithmeticError, ValueError) as e:
            messages.error(request, str(e) if isinstance(e, FundError) else _("Please check the price."))
    return render(request, "tradefund/purchase_new.html", {})


@login_required
def purchase_detail(request, pk):
    pr = get_object_or_404(PurchaseRequest.objects.select_related("ticket", "buyer__member"), pk=pk)
    member = request.member
    is_buyer = pr.buyer_id is not None and pr.buyer.member_id == member.pk
    if request.method == "POST":
        do = request.POST.get("do")
        try:
            if do == "volunteer":
                purchases.volunteer(pr, member)
                messages.success(request, _("Thank you. You offered to buy it."))
            elif do == "bought":
                upload = request.FILES.get("receipt")
                from apps.members import services as member_services

                try:
                    pf = member_services.store_private_file(member, upload, "receipt") if upload else None
                except member_services.FileRejected as e:
                    raise FundError(str(e)) from None
                purchases.record_purchase(pr, member, pf, request.POST.get("actual_price", "0").replace(",", "."))
                messages.success(request, _("Thank you. The purchase is recorded."))
            elif do == "delivered":
                purchases.mark_delivered(pr, member)
                messages.success(request, _("Thank you. It arrived."))
        except (FundError, ArithmeticError) as e:
            messages.error(request, str(e) if isinstance(e, FundError) else _("Please check the price."))
        return redirect("tradefund:purchase_detail", pk=pk)
    return render(
        request,
        "tradefund/purchase_detail.html",
        {
            "pr": pr,
            "is_buyer": is_buyer,
            "can_volunteer": services.is_holder(member)
            and pr.status == "approved"
            and pr.pay_method == "pooled_to_buyer"
            and pr.buyer_id is None,
            "can_report_bought": (is_buyer and pr.status == "approved" and pr.funded)
            or (
                pr.pay_method == "holder_pays_seller"
                and pr.status == "bought"
                and pr.requester_id == member.pk
                and not pr.receipt_id
            ),
            "can_deliver": pr.status == "bought" and purchases.can_confirm_delivery(pr, member),
        },
    )


# --- Donations (P08.T08) ---


def donate(request):
    """Anyone may donate: the page picks a holder and shows their account number and the reference."""
    from django.conf import settings  # noqa: F401

    from apps.rules.services import get_param

    from . import donations

    context = {"currencies": get_param("tradefund.donation_currencies")}
    if request.method == "POST":
        try:
            donation = donations.pledge(
                request.POST.get("amount", ""),
                request.POST.get("currency", "EUR"),
                donor_member=getattr(request, "member", None),
                donor_name=request.POST.get("name", ""),
            )
            context.update(donation=donation, iban=donations.holder_iban(donation))
        except FundError as e:
            messages.error(request, str(e))
    return render(request, "tradefund/donate.html", context)


@login_required
def my_donations(request):
    from . import donations

    holder = Holder.objects.filter(member=request.member).first()
    if holder is None:
        return redirect("tradefund:become_holder")
    if request.method == "POST":
        try:
            if request.POST.get("do") == "own":
                donations.record_own_donation(holder, request.POST.get("amount", ""))
                messages.success(request, _("Thank you. Your donation was recorded."))
            else:
                donation = get_object_or_404(holder.donations, pk=request.POST.get("donation"))
                donations.confirm_received(donation, request.member, request.POST.get("amount", ""))
                messages.success(request, _("Thank you. The donation is recorded."))
        except FundError as e:
            messages.error(request, str(e))
        return redirect("tradefund:my_donations")
    return render(
        request,
        "tradefund/my_donations.html",
        {
            "holder": holder,
            "pledged": holder.donations.filter(status="pledged"),
            "received": holder.donations.filter(status="received")[:20],
        },
    )
