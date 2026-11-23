from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import AppendOnlyModel


class UnitOfMeasure(models.Model):
    DIMENSIONS = [
        ("count", _("count")),
        ("mass", _("mass")),
        ("volume", _("volume")),
        ("length", _("length")),
        ("area", _("area")),
        ("energy", _("energy")),
        ("time", _("time")),
        ("service", _("service")),
        ("distance", _("distance")),
    ]

    code = models.CharField(max_length=12, primary_key=True)
    name = models.CharField(max_length=40)
    dimension = models.CharField(max_length=10, choices=DIMENSIONS)

    def __str__(self):
        return self.name


class Item(models.Model):
    """A kind of thing: "rye bread, 750 g", "haircut". Offers (one per unit) say how it is made."""

    KINDS = [("product", _("product")), ("service", _("service"))]
    STATUSES = [("active", _("active")), ("placeholder", _("not made in Unicorn")), ("retired", _("retired"))]

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=8, choices=KINDS)
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="items")
    trade_code = models.CharField(max_length=16, blank=True)
    description = models.TextField(blank=True)
    shelf_life_days = models.PositiveIntegerField(null=True, blank=True)  # empty = keeps; products only
    status = models.CharField(max_length=12, choices=STATUSES, default="active")
    created_by_unit = models.ForeignKey("units.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["name", "uom"], name="unique_item_name_uom")]

    def __str__(self):
        return f"{self.name} ({self.uom_id})"

    def clean(self):
        if self.kind == "service" and self.uom_id not in ("service", "h"):
            raise ValidationError(_("A service is counted per service or per hour."))
        if self.kind == "service" and self.shelf_life_days is not None:
            raise ValidationError(_("Only products have a shelf life."))


class Offer(models.Model):
    """One unit's way of making an item: its cycle, recipe and price. Each offer is its own row of the table."""

    STATUSES = [
        ("draft", _("draft")),
        ("active", _("active")),
        ("paused", _("paused")),
        ("retired", _("retired")),
        ("value_error", _("price cannot be computed")),
    ]
    PLACES = [("unit", _("at the unit")), ("customer", _("at the customer's place")), ("online", _("online"))]
    BASES = [("declared", _("from the recipe")), ("measured", _("measured from the last 3 months"))]

    unit = models.ForeignKey("units.Unit", on_delete=models.PROTECT, related_name="offers")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="offers")
    status = models.CharField(max_length=12, choices=STATUSES, default="draft")
    status_note = models.CharField(max_length=120, blank=True)

    # product cycle
    batch_size = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    min_batch = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    cycle_days = models.PositiveIntegerField(default=0)
    setup_minutes = models.PositiveIntegerField(default=0)
    direct_minutes_per_batch = models.PositiveIntegerField(null=True, blank=True)

    # service cycle
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    travel_minutes = models.PositiveIntegerField(default=0)
    place = models.CharField(max_length=10, choices=PLACES, default="unit")
    max_per_week = models.PositiveIntegerField(null=True, blank=True)

    advance_share = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    paused_for_euros = models.BooleanField(default=False)  # the trade fund is short of euros (P08.T10)
    sold_outside = models.BooleanField(default=False)
    outside_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    outside_currency = models.CharField(max_length=3, default="EUR")
    outside_seller = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )  # the seller of record: a worker of the unit with an active SellerProfile (P10.T01)

    # computed by the value engine only (HF-3)
    declared_hours_per_unit = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    measured_hours_per_unit = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    value_direct = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    value_indirect = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    value_total = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    euro_content = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    values_computed_at = models.DateTimeField(null=True, blank=True)
    value_basis = models.CharField(max_length=10, choices=BASES, default="declared")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["item__name", "unit__name"]

    def __str__(self):
        return f"{self.item.name} by {self.unit.name}"

    @property
    def is_service(self):
        return self.item.kind == "service"

    def clean(self):
        errors = []
        if self.item_id is None:
            return
        if self.item.kind == "product":
            if not self.batch_size or self.batch_size <= 0:
                errors.append(_("A product needs a batch size above zero."))
            if not self.direct_minutes_per_batch or self.direct_minutes_per_batch <= 0:
                errors.append(_("A product needs the working time of a batch."))
            if self.duration_minutes or self.capacity or self.travel_minutes or self.max_per_week:
                errors.append(_("A product has no session fields: duration, capacity, travel or sessions a week."))
        else:
            if not self.duration_minutes or self.duration_minutes <= 0:
                errors.append(_("A service needs a duration above zero."))
            if not self.capacity or self.capacity < 1:
                errors.append(_("A service needs a capacity of at least 1."))
            if self.batch_size or self.min_batch or self.direct_minutes_per_batch or self.setup_minutes:
                errors.append(_("A service has no batch fields: batch size, setup or working time of a batch."))
        if errors:
            raise ValidationError(errors)


