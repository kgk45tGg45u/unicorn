from django import template

from apps.macro import lights as lights_module

register = template.Library()


@register.inclusion_tag("partials/lights.html")
def show_lights():
    data = lights_module.latest()
    return {"lights": [(key, row) for key, row in data.items()]}
