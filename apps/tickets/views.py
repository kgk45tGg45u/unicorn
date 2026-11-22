from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import sensitive_action
from apps.core.models import AuditEvent

from . import confirm, routing, services, types
from .forms import TicketForm
from .models import Comment, Notification, Seat, Ticket


def _status_history(ticket):
    events = AuditEvent.objects.filter(object_type="Ticket", object_id=str(ticket.pk)).order_by("created_at", "id")
    rows = [
        (e.created_at, e.data.get("status") or e.data.get("type") or "") for e in events if e.verb.startswith("ticket.")
    ]
    return [(when, services.status_words(status)) for when, status in rows if status]


@login_required
def ticket_list(request):
    member = request.member
    tab = request.GET.get("tab", "me")
    tickets = Ticket.objects.select_related("author", "scope_unit")
    seats = []
    if tab == "me":
        from apps.units.models import UnitMembership

        units = UnitMembership.objects.filter(member=member, left_at__isnull=True).values_list("unit_id", flat=True)
        tickets = tickets.filter(Q(author=member) | Q(scope_unit_id__in=list(units))).distinct()
        seats = services.my_open_seats(member)
    elif tab == "search":
        q = request.GET.get("q", "").strip()
        tickets = (
            tickets.filter(Q(title__icontains=q) | Q(body_md__icontains=q) | Q(number__icontains=q))
            if q
            else tickets.none()
        )
    kind, status = request.GET.get("type", ""), request.GET.get("status", "")
    if kind:
        tickets = tickets.filter(type=kind)
    if status:
        tickets = tickets.filter(status=status)
    page = Paginator(tickets, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "tickets/list.html",
        {
            "tab": tab,
            "page": page,
            "seats": seats,
            "q": request.GET.get("q", ""),
            "kind": kind,
            "status": status,
            "all_types": types.TYPES.values(),
            "all_statuses": Ticket.STATUSES,
        },
    )


@login_required
def ticket_detail(request, number):
    ticket = get_object_or_404(Ticket.objects.select_related("author", "scope_unit"), number=number)
    comments = list(ticket.comments.select_related("author").prefetch_related("marks"))
    by_parent = {}
    for c in comments:
        by_parent.setdefault(c.parent_id, []).append(c)
    flat = []

    def walk(parent_id, depth):
        for c in by_parent.get(parent_id, []):
            flat.append(
                {"comment": c, "depth": depth, "marks": len(c.marks.all()), "mine": c.author_id == request.member.pk}
            )
            walk(c.pk, min(depth + 1, 3))

    walk(None, 0)
    plan = ticket.plan_check or {}
    return render(
        request,
        "tickets/detail.html",
        {
            "ticket": ticket,
            "comments": flat,
            "history": _status_history(ticket),
            "plan_points": plan.get("points", []),
            "plan_color": plan.get("color", ""),
            "now": timezone.now(),
            "can_comment": services._can_take_part(request.member),
            "suggested": routing.suggest_answerers(ticket),
            "rounds": confirm.seat_rows(ticket),
            "reasons": confirm.reasons(ticket)
            if ticket.status in ("rejected", "approved", "done", "in_action")
            else [],
        },
    )


@login_required
def new_ticket(request):
    return render(request, "tickets/new.html", {"types": types.creatable_types()})


@login_required
def new_ticket_form(request, key):
    info = types.TYPES.get(key)
    if info is None or not info.creatable:
        return redirect("tickets:new")
    form = TicketForm(request.POST or None, info=info)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        unit = d.get("unit")
        payload = {"unit_id": unit.pk} if unit else {}
        try:
            ticket = services.create_ticket(
                key,
                request.member,
                d["title"],
                d.get("body", ""),
                scope="unit" if unit else "all",
                scope_unit=unit,
                brief=d.get("brief", ""),
                check=form.check(),
                action_payload=payload,
            )
        except services.TicketError as e:
            messages.error(request, str(e))
        else:
            return redirect("tickets:detail", number=ticket.number)
    return render(request, "tickets/new_form.html", {"form": form, "info": info})