class OfferInput(models.Model):
    """One input of a recipe, per batch (or per session), with where it comes from (docs/04 section 5)."""

    SOURCES = [
        ("unicorn", _("Made in Unicorn")),
        ("own_free", _("I provide it free")),
        ("buy_outside", _("Buy it from outside")),
    ]

    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="inputs")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="used_as_input")
    quantity_per_batch = models.DecimalField(max_digits=14, decimal_places=4)
    source = models.CharField(max_length=12, choices=SOURCES)
    preferred_supplier = models.ForeignKey(Offer, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    euro_price_estimate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=3, default="EUR")
    provided_by = models.ForeignKey("members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity_per_batch} {self.item.name} for {self.offer}"


class OfferTool(models.Model):
    """A durable thing a recipe uses again and again."""

    SOURCES = [
        ("unicorn_owned", _("Owned by Unicorn")),
        ("own_free", _("I provide it free")),
        ("to_buy", _("Not there yet: must be bought")),
    ]

    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="tools")
    tool_item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="used_as_tool")
    source = models.CharField(max_length=14, choices=SOURCES)
    uses_per_batch = models.DecimalField(max_digits=14, decimal_places=4)
    lifetime_uses = models.DecimalField(max_digits=14, decimal_places=4)
    value_uniq = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    euro_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EUR")
    provided_by = models.ForeignKey("members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.tool_item.name} for {self.offer}"


class OwnFreeConfirmation(models.Model):
    """A monthly question to a member: do you still provide this input? Answered when `confirmed_at` is set."""

    input = models.ForeignKey(OfferInput, on_delete=models.CASCADE, related_name="confirmations")
    month = models.DateField()  # the first of the month
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["input", "month"], name="one_confirmation_per_month")]

    def __str__(self):
        return f"{self.input} {self.month:%Y-%m}"


class ValueRun(models.Model):
    """One computation of all labour values."""

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    offers = models.PositiveIntegerField(default=0)
    method = models.CharField(max_length=10, default="spsolve")  # spsolve or jacobi
    converged = models.BooleanField(default=True)
    errors = models.JSONField(default=dict, blank=True)  # offer id -> what went wrong

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"value run {self.started_at:%Y-%m-%d %H:%M}"


class OfferValueHistory(AppendOnlyModel):
    """The values of one offer at one run. Append-only: prices have a public history (HF-3)."""

    run = models.ForeignKey(ValueRun, on_delete=models.PROTECT, related_name="history")
    offer = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name="history")
    direct = models.DecimalField(max_digits=18, decimal_places=4)
    indirect = models.DecimalField(max_digits=18, decimal_places=4)
    total = models.DecimalField(max_digits=18, decimal_places=4)
    euro = models.DecimalField(max_digits=18, decimal_places=4)
    basis = models.CharField(max_length=10, default="declared")

    def __str__(self):
        return f"{self.offer} {self.total}"


class JoinForcesSuggestion(models.Model):
    """Two units make the same item and one needs many more hours. Only a suggestion, never an order (HF-10)."""

    STATUSES = [
        ("new", _("new")),
        ("seen", _("seen")),
        ("dismissed", _("not now")),
        ("discussed", _("discussed")),
    ]

    offer_high = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="+")
    offer_low = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="+")
    gap = models.DecimalField(max_digits=10, decimal_places=4)
    status = models.CharField(max_length=10, choices=STATUSES, default="new")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.offer_high} vs {self.offer_low} ({self.status})"
