from django.shortcuts import get_object_or_404, render
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
