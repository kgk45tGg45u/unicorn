"""Payment requests (docs/07 section 4). The app never moves money (HF-12).

A request says: "Please pay X to Y with reference Z by this date". The payer and the receiver each confirm, and when
their amounts agree, the fund's books record the movement. Different amounts open a report for random confirmers.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import cur
from apps.core.notify import notify
from apps.members import crypto
from apps.members import services as member_services
from apps.rules.services import get_param

from . import books, fx, payers, trust
from .models import ExternalPayee, Holder, PaymentRequest
from .services import FundError

# Functions called with (request) when a payment is confirmed, or when a request cannot be paid now.
CONFIRMED_HOOKS: list = []
UNPAYABLE_HOOKS: list = []


def reference_for(ticket, number=None) -> str:
    if ticket is not None:
        return f"Unicorn trade fund, ticket {ticket.number}"
    return f"Unicorn trade fund, payment {number}" if number else "Unicorn trade fund"


def new_external_payee(created_by, name, iban, country="") -> ExternalPayee:
    iban = "".join((iban or "").split()).upper()
    if not (name or "").strip() or len(iban) < 8:
        raise FundError(_("Please give the name and the account number of the person or company to pay."))
    return ExternalPayee.objects.create(
        name=name.strip()[:120],
        iban_enc=crypto.system_encrypt(iban.encode()),
        country=country[:2],
        created_by=created_by,
    )


def spent_by_mandate(mandate) -> Decimal:
    rows = PaymentRequest.objects.filter(mandate=mandate).exclude(status__in=("cancelled", "missed"))
    return sum((fx.to_eur(r.amount, r.currency) for r in rows if not r.replaced_by.exists()), Decimal(0))


def check_mandate(mandate, amount, currency="EUR"):
    """A mandate's requests together must stay within its spending limit (docs/05 section 5)."""
    limit = Decimal(str(mandate.powers.get("spend_limit_eur", 0)))
    new = fx.to_eur(amount, currency)
    if spent_by_mandate(mandate) + new > limit:
        raise FundError(_("This is more than the mandate allows (%(limit)s euros in all).") % {"limit": limit})


def request_payment(
    *,
    payer,
    amount,
    currency,
    reason_kind,
    ticket=None,
    mandate=None,
    payee_holder=None,
    payee_member=None,
    payee_external=None,
    confirmer=None,
    description="",
    purpose="",
    ref=None,
    replaces=None,
) -> PaymentRequest:
    amount = cur(amount)
    if amount <= 0:
        raise FundError(_("A payment must be more than zero."))
    if sum(x is not None for x in (payee_holder, payee_member, payee_external)) != 1:
        raise FundError(_("A payment needs exactly one receiver."))
    if payer.status != Holder.ACTIVE:
        raise FundError(_("This holder cannot pay now."))
    if currency != payer.currency:
        raise FundError(_("This holder holds in %(currency)s.") % {"currency": payer.currency})
    if payee_holder is not None and payee_holder.currency != currency:
        raise FundError(_("A holder can only pass euros on to a holder in the same currency."))
    with transaction.atomic():
        payer = Holder.objects.select_for_update().get(pk=payer.pk)
        if payers.available(payer) < amount:
            raise FundError(_("This holder does not hold enough free euros for this payment."))
        if mandate is not None:
            check_mandate(mandate, amount, currency)
        ref_type, ref_id = ("", "")
        if isinstance(ref, tuple):
            ref_type, ref_id = str(ref[0]), str(ref[1])
        elif ref is not None:
            ref_type, ref_id = ref.__class__.__name__.lower(), str(ref.pk)
        pr = PaymentRequest.objects.create(
            ticket=ticket,
            mandate=mandate,
            payer=payer,
            payee_holder=payee_holder,
            payee_member=payee_member,
            payee_external=payee_external,
            confirmer=confirmer,
            amount=amount,
            currency=currency,
            reference=reference_for(ticket),
            description=(description or "")[:200],
            reason_kind=reason_kind,
            purpose=purpose,
            ref_type=ref_type,
            ref_id=ref_id,
            due_date=timezone.localdate() + timedelta(days=get_param("tradefund.payment_deadline_days")),
            replaces=replaces,
        )
        if ticket is None:
            pr.reference = reference_for(None, f"P-{pr.pk:06d}")
            pr.save(update_fields=["reference"])
        audit.record(
            "system", "payment.requested", pr, payer=payer.member.number, amount=str(amount), currency=currency
        )
        notify(
            payer.member,
            _("Please pay %(amount)s %(currency)s to %(to)s by %(date)s. Reference: %(ref)s.")
            % {
                "amount": amount,
                "currency": currency,
                "to": payee_label(pr),
                "date": pr.due_date,
                "ref": pr.reference,
            },
            f"/fund/pay/{pr.pk}/",
            email=True,
        )
        return pr


