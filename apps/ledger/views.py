import csv
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from . import services
from .models import Account, Entry

KIND_WORDS = {
    "hours_pay": gettext_lazy("Paid for hours"),
    "tax": gettext_lazy("Flat tax"),
    "purchase": gettext_lazy("Purchase"),
    "rent": gettext_lazy("Rent"),
    "transfer": gettext_lazy("Pension"),
    "retirement_in": gettext_lazy("Into retirement account"),
    "retirement_out": gettext_lazy("From retirement account"),
    "cancel": gettext_lazy("Period close"),
    "correction": gettext_lazy("Correction"),
}


def _rows(member):
    """The member's entries, newest first, each with the running balance after it."""
    account = services.member_account(member)
    entries = list(Entry.objects.filter(account=account).select_related("transaction").order_by("-transaction__seq"))
    tz = ZoneInfo(member.timezone)
    after = services.balance(account)
    rows = []
    for entry in entries:
        tx = entry.transaction
        rows.append(
            {
                "when": tx.created_at.astimezone(tz),
                "kind": KIND_WORDS.get(tx.kind, tx.kind),
                "reason": tx.reason,
                "amount": entry.amount,
                "balance": after,
            }
        )
        after -= entry.amount
    return rows


def _member_or_none(request):
    member = request.member
    if member is None or not Account.objects.filter(kind=Account.MEMBER, member=member).exists():
        return None
    return member


@login_required
def my_uniq(request):
    member = _member_or_none(request)
    if member is None:
        return render(request, "ledger/no_account.html")
    account = services.member_account(member)
    page = Paginator(_rows(member), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "ledger/my_account.html",
        {
            "balance": services.balance(account),
            "held": services.balance(account) - services.available(account),
            "available": services.available(account),
            "retirement": services.balance(services.retirement_account(member)),
            "tax_rate": services.current_period().tax_rate,
            "page": page,
        },
    )


@login_required
def my_uniq_csv(request):
    member = _member_or_none(request)
    if member is None:
        return redirect("ledger:my_uniq")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="my-uniq.csv"'
    writer = csv.writer(response)
    writer.writerow([_("date"), _("kind"), _("reason"), _("amount"), _("balance")])
    for row in _rows(member):
        writer.writerow([row["when"].isoformat(), str(row["kind"]), row["reason"], row["amount"], row["balance"]])
    return response
