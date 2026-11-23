"""What unions do: advice, standards, recipe templates, mediation inside a trade, training (docs/05 section 7).

A union advises. Nothing here binds a unit, sets a price or changes who decides a ticket (HF-15, HF-20).
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.notify import notify
from apps.tickets import briefs
from apps.tickets import services as ticket_services

from . import services
from .models import AdviceComment, AdviceRequest, RecipeTemplate, Union, UnionPage

# --- Advice on tickets ---


def trade_of(ticket) -> str:
    """The trade a ticket is about: its unit's trade, or the trade of the offer or item it names."""
    from apps.catalogue.models import Item, Offer

    if ticket.scope_unit_id and ticket.scope_unit.trade_code:
        return ticket.scope_unit.trade_code
    p = ticket.action_payload or {}
    offer_id = p.get("offer_id") or (p.get("target_id") if p.get("target_type") == "offer" else None)
    if offer_id:
        offer = Offer.objects.filter(pk=offer_id).select_related("item", "unit").first()
        if offer is not None:
            return offer.item.trade_code or offer.unit.trade_code
    if p.get("item_id"):
        item = Item.objects.filter(pk=p["item_id"]).first()
        if item is not None:
            return item.trade_code
    return ""


def ask_for_advice(ticket):
    """Called when the secretariat routes a ticket: every active union that covers the trade is asked to advise."""
    code = trade_of(ticket)
    if not code:
        return []
    asked = []
    for union in Union.objects.filter(status="active"):
        if code not in union.trade_codes:
            continue
        request, created = AdviceRequest.objects.get_or_create(
            ticket=ticket, union=union, defaults={"trade_code": code}
        )
        if not created:
            continue
        asked.append(request)
        audit.record("system", "union.advice_asked", union, ticket=ticket.number)
        for delegate in services.current_delegates(union):
            notify(
                delegate.member,
                _("Your union is asked to advise on %(number)s: %(title)s")
                % {"number": ticket.number, "title": ticket.title},
                f"/tickets/{ticket.number}/",
            )
    return asked


def advice_requests_for(member, ticket):
    """The requests on this ticket that `member` may answer as a delegate."""
    if member is None:
        return []
    return [
        r for r in ticket.advice_requests.select_related("union") if services.delegate_for(member, r.union) is not None
    ]


def give_advice(ticket, member, union, body):
    """A delegate answers for the union. The comment is marked as advice, which is never binding."""
    request = AdviceRequest.objects.filter(ticket=ticket, union=union).first()
    if request is None or services.delegate_for(member, union) is None:
        raise services.BodyError(_("Only the delegates of an asked union can write its advice."))
    with transaction.atomic():
        comment = ticket_services.add_comment(ticket, member, body)
        AdviceComment.objects.create(request=request, comment=comment)
        audit.record(member.number, "union.advice_given", union, ticket=ticket.number)
        return comment


def advice_comment_ids(ticket) -> dict:
    """comment id -> union name, for the comments on a ticket that are union advice."""
    rows = AdviceComment.objects.filter(request__ticket=ticket).select_related("request__union")
    return {r.comment_id: r.request.union.name for r in rows}


# --- Pages (standards, training material) ---


def _publish_page(decision):
    p = decision.payload
    slug = slugify(p.get("slug") or p["title"])[:80]
    last = UnionPage.objects.filter(union=decision.union, slug=slug).order_by("-version").first()
    page = UnionPage.objects.create(
        union=decision.union,
        title=p["title"].strip()[:120],
        slug=slug,
        body_md=p["body_md"],
        version=(last.version + 1) if last else 1,
        published_at=timezone.now(),
        decision=decision,
    )
    audit.record("system", "union.page_published", decision.union, page=slug, version=page.version)
    return {"page": slug, "version": page.version}


def latest_pages(union):
    seen, pages = set(), []
    for page in union.pages.order_by("slug", "-version"):
        if page.slug not in seen:
            seen.add(page.slug)
            pages.append(page)
    return pages


# --- Recipe templates ---


