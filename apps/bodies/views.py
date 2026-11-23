"""Pages for unions, local councils and consumers' councils (P13.T11). Reading is open; acting needs a login."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.rules.services import get_param
from apps.tickets.models import Ticket
from apps.units import services as unit_services
from apps.units.models import Unit

from . import consumers, duties, experts, local, services
from .models import (
    ConsumerCouncil,
    Guideline,
    LocalCouncil,
    Union,
    UnionDecision,
)

ERRORS = (services.BodyError, ValueError)


def _me(request):
    return getattr(request, "member", None) if request.user.is_authenticated else None


def _back(request, fallback):
    return redirect(request.POST.get("next") or fallback)


# --- The list ---


def index(request):
    q = (request.GET.get("q") or "").strip()
    unions = Union.objects.exclude(status="dissolved")
    councils = LocalCouncil.objects.filter(status="active")
    consumer = ConsumerCouncil.objects.filter(status="active")
    if q:
        unions = unions.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(trade_codes__icontains=q))
        councils = councils.filter(Q(name__icontains=q) | Q(postcode_prefix__startswith=q))
        consumer = consumer.filter(Q(name__icontains=q) | Q(topic__icontains=q))
    return render(
        request,
        "bodies/index.html",
        {
            "q": q,
            "unions": unions,
            "councils": councils,
            "consumer_councils": consumer,
            "mine": _my_bodies(_me(request)),
        },
    )


# --- Unions ---


def union_page(request, slug):
    union = get_object_or_404(Union, slug=slug)
    me = _me(request)
    delegates = services.current_delegates(union)
    my_row = services.delegate_for(me, union) if me else None
    voted_units = set()
    open_decisions = []
    for d in union.decisions.filter(status="open"):
        voted = set(d.votes.values_list("unit_id", flat=True))
        open_decisions.append(
            {"decision": d, "votes": d.votes.count(), "can_vote": bool(my_row) and my_row.unit_id not in voted}
        )
        voted_units |= voted
    my_units = [u for u in services.member_units(union) if me and unit_services.can_edit_unit(me, u)]
    return render(
        request,
        "bodies/union.html",
        {
            "union": union,
            "units": services.member_units(union),
            "delegates": delegates,
            "rules": services.current_rules(union),
            "pages": duties.latest_pages(union),
            "templates": union.templates.select_related("item"),
            "open_decisions": open_decisions,
            "closed_decisions": union.decisions.exclude(status="open")[:10],
            "advice": union.advice_requests.select_related("ticket")[:20],
            "nominations": union.nominations.select_related("member")[:20],
            "is_delegate": my_row is not None,
            "my_units": my_units,
            "can_act": services.can_act_for(me, union) if me else False,
            "min_units": get_param("governance.unions.min_councils"),
        },
    )


@login_required
def union_new(request):
    me = request.member
    units = [u for u in Unit.objects.exclude(status__in=["closed", "merged"]) if unit_services.can_edit_unit(me, u)]
    if request.method == "POST":
        unit = next((u for u in units if str(u.pk) == request.POST.get("unit")), None)
        try:
            if unit is None:
                raise services.BodyError(_("Please choose one of your units."))
            codes = [c for c in request.POST.get("trade_codes", "").replace(";", ",").split(",")]
            union = services.form_union(
                me, unit, request.POST.get("name", ""), codes, request.POST.get("description", "")
            )
            messages.success(request, _("The union is forming. Your unit's council decides whether the unit joins."))
            return redirect("bodies:union", slug=union.slug)
        except ERRORS as e:
            messages.error(request, str(e))
    return render(request, "bodies/union_new.html", {"units": units})


@login_required
@require_POST
def union_invite(request, slug):
    union = get_object_or_404(Union, slug=slug)
    unit = Unit.objects.filter(slug=request.POST.get("unit", "").strip()).first()
    try:
        if unit is None:
            raise services.BodyError(_("There is no unit with this name."))
        services.invite_unit(request.member, union, unit)
        messages.success(request, _("The invitation was sent to the unit's responsible."))
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:union", slug=slug)


@login_required
@require_POST
def union_leave(request, slug, unit_slug):
    union = get_object_or_404(Union, slug=slug)
    unit = get_object_or_404(Unit, slug=unit_slug)
    try:
        services.leave_union(request.member, union, unit)
        messages.success(request, _("The request to leave was sent to the unit's council."))
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:union", slug=slug)


@login_required
@require_POST
def union_decide(request, slug):
    """A delegate opens a plain decision: a trade standard, or something to record."""
    union = get_object_or_404(Union, slug=slug)
    kind = "standard" if request.POST.get("kind") == "standard" else "other"
    payload = (
        {"title": request.POST.get("title", ""), "body_md": request.POST.get("text", "")} if kind == "standard" else {}
    )
    try:
        services.open_decision(
            request.member, union, request.POST.get("title", ""), request.POST.get("text", ""), kind, payload
        )
        messages.success(request, _("The decision is open for the delegates."))
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:union", slug=slug)


@login_required
@require_POST
def union_vote(request, pk):
    decision = get_object_or_404(UnionDecision, pk=pk)
    try:
        services.vote(decision, request.member, request.POST.get("choice", ""))
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:union", slug=decision.union.slug)


@login_required
@require_POST
def give_advice(request, number, union_pk):
    ticket = get_object_or_404(Ticket, number=number)
    union = get_object_or_404(Union, pk=union_pk)
    try:
        duties.give_advice(ticket, request.member, union, request.POST.get("body", ""))
        messages.success(request, _("Your advice was added."))
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("tickets:detail", number=number)


# --- Expert nominations ---


@login_required
def nominations(request):
    return render(request, "bodies/nominations.html", {"rows": experts.pending_for(request.member)})


@login_required
@require_POST
def nomination_answer(request, pk):
    from .models import ExpertNomination

    nomination = get_object_or_404(ExpertNomination, pk=pk)
    try:
        if request.POST.get("answer") == "accept":
            experts.accept(nomination, request.member)
            messages.success(request, _("Thank you. The planning group will decide whether to approve you."))
        else:
            experts.decline(nomination, request.member)
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:nominations")


# --- Local councils ---


def local_page(request, pk):
    council = get_object_or_404(LocalCouncil, pk=pk)
    me = _me(request)
    needs = local.area_needs(council)
    return render(
        request,
        "bodies/local.html",
        {
            "council": council,
            "member_count": local.members_in_area(council.country, council.postcode_prefix).count(),
            "responsible": local.current_responsible(council),
            "volunteers": local.active_volunteers(council),
            "belongs": bool(me) and local.belongs(me, council),
            "i_volunteer": bool(me) and any(v.member_id == me.pk for v in local.active_volunteers(council)),
            "tickets": local.area_tickets(council)[:20],
            "task_lists": local.area_task_lists(council)[:20],
            "needs": needs,
            "points": local.area_pickup_points(council),
            "helpers": local.area_helpers(council),
        },
    )


@login_required
def local_new(request):
    if request.method == "POST":
        try:
            ticket = local.propose_council(
                request.member,
                request.POST.get("name", ""),
                request.POST.get("prefix", ""),
                request.POST.get("level", "town"),
            )
            messages.success(request, _("Random members of the area will now decide."))
            return redirect("tickets:detail", number=ticket.number)
        except ERRORS as e:
            messages.error(request, str(e))
    return render(
        request,
        "bodies/local_new.html",
        {"levels": LocalCouncil.LEVELS, "needed": get_param("governance.local.min_members")},
    )


@login_required
@require_POST
def local_volunteer(request, pk):
    council = get_object_or_404(LocalCouncil, pk=pk)
    try:
        if request.POST.get("do") == "withdraw":
            local.withdraw(request.member, council)
        else:
            local.volunteer(request.member, council)
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:local", pk=pk)


@login_required
@require_POST
def local_decide(request, pk):
    council = get_object_or_404(LocalCouncil, pk=pk)
    try:
        ticket = local.propose_decision(
            request.member, council, request.POST.get("title", ""), request.POST.get("text", "")
        )
        messages.success(request, _("Random members of the area will now decide."))
        return redirect("tickets:detail", number=ticket.number)
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:local", pk=pk)


# --- Consumers' councils ---


def consumer_page(request, pk):
    council = get_object_or_404(ConsumerCouncil, pk=pk)
    me = _me(request)
    open_votes = []
    for g in council.guidelines.filter(status="voting"):
        mine = g.votes.filter(member=me).exists() if me else True
        open_votes.append(
            {
                "guideline": g,
                "votes": g.votes.count(),
                "can_vote": bool(me) and consumers.is_member(me, council) and not mine,
            }
        )
    return render(
        request,
        "bodies/consumer.html",
        {
            "council": council,
            "members": consumers.members(council),
            "is_member": bool(me) and consumers.is_member(me, council),
            "published": consumers.published(council),
            "open_votes": open_votes,
            "tickets": Ticket.objects.filter(author__in=consumers.members(council), type__in=("complaint", "idea"))[
                :10
            ],
        },
    )


@login_required
def consumer_new(request):
    if request.method == "POST":
        try:
            council = consumers.create_council(
                request.member,
                request.POST.get("name", ""),
                request.POST.get("topic", ""),
                request.POST.get("description", ""),
            )
            return redirect("bodies:consumer", pk=council.pk)
        except ERRORS as e:
            messages.error(request, str(e))
    return render(request, "bodies/consumer_new.html")


@login_required
@require_POST
def consumer_membership(request, pk):
    council = get_object_or_404(ConsumerCouncil, pk=pk)
    try:
        if request.POST.get("do") == "leave":
            consumers.leave(request.member, council)
        else:
            consumers.join(request.member, council)
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:consumer", pk=pk)


@login_required
@require_POST
def guideline_propose(request, pk):
    council = get_object_or_404(ConsumerCouncil, pk=pk)
    try:
        consumers.propose_guideline(
            request.member, council, request.POST.get("title", ""), request.POST.get("text", "")
        )
        messages.success(request, _("The members can vote for 7 days."))
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:consumer", pk=pk)


@login_required
@require_POST
def guideline_vote(request, pk):
    guideline = get_object_or_404(Guideline, pk=pk)
    try:
        consumers.vote(guideline, request.member, request.POST.get("choice", ""))
    except ERRORS as e:
        messages.error(request, str(e))
    return redirect("bodies:consumer", pk=guideline.council_id)


# --- My bodies, for the dashboard ---


def _my_bodies(member):
    """The bodies a member belongs to, and anything that waits for them."""
    if member is None:
        return None
    from apps.units.models import UnitMembership

    unit_ids = UnitMembership.objects.filter(member=member, left_at__isnull=True).values("unit_id")
    from .models import ConsumerMembership, ExpertNomination, UnionMembership

    unions = list(
        Union.objects.filter(
            pk__in=UnionMembership.objects.filter(unit_id__in=unit_ids, left_at__isnull=True).values("union_id")
        ).exclude(status="dissolved")
    )
    waiting = []
    for union in unions:
        row = services.delegate_for(member, union)
        if row is None:
            continue
        for d in union.decisions.filter(status="open"):
            if not d.votes.filter(unit=row.unit).exists():
                waiting.append(
                    {
                        "text": _("Vote for your unit: %(title)s") % {"title": d.title},
                        "url": f"/bodies/unions/{union.slug}/",
                    }
                )
    for n in ExpertNomination.objects.filter(member=member, status="pending"):
        waiting.append(
            {
                "text": _("%(union)s names you as an expert adviser") % {"union": n.union.name},
                "url": "/bodies/nominations/",
            }
        )
    invites = Ticket.objects.filter(type="union_join", status="draft", author=member)
    for t in invites:
        waiting.append({"text": t.title, "url": f"/tickets/{t.number}/"})
    consumer_ids = ConsumerMembership.objects.filter(member=member, left_at__isnull=True).values("council_id")
    consumer = list(ConsumerCouncil.objects.filter(pk__in=consumer_ids, status="active"))
    for c in consumer:
        for g in c.guidelines.filter(status="voting"):
            if not g.votes.filter(member=member).exists():
                waiting.append(
                    {
                        "text": _("Vote on the guideline: %(title)s") % {"title": g.title},
                        "url": f"/bodies/consumers/{c.pk}/",
                    }
                )
    return {"unions": unions, "local": local.councils_of(member), "consumers": consumer, "waiting": waiting}


def my_bodies(member):
    return _my_bodies(member)
