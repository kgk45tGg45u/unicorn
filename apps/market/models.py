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
    HANDED_OVER, DELIVERED, REFUSED, CANCELLED = "handed_over", "delivered", "refused", "cancelled"
    STATUSES = [
        (PLACED, _("placed")),
        (FROM_STOCK, _("taken from the shelf")),
        (IN_PRODUCTION, _("being made")),
        (READY, _("ready")),
        (HANDED_OVER, _("handed over")),
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
    handed_over_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    dispute_text = models.CharField(max_length=300, blank=True)
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
    PURPOSES = [
        ("members", _("for members")),
        ("outside", _("for outside customers")),
        ("accumulation", _("tools and workplaces for Unicorn itself")),
    ]
    purpose = models.CharField(max_length=12, choices=PURPOSES, default="members")
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

    def save(self, *args, **kwargs):
        if self.offer.item.kind == "service":  # HF-9: services cannot be stored
            raise ValueError("A service cannot be put on a shelf.")
        super().save(*args, **kwargs)


class WasteRecord(AppendOnlyModel):
    """Products nobody bought, written off. The next tax balance takes their hours back (HF-9)."""

    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, related_name="waste")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    hours = models.DecimalField(max_digits=18, decimal_places=4)  # quantity x the offer's value when written off
    period = models.ForeignKey("ledger.Period", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quantity} wasted ({self.hours} h)"


class ServiceSlot(models.Model):
    """One session of a service at a time. A service cannot be stored (HF-9): an unused hour is gone."""

    STATUSES = [("open", _("open")), ("full", _("full")), ("cancelled", _("cancelled")), ("done", _("done"))]

    offer = models.ForeignKey("catalogue.Offer", on_delete=models.PROTECT, related_name="slots")
    provider = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="slots")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    capacity_left = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    hours_entry = models.ForeignKey(
        "units.HoursEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )  # the provider's hours for this session, made once
    idle_minutes = models.PositiveIntegerField(default=0)  # the empty seats' share of the session, for the idle light
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "id"]
        indexes = [models.Index(fields=["offer", "status", "starts_at"])]

    def __str__(self):
        return f"{self.offer} at {self.starts_at:%Y-%m-%d %H:%M}"


class Booking(models.Model):
    """A customer's seat in a slot. The price is fixed at booking (HF-3)."""

    STATUSES = [
        ("booked", _("booked")),
        ("performed", _("performed")),
        ("confirmed", _("confirmed")),
        ("disputed", _("disputed")),
        ("no_show", _("did not come")),
        ("cancelled", _("cancelled")),
    ]

    slot = models.ForeignKey(ServiceSlot, on_delete=models.PROTECT, related_name="bookings")
    customer = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="bookings")
    price_uniq = models.DecimalField(max_digits=18, decimal_places=4)
    hold = models.ForeignKey("ledger.Hold", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=STATUSES, default="booked")
    performed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    dispute_text = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["customer", "status"])]

    def __str__(self):
        return f"{self.customer.number} in {self.slot} ({self.status})"


class StandingOrder(models.Model):
    """A subscription to a product, for example a vegetable box every week. Each delivery is a new order line."""

    EVERY = [("week", _("every week")), ("month", _("every month"))]
    STATUSES = [("active", _("active")), ("paused", _("paused")), ("ended", _("ended"))]

    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="standing_orders")
    offer = models.ForeignKey("catalogue.Offer", on_delete=models.PROTECT, related_name="standing_orders")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    every = models.CharField(max_length=6, choices=EVERY)
    next_date = models.DateField()
    status = models.CharField(max_length=8, choices=STATUSES, default="active")
    last_result = models.CharField(max_length=200, blank=True)  # what happened the last time it ran
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["next_date", "id"]
        indexes = [models.Index(fields=["status", "next_date"])]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="standing_quantity_positive")]

    def __str__(self):
        return f"{self.quantity} x {self.offer} {self.get_every_display()} ({self.status})"


class Sale(models.Model):
    """Paying in person: the seller makes a sale in the app, the buyer scans its QR code and confirms."""

    STATUSES = [("open", _("open")), ("paid", _("paid")), ("expired", _("expired"))]

    offer = models.ForeignKey("catalogue.Offer", on_delete=models.PROTECT, related_name="sales")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    seller = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="sales_made")
    code = models.CharField(max_length=10, unique=True)
    amount_uniq = models.DecimalField(max_digits=18, decimal_places=4)  # the price at the time of the sale (HF-3)
    status = models.CharField(max_length=8, choices=STATUSES, default="open")
    expires_at = models.DateTimeField()
    buyer = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="sales_bought"
    )
    stock_lot = models.ForeignKey(StockLot, null=True, blank=True, on_delete=models.PROTECT, related_name="sales")
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"sale {self.code} of {self.quantity} {self.offer} ({self.status})"


