from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import AppendOnlyModel


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


class FundEntry(AppendOnlyModel):
    """One change in who holds what for the group. Append-only and hash-chained like the UNIQ books (HF-7).

    `amount` is signed for every kind except `reserve_mark` and `reserve_unmark`, which are always positive and
    only move an amount between "free" and "reserve" inside the holder's holding.
    """

    KINDS = [
        ("setaside", _("set-aside")),
        ("donation", _("donation")),
        ("transfer_in", _("received from another holder")),
        ("transfer_out", _("passed to another holder")),
        ("payment_out", _("payment")),
        ("reserve_mark", _("marked as loss reserve")),
        ("reserve_unmark", _("released from the loss reserve")),
        ("correction", _("correction")),
    ]
    REASON_KINDS = [
        ("loan", _("loan")),
        ("group_purchase", _("group purchase")),
        ("gift", _("gift")),
        ("bill", _("bill")),
        ("internal", _("between holders")),
    ]

    seq = models.BigIntegerField(unique=True)
    holder = models.ForeignKey(Holder, on_delete=models.PROTECT, related_name="entries")
    kind = models.CharField(max_length=16, choices=KINDS)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    reason = models.TextField()
    reason_kind = models.CharField(max_length=16, choices=REASON_KINDS)
    ref_type = models.CharField(max_length=40, blank=True)
    ref_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField()
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64)

    class Meta:
        ordering = ["seq"]
        verbose_name_plural = "fund entries"

    def __str__(self):
        return f"#{self.seq} {self.kind} {self.amount} {self.currency}"
