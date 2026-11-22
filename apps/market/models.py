from django.db import models
from django.utils.translation import gettext_lazy as _


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
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["offer", "status"])]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="orderline_quantity_positive")]

    def __str__(self):
        return f"{self.quantity} x {self.offer} ({self.status})"
