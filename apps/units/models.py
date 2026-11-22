from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.members.models import Licence


def default_cover_radius():
    """The live default radius; falls back to 10 km before the defaults are loaded."""
    from apps.rules.services import get_param

    try:
        return get_param("logistics.default_cover_radius_km")
    except KeyError:
        return Decimal("10")


class Unit(models.Model):
    KINDS = [
        ("production", _("production")),
        ("service", _("service")),
        ("social", _("social")),
        ("courier", _("courier")),
        ("coordination", _("coordination")),
    ]
    MODES = [
        ("continuous", _("continuous")),
        ("on_order", _("on order")),
        ("seasonal", _("seasonal")),
        ("project", _("project")),
    ]
    STATUSES = [
        ("trial", _("trial")),
        ("open", _("open")),
        ("paused", _("paused")),
        ("dormant", _("dormant")),
        ("closing", _("closing")),
        ("closed", _("closed")),
        ("merged", _("merged")),
    ]

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80, unique=True)
    kind = models.CharField(max_length=16, choices=KINDS)
    mode = models.CharField(max_length=12, choices=MODES, default="continuous")
    status = models.CharField(max_length=10, choices=STATUSES, default="trial")
    trade_code = models.CharField(max_length=16, blank=True)
    description = models.TextField(blank=True)

    town = models.CharField(max_length=80, blank=True)
    postcode = models.CharField(max_length=12, blank=True)
    country = models.CharField(max_length=2, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    cover_radius_km = models.DecimalField(max_digits=7, decimal_places=2, default=default_cover_radius)
    cover_postcodes = models.JSONField(default=list, blank=True)

    licence_kind_required = models.CharField(max_length=20, choices=Licence.KINDS, blank=True)
    insurance_confirmed = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="units_created"
    )
    opened_at = models.DateTimeField(null=True, blank=True)
    trial_until = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="merged_from")
    last_activity_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
