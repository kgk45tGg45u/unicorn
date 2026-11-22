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
