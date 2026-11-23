from django.db import models
from django.utils.translation import gettext_lazy as _


class MandateApplication(models.Model):
    """A volunteer for a decision that needs one person to carry it out (docs/05 section 5 item 2)."""

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.PROTECT, related_name="mandate_applications")
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="mandate_applications")
    statement = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["ticket", "member"], name="one_application_each")]

    def __str__(self):
        return f"{self.member.number} applies for {self.ticket.number}"


class Mandate(models.Model):
    """Power given to one delegate for one decision only (glossary: Mandate)."""

    STATUSES = [
        ("active", _("active")),
        ("done", _("done")),
        ("revoked", _("revoked")),
        ("expired", _("expired")),
    ]

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.PROTECT, related_name="mandates")
    delegate = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="mandates")
    scope_md = models.TextField()
    powers = models.JSONField(default=dict)  # spend_limit_eur, may_sign, may_represent, other
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=8, choices=STATUSES, default="active")
    report_md = models.TextField(blank=True)
    report_at = models.DateTimeField(null=True, blank=True)
    hours_entry = models.ForeignKey(
        "units.HoursEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"mandate of {self.delegate.number} for {self.ticket.number} ({self.status})"


class Task(models.Model):
    """A piece of work from a `task_list` ticket that anyone can take (docs/05 section 5 item 3)."""

    STATUSES = [
        ("open", _("open")),
        ("claimed", _("claimed")),
        ("done", _("done")),
        ("confirmed", _("confirmed")),
    ]

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.PROTECT, related_name="tasks")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    standard_minutes = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    claimed_by = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="tasks_claimed"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    evidence_text = models.TextField(blank=True)
    evidence_file = models.ForeignKey(
        "members.PrivateFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    confirmed_by = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="tasks_confirmed"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    paid_entry = models.ForeignKey(
        "units.HoursEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    check_ticket = models.ForeignKey(
        "tickets.Ticket", null=True, blank=True, on_delete=models.PROTECT, related_name="checked_tasks"
    )
    kind = models.CharField(max_length=12, default="task")  # "task", or "against" for an "against" brief of a vote
    referendum_id = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.title} ({self.status})"
