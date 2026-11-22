import secrets

from django.db import IntegrityError, transaction

from .models import Member

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_number() -> str:
    chars = "".join(secrets.choice(CROCKFORD) for _ in range(8))
    return f"M-{chars[:4]}-{chars[4:]}"


def create_applicant(user, display_name, country, currency="EUR", postcode="") -> Member:
    """Make a Member with a unique random number (retry on collision)."""
    for _attempt in range(10):
        try:
            with transaction.atomic():
                return Member.objects.create(
                    user=user,
                    number=new_number(),
                    display_name=display_name,
                    country=country.upper(),
                    currency=currency.upper(),
                    postcode=postcode,
                )
        except IntegrityError:
            if Member.objects.filter(user=user).exists():
                raise
    raise RuntimeError("could not make a unique member number")


def is_verified(member) -> bool:
    """HF-13: only a member with status `member` may vote, hold fund euros, confirm or be drawn."""
    return member is not None and member.status == Member.MEMBER


def active_members():
    return Member.objects.filter(status=Member.MEMBER)
