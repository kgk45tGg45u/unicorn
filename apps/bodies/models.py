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


class UnionPage(models.Model):
    """A trade standard or training material. Changing a page makes a new version; it needs a union decision."""

    union = models.ForeignKey(Union, on_delete=models.PROTECT, related_name="pages")
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80)
    body_md = models.TextField()
    version = models.PositiveIntegerField(default=1)
    published_at = models.DateTimeField()
    decision = models.ForeignKey(UnionDecision, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["union", "slug", "-version"]
        constraints = [models.UniqueConstraint(fields=["union", "slug", "version"], name="unique_union_page_version")]

    def __str__(self):
        return f"{self.title} (version {self.version})"


class RecipeTemplate(models.Model):
    """A suggested recipe for an item. It is never a price and never binds a unit (docs/05 section 7)."""

    union = models.ForeignKey(Union, on_delete=models.PROTECT, related_name="templates")
    item = models.ForeignKey("catalogue.Item", on_delete=models.PROTECT, related_name="+")
    title = models.CharField(max_length=120)
    notes_md = models.TextField(blank=True)
    published_at = models.DateTimeField()
    decision = models.ForeignKey(UnionDecision, on_delete=models.PROTECT, related_name="+")
    # [{"item": id, "quantity": "per unit of output", "source": "unicorn|own_free|buy_outside"}]
    inputs = models.JSONField(default=list, blank=True)
    # [{"item": id, "source": "unicorn_owned|own_free|to_buy", "uses": "per unit of output", "lifetime_uses": n}]
    tools = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["union", "title"]

    def __str__(self):
        return self.title


class AdviceRequest(models.Model):
    """The secretariat asked a union to advise on a ticket. The ticket's decision method does not change (HF-15)."""

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.PROTECT, related_name="advice_requests")
    union = models.ForeignKey(Union, on_delete=models.PROTECT, related_name="advice_requests")
    trade_code = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["ticket", "union"], name="one_advice_request_each")]

    def __str__(self):
        return f"{self.union.name} advises on {self.ticket.number}"


class AdviceComment(models.Model):
    """A comment written as the union's advice. It is shown first on the ticket and marked "not binding"."""

    request = models.ForeignKey(AdviceRequest, on_delete=models.PROTECT, related_name="comments")
    comment = models.OneToOneField("tickets.Comment", on_delete=models.PROTECT, related_name="advice")

    def __str__(self):
        return f"advice {self.comment_id}"


class ExpertNomination(models.Model):
    """A union names a member as an expert adviser for the planning group. The member must accept (docs/05 s. 8)."""

    STATUSES = [("pending", _("waiting")), ("accepted", _("accepted")), ("declined", _("declined"))]

    union = models.ForeignKey(Union, on_delete=models.PROTECT, related_name="nominations")
    decision = models.ForeignKey(UnionDecision, on_delete=models.PROTECT, related_name="+")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="expert_nominations")
    group = models.ForeignKey("plan.PlanningGroup", on_delete=models.PROTECT, related_name="+")
    statement = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["group", "member", "union"], name="one_nomination_each")]

    def __str__(self):
        return f"{self.union.name} names {self.member.number}"


class LocalCouncil(models.Model):
    """An open assembly of the members who live in an area (docs/05 section 7). Who belongs is computed."""

    LEVELS = [
        ("district", _("district")),
        ("town", _("town")),
        ("region", _("region")),
        ("country", _("country")),
    ]
    STATUSES = [("active", _("active")), ("closed", _("closed"))]

    name = models.CharField(max_length=80)
    country = models.CharField(max_length=2)
    postcode_prefix = models.CharField(max_length=12)
    level = models.CharField(max_length=10, choices=LEVELS)
    status = models.CharField(max_length=8, choices=STATUSES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    ticket = models.ForeignKey("tickets.Ticket", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["country", "postcode_prefix"]
        constraints = [models.UniqueConstraint(fields=["country", "postcode_prefix"], name="one_council_per_area")]

    def __str__(self):
        return self.name


class LocalVolunteer(models.Model):
    """A member of the area who offers to be the council's responsible in turn."""

    council = models.ForeignKey(LocalCouncil, on_delete=models.PROTECT, related_name="volunteers")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="local_volunteering")
    joined_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["council", "joined_at"]

    def __str__(self):
        return f"{self.member.number} volunteers for {self.council.name}"


class LocalResponsibility(models.Model):
    """Who holds the council's responsibility. `ends_at` is empty while current."""

    HOW = [("volunteer", _("volunteer")), ("rotation", _("rotation")), ("handover", _("handover"))]

    council = models.ForeignKey(LocalCouncil, on_delete=models.PROTECT, related_name="responsibilities")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="local_responsibilities")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    how = models.CharField(max_length=10, choices=HOW)
    declined_by = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["council", "-starts_at"]

    def __str__(self):
        return f"{self.member.number} is responsible for {self.council.name}"
