from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import uniq
from apps.rules.services import get_param
from apps.units import services as unit_services

from .models import Item, Offer


class CatalogueError(ValueError):
    """A plain-words reason why something cannot be done."""


def find_items(text):
    """Items whose name contains `text`, at most 20, retired ones left out."""
    text = (text or "").strip()
    if not text:
        return Item.objects.none()
    return Item.objects.filter(name__icontains=text).exclude(status="retired").select_related("uom")[:20]


def create_item(name, kind, uom, unit=None, **extra):
    item = Item(name=name.strip(), kind=kind, uom_id=getattr(uom, "pk", uom), created_by_unit=unit, **extra)
    try:
        item.full_clean(validate_unique=False)
    except ValidationError as e:
        raise CatalogueError(" ".join(e.messages)) from None
    if not item.name:
        raise CatalogueError(_("Please give the item a name."))
    try:
        with transaction.atomic():
            item.save()
    except IntegrityError:
        raise CatalogueError(_("There is already an item with this name and unit of measure.")) from None
    return item


def get_or_create_placeholder(name, uom, unit):
    """The item for something Unicorn does not make yet. One per name and unit of measure (docs/04 section 9)."""
    name = name.strip()
    uom_code = getattr(uom, "pk", uom)
    existing = Item.objects.filter(name__iexact=name, uom_id=uom_code).first()
    if existing:
        return existing
    kind = "service" if uom_code in ("service", "h") else "product"
    try:
        with transaction.atomic():
            return Item.objects.create(
                name=name, kind=kind, uom_id=uom_code, status="placeholder", created_by_unit=unit
            )
    except IntegrityError:
        return Item.objects.get(name__iexact=name, uom_id=uom_code)


# --- Offers ---


def declared_hours(offer) -> Decimal:
    """Hours per unit of the item from the recipe (docs/04 section 6)."""
    if offer.item.kind == "product":
        minutes = (offer.direct_minutes_per_batch or 0) + offer.setup_minutes
        return uniq(Decimal(minutes) / 60 / offer.batch_size)
    minutes = (offer.duration_minutes or 0) + (offer.travel_minutes if offer.place == "customer" else 0)
    return uniq(Decimal(minutes) / 60 / offer.capacity)


OFFER_FIELDS = (
    "batch_size",
    "min_batch",
    "cycle_days",
    "setup_minutes",
    "direct_minutes_per_batch",
    "duration_minutes",
    "capacity",
    "travel_minutes",
    "place",
    "max_per_week",
    "sold_outside",
    "outside_price",
    "outside_currency",
)


def _save_offer(offer):
    try:
        offer.full_clean(exclude=["unit", "item"])
    except ValidationError as e:
        raise CatalogueError(" ".join(e.messages)) from None
    if offer.item.kind == "product" and offer.min_batch is None:
        offer.min_batch = offer.batch_size
    offer.declared_hours_per_unit = declared_hours(offer)
    offer.save()
    return offer


def create_offer(member, unit, item, **data):
    """A new draft offer. Only the unit's responsible or council can do it (HF-20)."""
    if not unit_services.can_edit_unit(member, unit):
        raise CatalogueError(_("Only the unit's responsible or council can change its offers."))
    if item.status == "retired":
        raise CatalogueError(_("This item is retired."))
    offer = Offer(unit=unit, item=item, status="draft")
    if item.kind == "product":
        offer.advance_share = Decimal(str(get_param("economy.products.advance_share")))
    for key, value in data.items():
        if key not in OFFER_FIELDS:
            raise CatalogueError(_("Unknown field: %(name)s") % {"name": key})
        setattr(offer, key, value)
    with transaction.atomic():
        _save_offer(offer)
        audit.record(member.number, "offer.created", offer, unit=unit.pk, item=item.pk)
    return offer


def update_offer(member, offer, **data):
    if not unit_services.can_edit_unit(member, offer.unit):
        raise CatalogueError(_("Only the unit's responsible or council can change its offers."))
    for key, value in data.items():
        if key not in OFFER_FIELDS:
            raise CatalogueError(_("Unknown field: %(name)s") % {"name": key})
        setattr(offer, key, value)
    with transaction.atomic():
        _save_offer(offer)
        audit.record(member.number, "offer.updated", offer)
    return offer
