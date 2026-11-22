from .models import Unit

COORDINATION_SLUG = "coordination"


def coordination_unit():
    """The one system unit that holds Unicorn's own coordination work."""
    return Unit.objects.get(slug=COORDINATION_SLUG)
