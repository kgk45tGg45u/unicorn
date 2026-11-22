from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import uniq
from apps.members import services as member_services
from apps.rules.services import get_param
from apps.units import services as unit_services

from .models import Item, Offer, OfferInput, OfferTool, OfferValueHistory, OwnFreeConfirmation, ValueRun


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
    from django.utils import timezone

    row = OfferInput.objects.create(offer=offer, item=item, quantity_per_batch=quantity, source=source, **extra)
    Item.objects.filter(pk=item.pk).update(last_used_at=timezone.now())
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


# Functions (offer, member) called when an offer becomes active, before a placeholder turns into a normal item.
# The market adds one, so that the catalogue never imports it (P05.T12).
PUBLISH_HOOKS: list = []


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
        for hook in PUBLISH_HOOKS:
            hook(offer, member)
        on_publish(offer)
        request_recompute()
        return offer


def on_publish(offer):
    """A placeholder item that someone now makes becomes a normal item; the units that bought it outside are told."""
    item = offer.item
    if item.status != "placeholder":
        return
    item.status = "active"
    item.save(update_fields=["status"])
    p = preview(offer)
    users = (
        OfferInput.objects.filter(item=item, source__in=["own_free", "buy_outside"], offer__status="active")
        .exclude(offer__unit=offer.unit)
        .select_related("offer__unit")
    )
    told = set()
    for row in users:
        unit = row.offer.unit
        if unit.pk in told:
            continue
        told.add(unit.pk)
        for w in unit_services.workers(unit):
            if w.is_council or unit_services.workers(unit).count() == 1:
                unit_services._notify(
                    w.member,
                    _("%(unit)s now makes %(item)s") % {"unit": offer.unit.name, "item": item.name},
                    _(
                        "%(unit)s now makes %(item)s (%(value).2f UNIQ per %(uom)s, €%(euro).2f). "
                        "Switch your input to Unicorn?"
                    )
                    % {
                        "unit": offer.unit.name,
                        "item": item.name,
                        "value": p.total,
                        "uom": item.uom.name,
                        "euro": p.euro,
                    },
                )
    audit.record("system", "item.placeholder_activated", item, units_told=len(told))


def can_switch(row) -> bool:
    return row.source in ("own_free", "buy_outside") and active_offers_of(row.item).exists()


def switch_input_source(row, source, member):
    """Switch an input to Unicorn-made. A unit with a council decides it; a one-person unit switches at once."""
    if source != "unicorn":
        raise CatalogueError(_("An input can only be switched to Made in Unicorn."))
    _need_editor(member, row.offer)
    if not active_offers_of(row.item).exists():
        raise CatalogueError(_("Nobody in Unicorn makes %(item)s yet.") % {"item": row.item.name})
    unit = row.offer.unit
    if unit_services.has_council(unit):
        return unit_services.open_decision(
            member,
            unit,
            _("Switch %(item)s to Made in Unicorn") % {"item": row.item.name},
            _("Use %(item)s from Unicorn in the recipe of %(offer)s instead of providing or buying it outside.")
            % {"item": row.item.name, "offer": str(row.offer)},
            kind="production",
            payload={"switch_input": row.pk},
        )
    _apply_switch(row)
    return None


def _apply_switch(row):
    row.source = "unicorn"
    row.preferred_supplier = None
    row.save(update_fields=["source", "preferred_supplier"])
    audit.record("system", "offer.input_switched", row.offer, item=row.item_id)
    request_recompute()


def _production_decision_action(decision):
    row_id = (decision.payload or {}).get("switch_input")
    if row_id:
        row = OfferInput.objects.filter(pk=row_id, offer__unit=decision.unit).first()
        if row is not None and can_switch(row):
            _apply_switch(row)


unit_services.DECISION_ACTIONS["production"] = _production_decision_action