@login_required
@require_POST
def comment(request, number):
    ticket = get_object_or_404(Ticket, number=number)
    parent = Comment.objects.filter(pk=request.POST.get("parent") or 0, ticket=ticket).first()
    try:
        services.add_comment(ticket, request.member, request.POST.get("body", ""), parent)
    except services.TicketError as e:
        messages.error(request, str(e))
    return redirect("tickets:detail", number=number)


@login_required
@require_POST
def comment_edit(request, pk):
    c = get_object_or_404(Comment, pk=pk)
    try:
        services.edit_comment(c, request.member, request.POST.get("body", ""))
    except services.TicketError as e:
        messages.error(request, str(e))
    return redirect("tickets:detail", number=c.ticket.number)


@login_required
@require_POST
def helpful(request, pk):
    c = get_object_or_404(Comment, pk=pk)
    try:
        services.mark_helpful(c, request.member)
    except services.TicketError as e:
        messages.error(request, str(e))
    return redirect("tickets:detail", number=c.ticket.number)


@login_required
def notifications(request):
    rows = list(Notification.objects.filter(member=request.member)[:100])
    unread = [n.pk for n in rows if n.read_at is None]
    if unread and request.method == "POST":
        Notification.objects.filter(pk__in=unread).update(read_at=timezone.now())
        return redirect("tickets:notifications")
    return render(request, "tickets/notifications.html", {"rows": rows, "unread": len(unread)})


# --- A confirmer's seat (P06.T05) ---


def _my_seat(request, pk):
    return get_object_or_404(
        Seat.objects.select_related("confirmation__ticket", "member"), pk=pk, member=request.member
    )


@login_required
def seat_page(request, pk):
    import random

    seat = _my_seat(request, pk)
    ticket = seat.confirmation.ticket
    state = confirm.seat_state(seat)
    if state in ("check", "vote"):
        confirm.open_seat(seat)
    if request.method == "POST" and state == "check":
        try:
            right = confirm.answer_check(seat, request.POST.get("choice"))
        except confirm.SeatError as e:
            messages.error(request, str(e))
        else:
            if right:
                messages.success(request, _("Right. Now you can answer yes or no."))
            else:
                seat.refresh_from_db()
                if seat.replaced or seat.vote:
                    messages.warning(request, _("That was not right twice, so another member takes this seat."))
                else:
                    hint = ticket.check_hint or _("the brief")
                    messages.error(
                        request, _("That was not right. Read the part about %(hint)s and try again.") % {"hint": hint}
                    )
        return redirect("tickets:seat", pk=seat.pk)
    seat.refresh_from_db()
    state = confirm.seat_state(seat)
    order = list(range(len(ticket.check_choices)))
    random.Random(seat.pk * 7 + seat.check_attempts).shuffle(order)
    return render(
        request,
        "tickets/seat.html",
        {
            "seat": seat,
            "ticket": ticket,
            "state": state,
            "choices": [(i, ticket.check_choices[i]) for i in order],
            "min_reason": confirm.MIN_REASON,
        },
    )


@login_required
@sensitive_action
@require_POST
def seat_vote(request, pk):
    seat = _my_seat(request, pk)
    try:
        confirm.cast(
            seat,
            request.POST.get("vote"),
            request.POST.get("reason", ""),
            anonymous=bool(request.POST.get("anonymous")),
        )
        messages.success(request, _("Thank you. Your answer was recorded."))
    except confirm.SeatError as e:
        messages.error(request, str(e))
    return redirect("tickets:seat", pk=seat.pk)


@login_required
@require_POST
def seat_conflict(request, pk):
    seat = _my_seat(request, pk)
    try:
        confirm.declare_conflict(seat)
        messages.success(request, _("Thank you. Another member takes your seat."))
    except confirm.SeatError as e:
        messages.error(request, str(e))
    return redirect("tickets:list")
