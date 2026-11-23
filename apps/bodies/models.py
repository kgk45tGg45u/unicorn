from django.db import models
from django.utils.translation import gettext_lazy as _


class Union(models.Model):
    """Units of related trades that advise each other and the members. A union never commands (docs/05 section 7)."""

    STATUSES = [("forming", _("forming")), ("active", _("active")), ("dissolved", _("dissolved"))]

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    trade_codes = models.JSONField(default=list)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="forming")
    created_at = models.DateTimeField(auto_now_add=True)
    forming_since = models.DateTimeField(null=True, blank=True)  # set while fewer than the minimum units belong
    created_by_unit = models.ForeignKey("units.Unit", on_delete=models.PROTECT, related_name="unions_formed")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UnionMembership(models.Model):
    """A unit belongs to a union from `joined_at` until `left_at`. A unit has one open membership per union."""

    union = models.ForeignKey(Union, on_delete=models.PROTECT, related_name="memberships")
    unit = models.ForeignKey("units.Unit", on_delete=models.PROTECT, related_name="union_memberships")
    joined_at = models.DateTimeField()
    left_at = models.DateTimeField(null=True, blank=True)
    ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )  # the ticket that let the unit join

    class Meta:
        ordering = ["union", "joined_at"]

    def __str__(self):
        return f"{self.unit.name} in {self.union.name}"


class UnionRules(models.Model):
    """A union's own rules, versioned like a council's. The highest version is the current one."""

    DECISION_RULES = [("consensus", _("consensus")), ("majority", _("majority")), ("two_thirds", _("two thirds"))]

    union = models.ForeignKey(Union, on_delete=models.PROTECT, related_name="rules")
    version = models.PositiveIntegerField()
    decision_rule = models.CharField(max_length=12, choices=DECISION_RULES)
    quorum = models.DecimalField(max_digits=4, decimal_places=3)
    vote_days = models.PositiveIntegerField()
    rotation_months = models.PositiveIntegerField()  # how often a unit's delegate changes
    clauses_md = models.TextField(blank=True)
    adopted_at = models.DateTimeField()

    class Meta:
        ordering = ["union", "-version"]
        constraints = [models.UniqueConstraint(fields=["union", "version"], name="unique_union_rules_version")]

    def __str__(self):
        return f"Rules of {self.union.name}, version {self.version}"
