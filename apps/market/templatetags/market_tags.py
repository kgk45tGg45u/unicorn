from django import template

from apps.market import services

register = template.Library()


@register.inclusion_tag("market/_reviews.html", takes_context=True)
def offer_reviews(context, offer):
    """The average stars and the latest 10 reviews of an offer. The unit's council also gets a link to all of them."""
    request = context.get("request")
    member = getattr(request, "member", None)
    average, count = services.review_summary(offer)
    from apps.units import services as unit_services

    return {
        "offer": offer,
        "average": average,
        "count": count,
        "reviews": services.latest_reviews(offer),
        "is_council": bool(member) and unit_services.is_council_member(member, offer.unit),
    }


@register.inclusion_tag("market/_order_box.html", takes_context=True)
def offer_order_box(context, offer):
    """The order form of a product, or the booking calendar of a service."""
    request = context.get("request")
    member = getattr(request, "member", None)
    box = {
        "offer": offer,
        "member": member,
        "orderable": offer.status == "active" and offer.unit.status in ("trial", "open"),
        "can_buy": bool(member) and services.can_buy(member),
        "request": request,
    }
    if offer.is_service:
        box["slots"] = services.open_slots(offer)
    else:
        box["expected"] = services.expected_date(offer)
    return box


@register.filter
def qty(value):
    """A quantity without trailing zeros: 1.2000 becomes 1.2 and 2.0000 becomes 2."""
    from decimal import Decimal

    try:
        return format(Decimal(str(value)).normalize(), "f")
    except Exception:
        return value
