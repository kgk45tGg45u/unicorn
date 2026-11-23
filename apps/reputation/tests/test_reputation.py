import ast
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import timezone

from apps.reputation import services
from apps.reputation.models import ReputationScore, SuggestionLog
from apps.tickets import routing
from apps.tickets import services as ticket_services
from apps.tickets.models import Conflict, HelpfulMark, Notification
from apps.units import services as unit_services

from .conftest import make_member, make_unit

pytestmark = pytest.mark.django_db


def woodshop():
    unit = make_unit("woodshop", trade_code="wood")
    owner = make_member("owner@x.org", "Owner")
    unit_services.add_first_worker(unit, owner)
    return unit, owner


def question(unit, asker, title="How do I oil oak?"):
    return ticket_services.create_ticket("question", asker, title, scope="unit", scope_unit=unit)


def answered(unit, answerer, asker=None, n=1):
    """An answer with n helpful marks from n different verified members. Returns the comment."""
    asker = asker or make_member(f"asker-{answerer.number}@x.org", "Asker")
    comment = ticket_services.add_comment(question(unit, asker), answerer, "Use hard wax oil.")
    for i in range(n):
        HelpfulMark.objects.create(comment=comment, member=make_member(f"m-{comment.pk}-{i}@x.org", f"M{i}"))
    return comment


def age(mark_qs, days):
    mark_qs.update(created_at=timezone.now() - timedelta(days=days))


def test_the_topic_is_the_ticket_type_and_its_trade():
    unit, owner = woodshop()
    assert services.topic_of(question(unit, owner)) == "question:wood"
    plain = ticket_services.create_ticket("question", owner, "A general question")
    assert services.topic_of(plain) == "question"


def test_decay_halves_a_marks_weight_after_180_days():
    unit, owner = woodshop()
    answerer = make_member("wise@x.org", "Wise")
    comment = answered(unit, answerer)
    assert services.recompute() == 1
    assert ReputationScore.objects.get(member=answerer).score == Decimal("1.0000")
    age(HelpfulMark.objects.filter(comment=comment), 180)
    services.recompute()
    assert ReputationScore.objects.get(member=answerer).score == Decimal("0.5000")
    age(HelpfulMark.objects.filter(comment=comment), 360)
    services.recompute()
    assert ReputationScore.objects.get(member=answerer).score == Decimal("0.2500")


def test_a_mark_older_than_12_months_counts_nothing():
    unit, owner = woodshop()
    answerer = make_member("wise@x.org", "Wise")
    comment = answered(unit, answerer)
    age(HelpfulMark.objects.filter(comment=comment), 400)
    assert services.recompute() == 0
    assert not ReputationScore.objects.exists()
    assert services.helpful_count(answerer) == 0


def test_the_pair_limit_holds_each_month():
    unit, owner = woodshop()
    answerer = make_member("wise@x.org", "Wise")
    fan = make_member("fan@x.org", "Fan")
    asker = make_member("asker@x.org", "Asker")
    for i in range(5):  # five answers marked helpful by the same member in one month
        comment = ticket_services.add_comment(question(unit, asker, f"Question {i}"), answerer, "An answer")
        HelpfulMark.objects.create(comment=comment, member=fan)
    services.recompute()
    score = ReputationScore.objects.get(member=answerer).score
    assert Decimal("2.9") < score <= Decimal("3.0")  # three count, the rest do not


def test_marks_from_unverified_members_never_count():
    unit, owner = woodshop()
    answerer = make_member("wise@x.org", "Wise")
    comment = answered(unit, answerer, n=0)
    HelpfulMark.objects.create(comment=comment, member=make_member("new@x.org", "New", verified=False))
    assert services.recompute() == 0
    assert services.helpful_count(answerer) == 0
    HelpfulMark.objects.create(comment=comment, member=make_member("old@x.org", "Old"))
    assert services.helpful_count(answerer) == 1


