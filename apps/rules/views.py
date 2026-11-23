from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from .hard_frame import RULES
from .models import Parameter

TIER_WORDS = {
    "unit": _("the unit's council"),
    "confirm": _("4 random members"),
    "plan": _("the yearly plan"),
    "referendum": _("a vote of all members"),
    "hard": _("the hard frame"),
}


def index(request):
    groups = {}
    for p in Parameter.objects.all():
        group = p.key.split(".")[0]
        groups.setdefault(group, []).append({"param": p, "tier_words": TIER_WORDS.get(p.tier, p.tier)})
    return render(request, "rules/index.html", {"rules": RULES, "groups": groups})


def history(request, key):
    param = get_object_or_404(Parameter, key=key)
    return render(request, "rules/history.html", {"param": param, "changes": param.changes.all()})


TIER_ROUTES = {
    "unit": _("Four random members must all say yes. One no sends it to a panel of 12."),
    "confirm": _("Four random members must all say yes. One no sends it to a panel of 12."),
    "plan": _("This is decided in the yearly plan, or by a vote of all members."),
    "referendum": _("Four random members first check that the proposal is complete. Then all members vote."),
    "hard": _("This needs a hard-frame change."),
}


@login_required
def propose(request, key):
    """Propose a new value for one default. The ticket follows the default's tier (HF-16)."""
    from apps.tickets import services as ticket_services

    param = get_object_or_404(Parameter, key=key)
    error = None
    if request.method == "POST":
        raw = request.POST.get("new_value", "").strip()
        value = raw
        if param.type == "bool":
            value = raw.lower() in ("1", "true", "yes", "on")
        elif param.type == "list":
            value = [x.strip() for x in raw.split(",") if x.strip()]
        try:
            ticket = ticket_services.create_parameter_change(request.member, key, value, request.POST.get("reason", ""))
        except ticket_services.TicketError as e:
            error = str(e)
        else:
            return redirect("tickets:detail", number=ticket.number)
    return render(
        request,
        "rules/propose.html",
        {
            "param": param,
            "tier_words": TIER_WORDS.get(param.tier, param.tier),
            "route": TIER_ROUTES.get(param.tier, ""),
            "error": error,
        },
    )
