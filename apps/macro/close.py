"""The monthly close (docs/03 section 7): cancel Fund 1, account the hours, check the identities, set the next tax.

It is idempotent: running it twice for the same period does nothing the second time."""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.ledger import services as ledger
from apps.ledger.models import Account, Entry, Period

from . import accounts, identities, lights, retirement, tax, transfers
from .models import MacroSnapshot

ZERO = Decimal("0.0000")


def previous_month(today=None) -> tuple[int, int]:
    today = today or timezone.localdate()
    last = today.replace(day=1) - timedelta(days=1)
    return last.year, last.month


def _months_of_spending(period, members_balance):
    periods = lights._previous(period, 6)
    spent = -(
        Entry.objects.filter(
            account__kind=Account.MEMBER, transaction__period__in=periods, transaction__kind__in=("purchase", "rent")
        ).aggregate(t=Sum("amount"))["t"]
        or ZERO
    )
    average = spent / len(periods)
    return (members_balance / average).quantize(Decimal("0.01")) if average > 0 else None


def _open_identity_ticket(period, bad):
    from apps.tickets import services as ticket_services
    from apps.tickets.briefs import _check

    month = f"{period.year}-{period.month:02d}"
    lines = [f"- {identities.WORDS.get(k, k)} ({v})" for k, v in bad.items()]
    check = _check(_("Which month is this about?"), month, ["1999-01", "2099-12"], _("the first sentence"))
    return ticket_services.create_ticket(
        "audit_failure",
        None,
        _("The books of %(month)s do not add up") % {"month": month},
        brief="\n".join([_("The monthly close of %(month)s found:") % {"month": month}, *lines]),
        check=check,
        action_payload={"period": month, "identities": bad},
    )


def close_period(year, month) -> MacroSnapshot | None:
    """Run the steps of docs/03 section 7 for one month. Returns the snapshot."""
    with transaction.atomic():
        period = Period.objects.select_for_update().filter(year=year, month=month).first()
        if period is None:
            return None  # nothing happened that month
        existing = MacroSnapshot.objects.filter(period=period).first()
        if existing is not None and period.status == Period.CLOSED:
            return existing
        period.status = Period.CLOSING  # 1. freeze: nothing new is dated in it (payments are dated by the day)
        period.save(update_fields=["status"])

        previous = (
            MacroSnapshot.objects.filter(
                period__in=Period.objects.filter(year__lt=year) | Period.objects.filter(year=year, month__lt=month)
            )
            .order_by("-period__year", "-period__month")
            .first()
        )

        # 4. cancel Fund 1 into Fund 2 (HF-6)
        fund1 = ledger.fund1()
        balance = ledger.balance(fund1)
        if balance > 0 and not Entry.objects.filter(transaction__period=period, transaction__kind="cancel").exists():
            ledger.post(
                "cancel",
                f"Period {year}-{month:02d} closed: Fund 1 cancelled",
                [ledger.Leg(fund1, -balance), ledger.Leg(ledger.fund2(), balance)],
                period=period,
            )

        # 2-3. hours by use and the UNIQ flows
        data = accounts.hours_by_use(period, previous.inventory_value if previous else ZERO)
        # 5. outstanding UNIQ and their size in months of spending
        bal = identities.balances(period)
        outstanding = bal["members"] + bal["retirement"] + bal["fund1"]
        # 6. identities
        ident = identities.check_uniq_identities(period, data)
        bad = identities.failures(ident)
        if existing is not None and not bad:
            pass
        # 7. labour values from measured hours (docs/04 section 6)
        from apps.catalogue import services as catalogue_services

        catalogue_services.recompute_values()
        # 8. the next tax rate
        rate, inputs = tax.next_tax_rate(period, data)
        # 9. lights, the credit line, and the world
        light_data = lights.compute_lights(period)
        from . import world

        world_data = world.world_metrics(period)
        transfers.record_active_months(period)
        warnings = []
        if data["residual_warning"]:
            warnings.append(str(accounts.RESIDUAL_WORDS))
        snapshot_values = dict(
            hours_paid=data["hours_paid"],
            tax=data["tax"],
            net_issued=data["net_issued"],
            transfers=data["transfers"],
            spent=data["spent"],
            cancelled=data["cancelled"],
            outstanding=outstanding,
            months_of_spending=_months_of_spending(period, bal["members"]),
            consumption=data["consumption"],
            social=data["social"],
            accumulation=data["accumulation"],
            trade=data["trade"],
            waste=data["waste"],
            depreciation=data["depreciation"],
            inventory_change=data["inventory_change"],
            inventory_value=data["inventory_value"],
            hours_residual=data["hours_residual"],
            tax_rate_used=period.tax_rate,
            tax_rate_next=rate,
            tax_inputs={**inputs, "warnings": warnings},
            lights=light_data,
            world=world_data,
            identities={k: str(v) for k, v in ident.items()},
        )
        snapshot, _created = MacroSnapshot.objects.update_or_create(period=period, defaults=snapshot_values)
        lights.credit_line_check(period, data["hours_paid"])
        retirement.suggest(period, light_data)  # only a notice: nothing moves without the member (HF-8)
        if bad:
            period.next_tax_rate = rate
            period.save(update_fields=["next_tax_rate"])
            _open_identity_ticket(period, bad)
            audit.record("system", "period.close_blocked", period, identities=bad)
            return snapshot  # the period stays `closing` until an auditor acknowledges the ticket

        # 10. store, open the next period with its rate and planned hours, and publish
        period.status, period.closed_at, period.next_tax_rate = Period.CLOSED, timezone.now(), rate
        period.save(update_fields=["status", "closed_at", "next_tax_rate"])
        nxt_year, nxt_month = (year + 1, 1) if month == 12 else (year, month + 1)
        nxt = Period.objects.filter(year=nxt_year, month=nxt_month).first()
        planned = tax.expected_hours(period, data)
        if nxt is None:
            Period.objects.create(year=nxt_year, month=nxt_month, tax_rate=rate, planned_hours=planned)
        else:  # payments on the 1st came first: the rate only changes while no tax was taken yet
            changes = {"planned_hours": planned}
            if not Entry.objects.filter(transaction__period=nxt, transaction__kind="tax").exists():
                changes["tax_rate"] = rate
            for k, v in changes.items():
                setattr(nxt, k, v)
            nxt.save(update_fields=list(changes))
        audit.record("system", "period.closed", period, tax_next=str(rate))
        return snapshot


def acknowledge(period, auditor) -> Period:
    """An auditor looked at a failed identity check: the period may close (docs/03 section 7)."""
    if period.status != Period.CLOSING:
        return period
    period.status, period.closed_at = Period.CLOSED, timezone.now()
    period.save(update_fields=["status", "closed_at"])
    audit.record(auditor.number, "period.acknowledged", period)
    return period


def close_previous_month(today=None):
    """For the job and the command: close the month before today."""
    year, month = previous_month(today)
    return close_period(year, month)


def month_start(year, month) -> date:
    return date(year, month, 1)
