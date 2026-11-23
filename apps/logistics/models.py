"""Shipping and fulfilment (docs/06 section 8): postcodes, pickup points, couriers, carriers, shipments."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class PostcodePoint(models.Model):
    """The centre of a postcode, from the open GeoNames dataset (CC BY 4.0)."""

    country = models.CharField(max_length=2)
    postcode = models.CharField(max_length=12)
    town = models.CharField(max_length=120, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["country", "postcode"], name="one_point_per_postcode")]

    def __str__(self):
        return f"{self.country} {self.postcode} {self.town}"


class PickupPoint(models.Model):
    """A public place where orders can be collected: a shop, a community room."""

    name = models.CharField(max_length=120)
    address_public = models.CharField(max_length=200)
    postcode = models.CharField(max_length=12)
    country = models.CharField(max_length=2, default="DE")
    opening_notes = models.CharField(max_length=300, blank=True)
    managed_by_unit = models.ForeignKey(
        "units.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="managed_pickup_points"
    )
    managed_by_local_council_id = models.PositiveIntegerField(null=True, blank=True)  # the FK comes with P13
    manager = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )  # who confirms hand-overs
    serving_units = models.ManyToManyField("units.Unit", blank=True, related_name="pickup_points")
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class CourierOffer(models.Model):
    """The distance-dependent part of a courier's delivery offer."""

    offer = models.OneToOneField("catalogue.Offer", on_delete=models.CASCADE, related_name="courier_offer")
    speed_kmh = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    stop_minutes = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    max_km = models.DecimalField(max_digits=7, decimal_places=2, default=30)

    def __str__(self):
        return f"courier {self.offer_id}"


class Carrier(models.Model):
    """A capitalist carrier, entered by members through a ticket (`confirm` tier)."""

    name = models.CharField(max_length=80)
    countries = models.JSONField(default=list)
    rate_rules = models.JSONField(default=dict)  # {"base_eur": 5.49, "per_kg_eur": 0.0, "max_kg": 31.5}
    currency = models.CharField(max_length=3, default="EUR")
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Shipment(models.Model):
    """How one order line gets to its buyer."""

    MODES = [
        ("pickup", _("pickup at the unit")),
        ("pickup_point", _("pickup at a pickup point")),
        ("unicorn_courier", _("Unicorn courier")),
        ("capitalist_carrier", _("carrier")),
    ]
    STATUSES = [
        ("planned", _("planned")),
        ("sent", _("sent")),
        ("delivered", _("delivered")),
        ("failed", _("failed")),
    ]

    order = models.ForeignKey("market.Order", on_delete=models.PROTECT, related_name="shipments")
    line = models.OneToOneField("market.OrderLine", on_delete=models.PROTECT, related_name="shipment")
    mode = models.CharField(max_length=20, choices=MODES)
    proposed_mode = models.CharField(max_length=20, choices=MODES)
    confirmed_by_responsible = models.BooleanField(default=False)
    courier_line = models.OneToOneField(
        "market.OrderLine", null=True, blank=True, on_delete=models.PROTECT, related_name="courier_shipment"
    )
    courier_member = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    courier_minutes = models.PositiveIntegerField(default=0)
    carrier = models.ForeignKey(Carrier, null=True, blank=True, on_delete=models.PROTECT, related_name="shipments")
    pickup_point = models.ForeignKey(
        PickupPoint, null=True, blank=True, on_delete=models.PROTECT, related_name="shipments"
    )
    purchase_request = models.ForeignKey(
        "tradefund.PurchaseRequest", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    to_postcode = models.CharField(max_length=12, blank=True)
    to_country = models.CharField(max_length=2, blank=True)
    tracking = models.CharField(max_length=80, blank=True)
    problem = models.CharField(max_length=300, blank=True)  # "damaged" or "missing", with the buyer's words
    eur_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    uniq_cost = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    status = models.CharField(max_length=10, choices=STATUSES, default="planned")
    delivered_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"shipment of line {self.line_id} by {self.mode}"
