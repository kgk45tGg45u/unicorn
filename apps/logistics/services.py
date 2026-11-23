"""Delivery: pickup points, Unicorn couriers, capitalist carriers and what happens when a delivery fails.

The app proposes how an order travels; the selling unit's responsible confirms or changes it (HF-15).
A carrier costs the buyer no UNIQ: the trade fund pays its euros like bought materials (HF-3).
"""

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.ledger import services as ledger
from apps.members import services as member_services
from apps.units import services as unit_services

from . import geo, quotes
from .models import Carrier, CourierOffer, PickupPoint, Shipment

D = Decimal
EU = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT",
    "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}  # fmt: skip


class LogisticsError(ValueError):
    """A plain-words reason why something cannot be done."""


# --- Pickup points (P12.T03) ---


def create_point(member, name, address, postcode, country="DE", notes="", unit=None, manager=None) -> PickupPoint:
    if not member_services.is_verified(member):  # HF-13
        raise LogisticsError(_("Only verified members can add a pickup point."))
    if not (name or "").strip() or not (address or "").strip() or not geo.clean(postcode):
        raise LogisticsError(_("Please give the name, the public address and the postcode."))
    return PickupPoint.objects.create(
        name=name.strip()[:120],
        address_public=address.strip()[:200],
        postcode=geo.clean(postcode),
        country=country.upper(),
        opening_notes=notes[:300],
        managed_by_unit=unit,
        manager=manager or member,
    )


def points_for(unit):
    """The active pickup points the unit serves and that lie inside its cover area."""
    return [p for p in unit.pickup_points.filter(active=True) if geo.covers(unit, p.country, p.postcode)]


def serve_point(unit, point, member):
    if not unit_services.is_worker(member, unit):
        raise LogisticsError(_("Only a worker of the unit can choose which pickup points it serves."))
    if not geo.covers(unit, point.country, point.postcode):
        raise LogisticsError(_("This pickup point is outside the unit's cover area."))
    unit.pickup_points.add(point)
    return point


# --- Proposing how an order travels (P12.T04, T05, T07) ---


@dataclass
class Proposal:
    mode: str
    uniq: Decimal = D(0)
    eur: Decimal = D(0)
    courier_offer: CourierOffer | None = None
    carrier: Carrier | None = None
    notice: str = ""


def abroad_notice(from_country, to_country) -> str:
    """Outside the EU the seller must know about customs (`# OWNER-CHECK`)."""
    if (to_country or "").upper() and to_country.upper() not in EU:
        return str(
            _("Customs declaration needed; VAT and duties may apply in the destination country (ask a tax adviser).")
        )
    return ""


def _planning_rate() -> Decimal:
    from apps.macro import services as macro

    rate = macro.planning_rate()
    return D(str(rate)) if rate else D(1)


def _courier_options(unit, country, postcode):
    """Couriers that cover both ends, in the same country as the seller, never across a border (P12.T07)."""
    if (unit.country or "DE").upper() != country.upper():
        return []
    leg = geo.distance_km(unit, country, postcode)
    dest = geo.point_of(country, postcode)
    if leg is None or dest is None:
        return []
    found = []
    for co in CourierOffer.objects.filter(
        offer__status="active", offer__unit__kind="courier", offer__unit__status__in=("trial", "open")
    ).select_related("offer__unit", "offer__item"):
        cu = co.offer.unit
        if leg > float(co.max_km) or not (geo.covers(cu, country, postcode) and geo.covers(cu, country, unit.postcode)):
            continue
        labour, eur = quotes.courier_quote(co, SimpleNamespace(lat=unit.lat, lng=unit.lng), dest, distance_km=leg)
        found.append(Proposal("unicorn_courier", labour, eur, courier_offer=co))
    return found


def carriers_for(country):
    """Only carriers that list the destination country (P12.T07)."""
    return [c for c in Carrier.objects.filter(active=True) if country.upper() in {x.upper() for x in c.countries}]


