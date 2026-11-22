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
