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


class ExternalPayee(models.Model):
    """Someone outside Unicorn who is paid by the fund: a seller, a landlord, an insurer. The IBAN is encrypted."""

    name = models.CharField(max_length=120)
    iban_enc = models.BinaryField()  # system_encrypt (HF-14)
    country = models.CharField(max_length=2, blank=True)
    created_by = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"outside payee {self.pk}"


class PaymentRequest(models.Model):
    """ "Please pay X to Y with reference Z", confirmed by the payer and the receiver (docs/07 section 4, HF-12)."""

    STATUSES = [
        ("requested", _("requested")),
        ("sent", _("sent")),
        ("received", _("received")),
        ("confirmed", _("confirmed")),
        ("mismatch", _("the amounts differ")),
        ("overdue", _("overdue")),
        ("missed", _("missed")),
        ("cancelled", _("cancelled")),
    ]
    OPEN = ("requested", "sent", "received", "overdue")

    ticket = models.ForeignKey("tickets.Ticket", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    mandate = models.ForeignKey("tasks.Mandate", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    payer = models.ForeignKey(Holder, on_delete=models.PROTECT, related_name="payments_to_make")
    payee_holder = models.ForeignKey(
        Holder, null=True, blank=True, on_delete=models.PROTECT, related_name="payments_to_receive"
    )
    payee_member = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    payee_external = models.ForeignKey(ExternalPayee, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    confirmer = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )  # who confirms for an outside payee: the buyer or requester
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    reference = models.CharField(max_length=140)
    description = models.CharField(max_length=200, blank=True)  # the written reason in the fund's books
    reason_kind = models.CharField(max_length=16, choices=FundEntry.REASON_KINDS)
    purpose = models.CharField(max_length=20, blank=True)  # purchase, benefit, internal, reserve ...
    ref_type = models.CharField(max_length=40, blank=True)
    ref_id = models.CharField(max_length=40, blank=True)
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUSES, default="requested")
    sent_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    received_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    confirmed_by_buyer = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    invoice = models.ForeignKey(
        "members.PrivateFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reminded_at = models.DateTimeField(null=True, blank=True)
    replaces = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replaced_by")
    first_confirmer = models.CharField(max_length=5, blank=True)  # "payer" or "payee": who confirmed first
    flag_ticket = models.CharField(max_length=12, blank=True)
    final_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["status", "due_date"])]

    def __str__(self):
        return f"payment {self.pk}: {self.amount} {self.currency} ({self.status})"

    @property
    def payee_kind(self):
        return "holder" if self.payee_holder_id else "member" if self.payee_member_id else "external"


class TrustEvent(AppendOnlyModel):
    """One thing that moved a holder's trust rating. Append-only (docs/07 section 5, HF-11)."""

    KINDS = [
        ("start", _("start")),
        ("on_time", _("payment on time")),
        ("monthly", _("a month without problems")),
        ("late", _("payment late")),
        ("missed", _("payment missed")),
        ("mismatch", _("amounts differ, decided against")),
        ("left_without_handover", _("left without passing on the held euros")),
        ("annulled", _("event annulled")),
    ]

    holder = models.ForeignKey(Holder, on_delete=models.PROTECT, related_name="trust_events")
    kind = models.CharField(max_length=24, choices=KINDS)
    delta = models.DecimalField(max_digits=6, decimal_places=4)
    ref = models.CharField(max_length=60, blank=True)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.holder.member.number} {self.kind} {self.delta}"


class PurchaseRequest(models.Model):
    """A request to buy something from capitalism with fund euros (docs/07 section 3)."""

    SOURCES = [
        ("recipe_input", _("an input of a recipe")),
        ("tool", _("a tool")),
        ("adhoc", _("something else")),
        ("bill", _("a member's bill")),
        ("operations", _("an operating cost")),
    ]
    METHODS = [
        ("reimburse", _("the requester buys and is reimbursed")),
        ("holder_pays_seller", _("a holder pays the seller")),
        ("pooled_to_buyer", _("holders send parts to a buyer")),
    ]
    STATUSES = [
        ("checking", _("being checked")),
        ("approved", _("approved")),
        ("waiting_for_euros", _("waiting for euros")),
        ("paying", _("being paid")),
        ("bought", _("bought")),
        ("delivered", _("delivered")),
        ("closed", _("closed")),
        ("rejected", _("rejected")),
    ]

    requester = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="purchase_requests")
    unit = models.ForeignKey("units.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    item = models.ForeignKey("catalogue.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=200)
    why = models.CharField(max_length=300, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=4, default=1)
    est_price = models.DecimalField(max_digits=14, decimal_places=2)  # for the whole quantity
    currency = models.CharField(max_length=3, default="EUR")
    seller = models.CharField(max_length=200, blank=True)  # a name or a link
    payee_external = models.ForeignKey(ExternalPayee, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    deliver_to_unit = models.ForeignKey("units.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    deliver_to_member = models.ForeignKey(
        "members.Member", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    source = models.CharField(max_length=14, choices=SOURCES, default="adhoc")
    purchase_need = models.ForeignKey(
        "market.PurchaseNeed", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    offer_tool = models.ForeignKey(
        "catalogue.OfferTool", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    ticket = models.ForeignKey("tickets.Ticket", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    pay_method = models.CharField(max_length=20, choices=METHODS, blank=True)
    buyer = models.ForeignKey(Holder, null=True, blank=True, on_delete=models.PROTECT, related_name="purchases_to_make")
    buyer_deadline = models.DateTimeField(null=True, blank=True)  # volunteers may come forward until then
    funded = models.BooleanField(default=False)  # the money reached the buyer
    status = models.CharField(max_length=20, choices=STATUSES, default="checking")
    status_note = models.CharField(max_length=300, blank=True)
    receipt = models.ForeignKey(
        "members.PrivateFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actual_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    change_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"purchase {self.pk}: {self.description} ({self.status})"


class BuyerVolunteer(models.Model):
    """A holder who offers to buy for a pooled purchase. The highest trust wins when the time is up."""

    purchase = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="volunteers")
    holder = models.ForeignKey(Holder, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["purchase", "holder"], name="one_volunteering_each")]

    def __str__(self):
        return f"{self.holder} volunteers for {self.purchase_id}"


class GroupTool(models.Model):
    """A tool bought with fund euros. It belongs to the group and is lent to a unit (docs/07 section 3, step 5)."""

    STATUSES = [("in_use", _("in use")), ("returned", _("returned")), ("broken", _("broken"))]

    item = models.ForeignKey("catalogue.Item", on_delete=models.PROTECT, related_name="+")
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.PROTECT, related_name="tools")
    lent_to_unit = models.ForeignKey("units.Unit", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    euro_price = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="EUR")
    lifetime_uses = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    acquired_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=STATUSES, default="in_use")

    def __str__(self):
        return f"group tool {self.item.name}"
