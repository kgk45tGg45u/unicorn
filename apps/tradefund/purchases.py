"""Buying from capitalism with fund euros (docs/07 section 3).

The steps: a request, the plan check and the make-or-buy rule, approval (automatic, by random confirmers, or by a
referendum), a payment plan, the buyer's receipt, and the receiver's confirmation. The app never buys or pays
anything (HF-12): it asks holders to pay, and people confirm.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import cur
from apps.core.notify import notify
from apps.rules.services import get_param

from . import books, fx, payers, payments, trust
from .models import BuyerVolunteer, GroupTool, Holder, PaymentRequest, PurchaseRequest
from .services import FundError

BUYER_DAYS = 3  # the ticket asks for volunteer buyers for 3 days (docs/07 section 3)
OPEN_STATUSES = ("checking", "approved", "waiting_for_euros", "paying", "bought")


def est_eur(pr) -> Decimal:
    return fx.to_eur(pr.est_price, pr.currency)


def _active_holder(member):
    return Holder.objects.filter(member=member, status=Holder.ACTIVE).first()


# --- 1. The request and the check ---


def check_purchase(pr):
    """The plan check plus the make-or-buy rule: an amber point when Unicorn makes an equal item."""
    from apps.macro import services as macro
    from apps.plan import check as plan_check

    result = plan_check.check(
        {
            "type": "purchase",
            "purchase": pr.pk,
            "amount_eur": str(est_eur(pr)),
            "unit": pr.unit_id,
            "item": pr.item_id,
        }
    )
    if pr.item_id:
        from apps.catalogue.models import Offer

        rate = macro.planning_rate()
        per_unit = est_eur(pr) / (pr.quantity or 1)
        for offer in Offer.objects.filter(item_id=pr.item_id, status="active").select_related("unit")[:3]:
            make_hours = offer.value_total + offer.euro_content / rate
            buy_hours = per_unit / rate
            verdict = (
                _("At the planning rate, making it costs fewer hours than buying it.")
                if make_hours < buy_hours
                else _("At the planning rate, buying it costs fewer hours (for comparing only).")
            )
            result.points.append(
                plan_check.CheckPoint(
                    "amber",
                    _("Unicorn makes this: %(unit)s, %(value)s UNIQ. %(verdict)s")
                    % {"unit": offer.unit.name, "value": round(offer.value_total, 2), "verdict": verdict},
                )
            )
    return result


def create_purchase(
    requester,
    description,
    est_price,
    *,
    quantity=1,
    currency="EUR",
    seller="",
    seller_iban="",
    unit=None,
    item=None,
    why="",
    deliver_to_unit=None,
    deliver_to_member=None,
    source="adhoc",
    purchase_need=None,
    offer_tool=None,
) -> PurchaseRequest:
    from apps.members import services as member_services
    from apps.tickets import services as ticket_services
    from apps.tickets.briefs import _check

    if not member_services.is_verified(requester):  # HF-13
        raise FundError(_("Only verified members can ask the fund to buy something."))
    if not (description or "").strip():
        raise FundError(_("Please say what should be bought."))
    est_price = cur(est_price)
    if est_price <= 0:
        raise FundError(_("Please estimate the price."))
    with transaction.atomic():
        payee = payments.new_external_payee(requester, seller, seller_iban) if (seller_iban or "").strip() else None
        pr = PurchaseRequest.objects.create(
            requester=requester,
            unit=unit,
            item=item,
            description=description.strip()[:200],
            why=(why or "")[:300],
            quantity=quantity,
            est_price=est_price,
            currency=currency,
            seller=(seller or "")[:200],
            payee_external=payee,
            deliver_to_unit=deliver_to_unit or unit,
            deliver_to_member=deliver_to_member,
            source=source,
            purchase_need=purchase_need,
            offer_tool=offer_tool,
        )
        result = check_purchase(pr)
        points = [{"color": p.color, "text": p.text} for p in result.points]
        brief = "\n".join(
            [
                _("%(who)s asks the trade fund to buy %(what)s for about %(price)s %(cur)s.")
                % {"who": requester.number, "what": pr.description, "price": est_price, "cur": currency},
                _("Where: %(seller)s.") % {"seller": pr.seller or _("not said yet")},
                pr.why,
                _("The plan check says:"),
                *[f"- {p['text']}" for p in points],
                _("Do you agree that the fund should buy it?"),
            ]
        )
        check = _check(
            _("About how much will it cost?"),
            f"{est_price} {currency}",
            [f"{cur(est_price * 10)} {currency}", f"{cur(est_price / 10)} {currency}"],
            _("the first sentence"),
        )
        ticket = ticket_services.create_ticket(
            "purchase",
            requester,
            _("Buy: %(what)s") % {"what": pr.description},
            brief=brief,
            check=check,
            scope="unit" if unit else "all",
            scope_unit=unit,
            action_payload={"purchase_request": pr.pk, "amount_eur": str(est_eur(pr))},
            plan_check={"color": result.color, "points": points},
        )
        pr.ticket = ticket
        pr.save(update_fields=["ticket"])
        if purchase_need is not None:
            purchase_need.status = "requested"
            purchase_need.save(update_fields=["status"])
        audit.record(requester.number, "purchase.requested", pr, ticket=ticket.number)
        pr.refresh_from_db()
        return pr


# --- 2. Approval (docs/07 section 3, step 3) ---


def auto_rule(ticket) -> bool:
    """Green, and up to the automatic limit: approved without confirmers."""
    green = (ticket.plan_check or {}).get("color") == "green"
    amount = Decimal(str((ticket.action_payload or {}).get("amount_eur", "0")))
    return green and amount <= get_param("governance.ticket_limits.purchase_auto_eur")


def route_purchase(ticket) -> bool:
    """Above the confirmers' limit only a plan investment line (phase 11) or a referendum can approve it."""
    amount = Decimal(str((ticket.action_payload or {}).get("amount_eur", "0")))
    if amount <= get_param("governance.ticket_limits.purchase_confirm_max_eur"):
        return False
    # OWNER-CHECK: until the yearly plan has investment lines (P11), purchases above the limit go to a referendum.
    from apps.votes import services as vote_services

    vote_services.schedule_referendum(ticket, ticket.title)
    return True


