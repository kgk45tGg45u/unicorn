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
