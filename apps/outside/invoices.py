"""Invoices of outside sales (docs/07 section 6; legal frame section 4). Numbers have no gaps per seller and year."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.money import cur
from apps.core.notify import notify
from apps.members import crypto
from apps.tradefund import fx

from .models import Invoice, InvoiceCounter

VAT_RATE = Decimal("0.19")  # OWNER-CHECK: reduced rates apply to some goods
SMALL_LAST_YEAR = Decimal("25000")  # § 19 UStG: turnover last year
SMALL_THIS_YEAR = Decimal("100000")  # and this year
WARN_AT = Decimal("0.8")
KEEP_YEARS = 8  # OWNER-CHECK: legal keeping period


def next_number(seller, year) -> str:
    with transaction.atomic():
        counter, _created = InvoiceCounter.objects.select_for_update().get_or_create(seller=seller, year=year)
        counter.last += 1
        counter.save(update_fields=["last"])
        return f"{seller.number}-{year}-{counter.last:04d}"


def vat_note(profile, total) -> str:
    if profile.small_business:
        return str(_("No VAT is charged under § 19 UStG (small business)."))
    vat = cur(total - total / (1 + VAT_RATE))
    return str(_("The total includes VAT at %(rate)s%%: %(vat)s. VAT ID: %(id)s")) % {
        "rate": (VAT_RATE * 100).normalize(),
        "vat": vat,
        "id": profile.vat_id or "-",
    }


def issue_invoice(order, line, profile, amount, tax_reserve, setaside) -> Invoice:
    """Issued when the payment is confirmed; the customer's name and address are copied in, encrypted."""
    today = timezone.localdate()
    customer = order.outside_customer
    name = crypto.system_decrypt(customer.name_enc).decode()
    address = crypto.system_decrypt(customer.address_enc).decode()
    unit_price = line.price_eur
    total = cur(unit_price * line.quantity)
    invoice = Invoice.objects.create(
        order=order,
        seller=profile.member,
        number=next_number(profile.member, today.year),
        issued_on=today,
        customer_snapshot_enc=crypto.system_encrypt(f"{name}\n{address}".encode()),
        lines=[
            {
                "item": line.offer.item.name,
                "quantity": str(line.quantity.normalize()),
                "unit_price": str(unit_price),
                "total": str(total),
            }
        ],
        total=total,
        currency=line.currency,
        vat_note=vat_note(profile, total),
        paid_at=order.paid_at,
        tax_reserve=tax_reserve,
        setaside=setaside,
        total_eur=fx.to_eur(amount, line.currency),
        keep_until=today.replace(year=today.year + KEEP_YEARS),
    )
    audit.record(profile.member.number, "invoice.issued", invoice, number=invoice.number)
    return invoice


def customer_of(invoice) -> str:
    return crypto.system_decrypt(invoice.customer_snapshot_enc).decode()


def turnover_eur(seller, year) -> Decimal:
    rows = Invoice.objects.filter(seller=seller, paid_at__year=year, refunded_at__isnull=True)
    return sum((i.total_eur for i in rows), Decimal(0))


def check_small_business(seller):
    """At 80% of the limits (25,000 last year, 100,000 this year) tell the seller, once a year."""
    from apps.core.models import AuditEvent

    from .services import active_seller

    profile = active_seller(seller)
    if profile is None or not profile.small_business:
        return None
    year = timezone.localdate().year
    last, this = turnover_eur(seller, year - 1), turnover_eur(seller, year)
    if last < SMALL_LAST_YEAR * WARN_AT and this < SMALL_THIS_YEAR * WARN_AT:
        return None
    if AuditEvent.objects.filter(
        verb="seller.small_business_warning", actor_ref=seller.number, data__year=year
    ).exists():
        return None
    audit.record(seller.number, "seller.small_business_warning", profile, year=year)
    return notify(
        seller,
        _(
            "Your sales are near the small-business limits (25,000 euros last year, 100,000 euros this year). "
            "Above them you must charge VAT. Please ask your tax adviser."
        ),
        "/shop/seller/",
        email=True,
    )


def retention_days():
    return timedelta(days=365 * KEEP_YEARS)