def retire_placeholders(now=None):
    """Placeholders that nobody has used for `catalogue.placeholder_retire_months` are retired."""
    from django.utils import timezone

    now = now or timezone.now()
    cutoff = member_services._add_months(now, -get_param("catalogue.placeholder_retire_months"))
    count = 0
    for item in Item.objects.filter(status="placeholder"):
        last = item.last_used_at or item.created_at
        if last >= cutoff:
            continue
        if OfferInput.objects.filter(item=item, offer__status__in=["active", "paused", "draft"]).exists():
            continue  # still in a recipe
        item.status = "retired"
        item.save(update_fields=["status"])
        audit.record("system", "item.placeholder_retired", item)
        count += 1
    return count


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


# --- Computing values (the only code that writes an offer's value fields: HF-3) ---

# The market sets these two (P05.T09), so that the catalogue never imports it:
# SUPPLY_WEIGHTS_HOOK(offers_by_item) -> {item_id: {offer_id: share}} from the deliveries of the last months;
# MEASURED_HOURS_HOOK(offer) -> hours per unit measured from approved hours and deliveries, or None.
SUPPLY_WEIGHTS_HOOK = None
MEASURED_HOURS_HOOK = None


def _equal_weights(offers_by_item):
    return {item_id: {o.id: 1 / len(offers) for o in offers} for item_id, offers in offers_by_item.items()}


def _offer_data(offer, hours, q):
    """Hours, depreciation and euros per unit of one offer, as engine input."""
    from .engine import OfferData

    d = m = 0.0
    for t in offer.tools.all():
        if t.source != "unicorn_owned":
            continue
        d += float(t.value_uniq / t.lifetime_uses * t.uses_per_batch) / q
        m += float(t.euro_price / t.lifetime_uses * t.uses_per_batch) / q
    inputs = []
    for r in offer.inputs.all():
        if r.source == "buy_outside":
            m += float(r.quantity_per_batch * (r.euro_price_estimate or 0)) / q
        elif r.source == "unicorn":
            inputs.append((r.item_id, float(r.quantity_per_batch), r.preferred_supplier_id))
    return OfferData(offer.pk, offer.item_id, q, hours, d, m, inputs)


def _quantity(offer):
    return float(offer.batch_size if offer.item.kind == "product" else offer.capacity)


def recompute_values():
    """Compute every price from the recipes and store it. Offers with an error keep their last good values."""
    from django.utils import timezone

    from . import engine

    started = timezone.now()
    with transaction.atomic():
        offers = list(
            Offer.objects.filter(status__in=["active", "value_error"])
            .select_related("item", "unit")
            .prefetch_related("inputs", "tools")
        )
        errors = {}
        # An offer whose Unicorn-made input has no supplier left cannot be priced; this can chain.
        alive = {o.pk: o for o in offers}
        changed = True
        while changed:
            changed = False
            suppliers = {}
            for o in alive.values():
                suppliers.setdefault(o.item_id, []).append(o)
            for o in list(alive.values()):
                for r in o.inputs.all():
                    if r.source != "unicorn":
                        continue
                    ok = (r.preferred_supplier_id in alive) if r.preferred_supplier_id else (r.item_id in suppliers)
                    if not ok:
                        errors[o.pk] = "no_supplier"
                        del alive[o.pk]
                        changed = True
                        break
                else:
                    if any(r.currency != "EUR" for r in o.inputs.all() if r.source == "buy_outside"):
                        errors[o.pk] = "currency"
                        del alive[o.pk]
                        changed = True
        data = []
        for o in alive.values():
            if MEASURED_HOURS_HOOK is not None:
                measured = MEASURED_HOURS_HOOK(o)
                if measured != o.measured_hours_per_unit:
                    o.measured_hours_per_unit = measured
                    o.save(update_fields=["measured_hours_per_unit"])
            use_measured = o.measured_hours_per_unit is not None
            hours = float(o.measured_hours_per_unit if use_measured else declared_hours(o))
            data.append(_offer_data(o, hours, _quantity(o)))
        by_item = {}
        for o in alive.values():
            by_item.setdefault(o.item_id, []).append(o)
        weights = SUPPLY_WEIGHTS_HOOK(by_item) if SUPPLY_WEIGHTS_HOOK else _equal_weights(by_item)
        info = {}
        results = engine.solve(data, weights, info)
        run = ValueRun.objects.create(
            started_at=started,
            offers=len(offers),
            method=info.get("method", "spsolve"),
            converged=info.get("converged", True),
        )
        now = timezone.now()
        for o in offers:
            res = results.get(o.pk)
            if res is not None and res.error:
                errors[o.pk] = res.error
            if o.pk in errors:
                o.status = "value_error"
                o.status_note = _("The price cannot be computed: %(why)s") % {"why": errors[o.pk]}
                o.save(update_fields=["status", "status_note"])
                continue
            basis = "measured" if o.measured_hours_per_unit is not None else "declared"
            o.value_direct = uniq(Decimal(str(res.direct)))
            o.value_indirect = uniq(Decimal(str(res.indirect)))
            o.value_total = uniq(Decimal(str(res.total)))
            o.euro_content = uniq(Decimal(str(res.euro)))
            o.value_basis = basis
            o.values_computed_at = now
            if o.status == "value_error":
                o.status, o.status_note = "active", ""
            o.save()
            OfferValueHistory.objects.create(
                run=run,
                offer=o,
                direct=o.value_direct,
                indirect=o.value_indirect,
                total=o.value_total,
                euro=o.euro_content,
                basis=basis,
            )
        run.errors = {str(k): v for k, v in errors.items()}
        run.finished_at = timezone.now()
        run.save()
        audit.record("system", "catalogue.values_computed", run, offers=len(offers), errors=len(errors))
        return run


