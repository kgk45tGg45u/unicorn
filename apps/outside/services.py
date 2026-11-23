"""Selling to outsiders (docs/07 section 6). Members sell in their own name; the customer pays the seller directly.

No UNIQ ever move for an outside sale (HF-4): the euro price is a separate number on the line, and the hours inside
the product (its labour value, HF-3) are recorded for the month's `trade` use.
"""

import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core import mail
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import cur
from apps.members import crypto
from apps.members import services as member_services
from apps.members.models import ContractTemplate
from apps.rules.services import get_param
from apps.units import services as unit_services

from .models import OutsideCustomer, SellerProfile


class OutsideError(ValueError):
    """A plain-words reason why something cannot be done."""


# --- Becoming a seller (P10.T01) ---


def active_seller(member):
    return SellerProfile.objects.filter(member=member, active=True).first() if member else None


def activate_seller(member, trader_name, address, small_business=True, vat_id="", share=None, show_iban=True):
    from apps.tradefund import services as fund

    if not member_services.is_verified(member):  # HF-13
        raise OutsideError(_("Only verified members can sell to outsiders."))
    if not fund.is_holder(member):
        raise OutsideError(_("To sell outside you must also be a holder, so that the set-aside has a place."))
    if not (trader_name or "").strip() or not (address or "").strip():
        raise OutsideError(_("Please give the name and the address that go on your invoices."))
    template = ContractTemplate.objects.filter(kind="outside_seller", is_current=True).first()
    if template is None:
        raise OutsideError(_("The outside seller terms are not available yet."))
    share = (
        Decimal(str(share)) if share is not None else Decimal(str(get_param("economy.tax_on_outside_sales_estimate")))
    )
    with transaction.atomic():
        member_services.sign(member, template, "click", {"context": "outside_seller"})
        profile, _created = SellerProfile.objects.update_or_create(
            member=member,
            defaults=dict(
                active=True,
                trader_name=trader_name.strip()[:120],
                trader_address_enc=crypto.system_encrypt(address.strip().encode()),
                small_business=bool(small_business),
                vat_id=(vat_id or "").strip(),
                tax_reserve_share=share,
                show_iban=bool(show_iban),
            ),
        )
        audit.record(member.number, "seller.activated", profile)
        return profile


def change_tax_reserve(member, share, reason):
    """The seller may change their tax reserve share, with a reason that is kept in the record."""
    profile = active_seller(member)
    if profile is None:
        raise OutsideError(_("You are not an outside seller."))
    if len((reason or "").strip()) < 5:
        raise OutsideError(_("Please give a reason for the change."))
    try:
        share = Decimal(str(share))
    except InvalidOperation:
        raise OutsideError(_("Please enter the share as a number between 0 and 1.")) from None
    if not Decimal(0) <= share <= Decimal("0.6"):
        raise OutsideError(_("The share must be between 0 and 0.6."))
    old = profile.tax_reserve_share
    profile.tax_reserve_share = share
    profile.save(update_fields=["tax_reserve_share"])
    audit.record(
        member.number, "seller.tax_reserve_changed", profile, old=str(old), new=str(share), reason=reason.strip()
    )
    return profile


def apply_outside_offer(offer, price, currency, seller):
    """Set what is sold outside and by whom. UNIQ prices are untouched (HF-3)."""
    profile = active_seller(seller)
    if profile is None or not unit_services.is_worker(seller, offer.unit):
        raise OutsideError(_("The seller of record must be a worker of the unit with outside sales switched on."))
    if offer.is_service:
        raise OutsideError(_("For now, only products are sold in the outside shop."))  # OWNER-CHECK in docs/12
    price = cur(Decimal(str(price)))
    if price <= 0:
        raise OutsideError(_("Please give a price above zero."))
    offer.sold_outside, offer.outside_price, offer.outside_currency = True, price, (currency or "EUR").upper()[:3]
    offer.outside_seller = seller
    offer.save(update_fields=["sold_outside", "outside_price", "outside_currency", "outside_seller"])
    audit.record(seller.number, "offer.sold_outside", offer, price=str(price))
    return offer


