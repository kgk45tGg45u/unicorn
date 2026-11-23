"""Reputation (docs/05 section 10, P13.T08): helpful marks on answers, used only to suggest who might answer.

HF-15, HF-11: nothing here touches work, pay, votes, prices, draws or trust. Those apps never import this one
(`test_hf15_reputation_only_suggests`).
"""

from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.notify import notify
from apps.members.models import Member
from apps.members.services import _add_months
from apps.rules.services import get_param
from apps.tickets.models import Conflict, HelpfulMark

from .models import ReputationScore, SuggestionLog


def topic_of(ticket) -> str:
    """The type of the ticket plus its trade, for example `question:wood`."""
    from apps.bodies.duties import trade_of

    trade = trade_of(ticket)
    return f"{ticket.type}:{trade}" if trade else ticket.type


def _valid_marks(now):
    """Marks inside the window, from verified members, with at most N from one marker to one author a month."""
    cutoff = _add_months(now, -get_param("reputation.window_months"))
    limit = get_param("reputation.max_marks_per_pair_per_month")
    rows = (
        HelpfulMark.objects.filter(created_at__gte=cutoff, member__status=Member.MEMBER, member__deleted=False)
        .select_related("comment__ticket", "comment__author")
        .order_by("created_at", "id")
    )
    seen = defaultdict(int)
    for mark in rows:
        key = (mark.member_id, mark.comment.author_id, mark.created_at.year, mark.created_at.month)
        seen[key] += 1
        if seen[key] <= limit:
            yield mark


def weight(mark, now) -> Decimal:
    """A mark counts 1 when new and half as much after `half_life_days`."""
    age_days = max((now - mark.created_at).total_seconds() / 86400, 0)
    return Decimal(str(round(0.5 ** (age_days / get_param("reputation.half_life_days")), 6)))


def scores(now=None) -> dict:
    """{(member id, topic): score}, computed from the marks."""
    now = now or timezone.now()
    totals = defaultdict(Decimal)
    for mark in _valid_marks(now):
        totals[(mark.comment.author_id, topic_of(mark.comment.ticket))] += weight(mark, now)
    return totals


def recompute(now=None) -> int:
    """Rebuild the cache table. It holds nothing that cannot be rebuilt."""
    now = now or timezone.now()
    totals = scores(now)
    with transaction.atomic():
        ReputationScore.objects.all().delete()
        ReputationScore.objects.bulk_create(
            [
                ReputationScore(
                    member_id=member_id, topic=topic, score=score.quantize(Decimal("0.0001")), computed_at=now
                )
                for (member_id, topic), score in totals.items()
            ]
        )
    return len(totals)


# --- Suggestions ---


def _candidates(ticket):
    return (
        Member.objects.filter(status=Member.MEMBER, deleted=False, suggest_me=True)
        .exclude(pk__in=[ticket.author_id] if ticket.author_id else [])
        .exclude(pk__in=Conflict.objects.filter(ticket=ticket).values("member_id"))
    )


def suggest_answerers(ticket) -> list:
    """The top `suggest_count` members for the ticket's topic, then for its trade alone."""
    limit = get_param("reputation.suggest_count")
    if limit <= 0:
        return []
    allowed = set(_candidates(ticket).values_list("pk", flat=True))
    topic = topic_of(ticket)
    chosen = []

    def take(rows):
        for row in rows:
            if row.member_id in allowed and row.member_id not in {m.pk for m in chosen} and row.score > 0:
                chosen.append(row.member)
                if len(chosen) >= limit:
                    return

    take(ReputationScore.objects.filter(topic=topic).select_related("member").order_by("-score", "member__number"))
    if len(chosen) < limit and ":" in topic:
        trade = topic.split(":", 1)[1]
        take(
            ReputationScore.objects.filter(topic__endswith=f":{trade}")
            .exclude(topic=topic)
            .select_related("member")
            .order_by("-score", "member__number")
        )
    return chosen


def suggest_for_ticket(ticket) -> list:
    return suggest_answerers(ticket) if ticket.type == "question" else []


