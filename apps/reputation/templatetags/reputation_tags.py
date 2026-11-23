from django import template

from apps.reputation import services

register = template.Library()


@register.inclusion_tag("reputation/_unit_recognitions.html", takes_context=True)
def unit_recognitions(context, unit):
    rows = services.unit_recognitions(unit)
    return {"rows": [{"r": r, "label": services.label(r)} for r in rows], "request": context.get("request")}


@register.inclusion_tag("reputation/_my_recognitions.html", takes_context=True)
def my_recognitions(context, member):
    rows = services.member_recognitions(member)
    return {
        "rows": [{"r": r, "label": services.label(r)} for r in rows],
        "request": context.get("request"),
        "csrf_token": context.get("csrf_token"),
    }