def _of_ticket(ticket) -> PurchaseRequest | None:
    return PurchaseRequest.objects.filter(pk=(ticket.action_payload or {}).get("purchase_request")).first()


def _create_payment_requests(ticket):
    """The ticket action: the purchase was approved, so make the payment plan."""
    pr = _of_ticket(ticket)
    if pr is None:
        raise FundError(_("This ticket does not say what it is about."))
    if pr.ticket_id is None:  # an automatic approval comes before the request knows its ticket
        pr.ticket = ticket
        pr.save(update_fields=["ticket"])
    start_payment(pr)
    pr.refresh_from_db()
    return {"purchase": pr.pk, "method": pr.pay_method, "status": pr.status}


def _purchase_rejected(ticket):
    pr = _of_ticket(ticket)
    if pr is not None and pr.status == "checking":
        pr.status = "rejected"
        pr.save(update_fields=["status"])
        if pr.purchase_need_id:
            pr.purchase_need.status = "open"
            pr.purchase_need.save(update_fields=["status"])
    return {"purchase": pr.pk if pr else None, "rejected": True}


# --- 3. The payment plan (docs/07 section 3, step 4) ---


def start_payment(pr):
    with transaction.atomic():
        pr = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
        if pr.status not in ("checking", "waiting_for_euros"):
            return pr
        requester_holder = _active_holder(pr.requester)
        exclude = [requester_holder] if requester_holder else []
        parts = payers.choose_payers(pr.est_price, pr.currency, exclude=exclude)
        if not parts and requester_holder is not None:
            parts = payers.choose_payers(pr.est_price, pr.currency)  # a holder may pay it to the seller
        if not parts:
            return _wait(pr, _("The fund cannot pay this now. It will try again when euros are free."))
        can_reimburse = (
            requester_holder is not None
            and trust.score(requester_holder) >= get_param("tradefund.reimburse_min_trust")
            and est_eur(pr) <= trust.cap_eur(requester_holder)
            and all(h.pk != requester_holder.pk for h, _p in parts)
        )
        if can_reimburse:
            pr.pay_method, pr.buyer = "reimburse", requester_holder
            _pay_parts(pr, parts, payee_holder=requester_holder)
        elif pr.payee_external_id and len(parts) == 1:
            pr.pay_method = "holder_pays_seller"
            _pay_parts(pr, parts, payee_external=pr.payee_external, confirmer=pr.requester)
        else:
            pr.pay_method = "pooled_to_buyer"
            pr.status = "approved"
            pr.buyer_deadline = timezone.now() + timedelta(days=BUYER_DAYS)
            pr.status_note = _("Waiting for a buyer: holders can offer to buy it.")[:300]
            pr.save()
        audit.record("system", "purchase.plan", pr, method=pr.pay_method)
        return pr