def stop_outside_offer(offer):
    offer.sold_outside = False
    offer.save(update_fields=["sold_outside"])
    return offer


def propose_outside_offer(member, offer, price, currency, seller):
    """A council decision of kind `outside_prices`; a one-person unit decides directly."""
    if not unit_services.can_edit_unit(member, offer.unit):
        raise OutsideError(_("Only the unit's council can decide what is sold outside."))
    if not unit_services.has_council(offer.unit):
        return apply_outside_offer(offer, price, currency, seller)
    return unit_services.open_decision(
        member,
        offer.unit,
        _("Sell %(item)s to outside customers for %(price)s %(cur)s")
        % {"item": offer.item.name, "price": price, "cur": currency},
        kind="outside_prices",
        payload={"offer": offer.pk, "price": str(price), "currency": currency, "seller": seller.number},
    )


# --- The shop and checkout (P10.T02) ---


def shop_offers():
    from apps.catalogue.models import Offer

    return [
        o
        for o in Offer.objects.filter(
            sold_outside=True, status="active", outside_price__isnull=False, unit__status__in=("trial", "open")
        ).select_related("item", "unit", "outside_seller")
        if active_seller(o.outside_seller)
    ]


def reference_of(order) -> str:
    return f"O-{order.pk:06d}"


def seller_iban(profile) -> str:
    return member_services.get_private(profile.member).get("iban", "") if profile.show_iban else ""


def place_outside_order(offer, quantity, name, email, address, country, read_info, consent, delivery=None):
    """An outside customer orders without an account. The order waits until the seller confirms the payment."""
    from apps.catalogue import services as catalogue
    from apps.market.models import Order, OrderLine

    from . import cap

    if not read_info:
        raise OutsideError(_("Please tick that you have read the consumer information."))
    if not consent:
        raise OutsideError(_("Please agree to the privacy notice."))
    if not (name or "").strip() or "@" not in (email or "") or not (address or "").strip():
        raise OutsideError(_("Please give your name, email address and delivery address."))
    try:
        quantity = Decimal(str(quantity))
    except InvalidOperation:
        raise OutsideError(_("Please enter how many you want.")) from None
    if quantity <= 0 or quantity != quantity.quantize(Decimal("0.0001")):
        raise OutsideError(_("Please enter how many you want.")) from None
    with transaction.atomic():
        offer = type(offer).objects.select_related("item", "unit", "outside_seller").get(pk=offer.pk)
        profile = active_seller(offer.outside_seller)
        if not offer.sold_outside or offer.status != "active" or profile is None or offer.outside_price is None:
            raise OutsideError(_("This offer is not for sale outside Unicorn."))
        if offer.is_service:
            raise OutsideError(_("For now, only products are sold in the outside shop."))
        now = timezone.now()
        due = cap.earliest_date(offer, quantity)
        customer = OutsideCustomer.objects.create(
            name_enc=crypto.system_encrypt(name.strip().encode()),
            email_enc=crypto.system_encrypt(email.strip().encode()),
            address_enc=crypto.system_encrypt(address.strip().encode()),
            country=(country or "")[:2].upper(),
            privacy_consent_at=now,
            delete_contact_after=now + timedelta(days=180),
        )
        order = Order.objects.create(kind="outside", outside_customer=customer, public_token=secrets.token_urlsafe(24))
        line = OrderLine.objects.create(
            order=order,
            offer=offer,
            quantity=quantity,
            price_uniq=0,  # no UNIQ move for an outside sale (HF-4)
            total_uniq=0,
            price_eur=offer.outside_price,
            currency=offer.outside_currency,
            seller=offer.outside_seller,
            value_at_order=cur_hours(offer.value_total * quantity),
            due_date=due,
        )
        if delivery and delivery.get("mode") == "deliver":  # a carrier: couriers are paid in UNIQ, outsiders have none
            from apps.logistics import services as logistics

            try:
                logistics.arrange(line, None, delivery)
            except logistics.LogisticsError as e:
                raise OutsideError(str(e)) from None
        audit.record("outside", "outside.order_placed", order, offer=offer.pk, total=str(total_of(line)))
        unit_services.touch(offer.unit)
        _confirmation_mail(order, line, profile, email.strip())
        if cap.moved_to_next_month(offer, quantity, due, catalogue.lead_time_days(offer)):
            cap.tell_unit(offer)
        return order