def template_problems(payload) -> list[str]:
    from apps.catalogue.models import Item

    problems = []
    if not Item.objects.filter(pk=payload.get("item_id")).exists():
        problems.append(_("Please name the item the template is for."))
    if not (payload.get("title") or "").strip():
        problems.append(_("Please give the template a title."))
    for row in payload.get("inputs", []):
        try:
            ok = Decimal(str(row["quantity"])) > 0 and Item.objects.filter(pk=row["item"]).exists()
        except (KeyError, ArithmeticError, ValueError):
            ok = False
        if not ok or row.get("source", "unicorn") not in ("unicorn", "own_free", "buy_outside"):
            problems.append(_("Every input needs an item, a quantity above zero and a suggested source."))
            break
    for row in payload.get("tools", []):
        try:
            ok = (
                Decimal(str(row["uses"])) > 0
                and Decimal(str(row["lifetime_uses"])) > 0
                and Item.objects.filter(pk=row["item"]).exists()
            )
        except (KeyError, ArithmeticError, ValueError):
            ok = False
        if not ok or row.get("source", "unicorn_owned") not in ("unicorn_owned", "own_free", "to_buy"):
            problems.append(_("Every tool needs an item, the uses per output, its lifetime and a suggested source."))
            break
    return problems


def _publish_template(decision):
    p = decision.payload
    problems = template_problems(p)
    if problems:
        raise services.BodyError(problems[0])
    template = RecipeTemplate.objects.create(
        union=decision.union,
        item_id=p["item_id"],
        title=p["title"].strip()[:120],
        notes_md=p.get("notes_md", ""),
        published_at=timezone.now(),
        decision=decision,
        inputs=p.get("inputs", []),
        tools=p.get("tools", []),
    )
    audit.record("system", "union.template_published", decision.union, template=template.pk)
    return {"template": template.pk}


def apply_template(member, unit, template, **offer_data):
    """Start a new draft offer from a template. The unit edits and publishes it as usual; nothing else changes."""
    from apps.catalogue import services as catalogue
    from apps.catalogue.models import Item

    with transaction.atomic():
        offer = catalogue.create_offer(member, unit, template.item, **offer_data)
        size = offer.batch_size or Decimal(1)
        for row in template.inputs:
            item = Item.objects.get(pk=row["item"])
            catalogue.add_input(
                member,
                offer,
                item.name,
                item.uom_id,
                Decimal(str(row["quantity"])) * size,
                row.get("source", "unicorn"),
            )
        for row in template.tools:
            item = Item.objects.get(pk=row["item"])
            catalogue.add_tool(
                member,
                offer,
                item.name,
                row.get("source", "unicorn_owned"),
                Decimal(str(row["uses"])) * size,
                Decimal(str(row["lifetime_uses"])),
            )
        audit.record(member.number, "union.template_used", template.union, template=template.pk, offer=offer.pk)
        return offer


# --- Training ---


def _create_task_list(decision):
    """A training decision makes a task list of union scope; the hours are paid as coordination hours when confirmed."""
    p = decision.payload
    tasks = p.get("tasks") or []
    text = p.get("brief") or decision.text or decision.title
    check = briefs._check(
        _("Which union asked for this training?"),
        decision.union.name,
        [_("The planning group"), _("One single unit")],
        _("the first sentence"),
    )
    ticket = ticket_services.create_ticket(
        "task_list",
        decision.opened_by,
        decision.title,
        text,
        scope="union",
        scope_union=decision.union,
        brief=_("%(union)s decided on this training: %(text)s") % {"union": decision.union.name, "text": text},
        check=check,
        action_payload={"tasks": tasks, "union_decision": decision.pk},
    )
    return {"ticket": ticket.number}


# --- Mediation inside a trade ---


def mediator_pool(ticket):
    """For a mediation between units of one union: the members of the union's other units (never the parties')."""
    from apps.units.models import Unit, UnitMembership

    unit_ids = set((ticket.action_payload or {}).get("units", []))
    if len(unit_ids) < 2:
        return None
    for union in Union.objects.filter(status="active"):
        member_ids = set(services.member_units(union).values_list("pk", flat=True))
        if not unit_ids <= member_ids:
            continue
        others = Unit.objects.filter(pk__in=member_ids - unit_ids)
        pks = set(
            UnitMembership.objects.filter(unit__in=others, left_at__isnull=True).values_list("member_id", flat=True)
        )
        parties = set(
            UnitMembership.objects.filter(unit_id__in=unit_ids, left_at__isnull=True).values_list(
                "member_id", flat=True
            )
        )
        return f"union:{union.slug}", pks - parties
    return None


def register():
    from apps.tickets import mediation

    if mediator_pool not in mediation.PREFERRED_POOLS:
        mediation.PREFERRED_POOLS.append(mediator_pool)
    services.register_action("publish_page", _publish_page)
    services.register_action("publish_template", _publish_template)
    services.register_action("create_task_list", _create_task_list)