def payee_label(pr) -> str:
    """Who is paid, in words a payer may read: a member number, or the name of an outside party."""
    if pr.payee_holder_id:
        return pr.payee_holder.member.number
    if pr.payee_member_id:
        return pr.payee_member.number
    return pr.payee_external.name


def payee_iban(pr) -> str:
    if pr.payee_holder_id:
        return member_services.get_private(pr.payee_holder.member).get("iban", "")
    if pr.payee_member_id:
        return member_services.get_private(pr.payee_member).get("iban", "")
    return crypto.system_decrypt(pr.payee_external.iban_enc).decode()


def instructions(pr, viewer) -> dict:
    """What the payer must do. The account number is shown to the payer only."""
    data = {
        "amount": pr.amount,
        "currency": pr.currency,
        "to": payee_label(pr),
        "reference": pr.reference,
        "due_date": pr.due_date,
        "iban": None,
    }
    if viewer is not None and viewer.pk == pr.payer.member_id:
        data["iban"] = payee_iban(pr) or None
    return data


def _amount(value) -> Decimal:
    try:
        amount = cur(Decimal(str(value).replace(",", ".")))
    except (InvalidOperation, ValueError, TypeError):
        raise FundError(_("Please enter the amount as a number, for example 120.00.")) from None
    if amount <= 0:
        raise FundError(_("The amount must be more than zero."))
    return amount


def can_confirm_receipt(pr, member) -> bool:
    if member is None:
        return False
    if pr.payee_holder_id:
        return member.pk == pr.payee_holder.member_id
    if pr.payee_member_id:
        return member.pk == pr.payee_member_id
    return pr.confirmer_id == member.pk or (pr.ticket_id is not None and pr.ticket.author_id == member.pk)


def confirm_sent(pr, member, amount):
    """The payer says: I sent it, and this is the amount (a sensitive action)."""
    amount = _amount(amount)
    with transaction.atomic():
        pr = PaymentRequest.objects.select_for_update().get(pk=pr.pk)
        if member is None or member.pk != pr.payer.member_id:
            raise FundError(_("Only the payer can say that the payment was sent."))
        if pr.status not in ("requested", "overdue", "received"):
            raise FundError(_("This payment cannot be confirmed any more."))
        if pr.sent_amount is not None:
            raise FundError(_("You already confirmed this payment."))
        pr.sent_amount, pr.sent_at = amount, timezone.now()
        pr.first_confirmer = pr.first_confirmer or "payer"
        audit.record(member.number, "payment.sent", pr, amount=str(amount))
        if pr.received_amount is not None:
            pr.save()
            return _resolve(pr, second="payer")
        pr.status = "sent"
        pr.save()
        _tell_receiver(pr)
        return pr


def confirm_received(pr, member, amount, invoice=None):
    """The receiver says: I received it, and this is the amount. For an outside payee, the buyer confirms."""
    amount = _amount(amount)
    with transaction.atomic():
        pr = PaymentRequest.objects.select_for_update().get(pk=pr.pk)
        if not can_confirm_receipt(pr, member):
            raise FundError(_("Only the receiver can say that the payment arrived."))
        if pr.status not in ("requested", "overdue", "sent"):
            raise FundError(_("This payment cannot be confirmed any more."))
        if pr.received_amount is not None:
            raise FundError(_("You already confirmed this payment."))
        pr.received_amount, pr.received_at = amount, timezone.now()
        pr.first_confirmer = pr.first_confirmer or "payee"
        if pr.payee_external_id:
            pr.confirmed_by_buyer = member
            pr.invoice = invoice or pr.invoice
        audit.record(member.number, "payment.received", pr, amount=str(amount))
        if pr.sent_amount is not None:
            pr.save()
            return _resolve(pr, second="payee")
        pr.status = "received"
        pr.save()
        notify(
            pr.payer.member,
            _("The receiver says %(amount)s %(currency)s arrived. Please confirm that you sent it.")
            % {"amount": amount, "currency": pr.currency},
            f"/fund/pay/{pr.pk}/",
        )
        return pr


