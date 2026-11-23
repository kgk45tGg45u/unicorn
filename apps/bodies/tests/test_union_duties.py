from decimal import Decimal

import pytest
from django.db.models import Q

from apps.bodies import duties, services
from apps.bodies.models import AdviceRequest, RecipeTemplate, UnionPage
from apps.catalogue import services as catalogue
from apps.catalogue.models import Offer, OfferInput
from apps.tasks.models import Task
from apps.tickets import mediation
from apps.tickets import services as ticket_services
from apps.tickets.models import Notification, Ticket
from apps.units import services as unit_services

from .conftest import active_union, make_member, make_unit, one_person_unit

pytestmark = pytest.mark.django_db


def approve(union, decision, people, solo_member):
    services.vote(decision, people[0], "yes")
    services.vote(decision, solo_member, "yes")
    decision.refresh_from_db()
    assert decision.status == "approved"
    return decision


def test_a_ticket_about_a_chair_offer_notifies_the_unions_delegates_and_its_method_is_unchanged():
    union, crew, people, solo, solo_member = active_union()
    chair = catalogue.create_item("Oak chair", "product", "pc", unit=crew, trade_code="wood")
    offer = Offer.objects.create(unit=crew, item=chair, status="draft")
    asker = make_member("asker@x.org", "Asker")
    ticket = ticket_services.create_ticket(
        "question", asker, "Is this chair safe for children?", action_payload={"offer_id": offer.pk}
    )
    assert AdviceRequest.objects.filter(ticket=ticket, union=union).exists()
    for who in (people[0], solo_member):
        assert Notification.objects.filter(member=who, text__contains="asked to advise").exists()
    assert not Notification.objects.filter(member=people[1], text__contains="asked to advise").exists()
    ticket.refresh_from_db()
    assert ticket.decision_method == "none" and ticket.status == "open"  # the method is the type's own (HF-15)
    comment = duties.give_advice(ticket, people[0], union, "Use rounded corners and a non-toxic finish.")
    assert duties.advice_comment_ids(ticket) == {comment.pk: union.name}
    ticket.refresh_from_db()
    assert ticket.decision_method == "none"
    with pytest.raises(services.BodyError, match="Only the delegates"):
        duties.give_advice(ticket, people[1], union, "I am only a council member")


def test_a_ticket_of_another_trade_does_not_ask_the_union():
    union, crew, people, solo, solo_member = active_union()
    bakery = make_unit("bakery-x", trade_code="bread")
    baker = make_member("baker@x.org", "Baker")
    unit_services.add_first_worker(bakery, baker)
    ticket_services.create_ticket("question", baker, "Flour?", scope="unit", scope_unit=bakery)
    assert not AdviceRequest.objects.exists()


def test_the_ticket_page_shows_advice_first_and_marked_not_binding(client):
    union, crew, people, solo, solo_member = active_union()
    ticket = ticket_services.create_ticket(
        "question", make_member("q@x.org", "Q"), "A wood question", scope="unit", scope_unit=crew
    )
    ticket_services.add_comment(ticket, make_member("c@x.org", "Commenter"), "An ordinary comment")
    duties.give_advice(ticket, people[0], union, "The union's answer")
    client.force_login(people[1].user)
    page = client.get(f"/tickets/{ticket.number}/").content.decode()
    assert "(not binding)" in page
    assert page.index("The union&#x27;s answer") < page.index("An ordinary comment") or page.index(
        "The union's answer"
    ) < page.index("An ordinary comment")