def _wait(pr, note):
    pr.status, pr.status_note = "waiting_for_euros", str(note)[:300]
    pr.save(update_fields=["status", "status_note"])
    return pr


def _pay_parts(pr, parts, **payee):
    for holder, amount in parts:
        payments.request_payment(
            payer=holder,
            amount=amount,
            currency=pr.currency,
            reason_kind="group_purchase",
            ticket=pr.ticket,
            description=pr.description,
            purpose="purchase",
            ref=pr,
            **payee,
        )
    pr.status, pr.status_note = "paying", ""
    pr.save()


# --- Volunteer buyers (pooled purchases) ---


def volunteer(pr, member):
    holder = _active_holder(member)
    if holder is None:
        raise FundError(_("Only holders can buy for the group."))
    if pr.pay_method != "pooled_to_buyer" or pr.buyer_id or pr.status != "approved":
        raise FundError(_("This purchase does not need a buyer now."))
    if holder.currency != pr.currency:
        raise FundError(_("This purchase is in %(currency)s.") % {"currency": pr.currency})
    row, created = BuyerVolunteer.objects.get_or_create(purchase=pr, holder=holder)
    if created:
        audit.record(member.number, "purchase.volunteered", pr)
    return row


def pick_buyer(pr, now=None) -> Holder | None:
    """When the time is up: the volunteer with the highest trust and room wins, and holders send parts to them."""
    now = now or timezone.now()
    with transaction.atomic():
        pr = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
        if pr.buyer_id or pr.status != "approved" or pr.pay_method != "pooled_to_buyer":
            return pr.buyer
        if pr.buyer_deadline and now < pr.buyer_deadline:
            return None
        pool = [v.holder for v in pr.volunteers.select_related("holder__member") if v.holder.status == Holder.ACTIVE]
        pool = [h for h in pool if trust.room_eur(h) >= est_eur(pr)]
        if not pool:
            pr.buyer_deadline = now + timedelta(days=BUYER_DAYS)
            pr.status_note = _("Still waiting for a buyer. Holders with room under their cap can offer.")[:300]
            pr.save(update_fields=["buyer_deadline", "status_note"])
            return None
        buyer = max(pool, key=lambda h: (trust.score(h), -h.pk))
        parts = payers.choose_payers(pr.est_price, pr.currency, exclude=[buyer])
        if not parts:
            _wait(pr, _("The fund cannot pay this now. It will try again when euros are free."))
            return None
        pr.buyer = buyer
        _pay_parts(pr, parts, payee_holder=buyer)
        notify(
            buyer.member, _("You were chosen to buy: %(what)s.") % {"what": pr.description}, f"/fund/purchase/{pr.pk}/"
        )
        return buyer


# --- 4. Payments confirmed, the buyer's steps ---


def _on_payment_confirmed(payment):
    if payment.ref_type != "purchaserequest":
        return
    pr = PurchaseRequest.objects.select_for_update().filter(pk=payment.ref_id).first()
    if pr is None or pr.status != "paying":
        return
    if PaymentRequest.objects.filter(ref_type="purchaserequest", ref_id=str(pr.pk), status__in=PaymentRequest.OPEN):
        return
    if pr.pay_method == "holder_pays_seller":
        paid = sum(
            (
                p.final_amount or 0
                for p in PaymentRequest.objects.filter(
                    ref_type="purchaserequest", ref_id=str(pr.pk), status="confirmed"
                )
            ),
            Decimal(0),
        )
        pr.status, pr.actual_price, pr.status_note = "bought", paid, ""
        pr.save(update_fields=["status", "actual_price", "status_note"])
    else:
        pr.funded, pr.status = True, "approved"
        pr.status_note = _("The money is with the buyer. Please buy it and upload the receipt.")[:300]
        pr.save(update_fields=["funded", "status", "status_note"])
        notify(
            pr.buyer.member,
            _("The money for %(what)s arrived. Please buy it and upload the receipt.") % {"what": pr.description},
            f"/fund/purchase/{pr.pk}/",
        )


