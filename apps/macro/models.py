from django.db import models
from django.utils.translation import gettext_lazy as _

D18 = {"max_digits": 18, "decimal_places": 4, "default": 0}


class MacroSnapshot(models.Model):
    """One month's macro accounts, stored at the close (docs/03 sections 3 and 7). All values are hours = UNIQ."""

    period = models.OneToOneField("ledger.Period", on_delete=models.PROTECT, related_name="snapshot")
    hours_paid = models.DecimalField(**D18)
    tax = models.DecimalField(**D18)
    net_issued = models.DecimalField(**D18)
    transfers = models.DecimalField(**D18)
    spent = models.DecimalField(**D18)
    cancelled = models.DecimalField(**D18)
    outstanding = models.DecimalField(**D18)
    months_of_spending = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # hours by use
    consumption = models.DecimalField(**D18)
    social = models.DecimalField(**D18)
    accumulation = models.DecimalField(**D18)
    trade = models.DecimalField(**D18)
    waste = models.DecimalField(**D18)
    depreciation = models.DecimalField(**D18)
    inventory_change = models.DecimalField(**D18)
    inventory_value = models.DecimalField(**D18)  # at the period's end, for the next month's change
    hours_residual = models.DecimalField(**D18)
    tax_rate_used = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    tax_rate_next = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    tax_inputs = models.JSONField(default=dict)  # H, C, S*, T and the method: anyone can redo the calculation
    lights = models.JSONField(default=dict)
    world = models.JSONField(default=dict)
    identities = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period__year", "-period__month"]

    def __str__(self):
        return f"snapshot {self.period}"

    @property
    def residual_warning(self) -> bool:
        return bool(self.hours_paid) and abs(self.hours_residual) > self.hours_paid * 2 / 100


class ActiveMonth(models.Model):
    """A month that counts toward the pension: enough approved hours, or a recognised month of care or illness."""

    KINDS = [("hours", _("hours")), ("care", _("care")), ("illness", _("illness"))]

    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="active_months")
    month = models.DateField()  # the first of the month
    kind = models.CharField(max_length=8, choices=KINDS)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["member", "month", "kind"], name="one_active_month_per_kind")]
        ordering = ["-month"]

    def __str__(self):
        return f"{self.member.number} {self.month:%Y-%m} {self.kind}"


class TransferPlan(models.Model):
    """A transfer decided by a ticket (care): paid monthly by Fund 2 from `from_month` to `to_month`."""

    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="transfer_plans")
    monthly_amount = models.DecimalField(max_digits=18, decimal_places=4)
    from_month = models.DateField()
    to_month = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=200)
    ticket = models.ForeignKey("tickets.Ticket", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    def __str__(self):
        return f"transfer plan {self.pk} for {self.member.number}"


class Forecast(models.Model):
    """An expert's forecast attached to a ticket: a file and five numbers (docs/03 section 11)."""

    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.PROTECT, related_name="forecasts")
    file = models.ForeignKey("members.PrivateFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    author = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="+")
    goals = models.JSONField(default=dict)  # attractive, growing, independent, stable: true or false
    can_live_y10 = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    can_live_y20 = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    can_live_y30 = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"forecast for {self.ticket.number}"


class LightsCache(models.Model):
    """The lights of the current period, refreshed daily so that they do not wait for the month's end."""

    period = models.OneToOneField("ledger.Period", on_delete=models.CASCADE, related_name="lights_cache")
    lights = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"lights of {self.period}"


class PensionRecognition(models.Model):
    """A member was recognised as unable to work. The evidence is deleted 30 days after the decision."""

    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="pension_recognitions")
    kind = models.CharField(max_length=20, default="unable_to_work")
    ticket = models.ForeignKey("tickets.Ticket", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    evidence = models.ForeignKey(
        "members.PrivateFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    delete_evidence_at = models.DateTimeField(null=True, blank=True)
    evidence_shredded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member.number} {self.kind}"


class RetirementPlan(models.Model):
    """A member's payout plan after pension age: each month the balance divided by the months left."""

    member = models.OneToOneField("members.Member", on_delete=models.PROTECT, related_name="retirement_plan")
    active = models.BooleanField(default=True)
    started_on = models.DateField()

    def __str__(self):
        return f"retirement plan of {self.member.number}"