def test_a_standard_needs_a_union_decision_and_a_change_makes_a_new_version():
    union, crew, people, solo, solo_member = active_union()
    payload = {"title": "Oak drying", "body_md": "Dry oak for twelve months."}
    approve(
        union,
        services.open_decision(people[0], union, "Oak drying", kind="standard", payload=payload),
        people,
        solo_member,
    )
    payload2 = {"title": "Oak drying", "body_md": "Dry oak for twenty-four months."}
    approve(
        union,
        services.open_decision(people[0], union, "Oak drying 2", kind="standard", payload=payload2),
        people,
        solo_member,
    )
    pages = UnionPage.objects.filter(union=union, slug="oak-drying").order_by("version")
    assert [p.version for p in pages] == [1, 2]
    assert [p.slug for p in duties.latest_pages(union)] == ["oak-drying"]
    assert duties.latest_pages(union)[0].body_md.endswith("twenty-four months.")
    with pytest.raises(services.BodyError, match="title and a text"):
        services.open_decision(people[0], union, "Empty", kind="standard", payload={})


def _template(union, people, solo_member, chair, board, saw):
    payload = {
        "item_id": chair.pk,
        "title": "A simple chair",
        "notes_md": "Four legs.",
        "inputs": [{"item": board.pk, "quantity": "0.5", "source": "unicorn"}],
        "tools": [{"item": saw.pk, "source": "unicorn_owned", "uses": "0.25", "lifetime_uses": 4000}],
    }
    decision = services.open_decision(people[0], union, "A chair template", kind="recipe_template", payload=payload)
    approve(union, decision, people, solo_member)
    return RecipeTemplate.objects.get(union=union)


def test_a_template_creates_a_draft_offer_and_changes_nothing_else():
    union, crew, people, solo, solo_member = active_union()
    chair = catalogue.create_item("Oak chair", "product", "pc", trade_code="wood")
    board = catalogue.create_item("Oak board", "product", "pc", trade_code="wood")
    saw = catalogue.create_item("Saw", "product", "pc", trade_code="wood")
    template = _template(union, people, solo_member, chair, board, saw)
    before = (Offer.objects.count(), template.inputs, template.tools, chair.status)
    offer = duties.apply_template(
        people[0], crew, template, batch_size=Decimal(4), direct_minutes_per_batch=240, cycle_days=3
    )
    assert offer.status == "draft" and offer.item == chair and offer.unit == crew
    assert offer.value_total == 0  # a template never sets a price
    row = OfferInput.objects.get(offer=offer)
    assert row.item == board and row.quantity_per_batch == Decimal("2.0000") and row.source == "unicorn"
    assert offer.tools.get().uses_per_batch == Decimal("1.0000")
    assert Offer.objects.count() == before[0] + 1
    template.refresh_from_db()
    assert (template.inputs, template.tools) == (before[1], before[2])
    with pytest.raises(catalogue.CatalogueError, match="responsible or council"):
        duties.apply_template(make_member("z@x.org", "Z"), crew, template, batch_size=1, direct_minutes_per_batch=60)


def test_the_offer_form_offers_a_union_template(client):
    union, crew, people, solo, solo_member = active_union()
    chair = catalogue.create_item("Oak chair", "product", "pc", trade_code="wood")
    board = catalogue.create_item("Oak board", "product", "pc", trade_code="wood")
    saw = catalogue.create_item("Saw", "product", "pc", trade_code="wood")
    template = _template(union, people, solo_member, chair, board, saw)
    client.force_login(people[0].user)
    page = client.get(f"/units/{crew.slug}/offers/new/?item={chair.pk}").content.decode()
    assert "Start from a union template" in page and "A simple chair" in page
    response = client.post(
        f"/units/{crew.slug}/offers/new/",
        {
            "item": chair.pk,
            "template": template.pk,
            "batch_size": "4",
            "direct_minutes_per_batch": "240",
            "cycle_days": "3",
            "setup_minutes": "0",
        },
    )
    assert response.status_code == 302, response.content.decode()[-1500:]
    offer = Offer.objects.get(unit=crew, item=chair)
    assert offer.inputs.count() == 1 and offer.tools.count() == 1


