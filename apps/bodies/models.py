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
    adopted_by = models.ForeignKey(
        "UnionDecision", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )  # empty for version 1

    class Meta:
        ordering = ["union", "-version"]
        constraints = [models.UniqueConstraint(fields=["union", "version"], name="unique_union_rules_version")]

    def __str__(self):
        return f"Rules of {self.union.name}, version {self.version}"


class UnionDelegate(models.Model):
    """The member who speaks for a unit in its union. `ends_at` is empty while current."""

    HOW = [("first", _("first")), ("rotation", _("rotation")), ("handover", _("handover"))]

    union = models.ForeignKey(Union, on_delete=models.PROTECT, related_name="delegates")
    unit = models.ForeignKey("units.Unit", on_delete=models.PROTECT, related_name="union_delegates")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="union_delegations")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    how = models.CharField(max_length=10, choices=HOW)
    declined_by = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["union", "unit", "-starts_at"]

    def __str__(self):
        return f"{self.member.number} for {self.unit.name} in {self.union.name}"


class UnionDecision(models.Model):
    """A decision of the union's delegates. It binds only the union's own work (HF-15, HF-20)."""

    KINDS = [
        ("standard", _("trade standard")),
        ("recipe_template", _("recipe template")),
        ("nominate_expert", _("name an expert adviser")),
        ("training", _("training")),
        ("rules_change", _("change of the union's rules")),
        ("other", _("other")),
    ]
    STATUSES = [("open", _("open")), ("approved", _("approved")), ("rejected", _("rejected"))]

    union = models.ForeignKey(Union, on_delete=models.PROTECT, related_name="decisions")
    title = models.CharField(max_length=120)
    text = models.TextField(blank=True)
    kind = models.CharField(max_length=16, choices=KINDS, default="other")
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    opened_by = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="union_decisions_opened"
    )
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    result = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.title} ({self.status})"


class UnionVote(models.Model):
    """One vote for each member unit, cast by its delegate."""

    VOTES = [("yes", _("yes")), ("no", _("no")), ("abstain", _("abstain"))]

    decision = models.ForeignKey(UnionDecision, on_delete=models.PROTECT, related_name="votes")
    unit = models.ForeignKey("units.Unit", on_delete=models.PROTECT, related_name="+")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="union_votes")
    vote = models.CharField(max_length=8, choices=VOTES)
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["decision", "unit"], name="one_union_vote_per_unit")]

    def __str__(self):
        return f"{self.unit.name}: {self.vote}"
