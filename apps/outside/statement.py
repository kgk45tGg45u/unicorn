"""The outside part of the yearly statement (P10.T08): each invoice, the tax reserve kept and the set-aside."""

from decimal import Decimal

from django.utils.translation import gettext as _

from apps.tradefund import public

from .models import Invoice


def extension(member, year) -> dict:
    invoices = list(Invoice.objects.filter(seller=member, issued_on__year=year).order_by("issued_on", "id"))
    by_currency = {}
    for i in invoices:
        row = by_currency.setdefault(
            i.currency, {"total": Decimal(0), "tax_reserve": Decimal(0), "setaside": Decimal(0)}
        )
        if i.refunded_at is None:
            row["total"] += i.total
            row["tax_reserve"] += i.tax_reserve
            row["setaside"] += i.setaside
    return {
        "template": "outside/_statement.html",
        "title": _("Outside sales"),
        "invoices": invoices,
        "by_currency": by_currency,
        "total_eur": sum((i.total_eur for i in invoices if i.refunded_at is None), Decimal(0)),
    }


def register():
    if extension not in public.STATEMENT_EXTENSIONS:
        public.STATEMENT_EXTENSIONS.append(extension)
