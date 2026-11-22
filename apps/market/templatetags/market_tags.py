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