def _tell_receiver(pr):
    receiver = pr.payee_holder.member if pr.payee_holder_id else pr.payee_member if pr.payee_member_id else pr.confirmer
    if receiver is not None:
        notify(
            receiver,
            _("%(amount)s %(currency)s was sent to you. Please confirm when it arrives.")
            % {"amount": pr.sent_amount, "currency": pr.currency},
            f"/fund/pay/{pr.pk}/",
        )


def _resolve(pr, second):
    if pr.sent_amount == pr.received_amount:
        return _book(pr, pr.sent_amount)
    pr.status = "mismatch"
    pr.save(update_fields=["status"])
    _open_report(pr, second)
    return pr


def _book(pr, amount):
    """Both sides agree (or confirmers decided): write the fund's books and the trust events."""
    why = f"{pr.reference}. {pr.description}".strip()
    kind = "transfer_out" if pr.payee_holder_id else "payment_out"
    books.post_fund(pr.payer, kind, -amount, why, pr.reason_kind, ref=pr)
    if pr.payee_holder_id:
        books.post_fund(pr.payee_holder, "transfer_in", amount, why, pr.reason_kind, ref=pr)
    pr.status = "confirmed"
    pr.final_amount = amount
    pr.save(update_fields=["status", "final_amount"])
    was_late = pr.reminded_at is not None or (
        pr.sent_at is not None and timezone.localtime(pr.sent_at).date() > pr.due_date
    )
    trust.record(pr.payer, "late" if was_late else "on_time", ref=f"payment:{pr.pk}", note=why)
    audit.record("system", "payment.confirmed", pr, amount=str(amount))
    for hook in CONFIRMED_HOOKS:
        hook(pr)
    return pr


# --- The amounts differ: a report for random confirmers ---


def _open_report(pr, second):
    from apps.tickets import services as ticket_services
    from apps.tickets.briefs import _check

    reporter = pr.payer.member if second == "payer" else (pr.payee_holder.member if pr.payee_holder_id else None)
    if reporter is None:
        reporter = pr.payee_member if pr.payee_member_id else pr.confirmer
    reasons = [_("The amounts differ"), _("Nothing arrived"), _("Something else")]
    check = _check(
        _("What is the report about?"), str(reasons[0]), [str(r) for r in reasons[1:]], _("the first sentence")
    )
    brief = _(
        "The payer and the receiver of a payment of the trade fund do not agree. The payer says %(sent)s %(cur)s "
        "was sent. The receiver says %(got)s %(cur)s arrived. Yes means the report is right and the amount of "
        "the member who reported it counts. No means the amount of the other side counts."
    ) % {"sent": pr.sent_amount, "got": pr.received_amount, "cur": pr.currency}
    ticket = ticket_services.create_ticket(
        "flag",
        reporter,
        _("The amounts of payment %(id)s differ") % {"id": pr.pk},
        brief=brief,
        check=check,
        action_payload={
            "dispute": {"reason": str(reasons[0]), "payment_request": pr.pk, "reporter_side": second},
            "members": [pr.payer.member.number],
        },
    )
    pr.flag_ticket = ticket.number
    pr.save(update_fields=["flag_ticket"])
    for who in (pr.payer.member, reporter):
        if who is not None:
            notify(who, _("The amounts of a payment differ. Members will look at it."), f"/tickets/{ticket.number}/")


def dispute_decided(ticket, upheld):
    """The confirmers decided a payment report: book the amount that counts, and rate the side that was wrong."""
    info = (ticket.action_payload or {}).get("dispute") or {}
    pr = PaymentRequest.objects.filter(pk=info.get("payment_request")).first()
    if pr is None or pr.status != "mismatch":
        return
    with transaction.atomic():
        reporter_side = info.get("reporter_side")
        reporter_amount = pr.sent_amount if reporter_side == "payer" else pr.received_amount
        other_amount = pr.received_amount if reporter_side == "payer" else pr.sent_amount
        wrong_side = ("payee" if reporter_side == "payer" else "payer") if upheld else reporter_side
        wrong_holder = pr.payer if wrong_side == "payer" else pr.payee_holder
        if wrong_holder is not None:
            trust.record(wrong_holder, "mismatch", ref=f"payment:{pr.pk}", note=_("The amounts of a payment differed."))
        amount = reporter_amount if upheld else other_amount
        _book(pr, amount)


