import json
import secrets
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

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


def sign(member, template, method, context=None):
    """Record that a member signed a contract text, with the text's hash."""
    from apps.core import audit

    from .models import Signature

    with transaction.atomic():
        signature = Signature.objects.create(
            template=template,
            member=member,
            text_sha256=template.sha256,
            method=method,
            context=context or {},
        )
        audit.record(member.number, "contract.signed", signature, kind=template.kind, version=template.version)
        return signature


# --- Encrypted personal data and private files (HF-14) ---

PRIVATE_FIELDS = ("legal_name", "street", "city", "phone", "birth_date", "iban", "bic", "bank_name")
MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png"}


class FileRejected(ValueError):
    """The uploaded file is too big or of a type that is not allowed."""


def get_private(member) -> dict:
    from . import crypto
    from .models import MemberPrivate

    try:
        row = MemberPrivate.objects.filter(member=member).first()
        if row is None:
            crypto._member_fernet(member)  # raises if the key is destroyed
            return {}
        return json.loads(crypto.decrypt_for(member, row.blob))
    except crypto.KeyDestroyed:
        return {"deleted": True}


def set_private(member, **fields) -> dict:
    """Merge fields into the member's encrypted personal data."""
    from . import crypto
    from .models import MemberPrivate

    unknown = set(fields) - set(PRIVATE_FIELDS)
    if unknown:
        raise ValueError(f"unknown private fields: {', '.join(sorted(unknown))}")
    with transaction.atomic():
        row = MemberPrivate.objects.select_for_update().filter(member=member).first()
        data = json.loads(crypto.decrypt_for(member, row.blob)) if row else {}
        data.update(fields)
        blob = crypto.encrypt_for(member, json.dumps(data).encode("utf-8"))
        if row is None:
            MemberPrivate.objects.create(member=member, blob=blob)
        else:
            row.blob = blob
            row.save()
    update_hashes(member)
    return data


def store_private_file(member, uploaded_file, kind):
    from . import crypto
    from .models import PrivateFile

    content = uploaded_file.read()
    if len(content) > MAX_FILE_BYTES:
        raise FileRejected(_("The file is larger than 10 MB."))
    if uploaded_file.content_type not in ALLOWED_TYPES:
        raise FileRejected(_("Only PDF, JPEG and PNG files are allowed."))
    root = Path(settings.PRIVATE_MEDIA_ROOT)
    rel = f"{member.number}/{secrets.token_hex(16)}.bin"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(crypto.encrypt_for(member, content))
    return PrivateFile.objects.create(
        owner=member,
        kind=kind,
        path=rel,
        name_enc=crypto.encrypt_for(member, uploaded_file.name.encode("utf-8")),
        size=len(content),
        content_type=uploaded_file.content_type,
    )


def read_private_file(pf):
    """Return (original name, bytes). Raises KeyDestroyed after shredding."""
    from . import crypto

    name = crypto.decrypt_for(pf.owner, pf.name_enc).decode("utf-8")
    data = crypto.decrypt_for(pf.owner, (Path(settings.PRIVATE_MEDIA_ROOT) / pf.path).read_bytes())
    return name, data


def can_view_file(viewer, pf) -> bool:
    # Later phases add confirmers seated on the ticket that needs the file.
    return viewer is not None and viewer.pk == pf.owner_id


def shred(member) -> None:
    from . import crypto

    crypto.shred_key(member)


# --- Identity: one person, one account (HF-13, docs/08 section 2) ---

VERIFIED_HOOKS: list = []  # other apps add functions f(member); P02 opens the accounts


class IdentityError(ValueError):
    """An identity action is not allowed. The message is plain words for the member."""


