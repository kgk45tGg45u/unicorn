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

from . import confirm, flags, mediation, routing, services, types
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
    hidden_comments = flags.hidden_ids("comment")

    def walk(parent_id, depth):
        for c in by_parent.get(parent_id, []):
            hidden = c.pk in hidden_comments
            mine = c.author_id == request.member.pk
            flat.append(
                {
                    "comment": c,
                    "depth": depth,
                    "marks": len(c.marks.all()),
                    "mine": mine,
                    "hidden": hidden,
                    "reasons": flags.reasons_for("comment", c.pk) if hidden and mine else [],
                }
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
            "hidden": flags.is_hidden("ticket", ticket.pk) and ticket.author_id != request.member.pk,
            "can_contest": flags.can_contest(ticket, request.member),
            "petition": ticket.petitions.filter(status="open").first(),
            "can_petition": (
                ticket.status == "rejected" and ticket.petition_until and ticket.petition_until > timezone.now()
            )
            or (ticket.type == "referendum_request" and ticket.status == "open"),
            "referendum": ticket.referendums.order_by("-id").first(),
            "has_tasks": ticket.type in ("task_list", "delegate") or ticket.mandates.exists(),
            "is_staff": request.user.is_staff,
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
        payload.update(form.extra_payload())
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
    applicants = []
    if ticket.type == "delegate_choice" and len(ticket.action_payload.get("applicants", [])) > 1:
        from apps.members.models import Member

        applicants = list(Member.objects.filter(pk__in=ticket.action_payload["applicants"]).order_by("display_name"))
    return render(
        request,
        "tickets/seat.html",
        {
            "seat": seat,
            "ticket": ticket,
            "applicants": applicants,
            "document": _licence_document(ticket),
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
    vote, reason = request.POST.get("vote"), request.POST.get("reason", "")
    if vote == "none":  # "none of them" counts as a no (docs/05 section 5)
        vote, reason = "no", _("None of the applicants is the right person.")
    try:
        confirm.cast(
            seat,
            vote,
            reason,
            anonymous=bool(request.POST.get("anonymous")),
            ranking=[x for x in request.POST.getlist("rank") if x],
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


# --- Flags (P06.T08) ---


@login_required
@require_POST
def flag_view(request):
    from django.utils.http import url_has_allowed_host_and_scheme

    try:
        flags.flag(
            request.member,
            request.POST.get("target_type", ""),
            int(request.POST.get("target_id") or 0),
            request.POST.get("reason", ""),
            request.POST.get("text", ""),
        )
        messages.success(request, _("Thank you. Members will look at your report."))
    except flags.FlagError as e:
        messages.error(request, str(e))
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = "/tickets/"
    return redirect(target)


@login_required
@require_POST
def contest_view(request, number):
    ticket = get_object_or_404(Ticket, number=number)
    try:
        new = flags.contest(ticket, request.member)
    except flags.FlagError as e:
        messages.error(request, str(e))
        return redirect("tickets:detail", number=number)
    messages.success(request, _("A panel of 12 members will look at this again."))
    return redirect("tickets:detail", number=new.number)


# --- Mediation (P06.T09) ---


@login_required
def mediation_new(request):
    from apps.members.models import Member
    from apps.units.models import Unit

    form = TicketForm(request.POST or None, info=types.TYPES["mediation"])
    if "unit" in form.fields:
        del form.fields["unit"]
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        other = request.POST.get("other", "").strip()
        member = Member.objects.filter(number=other.upper(), deleted=False).first()
        unit = Unit.objects.filter(slug=other).first()
        try:
            if member is None and unit is None:
                raise mediation.MediationError(_("We could not find that member number or unit."))
            ticket = mediation.open_mediation(
                request.member,
                d["title"],
                d.get("body", ""),
                parties_members=[member] if member else [],
                parties_units=[unit] if unit else [],
                brief=d.get("brief", ""),
                check=form.check(),
            )
        except (mediation.MediationError, services.TicketError) as e:
            messages.error(request, str(e))
        else:
            return redirect("tickets:detail", number=ticket.number)
    return render(request, "tickets/mediation_new.html", {"form": form})


@login_required
def mediation_page(request, number):
    ticket = get_object_or_404(Ticket, number=number, type="mediation")
    member = request.member
    if not mediation._may_see(member, ticket):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    p = ticket.action_payload
    return render(
        request,
        "tickets/mediation.html",
        {
            "ticket": ticket,
            "thread": mediation.messages_for(ticket, member),
            "is_party": mediation.is_party(member, ticket),
            "is_mediator": mediation.is_mediator_of(member, ticket),
            "agreement": p.get("agreement", ""),
            "confirmed": member.number in p.get("confirmed", []),
            "positions": p.get("positions", {}),
            "mine": p.get("positions", {}).get(member.number, ""),
            "open": ticket.status == "confirming",
        },
    )


@login_required
@require_POST
def mediation_action(request, number, action):
    ticket = get_object_or_404(Ticket, number=number, type="mediation")
    member, post = request.member, request.POST
    try:
        if action == "post":
            mediation.post(ticket, member, post.get("body", ""))
        elif action == "position":
            mediation.write_position(ticket, member, post.get("text", ""))
        elif action == "agreement":
            mediation.propose_agreement(ticket, member, post.get("text", ""))
        elif action == "confirm":
            mediation.confirm_agreement(ticket, member)
        elif action == "none":
            mediation.no_agreement(ticket, member)
        elif action == "time":
            mediation.record_time(ticket, member, int(post.get("minutes") or 0))
        else:
            raise mediation.MediationError(_("This is not possible."))
        messages.success(request, _("Done."))
    except (mediation.MediationError, ValueError) as e:
        messages.error(request, str(e))
    return redirect("tickets:mediation", number=number)


def _licence_document(ticket):
    """The licence document a seat on a licence ticket may open (P06.T07)."""
    if ticket.type == "verify_licence":
        return ticket.action_payload.get("document_id")
    return None


# --- Changing the hard frame (P07.T06) ---


@login_required
def hard_frame_new(request):
    from apps.members import services as member_services

    from .forms import HardFrameForm

    form = HardFrameForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            forecast = member_services.store_private_file(request.member, d["forecast"], "other")
            ticket = services.create_hard_frame_change(
                request.member,
                d["rule"],
                d["new_text"],
                d["why"],
                d["code_change"],
                d["authors"],
                forecast,
                check=form.check(),
                brief=d.get("brief", ""),
            )
        except (services.TicketError, member_services.FileRejected) as e:
            messages.error(request, str(e))
        else:
            return redirect("tickets:detail", number=ticket.number)
    return render(request, "tickets/hard_frame.html", {"form": form})


@login_required
@require_POST
def release_view(request, number):
    ticket = get_object_or_404(Ticket, number=number)
    try:
        services.record_release(ticket, request.member, request.POST.get("tag", ""), request.POST.get("commit", ""))
        messages.success(request, _("The release was recorded."))
    except services.TicketError as e:
        messages.error(request, str(e))
    return redirect("tickets:detail", number=number)
