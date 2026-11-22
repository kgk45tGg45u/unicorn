import hashlib

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


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


class Signature(models.Model):
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

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Signatures cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Signatures cannot be deleted.")
