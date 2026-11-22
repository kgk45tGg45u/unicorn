import hashlib

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import AppendOnlyModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("email required")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_unusable_password() if password is None else user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True)
        return self.create_user(email, password, **extra)


class User(AbstractUser):
    username = None
    email = models.EmailField(_("email address"), unique=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.email


class Member(models.Model):
    """A person in Unicorn. Others see only the number and display name (HF-14)."""

    APPLICANT, MEMBER, SUSPENDED, FORMER = "applicant", "member", "suspended", "former"
    STATUS_CHOICES = [
        (APPLICANT, _("applicant")),
        (MEMBER, _("member")),
        (SUSPENDED, _("suspended")),
        (FORMER, _("former member")),
    ]

    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name="member")
    number = models.CharField(max_length=12, unique=True)  # M-XXXX-XXXX
    display_name = models.CharField(max_length=60)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=APPLICANT)
    is_founder = models.BooleanField(default=False)
    is_identity_helper = models.BooleanField(default=False)
    joined_at = models.DateTimeField(null=True, blank=True)  # contract signed
    verified_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    deleted = models.BooleanField(default=False)
    country = models.CharField(max_length=2)  # ISO 3166-1
    currency = models.CharField(max_length=3, default="EUR")  # ISO 4217
    timezone = models.CharField(max_length=40, default="Europe/Berlin")
    postcode = models.CharField(max_length=12, blank=True)  # the area only, never a street address
    public_profile = models.BooleanField(default=False)
    draw_pause_until = models.DateField(null=True, blank=True)
    receives_benefits = models.BooleanField(default=False)
    is_mediator = models.BooleanField(default=False)  # volunteers for the mediator pool (P06.T09)
    email_all_notifications = models.BooleanField(default=False)  # "email me everything" (P06.T02)
    last_active_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"{self.number} {self.display_name}"


class ContractTemplate(models.Model):
    """The text of a contract, versioned and hashed. A published version is never edited."""

    KINDS = [
        ("membership", _("Membership contract")),
        ("holder_agreement", _("Holder agreement")),
        ("council_rules", _("Council rules")),
        ("mandate", _("Mandate")),
        ("assist_consent", _("Consent to be helped")),
        ("outside_seller", _("Outside seller terms")),
    ]

    kind = models.CharField(max_length=20, choices=KINDS)
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=120)
    body_md = models.TextField()
    sha256 = models.CharField(max_length=64, blank=True)
    valid_from = models.DateTimeField()
    is_current = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "version"], name="unique_contract_version")]
        ordering = ["kind", "-version"]

    def __str__(self):
        return f"{self.title} v{self.version}"

    def save(self, *args, **kwargs):
        self.sha256 = hashlib.sha256(self.body_md.encode("utf-8")).hexdigest()
        super().save(*args, **kwargs)


class Signature(AppendOnlyModel):
    """A member signed a contract text. Append-only."""

    METHODS = [("passkey", "passkey"), ("code", "code"), ("click", "click")]

    template = models.ForeignKey(ContractTemplate, on_delete=models.PROTECT, related_name="signatures")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="signatures")
    signed_at = models.DateTimeField(auto_now_add=True)
    text_sha256 = models.CharField(max_length=64)
    method = models.CharField(max_length=10, choices=METHODS)
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-signed_at"]

    def __str__(self):
        return f"{self.member.number} signed {self.template}"


class DataKey(models.Model):
    """A member's own encryption key, wrapped with the server's master key (HF-14)."""

    member = models.OneToOneField(Member, on_delete=models.PROTECT, related_name="data_key")
    wrapped = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"key of {self.member.number}"


class MemberPrivate(models.Model):
    """Personal data as one encrypted JSON blob: legal_name, street, city, phone, birth_date, iban, bic, bank_name."""

    member = models.OneToOneField(Member, on_delete=models.PROTECT, related_name="private")
    blob = models.BinaryField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"private data of {self.member.number}"


