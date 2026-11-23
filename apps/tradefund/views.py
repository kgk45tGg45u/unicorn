from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import sensitive_action

from . import payments, services, trust
from .models import Holder, PaymentRequest, TrustEvent
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
