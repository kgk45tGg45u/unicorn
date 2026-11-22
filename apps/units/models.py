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
    status_note = models.CharField(max_length=120, blank=True)
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


class UnitMembership(models.Model):
    """A member works in a unit. Active while `left_at` is empty."""

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="memberships")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="unit_memberships")
    is_council = models.BooleanField(default=True)
    joined_at = models.DateTimeField()
    left_at = models.DateTimeField(null=True, blank=True)
    # The member id while active, empty after leaving: with the unique constraint, only one active row.
    active_key = models.PositiveIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["joined_at"]
        constraints = [
            models.UniqueConstraint(fields=["unit", "member", "active_key"], name="unique_active_membership"),
        ]

    def __str__(self):
        return f"{self.member.number} in {self.unit.name}"

    def save(self, *args, **kwargs):
        self.active_key = self.member_id if self.left_at is None else None
        super().save(*args, **kwargs)


class JoinRequest(models.Model):
    STATUSES = [("open", _("open")), ("accepted", _("accepted")), ("declined", _("declined"))]

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="join_requests")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="join_requests")
    message = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="join_decisions"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.member.number} asks to join {self.unit.name} ({self.status})"


class CouncilDecision(models.Model):
    KINDS = [
        ("production", _("production")),
        ("admission", _("admission")),
        ("rules_change", _("change of council rules")),
        ("outside_prices", _("outside prices")),
        ("close_unit", _("close the unit")),
        ("other", _("other")),
    ]
    STATUSES = [("open", _("open")), ("approved", _("approved")), ("rejected", _("rejected"))]

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="decisions")
    title = models.CharField(max_length=120)
    text = models.TextField(blank=True)
    kind = models.CharField(max_length=16, choices=KINDS, default="other")
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    opened_by = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="decisions_opened"
    )
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    result = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.title} ({self.status})"


class CouncilVote(models.Model):
    VOTES = [("yes", _("yes")), ("no", _("no")), ("abstain", _("abstain"))]

    decision = models.ForeignKey(CouncilDecision, on_delete=models.PROTECT, related_name="votes")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="council_votes")
    vote = models.CharField(max_length=8, choices=VOTES)
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["decision", "member"], name="one_vote_per_decision")]

    def __str__(self):
        return f"{self.member.number}: {self.vote}"


class CouncilRules(models.Model):
    """A unit's own rules (the optional custom internal contract). The highest version is the current one."""

    DECISION_RULES = [("consensus", _("consensus")), ("majority", _("majority")), ("two_thirds", _("two thirds"))]
    HOURS_APPROVAL = [
        ("any_other_member", _("any other member")),
        ("two_members", _("two members")),
        ("responsible_or_other", _("the responsible, or two others")),
    ]
    ADMISSION = [("open", _("open")), ("council_approves", _("the council approves"))]

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="rules")
    version = models.PositiveIntegerField()
    decision_rule = models.CharField(max_length=12, choices=DECISION_RULES)
    quorum = models.DecimalField(max_digits=4, decimal_places=3)
    vote_days = models.PositiveIntegerField()
    rotation_months = models.PositiveIntegerField()
    hours_approval = models.CharField(max_length=24, choices=HOURS_APPROVAL)
    admission = models.CharField(max_length=20, choices=ADMISSION)
    clauses_md = models.TextField(blank=True)
    adopted_at = models.DateTimeField()
    adopted_by = models.ForeignKey(CouncilDecision, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    template = models.ForeignKey(
        "members.ContractTemplate", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["unit", "-version"]
        constraints = [models.UniqueConstraint(fields=["unit", "version"], name="unique_rules_version")]

    def __str__(self):
        return f"Rules of {self.unit.name}, version {self.version}"


class Responsibility(models.Model):
    """Who holds the council's responsibility. `ends_at` is empty while current."""

    HOW = [
        ("founder", _("founder")),
        ("rotation", _("rotation")),
        ("vote", _("vote")),
        ("handover", _("handover")),
    ]

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="responsibilities")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="responsibilities")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    how = models.CharField(max_length=10, choices=HOW)
    declined_by = models.JSONField(default=list, blank=True)  # member ids who declined this turn

    class Meta:
        ordering = ["unit", "-starts_at"]

    def __str__(self):
        return f"{self.member.number} responsible for {self.unit.name}"


class HoursEntry(models.Model):
    """Hours a member worked for one unit, recorded in whole minutes."""

    ACTIVITIES = [
        ("order", _("production order")),
        ("booking", _("service performed")),
        ("shift", _("shift")),
        ("project", _("project")),
        ("coordination", _("coordination")),
        ("learning", _("learning")),
        ("own_initiative", _("own initiative")),
        ("other", _("other")),
    ]
    STATUSES = [
        ("draft", _("draft")),
        ("submitted", _("waiting for approval")),
        ("approved", _("approved")),
        ("rejected", _("rejected")),
        ("pending_sale", _("paid when the products sell")),
        ("paid", _("paid")),
    ]

    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="hours")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="hours")
    date = models.DateField()
    minutes = models.PositiveIntegerField()  # 1 to 1440
    activity = models.CharField(max_length=16, choices=ACTIVITIES, default="other")
    ref_type = models.CharField(max_length=32, blank=True)
    ref_id = models.CharField(max_length=32, blank=True)
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=14, choices=STATUSES, default="draft")
    needs_extra_approval = models.BooleanField(default=False)
    paid_fraction = models.DecimalField(
        max_digits=7, decimal_places=6, default=0
    )  # of own-initiative hours paid so far
    rejection_reason = models.CharField(max_length=300, blank=True)
    period = models.ForeignKey("ledger.Period", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    transaction = models.ForeignKey(
        "ledger.Transaction", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["member", "date"]), models.Index(fields=["unit", "status"])]

    def __str__(self):
        return f"{self.member.number}: {self.minutes} min for {self.unit.name} on {self.date}"


class TimerSession(models.Model):
    """A running start/stop timer. A member has at most one."""

    member = models.OneToOneField("members.Member", on_delete=models.PROTECT, related_name="timer")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+")
    started_at = models.DateTimeField()

    def __str__(self):
        return f"{self.member.number} timer for {self.unit.name}"


class HoursApproval(models.Model):
    """One approval of an hours entry. `approver` is empty when the system approved (one-person, coordination)."""

    entry = models.ForeignKey(HoursEntry, on_delete=models.PROTECT, related_name="approvals")
    approver = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="hours_approvals"
    )
    approved_at = models.DateTimeField()
    reason = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"approval of entry {self.entry_id}"
