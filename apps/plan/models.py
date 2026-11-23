"""The yearly plan (docs/05 section 8, docs/06 section 2): periods, variants, proposals and the planning group."""

from django.db import models
from django.utils.translation import gettext_lazy as _

CATEGORIES = [
    ("public_services", _("Public services")),
    ("education_research_culture", _("Education, research and culture")),
    ("social_security", _("Social security")),
    ("health_environment_sport", _("Health, environment and sport")),
    ("housing_regional", _("Housing and regional development")),
    ("food_agriculture", _("Food and agriculture")),
    ("water_energy_trade", _("Water, energy and trade")),
    ("transport_communication", _("Transport and communication")),
    ("financial_management", _("Financial management")),
    ("tools", _("Tools")),
    ("materials", _("Materials")),
    ("benefits", _("Benefits")),
    ("operations", _("Operations")),
    ("reserve", _("Reserve")),
]


class PlanPeriod(models.Model):
    """One plan period: a year at first, later more (`plan.period_years`)."""

    STATUSES = [
        ("proposals", _("collecting proposals")),
        ("drafting", _("the planning group drafts")),
        ("comments", _("public comments")),
        ("voting", _("ranked vote")),
        ("adopted", _("adopted, not started")),
        ("running", _("running")),
        ("closed", _("closed")),
    ]

    starts_on = models.DateField()
    ends_on = models.DateField()
    status = models.CharField(max_length=10, choices=STATUSES, default="proposals")
    adopted_variant = models.ForeignKey(
        "plan.PlanVariant", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    referendum = models.ForeignKey(
        "votes.Referendum", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    revote_on = models.DateField(null=True, blank=True)  # a failed quorum: the vote is repeated on this day
    extended_until = models.DateField(null=True, blank=True)  # and the current plan runs on until then
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_on", "-id"]

    def __str__(self):
        return f"plan {self.starts_on} to {self.ends_on}"

    @property
    def months(self) -> int:
        return (self.ends_on.year - self.starts_on.year) * 12 + self.ends_on.month - self.starts_on.month + 1


class PlanVariant(models.Model):
    """One whole plan. The default variant copies the current `plan`-tier defaults."""

    period = models.ForeignKey(PlanPeriod, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=60)
    summary_md = models.TextField(blank=True)
    parameters = models.JSONField(default=dict)  # plan-tier keys -> values
    planned_hours_per_month = models.JSONField(default=list)
    expected_euros_in_per_month = models.JSONField(default=list)
    engine_check = models.JSONField(default=dict)  # the engine's result (`check` is taken by Django)
    forecast = models.ForeignKey("macro.Forecast", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_default = models.BooleanField(default=False)
    submitted = models.BooleanField(default=False)
    proposals = models.ManyToManyField("plan.PlanProposal", blank=True, related_name="variants")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["period", "name"], name="one_variant_name_per_period")]

    def __str__(self):
        return f"{self.name} ({self.period})"


class BudgetLine(models.Model):
    variant = models.ForeignKey(PlanVariant, on_delete=models.CASCADE, related_name="budget_lines")
    category = models.CharField(max_length=32, choices=CATEGORIES)
    trade_code = models.CharField(max_length=16, blank=True)
    hours = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    eur = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.category} {self.trade_code}".strip()