def notify_suggested(ticket):
    """When a question is routed, the suggested members get one notification. Nothing else happens."""
    for member in suggest_for_ticket(ticket):
        _row, created = SuggestionLog.objects.get_or_create(ticket=ticket, member=member)
        if created:
            notify(
                member,
                _("You might know the answer to %(number)s: %(title)s")
                % {"number": ticket.number, "title": ticket.title},
                f"/tickets/{ticket.number}/",
            )


# --- What a member sees about themselves ---


def helpful_count(member, now=None) -> int:
    """The plain count of helpful marks on the member's answers in the window. Not the weighted score."""
    now = now or timezone.now()
    cutoff = _add_months(now, -get_param("reputation.window_months"))
    return HelpfulMark.objects.filter(
        comment__author=member, created_at__gte=cutoff, member__status=Member.MEMBER, member__deleted=False
    ).count()


def my_topics(member):
    return list(ReputationScore.objects.filter(member=member).order_by("-score"))


def set_suggestions(member, on: bool):
    member.suggest_me = bool(on)
    member.save(update_fields=["suggest_me"])
    return member


# --- Recognition instead of extra pay (P13.T09) ---

MAX_TEXT = 280


def _record(kind, unit, item=None, review=None, text="", from_member=None):
    """One row for the unit and one for each of its workers at this moment. Nothing is paid (HF-2)."""
    from apps.units import services as unit_services

    from .models import Recognition

    rows = [
        Recognition.objects.create(
            unit=unit, kind=kind, item=item, review=review, text=text[:MAX_TEXT], from_member=from_member
        )
    ]
    for worker in unit_services.workers(unit):
        rows.append(
            Recognition.objects.create(
                member=worker.member,
                unit=unit,
                kind=kind,
                item=item,
                review=review,
                text=text[:MAX_TEXT],
                from_member=from_member,
            )
        )
    return rows


def on_recognition(member, kind, obj):
    """Called through `apps.core.hooks.RECOGNITION_HOOK`. Other apps never import this module."""
    from apps.catalogue.models import Offer
    from apps.units import services as unit_services

    from .models import Recognition

    if kind == "first_maker":  # obj is the offer that was just published
        if Recognition.objects.filter(kind="first_maker", item=obj.item, member__isnull=True).exists():
            return []
        return _record("first_maker", obj.unit, item=obj.item)
    if kind == "filled_need":  # obj is the item; the maker's own offer of it says which unit
        offers = Offer.objects.filter(item=obj, status="active").select_related("unit").order_by("-id")
        offer = next((o for o in offers if unit_services.is_worker(member, o.unit)), None)
        return _record("filled_need", offer.unit, item=obj) if offer is not None else []
    if kind == "thanks":  # obj is the review
        if Recognition.objects.filter(kind="thanks", review=obj, member__isnull=True).exists():
            return []
        return _record("thanks", obj.offer.unit, item=obj.offer.item, review=obj, text=obj.text, from_member=obj.author)
    return []


def unit_recognitions(unit, limit=30):
    """What the unit page shows: the unit's own rows, without thanks that members reported and hid."""
    from apps.tickets import flags

    from .models import Recognition

    hidden = flags.hidden_ids("thanks")
    rows = Recognition.objects.filter(unit=unit, member__isnull=True).select_related("item", "from_member")
    return [r for r in rows[:limit] if r.pk not in hidden]


def member_recognitions(member):
    """What the portfolio shows: the member's rows. The member may hide any of them."""
    from .models import Recognition

    return list(Recognition.objects.filter(member=member).select_related("item", "unit", "from_member"))


def set_hidden(member, recognition, hidden: bool):
    if recognition.member_id != member.pk:
        raise ValueError(_("This recognition is not yours."))
    recognition.hidden_by_owner = bool(hidden)
    recognition.save(update_fields=["hidden_by_owner"])
    return recognition


def label(recognition) -> str:
    item = recognition.item.name if recognition.item_id else ""
    if recognition.kind == "first_maker":
        return _("First maker of %(item)s") % {"item": item}
    if recognition.kind == "filled_need":
        return _("Filled a need: %(item)s") % {"item": item}
    return _("Thanks for %(item)s") % {"item": item}
