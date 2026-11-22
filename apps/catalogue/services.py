from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import uniq
from apps.rules.services import get_param
from apps.units import services as unit_services

from .models import Item, Offer, OfferInput, OfferTool, OwnFreeConfirmation


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


# --- Recipes ---


class RecipeBlocked(CatalogueError):
    def __init__(self, messages):
        self.messages = messages
        super().__init__(" ".join(str(m) for m in messages))


def active_offers_of(item):
    return Offer.objects.filter(item=item, status="active")


def validate_recipe(offer) -> list[str]:
    """Plain sentences that say what stops this recipe from being published. Empty means it is fine."""
    problems = []
    workers = {w.member_id for w in unit_services.workers(offer.unit)}
    for r in offer.inputs.select_related("item", "preferred_supplier"):
        name = r.item.name
        if r.source == "unicorn":
            if r.item.status == "placeholder":
                problems.append(
                    _("%(item)s is not made in Unicorn yet. Choose 'I provide it free' or 'Buy it from outside'.")
                    % {"item": name}
                )
            elif not active_offers_of(r.item).exists():
                problems.append(
                    _("Nobody in Unicorn makes %(item)s yet. Choose 'I provide it free' or 'Buy it from outside'.")
                    % {"item": name}
                )
        if r.preferred_supplier_id and (r.source != "unicorn" or r.preferred_supplier.item_id != r.item_id):
            problems.append(_("The preferred supplier of %(item)s must be an offer of that item.") % {"item": name})
        if r.source == "buy_outside":
            if not r.euro_price_estimate or r.euro_price_estimate <= 0:
                problems.append(_("Please estimate the price in euros of %(item)s.") % {"item": name})
            if r.currency != "EUR":
                problems.append(_("For now, outside prices can only be given in euros (%(item)s).") % {"item": name})
        if r.source == "own_free" and (r.provided_by_id is None or r.provided_by_id not in workers):
            problems.append(_("Please say which worker of the unit provides %(item)s free.") % {"item": name})
    for t in offer.tools.select_related("tool_item"):
        name = t.tool_item.name
        if t.source == "to_buy":
            problems.append(_("Buy the tool first: ask the trade fund (%(item)s).") % {"item": name})
        if t.source == "own_free" and (t.provided_by_id is None or t.provided_by_id not in workers):
            problems.append(_("Please say which worker of the unit provides %(item)s free.") % {"item": name})
        if t.source == "unicorn_owned" and not (t.value_uniq > 0 or t.euro_price > 0):
            problems.append(_("Please give the value or the price of the tool %(item)s.") % {"item": name})
    return problems


def _need_editor(member, offer):
    if not unit_services.can_edit_unit(member, offer.unit):
        raise CatalogueError(_("Only the unit's responsible or council can change its offers."))
    if offer.status == "retired":
        raise CatalogueError(_("This offer is retired."))


def add_input(member, offer, name, uom, quantity, source, **extra):
    """Add an input. A name that no item has yet becomes a placeholder (docs/04 section 9)."""
    _need_editor(member, offer)
    item = Item.objects.filter(name__iexact=name.strip(), uom_id=getattr(uom, "pk", uom)).first()
    if item is None:
        item = get_or_create_placeholder(name, uom, offer.unit)
    if Decimal(str(quantity)) <= 0:
        raise CatalogueError(_("The quantity must be above zero."))
    if source not in dict(OfferInput.SOURCES):
        raise CatalogueError(_("Please choose where the input comes from."))
    row = OfferInput.objects.create(offer=offer, item=item, quantity_per_batch=quantity, source=source, **extra)
    audit.record(member.number, "offer.input_added", offer, item=item.pk, source=source)
    return row


def remove_input(member, row):
    _need_editor(member, row.offer)
    row.delete()


def add_tool(member, offer, name, source, uses_per_batch, lifetime_uses, **extra):
    _need_editor(member, offer)
    item = Item.objects.filter(name__iexact=name.strip(), uom_id="pc").first()
    if item is None:
        item = create_item(name, "product", "pc", unit=offer.unit)
    if Decimal(str(uses_per_batch)) <= 0 or Decimal(str(lifetime_uses)) <= 0:
        raise CatalogueError(_("Uses and lifetime must be above zero."))
    row = OfferTool.objects.create(
        offer=offer, tool_item=item, source=source, uses_per_batch=uses_per_batch, lifetime_uses=lifetime_uses, **extra
    )
    audit.record(member.number, "offer.tool_added", offer, item=item.pk, source=source)
    return row


