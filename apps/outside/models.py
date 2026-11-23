from django.db import models


class SellerProfile(models.Model):
    """A member who sells to outside customers in their own name (docs/07 section 6)."""

    member = models.OneToOneField("members.Member", on_delete=models.PROTECT, related_name="seller_profile")
    active = models.BooleanField(default=True)
    trader_name = models.CharField(max_length=120)  # shown on invoices
    trader_address_enc = models.BinaryField()  # system_encrypt: shown to customers on invoices (HF-14)
    small_business = models.BooleanField(default=True)  # § 19 UStG
    vat_id = models.CharField(max_length=20, blank=True)
    tax_reserve_share = models.DecimalField(max_digits=5, decimal_places=4)
    show_iban = models.BooleanField(default=True)  # the customer is shown the seller's account number
    started_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"seller {self.member.number}"


class OutsideCustomer(models.Model):
    """An outside customer. Name, email and address are encrypted and wiped 90 days after delivery."""

    name_enc = models.BinaryField(blank=True, default=b"")
    email_enc = models.BinaryField(blank=True, default=b"")
    address_enc = models.BinaryField(blank=True, default=b"")
    country = models.CharField(max_length=2, blank=True)
    privacy_consent_at = models.DateTimeField()
    delete_contact_after = models.DateTimeField(null=True, blank=True)
    wiped_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"outside customer {self.pk}"


class InvoiceCounter(models.Model):
    """The last invoice number of a seller in a year. Locked while a number is given out: no gaps."""

    seller = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="+")
    year = models.PositiveIntegerField()
    last = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["seller", "year"], name="one_counter_per_seller_year")]

    def __str__(self):
        return f"{self.seller.number} {self.year}: {self.last}"


class Invoice(models.Model):
    """An invoice of a seller to an outside customer. The customer's details are copied in, encrypted."""

    order = models.OneToOneField("market.Order", on_delete=models.PROTECT, related_name="invoice")
    seller = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="invoices")
    number = models.CharField(max_length=40)
    issued_on = models.DateField()
    customer_snapshot_enc = models.BinaryField()
    lines = models.JSONField(default=list)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    vat_note = models.CharField(max_length=200)
    paid_at = models.DateTimeField(null=True, blank=True)
    tax_reserve = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    setaside = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_eur = models.DecimalField(max_digits=14, decimal_places=2, default=0)  # at the ECB rate of the day
    refunded_at = models.DateTimeField(null=True, blank=True)
    keep_until = models.DateField()  # OWNER-CHECK: legal keeping period

    class Meta:
        constraints = [models.UniqueConstraint(fields=["seller", "number"], name="unique_invoice_number_per_seller")]
        ordering = ["-issued_on", "-id"]

    def __str__(self):
        return f"invoice {self.number}"