def _on_unpayable(payment):
    if payment.ref_type != "purchaserequest":
        return
    pr = PurchaseRequest.objects.filter(pk=payment.ref_id).first()
    if pr is not None and pr.status == "paying":
        _wait(pr, _("The fund cannot pay this now. It will try again when euros are free."))


def paid_to_buyer(pr) -> Decimal:
    rows = PaymentRequest.objects.filter(ref_type="purchaserequest", ref_id=str(pr.pk), status="confirmed")
    return sum((p.final_amount or Decimal(0) for p in rows), Decimal(0))


def record_purchase(pr, member, receipt, actual_price):
    """The buyer bought it: the receipt and the actual price. Change goes back to a holder with room."""
    actual_price = cur(actual_price)
    with transaction.atomic():
        pr = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
        if pr.pay_method == "holder_pays_seller":
            if member.pk != pr.requester_id:
                raise FundError(_("Only the member who asked for this can add the invoice."))
            pr.receipt = receipt or pr.receipt
            pr.save(update_fields=["receipt"])
            return pr
        if pr.buyer is None or member.pk != pr.buyer.member_id:
            raise FundError(_("Only the buyer can add the receipt."))
        if pr.status != "approved" or not pr.funded:
            raise FundError(_("The money has not reached you yet."))
        if receipt is None:
            raise FundError(_("Please upload the receipt."))
        if actual_price <= 0:
            raise FundError(_("Please enter the price you paid."))
        paid = paid_to_buyer(pr)
        if actual_price > paid:
            raise FundError(
                _(
                    "The price is higher than the %(paid)s %(cur)s you received. Please ask for the difference "
                    "with a new request."
                )
                % {"paid": paid, "cur": pr.currency}
            )
        why = _("Purchase %(id)s: %(what)s (receipt uploaded)") % {"id": pr.pk, "what": pr.description}
        books.post_fund(pr.buyer, "payment_out", -actual_price, why, "group_purchase", ref=pr)
        change = paid - actual_price
        pr.receipt, pr.actual_price, pr.change_due = receipt, actual_price, change
        pr.status, pr.status_note = "bought", ""
        pr.save()
        if change > 0:
            others = [
                h
                for h in Holder.objects.filter(status=Holder.ACTIVE, currency=pr.currency).exclude(pk=pr.buyer_id)
                if trust.room_eur(h) > 0
            ]
            if others:
                target = max(others, key=trust.room_eur)
                payments.request_payment(
                    payer=pr.buyer,
                    amount=change,
                    currency=pr.currency,
                    reason_kind="internal",
                    ticket=pr.ticket,
                    payee_holder=target,
                    description=_("Change from purchase %(id)s") % {"id": pr.pk},
                    purpose="change",
                )
        audit.record(member.number, "purchase.bought", pr, price=str(actual_price))
        return pr


def request_difference(pr, member, difference):
    """The price was higher than approved: a new, small purchase request for the difference."""
    if member.pk != pr.requester_id and (pr.buyer is None or member.pk != pr.buyer.member_id):
        raise FundError(_("Only the requester or the buyer can ask for the difference."))
    return create_purchase(
        member,
        _("Difference for purchase %(id)s: %(what)s") % {"id": pr.pk, "what": pr.description},
        difference,
        currency=pr.currency,
        seller=pr.seller,
        unit=pr.unit,
        deliver_to_unit=pr.deliver_to_unit,
        source="adhoc",
    )


def can_confirm_delivery(pr, member) -> bool:
    from apps.units import services as unit_services

    if member is None:
        return False
    if pr.deliver_to_member_id:
        return member.pk == pr.deliver_to_member_id
    if pr.deliver_to_unit_id:
        return unit_services.is_worker(member, pr.deliver_to_unit)
    return member.pk == pr.requester_id


