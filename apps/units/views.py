from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import sensitive_action

from . import services
from .models import JoinRequest, Unit


def unit_list(request):
    units = Unit.objects.exclude(status__in=["closed", "merged"]).exclude(kind="coordination")
    return render(request, "units/list.html", {"units": units})


def unit_page(request, slug):
    unit = get_object_or_404(Unit, slug=slug)
    member = request.member if request.user.is_authenticated else None
    is_worker = bool(member) and services.is_worker(member, unit)
    can_decide = bool(member) and services.can_decide_joins(member, unit)
    return render(
        request,
        "units/unit.html",
        {
            "unit": unit,
            "workers": [m.member for m in services.workers(unit)],
            "is_worker": is_worker,
            "responsible": services.responsible(unit),
            "i_am_responsible": bool(member)
            and (services.responsible(unit) or None) is not None
            and services.responsible(unit).member_id == member.pk,
            "can_join": bool(member) and not is_worker,
            "requests": unit.join_requests.filter(status="open").select_related("member") if can_decide else [],
        },
    )


@login_required
@require_POST
def request_join(request, slug):
    unit = get_object_or_404(Unit, slug=slug)
    try:
        services.request_to_join(unit, request.member, request.POST.get("message", "")[:500])
        messages.success(request, _("Your request was sent."))
    except services.UnitError as e:
        messages.error(request, str(e))
    return redirect("units:unit", slug=slug)


@sensitive_action
@require_POST
def decide_join(request, pk):
    join_request = get_object_or_404(JoinRequest, pk=pk)
    try:
        services.decide_join(join_request, request.member, request.POST.get("answer") == "accept")
    except services.UnitError as e:
        messages.error(request, str(e))
    return redirect("units:unit", slug=join_request.unit.slug)


@login_required
@require_POST
def leave(request, slug):
    unit = get_object_or_404(Unit, slug=slug)
    try:
        services.leave_unit(request.member, unit)
        messages.success(request, _("You left the unit."))
    except services.UnitError as e:
        messages.error(request, str(e))
    return redirect("units:unit", slug=slug)


def rules_page(request, slug):
    from . import council_rules

    unit = get_object_or_404(Unit, slug=slug)
    rules = council_rules.current(unit)
    ctx = {"unit": unit, "rules": rules}
    if rules:
        ctx["signed"], ctx["unsigned"] = council_rules.signers(unit)
        member = request.member if request.user.is_authenticated else None
        ctx["can_sign"] = bool(member) and member in ctx["unsigned"]
    return render(request, "units/rules.html", ctx)


@sensitive_action
@require_POST
def sign_rules(request, slug):
    from . import council_rules

    unit = get_object_or_404(Unit, slug=slug)
    try:
        council_rules.sign_current(request.member, unit)
        messages.success(request, _("You signed the rules."))
    except council_rules.RulesError as e:
        messages.error(request, str(e))
    return redirect("units:rules", slug=slug)


@login_required
def decision_list(request, slug):
    unit = get_object_or_404(Unit, slug=slug)
    can_open = services.can_decide_joins(request.member, unit)
    if request.method == "POST":
        if not can_open:
            messages.error(request, _("Only the unit's council can open a decision."))
        else:
            decision = services.open_decision(
                request.member,
                unit,
                request.POST.get("title", "")[:120] or _("Untitled"),
                request.POST.get("text", ""),
                request.POST.get("kind", "other")
                if request.POST.get("kind") in ("production", "admission", "outside_prices", "other")
                else "other",
            )
            return redirect("units:decision", pk=decision.pk)
    return render(
        request,
        "units/decisions.html",
        {"unit": unit, "decisions": unit.decisions.order_by("-opens_at"), "can_open": can_open},
    )


@login_required
def decision_page(request, pk):
    from .models import CouncilDecision

    decision = get_object_or_404(CouncilDecision, pk=pk)
    voted = decision.votes.filter(member=request.member).first()
    can_vote = decision.status == "open" and services.is_council_member(request.member, decision.unit) and voted is None
    return render(request, "units/decision.html", {"d": decision, "voted": voted, "can_vote": can_vote})


@sensitive_action
@require_POST
def decision_vote(request, pk):
    from .models import CouncilDecision

    decision = get_object_or_404(CouncilDecision, pk=pk)
    try:
        services.vote(decision, request.member, request.POST.get("vote", ""))
        messages.success(request, _("Your vote was recorded."))
    except services.UnitError as e:
        messages.error(request, str(e))
    return redirect("units:decision", pk=pk)


