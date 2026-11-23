"""What the fund shows everyone, and each member's yearly statement (docs/07 sections 2 and 6).

The public numbers carry no names and no member numbers (HF-14)."""

import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.money import cur

from . import allocation, books, fx
from .models import FundEntry, Holder, PaymentRequest, PurchaseRequest

IN_KINDS = ("setaside", "donation")
OUT_LABELS = {
    "materials": _("Materials"),
    "tools": _("Tools"),
    "benefits": _("Benefits and bills of members"),
    "operations": _("Running costs and other purchases"),
}


def category_of(entry) -> str:
    """What a payment out was for: materials, tools, benefits or operations."""
    purchase = None
    if entry.ref_type == "purchaserequest":
        purchase = PurchaseRequest.objects.filter(pk=entry.ref_id).first()
    elif entry.ref_type == "paymentrequest":
        pr = PaymentRequest.objects.filter(pk=entry.ref_id).first()
        if pr is not None and pr.purpose == "benefit":
            return "benefits"
        if pr is not None and pr.ref_type == "purchaserequest":
            purchase = PurchaseRequest.objects.filter(pk=pr.ref_id).first()
    if purchase is not None:
        return {"recipe_input": "materials", "tool": "tools", "bill": "benefits"}.get(purchase.source, "operations")
    return "operations"


def totals_by_currency():
    rows = []
    for row in (
        FundEntry.objects.exclude(kind__in=books.RESERVE_KINDS)
        .values("currency")
        .annotate(t=Sum("amount"))
        .order_by("currency")
    ):
        rows.append(
            {
                "currency": row["currency"],
                "amount": row["t"] or Decimal(0),
                "eur": fx.to_eur(row["t"] or 0, row["currency"]),
            }
        )
    return rows


def public_numbers(now=None) -> dict:
    now = now or timezone.now()
    since = now - timedelta(days=365)
    money_in = {k: Decimal(0) for k in IN_KINDS}
    money_out = {k: Decimal(0) for k in OUT_LABELS}
    for e in FundEntry.objects.filter(created_at__gte=since, kind__in=IN_KINDS + ("payment_out",)):
        eur = fx.to_eur(abs(e.amount), e.currency)
        if e.kind in IN_KINDS:
            money_in[e.kind] += eur
        else:
            money_out[category_of(e)] += eur
    total = books.fund_total_eur()
    holders = [h for h in Holder.objects.exclude(status=Holder.LEFT)]
    largest = max((fx.to_eur(books.holding(h), h.currency) for h in holders), default=Decimal(0))
    return {
        "totals": totals_by_currency(),
        "total_eur": total,
        "reserve_months": allocation.reserve_months(),
        "in": {k: cur(v) for k, v in money_in.items()},
        "out": {OUT_LABELS[k]: cur(v) for k, v in money_out.items()},
        "holders": len(holders),
        "largest_share": (largest / total * 100).quantize(Decimal("0.1")) if total > 0 else Decimal(0),
    }


# --- The yearly statement of one holder ---


def _ticket_number(entry):
    pr = None
    if entry.ref_type == "paymentrequest":
        pr = PaymentRequest.objects.filter(pk=entry.ref_id).select_related("ticket").first()
        return pr.ticket.number if pr is not None and pr.ticket_id else ""
    if entry.ref_type == "purchaserequest":
        purchase = PurchaseRequest.objects.filter(pk=entry.ref_id).select_related("ticket").first()
        return purchase.ticket.number if purchase is not None and purchase.ticket_id else ""
    return ""


# Functions called with (member, year) that return more to show on the statement. The outside shop adds invoices.
STATEMENT_EXTENSIONS: list = []


def statement(holder, year) -> dict:
    """What the holder set aside, held, sent on and received in a year, with dates and ticket numbers."""
    entries = FundEntry.objects.filter(holder=holder, created_at__year=year).exclude(kind__in=books.RESERVE_KINDS)
    rows = [
        {
            "date": timezone.localtime(e.created_at).date(),
            "kind": e.get_kind_display(),
            "kind_key": e.kind,
            "amount": e.amount,
            "currency": e.currency,
            "reason": e.reason,
            "ticket": _ticket_number(e),
        }
        for e in entries.order_by("seq")
    ]
    sums = {}
    for r in rows:
        sums[r["kind_key"]] = sums.get(r["kind_key"], Decimal(0)) + r["amount"]
    end = timezone.make_aware(datetime(year + 1, 1, 1))
    held_end = FundEntry.objects.filter(holder=holder, created_at__lt=end).exclude(kind__in=books.RESERVE_KINDS)
    return {
        "rows": rows,
        "sums": sums,
        "set_aside": sums.get("setaside", Decimal(0)),
        "sent_on": -(sums.get("transfer_out", Decimal(0)) + sums.get("payment_out", Decimal(0))),
        "received": sums.get("transfer_in", Decimal(0)) + sums.get("donation", Decimal(0)),
        "held_at_year_end": held_end.aggregate(t=Sum("amount"))["t"] or Decimal(0),
        "currency": holder.currency,
        "year": year,
        "extensions": [ext(holder.member, year) for ext in STATEMENT_EXTENSIONS],
    }


def statement_csv(holder, year) -> str:
    data = statement(holder, year)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["date", "kind", "amount", "currency", "reason", "ticket"])
    for r in data["rows"]:
        writer.writerow([r["date"].isoformat(), r["kind_key"], r["amount"], r["currency"], r["reason"], r["ticket"]])
    return out.getvalue()