def propose(unit, country, postcode, member_buyer=True) -> Proposal:
    """The make-or-buy rule: a courier when `courier_uniq + courier_eur / r < carrier_eur / r`, else a carrier."""
    country = (country or "DE").upper()
    rate = _planning_rate()
    couriers = _courier_options(unit, country, postcode) if member_buyer else []
    best_courier = min(couriers, key=lambda p: p.uniq + p.eur / rate, default=None)
    quoted = [(c, quotes.carrier_quote(c)) for c in carriers_for(country)]
    quoted = [(c, e) for c, e in quoted if e is not None]
    carrier, carrier_eur = min(quoted, key=lambda x: x[1], default=(None, None))
    notice = abroad_notice(unit.country or "DE", country)
    if best_courier and (carrier is None or best_courier.uniq + best_courier.eur / rate < carrier_eur / rate):
        best_courier.notice = notice
        return best_courier
    if carrier is not None:
        return Proposal("capitalist_carrier", D(0), carrier_eur, carrier=carrier, notice=notice)
    raise LogisticsError(_("We cannot bring this to that address yet. You can pick it up instead."))


# --- Arranging a delivery for a new order line ---


def _sender(unit):
    w = unit_services.workers(unit).filter(is_council=True).first() or unit_services.workers(unit).first()
    return w.member if w else None


def arrange(line, buyer, delivery) -> Shipment:
    """Called by `place_order`. `delivery` = {"mode": "pickup" | "deliver", "postcode", "country", "point"}."""
    unit = line.offer.unit
    mode = delivery.get("mode", "pickup")
    base = dict(
        order=line.order,
        line=line,
        to_postcode=geo.clean(delivery.get("postcode")),
        to_country=(delivery.get("country") or "DE").upper(),
    )
    if mode == "pickup":
        point = delivery.get("point")
        if point is not None:
            if point not in points_for(unit):
                raise LogisticsError(_("This pickup point is not served by the unit."))
            return Shipment.objects.create(
                **base,
                mode="pickup_point",
                proposed_mode="pickup_point",
                pickup_point=point,
                confirmed_by_responsible=True,
            )
        return Shipment.objects.create(**base, mode="pickup", proposed_mode="pickup", confirmed_by_responsible=True)
    if mode != "deliver":
        raise LogisticsError(_("Please choose pickup or delivery."))
    if not base["to_postcode"]:
        raise LogisticsError(_("Please give the postcode to deliver to."))
    proposal = propose(unit, base["to_country"], base["to_postcode"], member_buyer=buyer is not None)
    shipment = Shipment.objects.create(**base, mode=proposal.mode, proposed_mode=proposal.mode)
    _setup(shipment, proposal, buyer)
    return shipment


def _setup(shipment, proposal, buyer):
    """The side effects of the proposed mode: a courier line with its hold, or a purchase request for the carrier."""
    from apps.market.models import OrderLine
    from apps.tradefund import purchases

    line, unit = shipment.line, shipment.line.offer.unit
    if proposal.mode == "unicorn_courier":
        co = proposal.courier_offer
        courier_line = OrderLine.objects.create(
            order=shipment.order,
            offer=co.offer,
            quantity=1,
            price_uniq=proposal.uniq,
            total_uniq=proposal.uniq,
            due_date=line.due_date,
            status=OrderLine.READY,
        )
        try:
            courier_line.hold = ledger.place_hold(
                buyer,
                proposal.uniq,
                _("Delivery of %(item)s by %(unit)s") % {"item": line.offer.item.name, "unit": co.offer.unit.name},
                ref=courier_line,
            )
        except ledger.LedgerError:
            raise LogisticsError(_("Not enough UNIQ available for the delivery")) from None
        courier_line.save(update_fields=["hold"])
        shipment.courier_line, shipment.uniq_cost, shipment.eur_cost = courier_line, proposal.uniq, proposal.eur
    elif proposal.mode == "capitalist_carrier":
        sender = _sender(unit)
        if sender is None:
            raise LogisticsError(_("The unit has nobody who can send it."))
        shipment.carrier, shipment.eur_cost, shipment.uniq_cost = proposal.carrier, proposal.eur, D(0)
        shipment.purchase_request = purchases.create_purchase(
            sender,
            _("Shipping of %(item)s by %(carrier)s") % {"item": line.offer.item.name, "carrier": proposal.carrier.name},
            proposal.eur,
            unit=unit,
            why=_("Carrier for order %(n)s") % {"n": shipment.order_id},
            source="operations",
        )
    shipment.save()
    audit.record(
        "system", "shipment.proposed", shipment, mode=proposal.mode, eur=str(proposal.eur), uniq=str(proposal.uniq)
    )