@dataclass
class Preview:
    direct: Decimal
    indirect: Decimal
    total: Decimal
    euro: Decimal


def preview(offer) -> Preview:
    """What the recipe would cost, one level deep, using today's values of the inputs' offers."""
    direct = declared_hours(offer)
    q = Decimal(str(_quantity(offer)))
    indirect = euro = Decimal(0)
    for t in offer.tools.all():
        if t.source == "unicorn_owned":
            indirect += t.value_uniq / t.lifetime_uses * t.uses_per_batch / q
            euro += t.euro_price / t.lifetime_uses * t.uses_per_batch / q
    for r in offer.inputs.all():
        if r.source == "buy_outside":
            euro += r.quantity_per_batch * (r.euro_price_estimate or 0) / q
        elif r.source == "unicorn":
            if r.preferred_supplier_id:
                suppliers = [r.preferred_supplier]
            else:
                suppliers = list(active_offers_of(r.item))
            if suppliers:
                value = sum((s.value_total for s in suppliers), Decimal(0)) / len(suppliers)
                eur = sum((s.euro_content for s in suppliers), Decimal(0)) / len(suppliers)
                indirect += r.quantity_per_batch * value / q
                euro += r.quantity_per_batch * eur / q
    return Preview(direct, uniq(indirect), uniq(direct + indirect), uniq(euro))


# --- Lead time ---


def lead_time_days(offer, _depth=0, _seen=None) -> int:
    """Days until a batch is ready: its own cycle, the longest Unicorn-made input, and the outside-input days.

    For an input without a preferred supplier, the quickest active supplier counts. Stock is ignored until P05.
    """
    seen = set(_seen or ())
    if offer.pk in seen or _depth > 10:
        return offer.cycle_days
    seen.add(offer.pk)
    longest = 0
    outside = False
    for r in offer.inputs.select_related("item", "preferred_supplier"):
        if r.source == "buy_outside":
            outside = True
        elif r.source == "unicorn":
            suppliers = [r.preferred_supplier] if r.preferred_supplier_id else list(active_offers_of(r.item))
            if suppliers:
                longest = max(longest, min(lead_time_days(s, _depth + 1, seen) for s in suppliers))
    extra = get_param("market.outside_input_days") if outside else 0
    return offer.cycle_days + longest + extra


# --- "Join forces" suggestions ---

JOIN_FORCES_QUIET_MONTHS = 6


def _near(a, b) -> bool:
    """Until P12 adds coordinates: the same town, or the same first two postcode digits."""
    if a.town and b.town and a.town.strip().lower() == b.town.strip().lower():
        return True
    pa, pb = a.postcode.replace(" ", ""), b.postcode.replace(" ", "")
    return len(pa) >= 2 and len(pb) >= 2 and pa[:2] == pb[:2]


