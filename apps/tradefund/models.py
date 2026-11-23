from django.db import models
from django.utils.translation import gettext_lazy as _


class FxRate(models.Model):
    """The ECB reference rate of a day: units of the currency per 1 EUR. Never an exchange rate for UNIQ (HF-4)."""

    date = models.DateField()
    currency = models.CharField(max_length=3)
    per_eur = models.DecimalField(max_digits=18, decimal_places=6)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["date", "currency"], name="unique_fx_per_day")]
        ordering = ["-date", "currency"]

    def __str__(self):
        return f"{self.date} 1 EUR = {self.per_eur} {self.currency}"


class Holder(models.Model):
    """A verified member who keeps part of the trade fund in their own bank account (docs/07 section 2)."""

    ACTIVE, PAUSED, LEAVING, LEFT = "active", "paused", "leaving", "left"
    STATUSES = [
        (ACTIVE, _("active")),
        (PAUSED, _("paused")),
        (LEAVING, _("handing over")),
        (LEFT, _("left")),
    ]

    member = models.OneToOneField("members.Member", on_delete=models.PROTECT, related_name="holder")
    status = models.CharField(max_length=8, choices=STATUSES, default=ACTIVE)
    currency = models.CharField(max_length=3, default="EUR")
    separate_account = models.BooleanField(default=True)
    iban_shown_to_donors = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["member__number"]

    def __str__(self):
        return f"holder {self.member.number} ({self.currency}, {self.status})"
