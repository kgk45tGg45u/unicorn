from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from . import calendar, engine, services, variants, vote
from . import group as group_module
from .models import GroupDecision, GroupSeat, PlanningGroup, PlanPeriod, PlanProposal, PlanVariant


def home(request):
    current = services.running_period()
    upcoming = PlanPeriod.objects.exclude(status__in=("running", "closed")).order_by("-starts_on").first()
    season = upcoming or services.next_period()
    today = services.today()
    return render(
        request,
        "plan/home.html",
        {
            "running": current,
            "variant": current.adopted_variant if current else None,
            "upcoming": upcoming,
            "proposals": services.proposals_by_kind(season),
            "window_open": services.proposals_open(today),
            "opens": calendar.on("proposals_open", today.year),
            "closes": calendar.on("proposals_close", today.year),
            "groups": PlanningGroup.objects.filter(period=season),
            "variants": season.variants.filter(submitted=True),
            "implied_tax": engine.implied_flat_tax(current.adopted_variant)
            if current and current.adopted_variant
            else None,
        },
    )


@login_required
def propose(request):
    if request.method == "POST":
        p = request.POST
        payload = {k: p[k] for k in ("trade_code", "eur", "hours", "key", "value") if p.get(k)}
        try:
            services.file_proposal(request.member, p.get("kind", ""), p.get("title", ""), p.get("brief", ""), payload)
            messages.success(request, _("Your proposal is filed."))
            return redirect("plan:home")
        except services.PlanError as e:
            messages.error(request, str(e))
    return render(request, "plan/propose.html", {"kinds": PlanProposal.KINDS, "window_open": services.proposals_open()})


@login_required
def group_page(request, pk):
    group = get_object_or_404(PlanningGroup, pk=pk)
    member = request.member
    seat = GroupSeat.objects.filter(group=group, member=member, replaced=False).first()
    if request.method == "POST":
        p = request.POST
        try:
            do = p.get("do")
            if do in ("accept", "decline") and seat:
                group_module.answer(seat, do == "accept")
            elif do == "volunteer":
                group_module.volunteer_adviser(member, group, p.get("statement", ""))
            elif do == "hours":
                _entry, cut = group_module.record_hours(member, group, int(p.get("minutes") or 0), p.get("note", ""))
                if cut:
                    messages.info(request, _("Only part of it is paid: the weekly limit was reached."))
            elif do == "vote":
                group_module.vote(
                    get_object_or_404(GroupDecision, pk=p.get("decision"), group=group),
                    member,
                    p.get("answer") == "yes",
                )
            elif do == "approve_adviser":
                from .models import ExpertAdviser

                adviser = get_object_or_404(ExpertAdviser, pk=p.get("adviser"), group=group)
                group_module.propose_adviser(group, member, adviser)
            elif do == "include":
                group_module.open_decision(
                    group, member, "include", _("Include proposal %(id)s") % {"id": p.get("proposal")},
                    {"proposal": int(p["proposal"]), "variant": int(p["variant"])},
                )  # fmt: skip
            elif do == "leave_out":
                variants.leave_out(member, get_object_or_404(PlanProposal, pk=p.get("proposal")), p.get("reason", ""))
            elif do == "new_variant":
                variants.create_variant(member, group.period, p.get("name", ""))
        except (services.PlanError, ValueError) as e:
            messages.error(request, str(e))
        return redirect("plan:group", pk=pk)
    return render(
        request,
        "plan/group.html",
        {
            "group": group,
            "seat": seat,
            "is_seat": seat is not None and seat.accepted is not False,
            "seats": group_module.active_seats(group),
            "advisers": group.advisers.select_related("member"),
            "decisions": group.decisions.all(),
            "variants": group.period.variants.all(),
            "proposals": group.period.proposals.select_related("ticket"),
        },
    )


def variant_page(request, pk):
    variant = get_object_or_404(PlanVariant, pk=pk)
    member = getattr(request, "member", None)
    group = variant.period.groups.filter(kind="yearly").first()
    editor = bool(member and group and group_module.is_seat(member, group)) and not variant.submitted
    if request.method == "POST":
        if member is None:
            return redirect("account_login")
        p = request.POST
        try:
            do = p.get("do")
            if do == "comment":
                vote.comment(variant, member, p.get("body", ""))
            elif do == "param":
                variants.set_parameter(member, variant, p.get("key", ""), _guess(p.get("value", "")))
            elif do == "budget":
                variants.set_budget_line(
                    member, variant, p.get("category"), p.get("hours") or 0, p.get("eur") or 0, p.get("trade_code", "")
                )
            elif do == "invest":
                variants.add_investment(member, variant, p.get("title", ""), p.get("eur") or 0, p.get("hours") or 0)
            elif do == "focus":
                variants.add_focus(member, variant, p.get("text", ""), trade_code=p.get("trade_code", ""))
            elif do == "submit":
                variants.submit_variant(member, variant)
            elif do == "copy":
                variants.copy_variant(member, variant, p.get("name", ""))
            elif do == "check":
                engine.check_variant(variant)
        except (services.PlanError, ValueError) as e:
            messages.error(request, str(e))
        return redirect("plan:variant", pk=pk)
    from .models import CATEGORIES

    return render(
        request,
        "plan/variant.html",
        {
            "variant": variant,
            "editor": editor,
            "check": variant.engine_check or {},
            "brief": vote.brief_for(variant) if variant.submitted else "",
            "differences": vote.differences(variant),
            "categories": CATEGORIES,
            "can_comment": member is not None and variant.period.status == "comments",
            "others": variant.period.variants.exclude(pk=variant.pk),
        },
    )


def compare_page(request, pk, other):
    a = get_object_or_404(PlanVariant, pk=pk)
    b = get_object_or_404(PlanVariant, pk=other, period_id=a.period_id)
    return render(request, "plan/compare.html", {"a": a, "b": b, "diff": variants.compare(a, b)})


def _guess(text):
    """A typed value becomes a number or a truth value when it looks like one."""
    text = (text or "").strip()
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text