class InvestmentItem(models.Model):
    variant = models.ForeignKey(PlanVariant, on_delete=models.CASCADE, related_name="investments")
    title = models.CharField(max_length=160)
    item = models.ForeignKey("catalogue.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    trade_code = models.CharField(max_length=16, blank=True)
    unit = models.ForeignKey("units.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    eur = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    hours = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    priority = models.PositiveIntegerField(default=100)
    as_project_unit = models.BooleanField(default=False)  # becomes a `project` unit instead of a purchase request
    carried_out_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["priority", "id"]

    def __str__(self):
        return self.title


class FocusItem(models.Model):
    variant = models.ForeignKey(PlanVariant, on_delete=models.CASCADE, related_name="focus_items")
    item = models.ForeignKey("catalogue.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    trade_code = models.CharField(max_length=16, blank=True)
    text = models.CharField(max_length=200)

    def __str__(self):
        return self.text


class ClosureItem(models.Model):
    variant = models.ForeignKey(PlanVariant, on_delete=models.CASCADE, related_name="closures")
    item = models.ForeignKey("catalogue.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    trade_code = models.CharField(max_length=16, blank=True)
    unit = models.ForeignKey("units.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    from_date = models.DateField()
    hearing_until = models.DateField()
    hearing_opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"close {self.trade_code or self.item or self.unit} from {self.from_date}"


class PlanProposal(models.Model):
    """Something a member wants in the yearly plan, with its quick check."""

    KINDS = [
        ("invest", _("invest")),
        ("focus", _("focus")),
        ("close", _("close")),
        ("share_change", _("change a share")),
        ("budget_change", _("change a budget line")),
        ("parameter_change", _("change a default")),
    ]
    STATUSES = [("open", _("open")), ("included", _("included")), ("left_out", _("left out"))]

    ticket = models.OneToOneField("tickets.Ticket", on_delete=models.PROTECT, related_name="plan_proposal")
    period = models.ForeignKey(PlanPeriod, on_delete=models.PROTECT, related_name="proposals")
    kind = models.CharField(max_length=20, choices=KINDS)
    payload = models.JSONField(default=dict)
    quick_check = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    left_out_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"proposal {self.ticket.number}"


class PlanningGroup(models.Model):
    """The randomly drawn group that turns proposals into whole plans."""

    KINDS = [("yearly", _("yearly")), ("long_term", _("long-term"))]

    period = models.ForeignKey(PlanPeriod, on_delete=models.PROTECT, related_name="groups")
    kind = models.CharField(max_length=10, choices=KINDS, default="yearly")
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.PROTECT, related_name="+")
    confirmation = models.ForeignKey(
        "tickets.Confirmation", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    accept_until = models.DateField(null=True, blank=True)
    advisers_until = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.kind} planning group of {self.period}"


class GroupSeat(models.Model):
    group = models.ForeignKey(PlanningGroup, on_delete=models.CASCADE, related_name="seats")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="plan_seats")
    drawn_order = models.PositiveIntegerField()
    accepted = models.BooleanField(null=True, blank=True)
    replaced = models.BooleanField(default=False)

    class Meta:
        ordering = ["drawn_order"]
        constraints = [models.UniqueConstraint(fields=["group", "member"], name="one_seat_per_member_and_group")]

    def __str__(self):
        return f"seat of {self.member.number}"


class ExpertAdviser(models.Model):
    """An adviser writes analyses and answers questions, and does not vote in the group."""

    group = models.ForeignKey(PlanningGroup, on_delete=models.CASCADE, related_name="advisers")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="+")
    nominated_by_union = models.ForeignKey(
        "bodies.Union", null=True, blank=True, on_delete=models.PROTECT, related_name="expert_nominations"
    )
    statement = models.TextField(blank=True)
    approved = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "member"], name="one_adviser_row_per_member")]

    def __str__(self):
        return f"adviser {self.member.number}"


class GroupDecision(models.Model):
    """A vote of the group's seats (a simple majority): which proposals go in, which advisers, which variants."""

    group = models.ForeignKey(PlanningGroup, on_delete=models.CASCADE, related_name="decisions")
    kind = models.CharField(max_length=20)  # include | adviser | submit
    subject = models.CharField(max_length=200)
    payload = models.JSONField(default=dict)
    votes = models.JSONField(default=dict)  # member number -> "yes" | "no"
    status = models.CharField(max_length=10, default="open")  # open | approved | rejected
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.subject


class PlanComment(models.Model):
    variant = models.ForeignKey(PlanVariant, on_delete=models.CASCADE, related_name="comments")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"comment on {self.variant}"
