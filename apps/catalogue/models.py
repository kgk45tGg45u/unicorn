from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


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