def make_join_forces_suggestions(now=None):
    """For each item with offers in different, nearby units whose values differ by the set gap, suggest it once."""
    from itertools import combinations

    from django.utils import timezone

    from .models import JoinForcesSuggestion

    now = now or timezone.now()
    gap_limit = Decimal(str(get_param("governance.units.join_forces_value_gap")))
    quiet_since = member_services._add_months(now, -JOIN_FORCES_QUIET_MONTHS)
    created = 0
    by_item = {}
    for offer in Offer.objects.filter(status="active", value_total__gt=0).select_related("unit", "item"):
        by_item.setdefault(offer.item_id, []).append(offer)
    for offers in by_item.values():
        for a, b in combinations(offers, 2):
            if a.unit_id == b.unit_id or not _near(a.unit, b.unit):
                continue
            high, low = (a, b) if a.value_total >= b.value_total else (b, a)
            gap = (high.value_total / low.value_total - 1).quantize(Decimal("0.0001"))
            if gap < gap_limit:  # values are stored with 4 decimals, so the gap is compared at 4 decimals
                continue
            pair = JoinForcesSuggestion.objects.filter(
                offer_high__unit=high.unit, offer_low__unit=low.unit, offer_high__item=high.item
            ) | JoinForcesSuggestion.objects.filter(
                offer_high__unit=low.unit, offer_low__unit=high.unit, offer_high__item=high.item
            )
            if pair.filter(status__in=["new", "seen"]).exists():
                continue
            if pair.filter(status__in=["dismissed", "discussed"], decided_at__gte=quiet_since).exists():
                continue
            JoinForcesSuggestion.objects.create(offer_high=high, offer_low=low, gap=gap)
            created += 1
    return created


def suggestions_for_unit(unit):
    from .models import JoinForcesSuggestion

    return (
        JoinForcesSuggestion.objects.filter(status__in=["new", "seen"])
        .filter(models_q_unit(unit))
        .select_related("offer_high__unit", "offer_low__unit", "offer_high__item")
    )


def models_q_unit(unit):
    from django.db.models import Q

    return Q(offer_high__unit=unit) | Q(offer_low__unit=unit)


def suggestion_text(s) -> str:
    high, low = s.offer_high, s.offer_low
    return _(
        "%(high_unit)s and %(low_unit)s both make %(item)s; %(low_unit)s needs %(low).1f h, "
        "%(high_unit)s %(high).1f h. You might share recipes, tools or workers, or join."
    ) % {
        "high_unit": high.unit.name,
        "low_unit": low.unit.name,
        "item": high.item.name.lower(),
        "low": low.value_total,
        "high": high.value_total,
    }


def _can_act(member, suggestion):
    return unit_services.can_decide_joins(member, suggestion.offer_high.unit) or unit_services.can_decide_joins(
        member, suggestion.offer_low.unit
    )


def dismiss_suggestion(member, suggestion):
    from django.utils import timezone

    if not _can_act(member, suggestion):
        raise CatalogueError(_("Only the councils of the two units can answer this."))
    suggestion.status = "dismissed"
    suggestion.decided_at = timezone.now()
    suggestion.save(update_fields=["status", "decided_at"])
    audit.record(member.number, "join_forces.dismissed", suggestion)
    return suggestion


def start_conversation(member, suggestion):
    """Open a council decision of kind `other` in both units (P06 turns it into a `join_forces` ticket)."""
    from django.utils import timezone

    if not _can_act(member, suggestion):
        raise CatalogueError(_("Only the councils of the two units can answer this."))
    text = suggestion_text(suggestion)
    title = _("Talk with %(a)s and %(b)s about making %(item)s together") % {
        "a": suggestion.offer_high.unit.name,
        "b": suggestion.offer_low.unit.name,
        "item": suggestion.offer_high.item.name.lower(),
    }
    with transaction.atomic():
        for unit in (suggestion.offer_high.unit, suggestion.offer_low.unit):
            unit_services.open_system_decision(unit, title, text, kind="other")
        suggestion.status = "discussed"
        suggestion.decided_at = timezone.now()
        suggestion.save(update_fields=["status", "decided_at"])
        audit.record(member.number, "join_forces.discussed", suggestion)
    return suggestion