def _month_start():
    from django.utils import timezone

    now = timezone.localtime()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def vouch(voucher, vouchee, statement):
    from apps.core import audit
    from apps.rules.services import get_param

    from .models import InPersonCheck, Vouch

    if voucher.pk == vouchee.pk:
        raise IdentityError(_("You cannot vouch for yourself."))
    if not is_verified(voucher):
        raise IdentityError(_("Only verified members can vouch."))
    if not statement.strip():
        raise IdentityError(_("Please write a short statement."))
    if InPersonCheck.objects.filter(helper=voucher, member=vouchee).exists():
        raise IdentityError(_("A helper who checked someone in person cannot also vouch for them."))
    with transaction.atomic():
        limit = get_param("membership.vouches_per_voucher_per_month")
        if Vouch.objects.filter(voucher=voucher, created_at__gte=_month_start()).count() >= limit:
            raise IdentityError(_("You have reached the monthly limit of vouches."))
        if Vouch.objects.filter(voucher=voucher, vouchee=vouchee).exists():
            raise IdentityError(_("You have already vouched for this member."))
        v = Vouch.objects.create(voucher=voucher, vouchee=vouchee, statement=statement)
        audit.record(voucher.number, "vouch", v, vouchee=vouchee.number)
    try_verify(vouchee)
    return v


def record_in_person_check(helper, member, seen_on, town):
    from apps.core import audit

    from .models import InPersonCheck, Vouch

    if helper.pk == member.pk:
        raise IdentityError(_("You cannot check yourself."))
    if not (is_verified(helper) and helper.is_identity_helper):
        raise IdentityError(_("Only verified identity helpers can record an in-person check."))
    if Vouch.objects.filter(voucher=helper, vouchee=member).exists():
        raise IdentityError(_("A helper who vouched for someone cannot also check them in person."))
    if not town.strip():
        raise IdentityError(_("Please write the town where you met."))
    with transaction.atomic():
        check = InPersonCheck.objects.create(helper=helper, member=member, seen_on=seen_on, town=town)
        audit.record(helper.number, "in_person_check", check, member=member.number)
    try_verify(member)
    return check


def try_verify(member) -> bool:
    """Make the member verified once they have enough vouches and, if required, an in-person check."""
    from django.utils import timezone

    from apps.core import audit
    from apps.rules.services import get_param

    from .models import InPersonCheck, Member, Vouch

    with transaction.atomic():
        member = Member.objects.select_for_update().get(pk=member.pk)
        if member.status != Member.APPLICANT:
            return False
        if Vouch.objects.filter(vouchee=member).count() < get_param("membership.vouches_needed"):
            return False
        if get_param("membership.in_person_check") and not InPersonCheck.objects.filter(member=member).exists():
            return False
        member.status = Member.MEMBER
        member.verified_at = timezone.now()
        member.save(update_fields=["status", "verified_at"])
        audit.record("system", "member.verified", member, number=member.number)
        for hook in VERIFIED_HOOKS:
            hook(member)
    return True


def _normalise(kind, value):
    value = str(value)
    if kind == "email":
        return value.strip().lower()
    if kind == "phone":
        return "".join(ch for ch in value if ch.isdigit())
    if kind == "iban":
        return "".join(value.split()).upper()
    return " ".join(value.lower().split())


def update_hashes(member):
    """Recompute the member's duplicate-detection hashes; flag a match with another member."""
    from apps.core import audit
    from apps.core.hashing import hmac_hex

    from .models import Member, MemberHash

    private = get_private(member)
    wanted = {"email": member.user.email}
    for kind in ("phone", "iban"):
        if private.get(kind):
            wanted[kind] = private[kind]
    if private.get("legal_name") and private.get("birth_date"):
        wanted["name_birth"] = f"{private['legal_name']}|{private['birth_date']}"
    with transaction.atomic():
        MemberHash.objects.filter(member=member).delete()
        for kind, raw in wanted.items():
            digest = hmac_hex(f"{kind}:{_normalise(kind, raw)}")
            MemberHash.objects.create(member=member, kind=kind, value=digest)
            if MemberHash.objects.filter(kind=kind, value=digest).exclude(member=member).exists():
                audit.record("system", "duplicate_suspected", member, kind=kind)
                if member.status != Member.MEMBER:
                    Member.objects.filter(pk=member.pk).update(status=Member.APPLICANT)