@login_required
@require_POST
def decline_turn(request, slug):
    unit = get_object_or_404(Unit, slug=slug)
    try:
        services.decline_turn(request.member, unit)
        messages.success(request, _("You declined. The next worker has the responsibility."))
    except services.UnitError as e:
        messages.error(request, str(e))
    return redirect("units:unit", slug=slug)


@login_required
def open_unit(request):
    from .forms import OpenUnitForm

    form = OpenUnitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            unit = services.open_unit(request.member, form.cleaned_data)
        except services.UnitError as e:
            form.add_error(None, str(e))
        else:
            if unit.status == "paused":
                messages.info(request, _("Your unit is waiting for random confirmers to look at it."))
            return redirect("units:unit", slug=unit.slug)
    return render(request, "units/open.html", {"form": form})


@login_required
@require_POST
def reopen(request, slug):
    unit = get_object_or_404(Unit, slug=slug)
    try:
        services.reopen_unit(request.member, unit)
    except services.UnitError as e:
        messages.error(request, str(e))
    return redirect("units:unit", slug=slug)


@login_required
def my_hours(request):
    from datetime import date as date_cls

    from .models import HoursEntry, TimerSession

    member = request.member
    my_units = [m.unit for m in member.unit_memberships.filter(left_at__isnull=True).select_related("unit")]
    if request.method == "POST":
        try:
            unit = next(u for u in my_units if str(u.pk) == request.POST.get("unit"))
            minutes = int(request.POST.get("hours") or 0) * 60 + int(request.POST.get("minutes") or 0)
            day = date_cls.fromisoformat(request.POST.get("date", ""))
            services.record_hours(
                member,
                unit,
                day,
                minutes,
                activity=request.POST.get("activity", "other"),
                note=request.POST.get("note", ""),
            )
            messages.success(request, _("Your hours were sent for approval."))
        except (StopIteration, ValueError) as e:
            messages.error(
                request,
                str(e) if isinstance(e, services.UnitError) else _("Please check the unit, the date and the time."),
            )
        return redirect("units:my_hours")
    entries = list(HoursEntry.objects.filter(member=member).select_related("unit")[:100])
    return render(
        request,
        "units/hours.html",
        {
            "units": my_units,
            "entries": entries,
            "timer": TimerSession.objects.filter(member=member).select_related("unit").first(),
            "activities": HoursEntry.ACTIVITIES,
            "today": services.timezone.now().astimezone(services.BERLIN).date().isoformat(),
        },
    )


@login_required
@require_POST
def timer(request):
    try:
        if request.POST.get("action") == "start":
            unit = get_object_or_404(Unit, pk=request.POST.get("unit"))
            services.start_timer(request.member, unit)
        else:
            services.stop_timer(request.member)
            messages.success(request, _("Your time was saved as a draft. Send it for approval below."))
    except services.UnitError as e:
        messages.error(request, str(e))
    return redirect("units:my_hours")


@login_required
@require_POST
def submit_draft(request, pk):
    from .models import HoursEntry

    entry = get_object_or_404(HoursEntry, pk=pk, member=request.member)
    try:
        services.submit_hours(entry)
        messages.success(request, _("Your hours were sent for approval."))
    except services.UnitError as e:
        messages.error(request, str(e))
    return redirect("units:my_hours")


@login_required
def unit_hours(request, slug):
    unit = get_object_or_404(Unit, slug=slug)
    if not services.is_council_member(request.member, unit) and not services.is_worker(request.member, unit):
        messages.error(request, _("Only workers of the unit can see its hours."))
        return redirect("units:unit", slug=slug)
    return render(
        request,
        "units/unit_hours.html",
        {"unit": unit, "entries": unit.hours.exclude(status="draft").select_related("member")[:200]},
    )


@sensitive_action
def approve_page(request, slug):
    unit = get_object_or_404(Unit, slug=slug)
    if not services.is_council_member(request.member, unit):
        messages.error(request, _("Only council members can approve hours."))
        return redirect("units:unit", slug=slug)
    if request.method == "POST":
        from .models import HoursEntry

        done = 0
        reason = request.POST.get("reason", "")
        for entry in HoursEntry.objects.filter(
            unit=unit, pk__in=[int(x) for x in request.POST.getlist("entry") if x.isdigit()]
        ):
            try:
                if request.POST.get("answer") == "reject":
                    services.reject_hours(entry, request.member, reason)
                else:
                    services.approve_hours(entry, request.member, reason)
                done += 1
            except services.UnitError as e:
                messages.error(request, f"{entry.member.display_name}, {entry.date}: {e}")
        if done:
            messages.success(request, _("Done."))
        return redirect("units:approve", slug=slug)
    return render(request, "units/approve.html", {"unit": unit, "entries": services.waiting_for(request.member, unit)})
