"""Download all my data (GDPR Art. 15 and 20, P14.T03).

`EXPORTERS` is a list of functions `export(member) -> dict[str, list[dict]]` (table name to rows). Every part of the
app that keeps data about a member is listed in `apps/privacy/exporters.py`, and any app may add its own function.
Other members appear only as member numbers. Secret ballots cannot be exported: a ballot holds no member.
"""

import csv
import io
import json
import secrets
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

EXPORTERS: list = []
EXPORT_DAYS = 7

README = """Your data from Unicorn
======================

This file holds the data Unicorn keeps about you (GDPR Art. 15 and 20).

- data.json: everything, in one file. Each key is a table, each table is a list of rows.
- One CSV file for each table, to open in a spreadsheet.

Other members appear only as member numbers. Your personal details (name, address, bank account) are shown in the
table "private_data" in plain text, because they are yours.

Secret ballots cannot be exported. A secret ballot holds no member, so nobody can say how you voted. The table
"voter_records" shows only that you voted, and in which vote.

Encrypted fields of people outside Unicorn (for example the contact details of customers who bought from you) are not
in this file: they belong to those people.

This file is deleted from our server after 7 days.
"""


def register(fn):
    """Add an exporter. Safe to call twice with the same function."""
    if fn not in EXPORTERS:
        EXPORTERS.append(fn)
    return fn


def plain(value):
    """A value that json and csv can write."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        return None
    return value


def row_of(obj, numbers: dict) -> dict:
    """One row: the plain columns. Links to members become member numbers; encrypted columns are left out."""
    from apps.members.models import Member

    row = {"id": obj.pk}
    for field in obj._meta.concrete_fields:
        if field.name == "id" or field.name.endswith("_enc") or isinstance(field, models.BinaryField):
            continue
        if isinstance(field, models.ForeignKey):
            raw = getattr(obj, field.attname)
            if field.related_model is Member and raw is not None:
                if raw not in numbers:
                    numbers[raw] = Member.objects.filter(pk=raw).values_list("number", flat=True).first()
                row[field.name] = numbers[raw]
            else:
                row[field.name] = raw
        else:
            row[field.name] = plain(getattr(obj, field.attname))
    return row


def build(member) -> dict:
    """All exporters, merged into one dict of tables."""
    data: dict = {}
    for fn in EXPORTERS:
        for table, rows in fn(member).items():
            data.setdefault(table, []).extend(rows)
    return data


def make_zip(member) -> bytes:
    data = build(member)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README)
        z.writestr("data.json", json.dumps(data, indent=2, ensure_ascii=False, default=str))
        for table, rows in sorted(data.items()):
            buf = io.StringIO()
            columns = sorted({key for r in rows for key in r}) or ["id"]
            writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in r.items()})
            z.writestr(f"{table}.csv", buf.getvalue())
    return out.getvalue()


def _root() -> Path:
    return Path(settings.PRIVATE_MEDIA_ROOT)


def create_export(export):
    """Build the ZIP, encrypt it with the member's own key and store it privately. Safe to run twice."""
    from apps.core import audit
    from apps.members import crypto
    from apps.tickets.models import Notification

    if export.status == export.READY:
        return export
    member = export.member
    content = make_zip(member)
    rel = f"exports/{member.number}/{secrets.token_hex(16)}.zip.enc"
    target = _root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(crypto.encrypt_for(member, content))
    export.path, export.size, export.status = rel, len(content), export.READY
    export.expires_at = timezone.now() + timedelta(days=EXPORT_DAYS)
    export.save()
    audit.record(member.number, "privacy.export_ready", export)
    Notification.objects.create(
        member=member,
        text="Your data is ready to download. The link works for 7 days.",
        url=f"/me/data/{export.pk}/",
    )
    return export


def read_export(export) -> bytes:
    """The decrypted ZIP, for the member it belongs to."""
    from apps.members import crypto

    return crypto.decrypt_for(export.member, (_root() / export.path).read_bytes())


def delete_files(member_or_none=None) -> int:
    """Remove expired exports (all of a member's, when a member is given) and their files."""
    from .models import DataExport

    rows = DataExport.objects.exclude(path="")
    rows = (
        rows.filter(member=member_or_none)
        if member_or_none is not None
        else rows.filter(expires_at__lte=timezone.now())
    )
    count = 0
    for export in rows:
        (_root() / export.path).unlink(missing_ok=True)
        export.path, export.status = "", export.EXPIRED
        export.save(update_fields=["path", "status"])
        count += 1
    return count