def test_three_helpful_marks_suggest_the_member_for_a_new_wood_question():
    unit, owner = woodshop()
    answerer = make_member("wise@x.org", "Wise")
    answered(unit, answerer, n=3)
    services.recompute()
    asker = make_member("new-asker@x.org", "NewAsker")
    ticket = question(unit, asker, "Which finish for a chair?")
    assert routing.suggest_answerers(ticket) == [answerer]
    assert Notification.objects.filter(member=answerer, text__contains="You might know the answer").count() == 1
    assert SuggestionLog.objects.filter(ticket=ticket, member=answerer).exists()
    routing.route(ticket)  # routed again: nobody is told twice
    assert Notification.objects.filter(member=answerer, text__contains="You might know the answer").count() == 1


def test_the_trade_alone_fills_the_list_when_the_topic_has_too_few():
    unit, owner = woodshop()
    on_topic = make_member("topic@x.org", "OnTopic")
    other_type = make_member("other@x.org", "OtherType")
    answered(unit, on_topic, n=2)
    comment = ticket_services.add_comment(
        ticket_services.create_ticket("idea", owner, "An idea", scope="unit", scope_unit=unit), other_type, "A thought"
    )
    HelpfulMark.objects.create(comment=comment, member=make_member("mk@x.org", "Mk"))
    services.recompute()
    ticket = question(unit, make_member("q@x.org", "Q"))
    assert routing.suggest_answerers(ticket) == [on_topic, other_type]


def test_suggestions_exclude_the_author_declared_conflicts_and_those_who_switched_them_off():
    unit, owner = woodshop()
    a, b, c, d = (make_member(f"s{i}@x.org", f"S{i}") for i in range(4))
    for m in (a, b, c, d):
        answered(unit, m, n=2)
    services.recompute()
    services.set_suggestions(c, False)
    ticket = question(unit, a, "My own question")  # the author is never suggested
    assert a not in routing.suggest_answerers(ticket)
    Conflict.objects.create(ticket=ticket, member=b)
    assert routing.suggest_answerers(ticket) == [d]
    assert not Notification.objects.filter(member=c, text__contains="might know").exists()
    services.set_suggestions(c, True)
    assert c in routing.suggest_answerers(ticket)


def test_the_profile_shows_the_plain_count_and_the_member_can_switch_suggestions_off(client):
    unit, owner = woodshop()
    answerer = make_member("wise@x.org", "Wise")
    answered(unit, answerer, n=3)
    services.recompute()
    client.force_login(answerer.user)
    page = client.get("/me/").content.decode()
    assert "Helpful answers in the last 12 months: 3" in page and "question:wood" in page
    client.post("/me/suggest/")
    answerer.refresh_from_db()
    assert answerer.suggest_me is False
    assert "Suggest me for questions" in client.get("/me/").content.decode()


def test_the_daily_job_rebuilds_the_cache():
    from apps.core.jobs import JOBS

    unit, owner = woodshop()
    answered(unit, make_member("wise@x.org", "Wise"), n=1)
    ReputationScore.objects.create(member=owner, topic="stale", score=Decimal(9), computed_at=timezone.now())
    JOBS["reputation.recompute"]({})
    assert not ReputationScore.objects.filter(topic="stale").exists() and ReputationScore.objects.count() == 1


def test_hf15_reputation_only_suggests():
    """No part of Unicorn except the profile page imports the reputation app (HF-15, HF-11, HF-10)."""
    root = Path(__file__).resolve().parents[2]
    allowed = {root / "reputation", root / "members" / "views.py"}
    offenders = []
    for path in root.rglob("*.py"):
        if any(path == a or a in path.parents for a in allowed) or "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *[f"{node.module}.{a.name}" for a in node.names]]
                if node.module == "apps":
                    names += [f"apps.{a.name}" for a in node.names]
            if any(n == "apps.reputation" or n.startswith("apps.reputation.") for n in names):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []
