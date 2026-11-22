from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import AppendOnlyModel


class Order(models.Model):
    """One purchase by a member. Its lines hold the offer, the price and the status."""

    KINDS = [("member", _("member"))]  # P10 adds "outside"
    DELIVERY_MODES = [("pickup", _("pickup"))]  # P12 adds the courier and the carrier

    buyer = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="orders")
    kind = models.CharField(max_length=8, choices=KINDS, default="member")
    delivery_mode = models.CharField(max_length=16, choices=DELIVERY_MODES, default="pickup")
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"order {self.pk} of {self.buyer.number}"


class OrderLine(models.Model):
    """One offer, one quantity, one price. The price is fixed at ordering (HF-3)."""

    PLACED, FROM_STOCK, IN_PRODUCTION, READY = "placed", "from_stock", "in_production", "ready"
    DELIVERED, REFUSED, CANCELLED = "delivered", "refused", "cancelled"
    STATUSES = [
        (PLACED, _("placed")),
        (FROM_STOCK, _("taken from the shelf")),
        (IN_PRODUCTION, _("being made")),
        (READY, _("ready")),
        (DELIVERED, _("delivered")),
        (REFUSED, _("refused")),
        (CANCELLED, _("cancelled")),
    ]

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="lines")
    offer = models.ForeignKey("catalogue.Offer", on_delete=models.PROTECT, related_name="order_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    price_uniq = models.DecimalField(max_digits=18, decimal_places=4)  # per unit, as it was when ordered (HF-3)
    total_uniq = models.DecimalField(max_digits=18, decimal_places=4)
    hold = models.ForeignKey("ledger.Hold", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=14, choices=STATUSES, default=PLACED)
    due_date = models.DateField(null=True, blank=True)
    production_order = models.ForeignKey(
        "ProductionOrder", null=True, blank=True, on_delete=models.PROTECT, related_name="lines"
    )
    stock_lot = models.ForeignKey("StockLot", null=True, blank=True, on_delete=models.PROTECT, related_name="lines")
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["offer", "status"])]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="orderline_quantity_positive")]

    def __str__(self):
        return f"{self.quantity} x {self.offer} ({self.status})"


class ProductionOrder(models.Model):
    """One batch (or one week of a continuous unit) that a unit makes for orders, the shelf or other units."""

    ORIGINS = [
        ("orders", _("orders")),
        ("advance", _("made ahead")),
        ("own_initiative", _("own initiative")),
        ("input_request", _("input for another unit")),
    ]
    STATUSES = [
        ("open", _("not started")),
        ("started", _("being made")),
        ("done", _("done")),
        ("cancelled", _("cancelled")),
    ]

    offer = models.ForeignKey("catalogue.Offer", on_delete=models.PROTECT, related_name="production_orders")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)  # what the batch will make
    quantity_assigned = models.DecimalField(max_digits=14, decimal_places=4, default=0)  # promised to lines and units
    origin = models.CharField(max_length=14, choices=ORIGINS, default="orders")
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    due_date = models.DateField()
    week_start = models.DateField(null=True, blank=True)  # the Monday, for a continuous unit's weekly order
    started_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    quantity_done = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "id"]
        indexes = [models.Index(fields=["offer", "status"])]

    def __str__(self):
        return f"{self.quantity} x {self.offer} due {self.due_date} ({self.status})"


class WeeklyPlan(models.Model):
    """How much a continuous unit makes each week of an offer, as its council decided."""

    offer = models.ForeignKey("catalogue.Offer", on_delete=models.PROTECT, related_name="weekly_plans")
    quantity_per_week = models.DecimalField(max_digits=14, decimal_places=4)
    set_by = models.ForeignKey(
        "units.CouncilDecision", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    valid_from = models.DateField()

    class Meta:
        ordering = ["offer", "-valid_from", "-id"]

    def __str__(self):
        return f"{self.quantity_per_week} a week of {self.offer} from {self.valid_from}"


class PurchaseNeed(models.Model):
    """What a unit must buy from outside in a month for its recipes. Phase 08 turns these into purchase requests."""

    STATUSES = [("open", _("open")), ("requested", _("requested")), ("covered", _("covered"))]

    unit = models.ForeignKey("units.Unit", on_delete=models.PROTECT, related_name="purchase_needs")
    item = models.ForeignKey("catalogue.Item", on_delete=models.PROTECT, related_name="purchase_needs")
    month = models.DateField()  # the first of the month
    quantity = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    euro_estimate = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="EUR")
    status = models.CharField(max_length=10, choices=STATUSES, default="open")

    class Meta:
        ordering = ["month", "unit", "item"]
        indexes = [models.Index(fields=["unit", "item", "month", "status"])]

    def __str__(self):
        return f"{self.quantity} {self.item.name} for {self.unit.name} in {self.month:%Y-%m}"


class InputRequest(models.Model):
    """One input a production order needs, and where it comes from. No UNIQ move between units (HF-5)."""

    SOURCES = [
        ("unicorn", _("made in Unicorn")),
        ("own_free", _("provided free by a member")),
        ("buy_outside", _("bought from outside")),
    ]
    STATUSES = [
        ("open", _("open")),
        ("confirmed", _("confirmed")),
        ("delivered", _("delivered")),
        ("received", _("received")),
        ("cancelled", _("cancelled")),
    ]

    production_order = models.ForeignKey(ProductionOrder, on_delete=models.PROTECT, related_name="input_requests")
    offer_input = models.ForeignKey(
        "catalogue.OfferInput", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    item = models.ForeignKey("catalogue.Item", on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    source = models.CharField(max_length=12, choices=SOURCES)
    supplier_offer = models.ForeignKey(
        "catalogue.Offer", null=True, blank=True, on_delete=models.PROTECT, related_name="supplies"
    )
    child_production_order = models.ForeignKey(
        ProductionOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="serves_requests"
    )
    provided_by = models.ForeignKey("members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    purchase_need = models.ForeignKey(
        PurchaseNeed, null=True, blank=True, on_delete=models.PROTECT, related_name="requests"
    )
    euro_each = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    currency = models.CharField(max_length=3, default="EUR")
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    due_date = models.DateField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "id"]
        indexes = [models.Index(fields=["production_order", "status"])]

    def __str__(self):
        return f"{self.quantity} {self.item.name} for production order {self.production_order_id} ({self.status})"


class StockLot(models.Model):
    """Products on a unit's shelf: made ahead, made on the unit's own initiative, or refused by a buyer."""

    ORIGINS = [
        ("advance", _("made ahead")),
        ("own_initiative", _("own initiative")),
        ("refused", _("refused by a buyer")),
    ]
    STATUSES = [("available", _("available")), ("sold_out", _("sold out")), ("written_off", _("written off"))]

    offer = models.ForeignKey("catalogue.Offer", on_delete=models.PROTECT, related_name="stock_lots")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    quantity_left = models.DecimalField(max_digits=14, decimal_places=4)
    made_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    origin = models.CharField(max_length=14, choices=ORIGINS)
    status = models.CharField(max_length=12, choices=STATUSES, default="available")
    production_order = models.ForeignKey(
        ProductionOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="stock_lots"
    )

    class Meta:
        ordering = ["made_at", "id"]
        indexes = [models.Index(fields=["offer", "status"])]

    def __str__(self):
        return f"{self.quantity_left} of {self.quantity} {self.offer} ({self.status})"


class WasteRecord(AppendOnlyModel):
    """Products nobody bought, written off. The next tax balance takes their hours back (HF-9)."""

    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, related_name="waste")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    hours = models.DecimalField(max_digits=18, decimal_places=4)  # quantity x the offer's value when written off
    period = models.ForeignKey("ledger.Period", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quantity} wasted ({self.hours} h)"