def mark_delivered(pr, member):
    """The receiver confirms the delivery. A tool becomes a group tool, and the ticket closes."""
    from apps.tickets import services as ticket_services

    with transaction.atomic():
        pr = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
        if not can_confirm_delivery(pr, member):
            raise FundError(_("Only the receiver can confirm the delivery."))
        if pr.status != "bought":
            raise FundError(_("This purchase is not bought yet."))
        pr.status, pr.delivered_at = "closed", timezone.now()
        pr.save(update_fields=["status", "delivered_at"])
        if pr.purchase_need_id:
            pr.purchase_need.status = "covered"
            pr.purchase_need.save(update_fields=["status"])
        if pr.source == "tool" and pr.offer_tool_id:
            _tool_delivered(pr)
        if pr.ticket_id and pr.ticket.status == "in_action":
            ticket_services.set_status(pr.ticket, "done", str(_("Delivered.")))
        audit.record(member.number, "purchase.delivered", pr)
        return pr


def _tool_delivered(pr):
    """A tool bought this way belongs to the group and is lent to the unit. Its offer can now be published."""
    from apps.catalogue import services as catalogue_services

    tool = pr.offer_tool
    price = pr.actual_price or pr.est_price
    GroupTool.objects.create(
        item=tool.tool_item,
        purchase_request=pr,
        lent_to_unit=pr.deliver_to_unit,
        euro_price=price,
        currency=pr.currency,
        lifetime_uses=tool.lifetime_uses,
        acquired_at=timezone.now(),
    )
    tool.source, tool.euro_price, tool.currency = "unicorn_owned", price, pr.currency
    tool.save(update_fields=["source", "euro_price", "currency"])
    catalogue_services.request_recompute()


# --- Monthly purchase lists and retries ---


def _unit_requester(unit):
    from apps.units import services as unit_services

    current = unit_services.responsible(unit)
    if current is not None:
        return current.member
    first = unit_services.workers(unit).select_related("member").first()
    return first.member if first else None


def purchase_lists(today=None) -> int:
    """One purchase request per unit and item from the open needs of this month and earlier. Safe to run twice."""
    from apps.catalogue.services import first_of_month
    from apps.market.models import PurchaseNeed

    today = today or timezone.localdate()
    first = first_of_month(today)
    groups = {}
    for need in PurchaseNeed.objects.filter(status="open", month__lte=first).select_related("unit", "item"):
        groups.setdefault((need.unit_id, need.item_id, need.currency), []).append(need)
    made = 0
    for needs in groups.values():
        unit, item = needs[0].unit, needs[0].item
        total = sum((n.euro_estimate for n in needs), Decimal(0))
        requester = _unit_requester(unit)
        if requester is None or total <= 0:
            continue
        with transaction.atomic():
            create_purchase(
                requester,
                _("%(item)s for %(unit)s") % {"item": item.name, "unit": unit.name},
                total,
                quantity=sum((n.quantity for n in needs), Decimal(0)),
                currency=needs[0].currency,
                unit=unit,
                item=item,
                source="recipe_input",
                purchase_need=needs[0],
                why=_("Needed for the recipes of %(unit)s.") % {"unit": unit.name},
            )
            for n in needs[1:]:
                n.status = "requested"
                n.save(update_fields=["status"])
        made += 1
    return made


def run_waiting(now=None) -> int:
    """Daily: try again for purchases waiting for euros, and pick buyers whose time is up."""
    now = now or timezone.now()
    done = 0
    for pr in PurchaseRequest.objects.filter(status="waiting_for_euros"):
        before = pr.status
        start_payment(pr)
        pr.refresh_from_db()
        done += int(pr.status != before)
    for pr in PurchaseRequest.objects.filter(status="approved", pay_method="pooled_to_buyer", buyer__isnull=True):
        if pick_buyer(pr, now) is not None:
            done += 1
    return done


def register():
    from apps.tickets import actions, routing

    from . import payments as pay_module

    actions.register("create_payment_requests", _create_payment_requests, finishes=False)
    actions.register("purchase_rejected", _purchase_rejected)
    routing.AUTO_RULES["purchase"] = auto_rule
    routing.CUSTOM_ROUTES["purchase"] = route_purchase
    if _on_payment_confirmed not in pay_module.CONFIRMED_HOOKS:
        pay_module.CONFIRMED_HOOKS.append(_on_payment_confirmed)
    if _on_unpayable not in pay_module.UNPAYABLE_HOOKS:
        pay_module.UNPAYABLE_HOOKS.append(_on_unpayable)