def _teardown(shipment):
    """Undo the side effects of a mode that the responsible changes."""
    from apps.market.models import OrderLine

    if shipment.courier_line_id:
        cl = shipment.courier_line
        if cl.hold_id and cl.hold.status == "active":
            ledger.release_hold(cl.hold, _("The way of delivery was changed"))
        cl.status = OrderLine.CANCELLED
        cl.save(update_fields=["status"])
        shipment.courier_line = None
    if shipment.purchase_request_id:
        pr = shipment.purchase_request
        if pr.status in ("checking", "approved", "waiting_for_euros"):
            pr.status = "rejected"
            pr.save(update_fields=["status"])
        shipment.purchase_request = None
    shipment.carrier = None
    shipment.uniq_cost = shipment.eur_cost = D(0)


def confirm_mode(shipment, worker, mode=None):
    """The selling unit's responsible confirms the proposed mode, or changes it (HF-15)."""
    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        unit = shipment.line.offer.unit
        if not unit_services.is_worker(worker, unit):
            raise LogisticsError(_("Only a worker of the selling unit can confirm how it is sent."))
        if shipment.status != "planned":
            raise LogisticsError(_("This shipment has already left."))
        if mode and mode != shipment.mode:
            if shipment.mode in ("pickup", "pickup_point") or mode in ("pickup", "pickup_point"):
                raise LogisticsError(_("The buyer chooses between pickup and delivery."))
            proposals = {p.mode: p for p in _all_proposals(unit, shipment)}
            if mode not in proposals:
                raise LogisticsError(_("That way of delivery is not possible for this address."))
            _teardown(shipment)
            shipment.mode = mode
            _setup(shipment, proposals[mode], shipment.order.buyer)
        shipment.confirmed_by_responsible = True
        shipment.save(update_fields=["confirmed_by_responsible"])
        audit.record(worker.number, "shipment.confirmed", shipment, mode=shipment.mode)
        return shipment


def _all_proposals(unit, shipment):
    rate = _planning_rate()
    out = list(_courier_options(unit, shipment.to_country, shipment.to_postcode)) if shipment.order.buyer_id else []
    out.sort(key=lambda p: p.uniq + p.eur / rate)
    quoted = [(c, quotes.carrier_quote(c)) for c in carriers_for(shipment.to_country)]
    quoted = [(c, e) for c, e in quoted if e is not None]
    if quoted:
        c, e = min(quoted, key=lambda x: x[1])
        out.append(Proposal("capitalist_carrier", D(0), e, carrier=c))
    return out


# --- Sending and delivering (P12.T06) ---


def _need_ready(shipment):
    from apps.market.models import OrderLine

    if shipment.line.status not in (OrderLine.READY, OrderLine.FROM_STOCK):
        raise LogisticsError(_("The order is not ready to be sent yet."))


def hand_to_point(shipment, worker):
    """The unit brings the order to the pickup point; the point's manager confirms it next."""
    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if shipment.mode != "pickup_point":
            raise LogisticsError(_("This order is not going to a pickup point."))
        if not unit_services.is_worker(worker, shipment.line.offer.unit):
            raise LogisticsError(_("Only a worker of the selling unit can hand the order over."))
        _need_ready(shipment)
        shipment.status = "sent"
        shipment.save(update_fields=["status"])
        audit.record(worker.number, "shipment.at_point", shipment)
        return shipment