class PrivateFile(models.Model):
    """An uploaded file, stored encrypted outside the web root."""

    KINDS = [
        ("licence", _("licence")),
        ("receipt", _("receipt")),
        ("benefit_document", _("benefit document")),
        ("other", _("other")),
    ]

    owner = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="private_files")
    kind = models.CharField(max_length=20, choices=KINDS)
    path = models.CharField(max_length=200)  # relative to PRIVATE_MEDIA_ROOT
    name_enc = models.BinaryField()  # the encrypted original file name
    size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.kind} file {self.pk} of {self.owner.number}"


class Vouch(AppendOnlyModel):
    """A verified member says: I know this person, and this is their only account. Append-only."""

    voucher = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="vouches_given")
    vouchee = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="vouches_received")
    statement = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["voucher", "vouchee"], name="unique_vouch")]

    def __str__(self):
        return f"{self.voucher.number} vouches for {self.vouchee.number}"


class InPersonCheck(AppendOnlyModel):
    """An identity helper saw the person in person. Never holds an ID number or a copy of an ID. Append-only."""

    helper = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="checks_made")
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="checks_received")
    seen_on = models.DateField()
    town = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member.number} seen by {self.helper.number} on {self.seen_on}"


class MemberHash(models.Model):
    """HMAC of a normalised value, to find duplicate accounts. Not reversible; deleted with the account."""

    KINDS = [("email", "email"), ("phone", "phone"), ("iban", "iban"), ("name_birth", "name and birth date")]

    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="hashes")
    kind = models.CharField(max_length=12, choices=KINDS)
    value = models.CharField(max_length=64, db_index=True)

    def __str__(self):
        return f"{self.kind} hash of {self.member.number}"


class SiteState(models.Model):
    """A single row: when Unicorn launched. Until then it is in its founding phase."""

    launched_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"launched at {self.launched_at}" if self.launched_at else "not launched yet"

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]


class LaunchClick(models.Model):
    """A founder's click on "Unicorn launches". Unicorn launches when every founder has clicked (until P07)."""

    member = models.OneToOneField(Member, on_delete=models.PROTECT, related_name="launch_click")
    clicked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.member.number} clicked launch"


class Waitlist(models.Model):
    """An email waiting for the end of the founders' trial year. Deleted after the invitation or 24 months."""

    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    invited_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"waitlist {self.pk}"


class Skill(models.Model):
    """One trade a member can do. Shown in the portfolio; never used to rank or assign work (HF-10)."""

    LEVELS = [("learning", _("learning")), ("able", _("able")), ("expert", _("expert"))]

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="skills")
    trade_name = models.CharField(max_length=80)
    trade_code = models.CharField(max_length=16, blank=True)  # a CPA code such as CPA_Q87_88
    description = models.TextField(blank=True)
    level = models.CharField(max_length=10, choices=LEVELS, default="able")

    def __str__(self):
        return f"{self.trade_name} ({self.level})"


class Licence(models.Model):
    """A licence a trade needs by law (HF-17). The document is private; others see only the badge."""

    KINDS = [
        ("legal_advice", _("legal advice")),
        ("tax_advice", _("tax advice")),
        ("health_care", _("health care")),
        ("childcare_permit", _("childcare permit")),
        ("master_craftsman", _("master craftsman")),
        ("food_registration", _("food registration")),
        ("passenger_transport", _("passenger transport")),
        ("other", _("other")),
    ]
    STATUSES = [
        ("submitted", _("submitted")),
        ("verified", _("verified")),
        ("rejected", _("rejected")),
        ("expired", _("expired")),
    ]

    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="licences")
    kind = models.CharField(max_length=20, choices=KINDS)
    document = models.ForeignKey(PrivateFile, on_delete=models.PROTECT, related_name="licences")
    status = models.CharField(max_length=10, choices=STATUSES, default="submitted")
    expires_on = models.DateField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.CharField(max_length=32, blank=True)  # a ticket number later

    def __str__(self):
        return f"{self.kind} licence of {self.member.number} ({self.status})"


class Availability(models.Model):
    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="availability")
    hours_per_week = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    note = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"{self.member.number}: {self.hours_per_week} h/week"