def cur_hours(x):
    from apps.core.money import uniq

    return uniq(x)


def total_of(line) -> Decimal:
    return cur(line.price_eur * line.quantity)


def _confirmation_mail(order, line, profile, email):
    iban = seller_iban(profile)
    pay = (
        _("Please pay %(total)s %(cur)s to %(name)s, account number %(iban)s, with the reference %(ref)s.")
        % {
            "total": total_of(line),
            "cur": line.currency,
            "name": profile.trader_name,
            "iban": iban,
            "ref": reference_of(order),
        }
        if iban
        else _("Please pay %(total)s %(cur)s to %(name)s in person. Reference: %(ref)s.")
        % {"total": total_of(line), "cur": line.currency, "name": profile.trader_name, "ref": reference_of(order)}
    )
    body = "\n\n".join(
        [
            _("Thank you for your order: %(qty)s x %(item)s.")
            % {"qty": line.quantity.normalize(), "item": line.offer.item.name},
            pay,
            _("Delivery: from %(date)s.") % {"date": line.due_date},
            _("You can withdraw within 14 days. Your order page: %(url)s")
            % {"url": f"{_site()}/shop/order/{order.public_token}/"},
        ]
    )
    mail.send_mail(_("Your order %(ref)s") % {"ref": reference_of(order)}, body, None, [email])


def _site():
    from django.conf import settings

    return settings.SITE_URL


# --- Payment received: the set-aside (P10.T03) ---


def confirm_customer_payment(order, seller, amount):
    """The seller says the customer paid. Production can start, an invoice is issued and the set-aside is booked."""
    from apps.market import services as market
    from apps.tradefund.models import Holder
    from apps.tradefund.services import FundError, record_setaside

    from . import invoices

    try:
        amount = cur(Decimal(str(amount).replace(",", ".")))
    except InvalidOperation:
        raise OutsideError(_("Please enter the amount as a number.")) from None
    if amount <= 0:
        raise OutsideError(_("The amount must be more than zero."))
    with transaction.atomic():
        order = type(order).objects.select_for_update().get(pk=order.pk)
        line = order.lines.select_related("offer__unit", "offer__item").get()
        if order.kind != "outside" or line.seller_id != getattr(seller, "pk", None):
            raise OutsideError(_("Only the seller of this order can confirm the payment."))
        if order.paid_at is not None:
            raise OutsideError(_("This payment was already confirmed."))
        if line.status == "cancelled":
            raise OutsideError(_("This order was cancelled."))
        profile = active_seller(seller)
        holder = Holder.objects.filter(member=seller, status=Holder.ACTIVE).first()
        if profile is None or holder is None:
            raise OutsideError(_("The seller must be an active holder."))
        tax_reserve = cur(amount * profile.tax_reserve_share)
        setaside = cur((amount - tax_reserve) * Decimal(str(get_param("tradefund.setaside_share_of_net"))))
        order.paid_at = timezone.now()
        order.save(update_fields=["paid_at"])
        invoice = invoices.issue_invoice(order, line, profile, amount, tax_reserve, setaside)
        try:
            if setaside > 0:
                record_setaside(
                    holder,
                    setaside,
                    line.currency,
                    _("Set-aside of outside sale %(no)s") % {"no": invoice.number},
                    ref=("invoice", invoice.pk),
                )
        except FundError as e:
            raise OutsideError(str(e)) from None
        if line.offer.is_service:  # a courier leg: the trip is made when the product is sent
            line.status = "ready"
            line.save(update_fields=["status"])
        else:
            market._fulfil(line)  # production can start now
        audit.record(seller.number, "outside.paid", order, amount=str(amount), setaside=str(setaside))
        invoices.check_small_business(seller)
        return invoice