def point_confirm(shipment, manager):
    """The point's manager says the order is there; the buyer confirms the pickup (as for any hand-over)."""
    from apps.market import services as market

    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        point = shipment.pickup_point
        if point is None or point.manager_id != manager.pk:
            raise LogisticsError(_("Only the manager of the pickup point can confirm this."))
        if shipment.status != "sent":
            raise LogisticsError(_("The unit has not brought the order yet."))
        shipment.status, shipment.delivered_at = "delivered", timezone.now()
        shipment.save(update_fields=["status", "delivered_at"])
        market.mark_arrived(market._lock_line(shipment.line), manager.number)
        return shipment


def mark_sent(shipment, worker, tracking=""):
    """The unit hands the order to the courier or the carrier."""
    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if not unit_services.is_worker(worker, shipment.line.offer.unit):
            raise LogisticsError(_("Only a worker of the selling unit can send the order."))
        if shipment.mode not in ("unicorn_courier", "capitalist_carrier"):
            raise LogisticsError(_("This order is picked up, not sent."))
        if not shipment.confirmed_by_responsible:
            raise LogisticsError(_("Please confirm how the order is sent first."))
        if shipment.status != "planned":
            raise LogisticsError(_("This order has already left."))
        _need_ready(shipment)
        if shipment.mode == "capitalist_carrier" and not (tracking or "").strip():
            raise LogisticsError(_("Please enter the carrier's tracking number."))
        shipment.status, shipment.tracking = "sent", (tracking or "").strip()[:80]
        shipment.save(update_fields=["status", "tracking"])
        audit.record(worker.number, "shipment.sent", shipment, mode=shipment.mode)
        return shipment


def courier_delivered(shipment, courier):
    """The courier marks the delivery done and records its time; the buyer then confirms, and the courier is paid."""
    from apps.market import services as market

    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if shipment.mode != "unicorn_courier" or shipment.courier_line_id is None:
            raise LogisticsError(_("This order is not delivered by a courier."))
        if not unit_services.is_worker(courier, shipment.courier_line.offer.unit):
            raise LogisticsError(_("Only a worker of the courier unit can mark this as delivered."))
        if shipment.status != "sent":
            raise LogisticsError(_("The order has not been sent yet."))
        co = shipment.courier_line.offer.courier_offer
        km = geo.distance_km(shipment.line.offer.unit, shipment.to_country, shipment.to_postcode) or 0
        shipment.status, shipment.delivered_at = "delivered", timezone.now()
        shipment.courier_member = courier
        shipment.courier_minutes = max(1, round(quotes.courier_minutes(co, km)))
        shipment.save()
        market.mark_arrived(market._lock_line(shipment.line), courier.number)
        market.mark_arrived(market._lock_line(shipment.courier_line), courier.number, auto_confirm=False)
        audit.record(courier.number, "shipment.delivered", shipment)
        return shipment


def carrier_delivered(shipment, buyer):
    """With a carrier the buyer confirms that the parcel arrived; the order's lines are confirmed with it."""
    from apps.market import services as market

    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if shipment.mode != "capitalist_carrier" or shipment.order.buyer_id != buyer.pk:
            raise LogisticsError(_("This is not your parcel."))
        if shipment.status != "sent":
            raise LogisticsError(_("The parcel has not been sent yet."))
        shipment.confirmed_by = buyer
        shipment.save(update_fields=["confirmed_by"])
        market.confirm_received(shipment.line, buyer)  # settles the shipment through the delivered hook
        shipment.refresh_from_db()
        return shipment


def on_line_delivered(line):
    """A delivered product line settles its shipment; a delivered courier line pays the courier."""
    from apps.market import services as market
    from apps.market.models import OrderLine

    shipment = getattr(line, "shipment", None) if hasattr(line, "shipment") else None
    if shipment is not None:
        shipment = Shipment.objects.get(pk=shipment.pk)
        shipment.status, shipment.delivered_at = "delivered", shipment.delivered_at or timezone.now()
        shipment.save(update_fields=["status", "delivered_at"])
        cl = shipment.courier_line
        if cl is not None and cl.status == OrderLine.HANDED_OVER:
            market._deliver(market._lock_line(cl), "system")
    shipment_as_courier = Shipment.objects.filter(courier_line=line).first()
    if shipment_as_courier is not None and shipment_as_courier.courier_member_id:
        unit_services.record_hours(
            shipment_as_courier.courier_member,
            line.offer.unit,
            timezone.localdate(),
            shipment_as_courier.courier_minutes,
            activity="other",
            note=_("Delivery of order %(n)s") % {"n": shipment_as_courier.order_id},
            ref_type="orderline",
            ref_id=line.pk,
        )


