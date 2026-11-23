import csv

from django.http import HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.ledger.services import current_period
from apps.rules.models import Parameter

from . import tax, world
from .models import MacroSnapshot


def on_track(request):
    """ "Are we on track?": the real world against the simulation's default world (docs/03 section 10)."""
    snap = MacroSnapshot.objects.first()
    real = snap.world if snap else world.world_metrics(current_period())
    rows, benchmark, _year = world.on_track(real, world.months_since_launch())
    return render(
        request,
        "macro/on_track.html",
        {"rows": rows, "month_index": world.months_since_launch(), "has_snapshot": snap is not None},
    )


def snapshots_csv(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="unicorn-macro-snapshots.csv"'
    writer = csv.writer(response)
    fields = [
        "hours_paid", "tax", "net_issued", "transfers", "spent", "cancelled", "outstanding", "months_of_spending",
        "consumption", "social", "accumulation", "trade", "waste", "depreciation", "inventory_change",
        "hours_residual", "tax_rate_used", "tax_rate_next",
    ]  # fmt: skip
    writer.writerow(["period", *fields])
    for s in MacroSnapshot.objects.order_by("period__year", "period__month"):
        writer.writerow([str(s.period), *[getattr(s, f) for f in fields]])
    return response


def forecast_data_csv(request):
    """The numbers experts feed into ../Unicorn-simulation. No personal data and no member numbers."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="unicorn-forecast-data.csv"'
    writer = csv.writer(response)
    writer.writerow(["section", "key", "value"])
    for s in MacroSnapshot.objects.order_by("period__year", "period__month"):
        month = str(s.period)
        writer.writerow(["month", f"{month}.tax_rate_used", s.tax_rate_used])
        for key, value in (s.world or {}).items():
            writer.writerow(["world", f"{month}.{key}", value if value is not None else ""])
        for key, light in (s.lights or {}).items():
            writer.writerow(["light", f"{month}.{key}", f"{light.get('color')}:{light.get('value') or ''}"])
    for p in Parameter.objects.order_by("key"):
        writer.writerow(["parameter", p.key, p.value])
    return response


def tax_explanation():
    return tax.EXPLANATION or _("")


def my_world(request):
    """Optional: "I have a capitalist job" and "my net hourly wage", for the world tracker and attractiveness."""
    from django.contrib import messages
    from django.contrib.auth.decorators import login_required
    from django.shortcuts import redirect

    @login_required
    def view(request):
        from decimal import Decimal, InvalidOperation

        from apps.members import services as member_services

        member = request.member
        if request.method == "POST":
            choice = request.POST.get("has_job", "")
            member.has_capitalist_job = {"yes": True, "no": False}.get(choice)
            member.save(update_fields=["has_capitalist_job"])
            wage = request.POST.get("wage", "").replace(",", ".").strip()
            try:
                member_services.set_private(member, net_hourly_wage_eur=str(Decimal(wage)) if wage else "")
                messages.success(request, _("Thank you. This is saved."))
            except InvalidOperation:
                messages.error(request, _("Please enter the wage as a number, for example 17.50."))
            return redirect("macro:my_world")
        private = member_services.get_private(member)
        return render(
            request,
            "macro/my_world.html",
            {"member": member, "wage": private.get("net_hourly_wage_eur", "")},
        )

    return view(request)