def cancel_unpaid(now=None) -> int:
    """Outside orders unpaid after 14 days are cancelled, and the customer is told. Safe to run twice."""
    from apps.market.models import Order

    now = now or timezone.now()
    done = 0
    for order in Order.objects.filter(kind="outside", paid_at__isnull=True, created_at__lte=now - timedelta(days=14)):
        line = order.lines.first()
        if line is None or line.status == "cancelled":
            continue
        line.status = "cancelled"
        line.save(update_fields=["status"])
        _mail_customer(
            order,
            _("Your order %(ref)s was cancelled") % {"ref": reference_of(order)},
            _("We did not receive the payment within 14 days, so the order was cancelled."),
        )
        audit.record("system", "outside.order_cancelled", order)
        done += 1
    return done


def _mail_customer(order, subject, body):
    customer = order.outside_customer
    if customer is None or customer.wiped_at is not None:
        return
    mail.send_mail(subject, body, None, [crypto.system_decrypt(customer.email_enc).decode()])


def refund_order(order, seller, reason):
    """The seller refunds the customer from their own account; the set-aside is reversed, the tax reserve stays."""
    from apps.market import services as market
    from apps.tradefund.models import Holder
    from apps.tradefund.services import FundError, reverse_setaside

    if len((reason or "").strip()) < 3:
        raise OutsideError(_("Please say why the order is refunded."))
    with transaction.atomic():
        order = type(order).objects.select_for_update().get(pk=order.pk)
        invoice = getattr(order, "invoice", None)
        line = order.lines.get()
        if line.seller_id != seller.pk or invoice is None:
            raise OutsideError(_("Only the seller of a paid order can refund it."))
        if invoice.refunded_at is not None:
            raise OutsideError(_("This order was already refunded."))
        holder = Holder.objects.get(member=seller)
        try:
            if invoice.setaside > 0:
                reverse_setaside(
                    holder,
                    invoice.setaside,
                    invoice.currency,
                    _("Refund of outside sale %(no)s: %(why)s") % {"no": invoice.number, "why": reason.strip()},
                    ref=("invoice", invoice.pk),
                )
        except FundError as e:
            raise OutsideError(str(e)) from None
        if line.status not in ("delivered",):
            if line.production_order_id or line.stock_lot_id:
                market._unassign(line)
            line.status = "cancelled"
            line.save(update_fields=["status"])
        invoice.refunded_at = timezone.now()
        invoice.save(update_fields=["refunded_at"])
        audit.record(seller.number, "outside.refunded", order, reason=reason.strip())
        return invoice


# --- Delivery and what the macro accounts read (P10.T07) ---


def deliver(line, seller):
    """The seller hands the product over (pickup). Its hours count as `trade` in the books of hours."""
    from apps.market import services as market
    from apps.market.models import OrderLine

    with transaction.atomic():
        line = market._lock_line(line)
        if line.order.kind != "outside" or line.seller_id != seller.pk:
            raise OutsideError(_("Only the seller of this order can hand it over."))
        if line.order.paid_at is None:
            raise OutsideError(_("The payment is not confirmed yet."))
        if line.status == OrderLine.DELIVERED:
            return line
        if line.status not in (OrderLine.READY, OrderLine.FROM_STOCK):
            raise OutsideError(_("This order is not ready to be handed over."))
        if line.stock_lot_id:
            market.draw_stock(line.stock_lot, line.quantity)
        line.status, line.delivered_at = OrderLine.DELIVERED, timezone.now()
        line.save(update_fields=["status", "delivered_at"])
        customer = line.order.outside_customer
        customer.delete_contact_after = line.delivered_at + timedelta(days=90)
        customer.save(update_fields=["delete_contact_after"])
        audit.record(seller.number, "outside.delivered", line, hours=str(line.value_at_order))
        unit_services.touch(line.offer.unit)
        return line


