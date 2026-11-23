from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import sensitive_action
from apps.tickets.models import Ticket

from . import services
from .models import Petition, Referendum, VoterRecord


def vote_list(request):
    """Open votes, and the published results of closed ones. Results hold counts only."""
    member = getattr(request, "member", None)
    open_ones = Referendum.objects.filter(status__in=["open", "scheduled"]).select_related("ticket")
    voted = set()
    if member is not None:
        voted = set(
            VoterRecord.objects.filter(member=member, referendum__in=open_ones).values_list("referendum_id", flat=True)
        )
    return render(
        request,
        "votes/list.html",
        {
            "open_ones": open_ones,
            "voted": voted,
            "closed": Referendum.objects.filter(status="closed").select_related("ticket")[:50],
            "petitions": Petition.objects.filter(status="open").select_related("ticket"),
        },
    )


def referendum_page(request, pk):
    r = get_object_or_404(Referendum.objects.select_related("ticket", "forecast"), pk=pk)
    member = getattr(request, "member", None)
    voted = member is not None and VoterRecord.objects.filter(referendum=r, member=member).exists()
    open_now = r.status == "open" and timezone.now() < r.closes_at
    return render(
        request,
        "votes/referendum.html",
        {"r": r, "voted": voted, "can_vote": open_now and not voted and member is not None, "now": timezone.now()},
    )


@login_required
@sensitive_action
@require_POST
def cast_vote(request, pk):
    r = get_object_or_404(Referendum, pk=pk)
    choice = request.POST.get("choice")
    if r.method == "ranked_irv":
        choice = [o for o in request.POST.getlist("rank") if o]
    try:
        receipt = services.cast(r, request.member, choice)
    except services.VoteError as e:
        messages.error(request, str(e))
        return redirect("votes:referendum", pk=r.pk)
    return render(request, "votes/receipt.html", {"r": r, "receipt": receipt})


def check_receipt(request):
    ballot, choice = None, ""
    code = request.GET.get("code", "").strip()
    if code:
        ballot = services.check_receipt(code)
    if ballot is not None:
        choice = ", ".join(str(x) for x in ballot.choice) if isinstance(ballot.choice, list) else str(ballot.choice)
    return render(request, "votes/check.html", {"code": code, "ballot": ballot, "choice": choice})


def petition_page(request, pk):
    p = get_object_or_404(Petition.objects.select_related("ticket"), pk=pk)
    member = getattr(request, "member", None)
    signed = member is not None and p.signatures.filter(member=member).exists()
    days_left = max((p.closes_at - timezone.now()).days, 0) if p.status == "open" else 0
    return render(
        request,
        "votes/petition.html",
        {"p": p, "count": p.signatures.count(), "signed": signed, "days_left": days_left},
    )


@login_required
@require_POST
def sign_petition(request, pk):
    p = get_object_or_404(Petition, pk=pk)
    try:
        services.sign(p, request.member)
        messages.success(request, _("Thank you. Your signature was added."))
    except services.VoteError as e:
        messages.error(request, str(e))
    return redirect("votes:petition", pk=p.pk)


@login_required
@require_POST
def open_petition(request, number):
    ticket = get_object_or_404(Ticket, number=number)
    try:
        p = services.open_petition(ticket, request.member, request.POST.get("question", ""))
    except services.VoteError as e:
        messages.error(request, str(e))
        return redirect("tickets:detail", number=number)
    return redirect("votes:petition", pk=p.pk)
