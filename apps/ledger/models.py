from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import AppendOnlyModel


class Account(models.Model):
    """A UNIQ account: a member's, a member's retirement account, or one of the two funds."""

    MEMBER, RETIREMENT, FUND1, FUND2 = "member", "retirement", "fund1", "fund2"
    KINDS = [
        (MEMBER, _("member")),
        (RETIREMENT, _("retirement")),
        (FUND1, _("Fund 1")),
        (FUND2, _("Fund 2")),
    ]

    kind = models.CharField(max_length=12, choices=KINDS)
    member = models.ForeignKey(
        "members.Member", on_delete=models.PROTECT, null=True, blank=True, related_name="accounts"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "member"], name="unique_account_per_kind_member"),
            models.CheckConstraint(
                condition=(Q(kind__in=["member", "retirement"], member__isnull=False))
                | (Q(kind__in=["fund1", "fund2"], member__isnull=True)),
                name="account_member_matches_kind",
            ),
        ]

    def __str__(self):
        return f"{self.kind} {self.member.number}" if self.member_id else self.get_kind_display()


class AccountBalance(models.Model):
    """A cache of an account's balance. Only `post()` changes it; the nightly audit checks it."""

    account = models.OneToOneField(Account, on_delete=models.PROTECT, related_name="balance_row")
    balance = models.DecimalField(max_digits=18, decimal_places=4, default=0)

    def __str__(self):
        return f"{self.account}: {self.balance}"


class Period(models.Model):
    """A calendar month in Europe/Berlin."""

    OPEN, CLOSING, CLOSED = "open", "closing", "closed"
    STATUSES = [(OPEN, "open"), (CLOSING, "closing"), (CLOSED, "closed")]

    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    status = models.CharField(max_length=8, choices=STATUSES, default=OPEN)
    tax_rate = models.DecimalField(max_digits=6, decimal_places=4)
    next_tax_rate = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)  # set by P09
    planned_hours = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["year", "month"], name="unique_period")]
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"{self.year}-{self.month:02d}"


class Transaction(AppendOnlyModel):
    """One posting in the UNIQ books. Written only by `ledger.services.post()`. Append-only and hash-chained."""

    KINDS = [
        ("hours_pay", "hours_pay"),
        ("tax", "tax"),
        ("purchase", "purchase"),
        ("rent", "rent"),
        ("transfer", "transfer"),
        ("retirement_in", "retirement_in"),
        ("retirement_out", "retirement_out"),
        ("cancel", "cancel"),
        ("correction", "correction"),
    ]

    seq = models.BigIntegerField(unique=True)
    period = models.ForeignKey(Period, on_delete=models.PROTECT, related_name="transactions")
    kind = models.CharField(max_length=16, choices=KINDS)
    reason = models.TextField()
    ref_type = models.CharField(max_length=40, blank=True)
    ref_id = models.CharField(max_length=40, blank=True)
    actor_ref = models.CharField(max_length=32)
    created_at = models.DateTimeField()
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64)

    class Meta:
        ordering = ["seq"]

    def __str__(self):
        return f"#{self.seq} {self.kind}"


class Entry(AppendOnlyModel):
    """One leg of a transaction: a signed amount on an account. Negative = debit, positive = credit."""

    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="entries")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="entries")
    amount = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        verbose_name_plural = "entries"
        constraints = [models.CheckConstraint(condition=~Q(amount=0), name="entry_amount_not_zero")]

    def __str__(self):
        return f"{self.account} {self.amount}"


class ChainHead(models.Model):
    """The end of a hash chain. `post()` locks this row, which serialises all postings."""

    name = models.CharField(max_length=16, primary_key=True)  # "uniq"; P08 adds "fund"
    last_seq = models.BigIntegerField(default=0)
    last_hash = models.CharField(max_length=64, default="0" * 64)

    def __str__(self):
        return f"{self.name} at #{self.last_seq}"


class Hold(models.Model):
    """UNIQ reserved for an order or booking until delivery. Not part of the chain; mutable."""

    ACTIVE, CAPTURED, RELEASED = "active", "captured", "released"
    STATUSES = [(ACTIVE, "active"), (CAPTURED, "captured"), (RELEASED, "released")]

    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="holds")
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE)
    reason = models.TextField()
    ref_type = models.CharField(max_length=40, blank=True)
    ref_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="hold_amount_positive")]
        indexes = [models.Index(fields=["account", "status"])]

    def __str__(self):
        return f"hold {self.amount} on {self.account} ({self.status})"