def place_courier_leg(product_order, proposal):
    """An outside customer pays a courier in euros. The trip is its own outside order with the courier as seller, so
    it has its own payment reference, invoice and set-aside, and the customer pays the courier directly (HF-4)."""
    from apps.market.models import Order, OrderLine

    co = proposal.courier_offer
    seller = co.outside_seller
    profile = active_seller(seller)
    if profile is None:
        raise OutsideError(_("The courier cannot sell outside yet."))
    with transaction.atomic():
        order = Order.objects.create(
            kind="outside",
            outside_customer=product_order.outside_customer,
            public_token=secrets.token_urlsafe(24),
        )
        line = OrderLine.objects.create(
            order=order,
            offer=co.offer,
            quantity=Decimal(1),
            price_uniq=0,
            total_uniq=0,
            price_eur=proposal.eur,
            currency="EUR",
            seller=seller,
            value_at_order=cur_hours(proposal.hours),  # the hours of the trip count as `trade`
            due_date=timezone.localdate(),
        )
        audit.record("outside", "outside.courier_ordered", order, total=str(total_of(line)))
        customer = product_order.outside_customer
        _confirmation_mail(order, line, profile, crypto.system_decrypt(customer.email_enc).decode())
        return line


def ask_customer_to_confirm(shipment):
    _mail_customer(
        shipment.order,
        _("Your order %(ref)s was delivered") % {"ref": reference_of(shipment.order)},
        _("Please confirm that it arrived: %(url)s") % {"url": f"{_site()}/shop/order/{shipment.order.public_token}/"},
    )


def _hand_over_leg(line):
    """Deliver an outside line without asking the seller again (the customer has confirmed)."""
    deliver(line, line.seller)


def customer_received(order):
    """The customer confirms through the link in the email that it arrived (P12.T06). A courier is paid its hours."""
    from apps.logistics import services as logistics
    from apps.logistics.models import Shipment

    shipment = Shipment.objects.filter(order=order).first()
    if shipment is None or shipment.status not in ("sent", "delivered"):
        raise OutsideError(_("There is no parcel on its way for this order."))
    if shipment.status == "sent" and shipment.mode == "unicorn_courier":
        raise OutsideError(_("The courier has not marked it as delivered yet."))
    line = order.lines.get()
    _hand_over_leg(line)
    if shipment.courier_line_id:
        _hand_over_leg(shipment.courier_line)
        logistics.pay_courier_hours(shipment, shipment.courier_line)
    shipment.status, shipment.delivered_at = "delivered", shipment.delivered_at or timezone.now()
    shipment.save(update_fields=["status", "delivered_at"])
    return shipment


def auto_confirm_deliveries(now=None) -> int:
    """Outside deliveries that nobody confirmed count as received after `market.delivery_confirm_hours`."""
    from apps.logistics.models import Shipment

    cutoff = (now or timezone.now()) - timedelta(hours=get_param("market.delivery_confirm_hours"))
    done = 0
    for s in Shipment.objects.filter(
        order__buyer__isnull=True, status="delivered", delivered_at__lte=cutoff
    ).select_related("order"):
        if s.line.status != "delivered":
            customer_received(s.order)
            done += 1
    return done


