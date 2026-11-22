from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from .models import Item


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