class PlausibilityRecord(models.Model):
    """One monthly check of an offer: do the hours paid and the inputs ordered fit the output delivered?"""

    KINDS = [("hours", _("hours against output")), ("inputs", _("inputs against output"))]

    offer = models.ForeignKey("catalogue.Offer", on_delete=models.CASCADE, related_name="plausibility")
    month = models.DateField()  # the first of the month
    kind = models.CharField(max_length=8, choices=KINDS)
    value = models.DecimalField(max_digits=12, decimal_places=4)  # the gap (hours) or the ratio (inputs)
    flagged = models.BooleanField(default=False)
    notified = models.BooleanField(default=False)

    class Meta:
        ordering = ["-month", "offer"]
        constraints = [models.UniqueConstraint(fields=["offer", "month", "kind"], name="one_plausibility_per_month")]

    def __str__(self):
        return f"{self.offer} {self.month:%Y-%m} {self.kind}: {self.value}"


class Review(models.Model):
    """What a buyer or customer says about an offer. It goes to the unit's council as feedback and never touches
    prices, pay or the order in which offers are listed (HF-3, HF-10)."""

    offer = models.ForeignKey("catalogue.Offer", on_delete=models.PROTECT, related_name="reviews")
    order_line = models.OneToOneField(OrderLine, null=True, blank=True, on_delete=models.PROTECT, related_name="review")
    booking = models.OneToOneField(Booking, null=True, blank=True, on_delete=models.PROTECT, related_name="review")
    author = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="reviews")
    stars = models.PositiveSmallIntegerField()
    text = models.TextField(blank=True)
    as_thanks = models.BooleanField(default=False)  # also shown as a thank-you on the unit page
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(stars__gte=1, stars__lte=5), name="review_stars_1_to_5"),
            models.CheckConstraint(
                condition=models.Q(order_line__isnull=False, booking__isnull=True)
                | models.Q(order_line__isnull=True, booking__isnull=False),
                name="review_of_one_thing",
            ),
        ]

    def __str__(self):
        return f"{self.stars} stars for {self.offer}"


class WaitingListEntry(models.Model):
    """'Tell me when it is available.' Shown on the needs board as wanted."""

    member = models.ForeignKey("members.Member", on_delete=models.CASCADE, related_name="waiting")
    item = models.ForeignKey("catalogue.Item", on_delete=models.PROTECT, related_name="waiting")
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["item", "fulfilled_at"])]

    def __str__(self):
        return f"{self.member.number} waits for {self.item.name}"


class SearchMiss(models.Model):
    """A search with no result, counted by area and text. The searcher is never stored (docs/06 section 7)."""

    area = models.CharField(max_length=2)  # the first two digits of the searcher's postcode
    text = models.CharField(max_length=120)  # lower case, trimmed
    month = models.DateField()  # the first of the month
    count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-month", "-count"]
        constraints = [models.UniqueConstraint(fields=["area", "text", "month"], name="one_miss_row_per_month")]

    def __str__(self):
        return f"{self.text} in {self.area} ({self.count})"


class DemandSignal(models.Model):
    """Members' demand against supply for one offer in one month (docs/03 section 9). Only a suggestion (HF-15)."""

    FLAGS = [("", ""), ("wanted", _("wanted")), ("less", _("consider making less ahead"))]

    offer = models.ForeignKey("catalogue.Offer", on_delete=models.CASCADE, related_name="demand_signals")
    month = models.DateField()  # the first of the month
    demand = models.DecimalField(max_digits=14, decimal_places=4)  # ordered + waiting
    supply = models.DecimalField(max_digits=14, decimal_places=4)  # made ahead + made
    ratio = models.DecimalField(max_digits=10, decimal_places=4)
    flag = models.CharField(max_length=8, choices=FLAGS, blank=True, default="")

    class Meta:
        ordering = ["-month", "offer"]
        constraints = [models.UniqueConstraint(fields=["offer", "month"], name="one_signal_per_offer_month")]

    def __str__(self):
        return f"{self.offer} {self.month:%Y-%m}: {self.ratio}"