def report_problem(shipment, buyer, reason, text=""):
    """'Damaged' or 'missing': a flag ticket opens and the held UNIQ stay held (P06.T08)."""
    from apps.market import services as market

    if reason not in ("damaged", "missing"):
        raise LogisticsError(_("Please say whether it is damaged or missing."))
    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if shipment.order.buyer_id != buyer.pk:
            raise LogisticsError(_("This is not your order."))
        market.dispute(shipment.line, buyer, "not_received" if reason == "missing" else "damaged", text)
        if shipment.courier_line_id:
            cl = shipment.courier_line
            cl.disputed_at = timezone.now()
            cl.save(update_fields=["disputed_at"])
        shipment.status, shipment.problem = "failed", f"{reason}: {text}".strip()[:300]
        shipment.save(update_fields=["status", "problem"])
        return shipment


def resolve(shipment, worker, how, reason):
    """After a failed delivery the selling unit's responsible chooses: replace it, or refund the buyer."""
    from apps.market import services as market
    from apps.market.models import OrderLine

    if how not in ("replace", "refund"):
        raise LogisticsError(_("Please choose to replace the order or to refund it."))
    if len((reason or "").strip()) < 3:
        raise LogisticsError(_("Please write a reason."))
    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        line = market._lock_line(shipment.line)
        if not unit_services.is_worker(worker, line.offer.unit):
            raise LogisticsError(_("Only a worker of the selling unit can decide this."))
        if shipment.status != "failed" or line.status == OrderLine.CANCELLED:
            raise LogisticsError(_("There is nothing to settle for this shipment."))
        if how == "replace":  # the hold stays; a damaged product is made again, a missing one is sent again
            if shipment.problem.startswith("damaged"):
                line.status = OrderLine.PLACED
                line.save(update_fields=["status"])
                market.assign_to_batch(line)
            else:
                line.status = OrderLine.READY
                line.save(update_fields=["status"])
            line.disputed_at, line.dispute_text, line.handed_over_at = None, "", None
            line.save(update_fields=["disputed_at", "dispute_text", "handed_over_at"])
            if shipment.courier_line_id:
                cl = shipment.courier_line
                cl.status, cl.disputed_at, cl.handed_over_at = OrderLine.READY, None, None
                cl.save(update_fields=["status", "disputed_at", "handed_over_at"])
            shipment.status, shipment.problem = "planned", ""
            shipment.save(update_fields=["status", "problem"])
        else:
            for ln in [line, shipment.courier_line]:
                if ln is not None:
                    _refund_line(ln, reason)
            shipment.save(update_fields=["status"])
        audit.record(worker.number, f"shipment.{how}", shipment, reason=reason.strip())
        return shipment


def _refund_line(line, reason):
    """Release the hold; if the line was already paid, post a correction with a reason (P02.T03)."""
    from apps.ledger.models import Transaction

    if line.hold_id and line.hold.status == "active":
        ledger.release_hold(line.hold, _("Refunded: %(why)s") % {"why": reason.strip()})
    elif line.hold_id:
        tx = Transaction.objects.filter(kind="purchase", ref_type="orderline", ref_id=str(line.pk)).first()
        if tx is not None:
            ledger.post(
                "correction",
                _("Refunded: %(why)s") % {"why": reason.strip()},
                [ledger.Leg(e.account, -e.amount) for e in tx.entries.all()],
                ref=tx,
            )
    line.status = "cancelled"
    line.save(update_fields=["status"])