def set_courier_rates(member, courier_offer, base_eur, per_km_eur, seller):
    """The courier unit's council sets what outside customers pay for a delivery, and who sells it (HF-4)."""
    unit = courier_offer.offer.unit
    if not unit_services.can_edit_unit(member, unit):
        raise OutsideError(_("Only the courier unit's council can set its prices for outside customers."))
    if active_seller(seller) is None or not unit_services.is_worker(seller, unit):
        raise OutsideError(_("The seller must be a worker of the courier unit with outside sales switched on."))
    try:
        base, per_km = cur(Decimal(str(base_eur))), cur(Decimal(str(per_km_eur or 0)))
    except InvalidOperation:
        raise OutsideError(_("Please enter the prices as numbers.")) from None
    if base < 0 or per_km < 0 or (base == 0 and per_km == 0):
        raise OutsideError(_("Please give a price above zero."))
    courier_offer.outside_base_eur, courier_offer.outside_per_km_eur, courier_offer.outside_seller = (
        base,
        per_km,
        seller,
    )
    courier_offer.save(update_fields=["outside_base_eur", "outside_per_km_eur", "outside_seller"])
    audit.record(member.number, "courier.outside_rates", courier_offer, base=str(base), per_km=str(per_km))
    return courier_offer


def _first_of(year, month):
    from datetime import date

    return date(year, month, 1)


def _paid_invoices(since=None, year=None, month=None):
    from .models import Invoice

    qs = Invoice.objects.filter(paid_at__isnull=False, refunded_at__isnull=True)
    if year:
        qs = qs.filter(paid_at__year=year, paid_at__month=month)
    if since:
        qs = qs.filter(paid_at__gte=since)
    return qs


def confirmed_sales_eur(year, month) -> Decimal:
    return cur(sum((i.total_eur for i in _paid_invoices(year=year, month=month)), Decimal(0)))


def tax_share(year, month):
    rows = list(_paid_invoices(year=year, month=month))
    total = sum((i.total_eur for i in rows), Decimal(0))
    if not total:
        return None
    from apps.tradefund import fx

    reserve = sum((fx.to_eur(i.tax_reserve, i.currency) for i in rows), Decimal(0))
    return (reserve / total).quantize(Decimal("0.0001"))


def sales_after_tax_and_hours(months):
    """(euros after the sellers' tax reserves, hours inside the delivered outside lines, months with data)."""
    from apps.market.models import OrderLine
    from apps.tradefund import fx

    since = timezone.now() - timedelta(days=31 * months)
    invoices = list(_paid_invoices(since=since))
    euros = sum((fx.to_eur(i.total - i.tax_reserve, i.currency) for i in invoices), Decimal(0))
    hours = sum(
        (
            line.value_at_order
            for line in OrderLine.objects.filter(order__kind="outside", status="delivered", delivered_at__gte=since)
        ),
        Decimal(0),
    )
    covered = len({(i.paid_at.year, i.paid_at.month) for i in invoices})
    return euros, hours, covered


def wipe_contacts(now=None) -> int:
    """After the keeping period the customer's contact fields are wiped; the invoice keeps its own copy."""
    now = now or timezone.now()
    done = 0
    for c in OutsideCustomer.objects.filter(delete_contact_after__lte=now, wiped_at__isnull=True):
        c.name_enc = c.email_enc = c.address_enc = b""
        c.wiped_at = now
        c.save(update_fields=["name_enc", "email_enc", "address_enc", "wiped_at"])
        done += 1
    return done


# --- Withdrawal (P10.T06) ---

WITHDRAWAL_DAYS = 14


def withdrawal_open(order, now=None) -> bool:
    now = now or timezone.now()
    line = order.lines.first()
    start = (line.delivered_at if line is not None and line.delivered_at else None) or order.created_at
    return order.withdrawn_at is None and now <= start + timedelta(days=WITHDRAWAL_DAYS)


def request_withdrawal(order, now=None):
    from apps.core.notify import notify

    if order.withdrawn_at is not None:
        raise OutsideError(_("You already withdrew from this order."))
    if not withdrawal_open(order, now):
        raise OutsideError(_("The 14 days to withdraw have ended."))
    line = order.lines.get()
    order.withdrawn_at = now or timezone.now()
    order.save(update_fields=["withdrawn_at"])
    notify(
        line.seller,
        _("A customer withdrew from order %(ref)s. Please refund them.") % {"ref": reference_of(order)},
        f"/shop/seller/{order.pk}/",
        email=True,
    )
    audit.record("outside", "outside.withdrawn", order)
    return order