def test_a_template_with_bad_numbers_is_refused_when_opened():
    union, crew, people, solo, solo_member = active_union()
    chair = catalogue.create_item("Oak chair", "product", "pc")
    with pytest.raises(services.BodyError, match="input"):
        services.open_decision(
            people[0],
            union,
            "Bad",
            kind="recipe_template",
            payload={"item_id": chair.pk, "title": "x", "inputs": [{"item": chair.pk, "quantity": "0"}]},
        )


def _mediation(unit_a, unit_b, author):
    check = {"question": "What is it?", "choices": ["A saw", "B", "C"], "correct": 0, "hint": "x"}
    return mediation.open_mediation(
        author,
        "A quarrel about a shared saw",
        "We disagree.",
        parties_units=[unit_a, unit_b],
        brief="Two units disagree.",
        check=check,
    )


def test_the_mediation_draw_prefers_the_union_pool_and_excludes_the_parties():
    from datetime import timedelta

    from django.utils import timezone

    from apps.members.models import Member

    union, crew, people, solo, solo_member = active_union()
    third, third_people = None, []
    from .conftest import council_unit

    third, third_people = council_unit("woodshop-third", [f"t{i}@x.org" for i in range(4)])
    services.accept_invitation(services.invite_unit(solo_member, union, third), third_people[0])
    decision = third.decisions.get()
    for p in third_people:
        unit_services.vote(decision, p, "yes")
    assert services.is_member_unit(union, third)
    outsiders = [make_member(f"o{i}@x.org", f"O{i}") for i in range(6)]
    everyone = [*people, solo_member, *third_people, *outsiders]
    Member.objects.filter(pk__in=[m.pk for m in everyone]).update(
        joined_at=timezone.now() - timedelta(days=400), is_mediator=True
    )
    ticket = _mediation(crew, solo, people[0])
    ticket.refresh_from_db()
    assert ticket.action_payload["mediator_pool"] == f"union:{union.slug}"
    drawn = set(mediation.mediators(ticket).values_list("pk", flat=True))
    pool = {m.pk for m in third_people}
    assert len(drawn) == 3 and drawn <= pool  # only the union's other unit; never the parties' workers
    parties = {m.pk for m in people} | {solo_member.pk}
    assert not drawn & parties


def test_the_mediation_draw_falls_back_to_the_general_pool_when_the_union_pool_is_too_small():
    from datetime import timedelta

    from django.utils import timezone

    from apps.members.models import Member

    union, crew, people, solo, solo_member = active_union()
    outsiders = [make_member(f"o{i}@x.org", f"O{i}") for i in range(6)]
    Member.objects.filter(pk__in=[m.pk for m in outsiders]).update(
        joined_at=timezone.now() - timedelta(days=400), is_mediator=True
    )
    ticket = _mediation(crew, solo, people[0])
    ticket.refresh_from_db()
    assert ticket.action_payload["mediator_pool"] == "volunteers"
    assert {m.pk for m in mediation.mediators(ticket)} <= {m.pk for m in outsiders}


def test_a_training_decision_makes_a_task_list_of_union_scope():
    union, crew, people, solo, solo_member = active_union()
    payload = {"tasks": [{"title": "Teach safe sawing", "minutes": 90, "description": "A short course"}]}
    decision = services.open_decision(people[0], union, "Sawing course", kind="training", payload=payload)
    approve(union, decision, people, solo_member)
    number = decision.result["done"]["ticket"]
    ticket = Ticket.objects.get(number=number)
    assert ticket.type == "task_list" and ticket.scope == "union" and ticket.scope_union == union
    assert ticket.action_payload["tasks"][0]["minutes"] == 90
    assert not Task.objects.filter(ticket=ticket).exists()  # the tasks appear when the confirmers approve it
    with pytest.raises(services.BodyError, match="at least one task"):
        services.open_decision(people[0], union, "Empty", kind="training", payload={})


def test_unused_imports_stay_quiet():
    assert Q and one_person_unit