def register():
    from apps.tasks import services as task_services
    from apps.tickets import flags

    if dispute_decided not in flags.DISPUTE_HOOKS:
        flags.DISPUTE_HOOKS.append(dispute_decided)
    task_services.PAYMENT_REQUEST_HOOK = mandate_spend


def mandate_spend(mandate, amount_eur, note=""):
    """Replaces the stub of P07.T07: a delegate's spending must stay within the mandate's limit, in total."""
    check_mandate(mandate, Decimal(str(amount_eur)), "EUR")
    return {"mandate": mandate.pk, "amount": str(amount_eur), "cleared": True}


# --- Deadlines ---


def run_deadlines(today=None) -> dict:
    """Daily. Past the due date: overdue and a reminder. After the extra days: missed, a trust event, a new payer,
    or the loss reserve. Safe to run twice."""
    today = today or timezone.localdate()
    extra = timedelta(days=get_param("tradefund.missed_after_extra_days"))
    counts = {"overdue": 0, "missed": 0, "reassigned": 0}
    for pr in PaymentRequest.objects.filter(status__in=("requested", "overdue"), due_date__lt=today).select_related(
        "payer__member"
    ):
        with transaction.atomic():
            pr = PaymentRequest.objects.select_for_update().get(pk=pr.pk)
            if pr.status == "requested":
                pr.status, pr.reminded_at = "overdue", timezone.now()
                pr.save(update_fields=["status", "reminded_at"])
                notify(
                    pr.payer.member,
                    _("Your payment of %(amount)s %(currency)s to %(to)s is overdue. Please send it soon.")
                    % {"amount": pr.amount, "currency": pr.currency, "to": payee_label(pr)},
                    f"/fund/pay/{pr.pk}/",
                    email=True,
                )
                counts["overdue"] += 1
            if pr.status == "overdue" and today > pr.due_date + extra:
                counts["missed"] += 1
                counts["reassigned"] += _miss(pr)
    return counts


def _miss(pr) -> int:
    pr.status = "missed"
    pr.save(update_fields=["status"])
    if pr.purpose == "handover":  # a holder who does not pass on their part has gone: the loss reserve covers it
        from . import services

        services.vanished(pr.payer, _("A holder did not hand over the held euros in time."))
        return 0
    trust.record(pr.payer, "missed", ref=f"payment:{pr.pk}", note=_("A payment was not sent in time."))
    notify(
        pr.payer.member,
        _("Your payment of %(amount)s %(currency)s counts as missed. Another holder pays it now.")
        % {"amount": pr.amount, "currency": pr.currency},
        f"/fund/pay/{pr.pk}/",
        email=True,
    )
    return len(reassign(pr))


def reassign(pr) -> list:
    """A new request to another payer; if no holder can pay, the loss reserve covers it."""
    tried, cursor = {pr.payer_id}, pr.replaces
    while cursor is not None:
        tried.add(cursor.payer_id)
        cursor = cursor.replaces
    parts = payers.choose_payers(pr.amount, pr.currency, exclude=tried)
    created = []
    if parts:
        for holder, part in parts:
            created.append(
                request_payment(
                    payer=holder,
                    amount=part,
                    currency=pr.currency,
                    reason_kind=pr.reason_kind,
                    ticket=pr.ticket,
                    mandate=pr.mandate,
                    payee_holder=pr.payee_holder,
                    payee_member=pr.payee_member,
                    payee_external=pr.payee_external,
                    confirmer=pr.confirmer,
                    description=pr.description,
                    purpose=pr.purpose,
                    ref=(pr.ref_type, pr.ref_id) if pr.ref_type else None,
                    replaces=pr,
                )
            )
        return created
    created = trust.cover_from_reserve(pr)
    if not created:
        audit.record("system", "payment.unpayable", pr)
        for hook in UNPAYABLE_HOOKS:
            hook(pr)
    return created
