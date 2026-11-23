from django import template

from apps.macro import lights as lights_module

register = template.Library()


@register.inclusion_tag("partials/lights.html")
def show_lights():
    data = lights_module.latest()
    return {"lights": [(key, row) for key, row in data.items()]}


@register.inclusion_tag("macro/_forecasts.html")
def show_forecasts(ticket):
    return {"forecasts": ticket.forecasts.select_related("author")}
