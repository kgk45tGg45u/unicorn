from django.db import models
from django.utils.translation import gettext_lazy as _

from . import types


class TicketCounter(models.Model):
    """A single row that hands out the next ticket number."""

    last = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"last ticket number {self.last}"


class Ticket(models.Model):
    """Any request, proposal, complaint, flag or decision, with its history (docs/05 section 2)."""

    SCOPES = [
        ("unit", _("one unit")),
        ("union", _("one union")),
        ("local", _("one area")),
        ("all", _("all of Unicorn")),
    ]
    STATUSES = [
        ("draft", _("draft")),
        ("open", _("open")),
        ("confirming", _("with random confirmers")),
        ("panel", _("with a panel of 12")),
        ("petition", _("open for a petition")),
        ("referendum", _("in a vote of all members")),
        ("approved", _("approved")),
        ("rejected", _("rejected")),
        ("in_action", _("being carried out")),
        ("done", _("done")),
        ("withdrawn", _("withdrawn")),
        ("expired", _("expired")),
    ]

    number = models.CharField(max_length=9, unique=True)
    type = models.CharField(max_length=32)
    title = models.CharField(max_length=160)
    body_md = models.TextField(blank=True)
    author = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="tickets"
    )

    scope = models.CharField(max_length=6, choices=SCOPES, default="all")
    scope_unit = models.ForeignKey(
        "units.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="tickets"
    )
    scope_union = models.ForeignKey(
        "bodies.Union", null=True, blank=True, on_delete=models.PROTECT, related_name="tickets"
    )
    scope_area = models.CharField(max_length=12, blank=True)
    scope_country = models.CharField(max_length=2, default="DE")  # with scope_area: the area is in this country

    brief_md = models.TextField(blank=True)
    check_question = models.CharField(max_length=300, blank=True)
    check_choices = models.JSONField(default=list, blank=True)
    check_correct = models.PositiveSmallIntegerField(default=0)
    check_hint = models.CharField(max_length=200, blank=True)  # "Read the part about ..." after a wrong answer
    plan_check = models.JSONField(null=True, blank=True)

    decision_method = models.CharField(max_length=12, default="none")
    status = models.CharField(max_length=12, choices=STATUSES, default="open")
    status_note = models.CharField(max_length=300, blank=True)
    action = models.CharField(max_length=40, blank=True)
    action_payload = models.JSONField(default=dict, blank=True)
    action_result = models.JSONField(default=dict, blank=True)

    petition_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["type", "status"])]

    def __str__(self):
        return f"{self.number} {self.title}"

    @property
    def type_info(self):
        return types.TYPES.get(self.type)

    @property
    def decision_question(self) -> str:
        """The question the deciders answer with yes or no."""
        if (self.action_payload or {}).get("then") == "referendum":
            return str(_("Is this proposal complete and understandable? You are not asked whether you agree with it."))
        return str(_("Should this go ahead?"))

    @property
    def type_label(self):
        info = self.type_info
        return info.label if info else self.type


class Comment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="comments")
    author = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="ticket_comments")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replies")
    body_md = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"comment {self.pk} on {self.ticket.number}"


class HelpfulMark(models.Model):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="marks")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="helpful_marks_given")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["comment", "member"], name="one_helpful_mark_each")]

    def __str__(self):
        return f"{self.member.number} found comment {self.comment_id} helpful"


class Notification(models.Model):
    member = models.ForeignKey("members.Member", on_delete=models.CASCADE, related_name="notifications")
    text = models.CharField(max_length=300)
    url = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["member", "read_at"])]

    def __str__(self):
        return f"notification for {self.member.number}"


class Conflict(models.Model):
    """A member declared a conflict of interest on a ticket and is replaced."""

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="conflicts")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="conflicts")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["ticket", "member"], name="one_conflict_each")]

    def __str__(self):
        return f"{self.member.number} has a conflict on {self.ticket.number}"


class Confirmation(models.Model):
    """One random draw for a ticket. Its seed, fingerprint date and eligible-list hash let anyone repeat it."""

    ROUNDS = [
        ("confirmers", "confirmers"),
        ("panel", "panel"),
        ("mediation", "mediation"),
        ("replacement", "replacement"),
        ("group", "group"),
    ]
    STATUSES = [("open", "open"), ("approved", "approved"), ("rejected", "rejected"), ("timed_out", "timed out")]

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="confirmations")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replacements")
    round = models.CharField(max_length=12, choices=ROUNDS)
    size = models.PositiveSmallIntegerField()
    seed = models.CharField(max_length=64)
    fingerprint_date = models.DateField(null=True, blank=True)
    eligible_count = models.PositiveIntegerField()
    eligible_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="open")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.round} draw for {self.ticket.number}"

    @property
    def root(self):
        return self.parent or self


class Seat(models.Model):
    confirmation = models.ForeignKey(Confirmation, on_delete=models.PROTECT, related_name="seats")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="seats")
    drawn_order = models.PositiveSmallIntegerField()
    replaces = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replaced_by")
    notified_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    check_attempts = models.PositiveSmallIntegerField(default=0)
    check_passed = models.BooleanField(default=False)
    vote = models.CharField(max_length=3, choices=[("yes", "yes"), ("no", "no")], null=True, blank=True)  # noqa: DJ001  empty means "not answered yet"
    reason = models.TextField(blank=True)
    voted_at = models.DateTimeField(null=True, blank=True)
    deadline = models.DateTimeField()
    replaced = models.BooleanField(default=False)
    anonymous = models.BooleanField(default=False)  # the member chose not to be named after the decision
    answered = models.BooleanField(default=False)  # false when the "no" is only the system counting silence
    ranking = models.JSONField(null=True, blank=True)  # a ranked list of applicant ids, for choosing a delegate
    paid_entry = models.ForeignKey(
        "units.HoursEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["confirmation_id", "drawn_order"]
        indexes = [models.Index(fields=["member", "vote"])]

    def __str__(self):
        return f"seat {self.pk} of {self.member.number} on {self.confirmation.ticket.number}"


class Flag(models.Model):
    """One member's report of something wrong (docs/05 section 9). Flags on the same thing share one ticket."""

    TARGETS = [(t, t) for t in ("offer", "comment", "ticket", "profile", "hours", "payment", "review")]
    REASONS = [
        ("illegal", _("illegal")),
        ("wrong_data", _("wrong data or fraud")),
        ("harassment", _("harassment")),
        ("privacy", _("privacy")),
        ("other", _("other")),
    ]

    target_type = models.CharField(max_length=10, choices=TARGETS)
    target_id = models.PositiveIntegerField()
    reason = models.CharField(max_length=12, choices=REASONS)
    text = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="flags")
    created_at = models.DateTimeField(auto_now_add=True)
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="flags")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["target_type", "target_id", "created_by"], name="one_flag_each"),
        ]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"flag on {self.target_type} {self.target_id}"


class Hidden(models.Model):
    """Something hidden while members review a report. It is shown again when `until` is set."""

    target_type = models.CharField(max_length=10)
    target_id = models.PositiveIntegerField()
    since = models.DateTimeField(auto_now_add=True)
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="hidden")
    until = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["target_type", "target_id", "until"])]

    def __str__(self):
        return f"{self.target_type} {self.target_id} hidden"


class MediationMessage(models.Model):
    """A message in the private thread of a mediation: only the parties and the mediators can read it."""

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="mediation_messages")
    author = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="mediation_messages")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"message {self.pk} in {self.ticket.number}"