def remove_tool(member, row):
    _need_editor(member, row.offer)
    row.delete()


def _euros_per_batch(offer):
    total = sum(
        (r.quantity_per_batch * r.euro_price_estimate for r in offer.inputs.filter(source="buy_outside")), Decimal(0)
    )
    return total


def request_recompute():
    """Queue one value run. Many edits within a minute make one run."""
    from django.utils import timezone

    from apps.core.jobs import enqueue

    enqueue("catalogue.recompute", dedupe_key=f"catalogue.recompute:{timezone.now():%Y%m%d%H%M}")


def publish_offer(offer, member):
    """Check the recipe, the unit's licence and insurance (HF-17) and the plan, then make the offer active."""
    from apps.plan import check as plan_check

    _need_editor(member, offer)
    with transaction.atomic():
        offer = Offer.objects.select_for_update().get(pk=offer.pk)
        if offer.status in ("active", "retired"):
            raise CatalogueError(_("This offer cannot be published now."))
        problems = validate_recipe(offer)
        unit = offer.unit
        if unit.licence_kind_required:
            from apps.members import services as member_services

            if not any(
                member_services.has_verified_licence(w.member, unit.licence_kind_required)
                for w in unit_services.workers(unit)
            ):
                problems.append(_("This trade needs a licence by law, and nobody in the unit has a verified one."))
        if (unit.kind in ("service", "social") or offer.item.kind == "service") and not unit.insurance_confirmed:
            problems.append(_("A service needs insurance. Please confirm the unit's insurance first."))
        if problems:
            raise RecipeBlocked(problems)
        result = plan_check.check(
            {"type": "offer", "offer": offer.pk, "euros_per_batch": str(_euros_per_batch(offer)), "unit": unit.pk}
        )
        if result.color == "red":
            offer.status_note = _("waiting for random confirmers")
            offer.save(update_fields=["status_note"])
            audit.record(member.number, "offer.publish_held", offer, check="red")
            return offer
        offer.status = "active"
        offer.status_note = ""
        offer.save(update_fields=["status", "status_note"])
        audit.record(member.number, "offer.published", offer, check=result.color)
        on_publish(offer)
        request_recompute()
        return offer


def on_publish(offer):
    """Extension point: P04.T09 makes a placeholder item active here."""


# --- Members confirm "I still provide it free" every month ---


def first_of_month(day):
    return day.replace(day=1)


def confirm_own_free(member, row):
    from django.utils import timezone

    if row.provided_by_id != member.pk:
        raise CatalogueError(_("Only the member who provides it can confirm."))
    month = first_of_month(timezone.localdate())
    conf, _created = OwnFreeConfirmation.objects.get_or_create(input=row, month=month)
    if conf.confirmed_at is None:
        conf.confirmed_at = timezone.now()
        conf.save(update_fields=["confirmed_at"])
    return conf


def ask_own_free(today=None):
    """Monthly: ask every member who provides an input free to confirm. Two months unanswered pause the offer."""
    from django.utils import timezone

    today = today or timezone.localdate()
    month = first_of_month(today)
    prev1 = first_of_month(month - timedelta(days=1))
    prev2 = first_of_month(prev1 - timedelta(days=1))
    paused = 0
    rows = OfferInput.objects.filter(source="own_free", offer__status="active").select_related(
        "offer", "provided_by", "item"
    )
    for row in rows:
        conf, created = OwnFreeConfirmation.objects.get_or_create(input=row, month=month)
        if created and row.provided_by is not None:
            unit_services._notify(
                row.provided_by,
                _("Do you still provide %(item)s?") % {"item": row.item.name},
                _("Please confirm on the recipe page of %(offer)s that you still provide it free.")
                % {"offer": str(row.offer)},
            )
        old = OwnFreeConfirmation.objects.filter(input=row, month__in=[prev1, prev2])
        if old.count() == 2 and not old.filter(confirmed_at__isnull=False).exists() and conf.confirmed_at is None:
            offer = row.offer
            offer.status = "paused"
            offer.status_note = _("waiting for %(item)s to be confirmed") % {"item": row.item.name}
            offer.save(update_fields=["status", "status_note"])
            audit.record("system", "offer.paused_unconfirmed", offer, item=row.item_id)
            boss = unit_services.responsible(offer.unit)
            if boss is not None:
                unit_services._notify(
                    boss.member,
                    _("%(offer)s is paused") % {"offer": str(offer)},
                    _("Nobody confirmed for two months that %(item)s is still provided free.")
                    % {"item": row.item.name},
                )
            paused += 1
    return paused
