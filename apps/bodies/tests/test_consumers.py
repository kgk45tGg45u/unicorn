from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bodies import consumers, services
from apps.bodies.models import GuidelineDeclaration
from apps.catalogue import services as catalogue
from apps.catalogue.models import Offer
from apps.tickets import flags
from apps.tickets.models import Flag, Hidden
from apps.units.tests.conftest import make_member

from .conftest import council_unit, one_person_unit

pytestmark = pytest.mark.django_db


def council_of(n=4):
    people = [make_member(f"c{i}@x.org", f"Consumer{i}") for i in range(n)]
    council = consumers.create_council(people[0], "Good food", "food quality", "We care about what we eat")
    for p in people[1:]:
        consumers.join(p, council)
    return council, people


def published_guideline(council, people, title="Fresh and local"):
    g = consumers.propose_guideline(people[0], council, title, "Food is made within 100 km.")
    for p in people[:3]:
        consumers.vote(g, p, "yes")
    consumers.vote(g, people[3], "no")
    g.refresh_from_db()
    assert g.status == "published"
    return g


def test_anyone_verified_can_form_join_and_leave():
    council, people = council_of(3)
    assert len(consumers.members(council)) == 3
    consumers.leave(people[2], council)
    assert len(consumers.members(council)) == 2
    consumers.join(people[2], council)  # leaving is never final
    assert len(consumers.members(council)) == 3
    applicant = make_member("applicant@x.org", "Applicant", verified=False)
    with pytest.raises(services.BodyError, match="verified"):
        consumers.join(applicant, council)
    with pytest.raises(services.BodyError, match="already"):
        consumers.create_council(people[0], "good food", "again")


def test_a_guideline_needs_the_members_majority():
    council, people = council_of(4)
    g = consumers.propose_guideline(people[0], council, "Fresh and local", "Food is made within 100 km.")
    consumers.vote(g, people[0], "yes")
    consumers.vote(g, people[1], "no")
    with pytest.raises(services.BodyError, match="already voted"):
        consumers.vote(g, people[1], "yes")
    assert consumers.close_due_guidelines(timezone.now()) == 0  # seven days have not passed
    assert consumers.close_due_guidelines(timezone.now() + timedelta(days=8)) == 1
    g.refresh_from_db()
    assert g.status == "rejected" and g.result["yes"] == 1 and g.result["no"] == 1  # a tie is not a majority


def test_a_majority_of_those_who_vote_publishes_and_only_members_vote():
    council, people = council_of(4)
    g = consumers.propose_guideline(people[0], council, "Fresh and local", "Food is made within 100 km.")
    with pytest.raises(services.BodyError, match="Only members"):
        consumers.vote(g, make_member("out@x.org", "Outsider"), "yes")
    consumers.vote(g, people[0], "yes")  # one yes and nobody against after 7 days is a majority of those who vote
    consumers.close_due_guidelines(timezone.now() + timedelta(days=8))
    g.refresh_from_db()
    assert g.status == "published" and g.version == 1 and g.published_at is not None
    again = consumers.propose_guideline(people[1], council, "Fresh and local", "Within 80 km.")
    consumers.vote(again, people[1], "yes")
    consumers.close_due_guidelines(timezone.now() + timedelta(days=8))
    again.refresh_from_db()
    assert again.version == 2 and [x.version for x in consumers.published(council)] == [2, 1]
    with pytest.raises(services.BodyError, match="closed"):
        consumers.vote(again, people[2], "yes")


def _offer(unit):
    item = catalogue.create_item("Oak chair", "product", "pc", unit=unit)
    return Offer.objects.create(unit=unit, item=item, status="active")


def test_a_one_person_unit_declares_at_once_and_a_council_unit_votes_on_it():
    council, people = council_of(4)
    guideline = published_guideline(council, people)
    solo, solo_member = one_person_unit("farm", "farm@x.org")
    offer = _offer(solo)
    consumers.declare(solo_member, offer, guideline)
    assert [d.guideline for d in consumers.declarations_for(offer)] == [guideline]
    with pytest.raises(services.BodyError, match="already says"):
        consumers.declare(solo_member, offer, guideline)
    crew, crew_people = council_unit("farm-crew", ["f0@x.org", "f1@x.org", "f2@x.org"])
    crew_offer = _offer_named(crew, "Cheese")
    decision = consumers.declare(crew_people[0], crew_offer, guideline)
    assert decision.status == "open" and not consumers.declarations_for(crew_offer)
    from apps.units import services as unit_services

    for p in crew_people:
        unit_services.vote(decision, p, "yes")
    assert len(consumers.declarations_for(crew_offer)) == 1
    with pytest.raises(services.BodyError, match="council"):
        consumers.declare(make_member("z@x.org", "Z"), crew_offer, guideline)


def _offer_named(unit, name):
    item = catalogue.create_item(name, "product", "pc", unit=unit)
    return Offer.objects.create(unit=unit, item=item, status="active")


def test_a_declaration_can_be_flagged_and_is_hidden_after_enough_reports():
    council, people = council_of(4)
    guideline = published_guideline(council, people)
    solo, solo_member = one_person_unit("farm2", "farm2@x.org")
    offer = _offer(solo)
    consumers.declare(solo_member, offer, guideline)
    declaration = GuidelineDeclaration.objects.get()
    with pytest.raises(flags.FlagError, match="your own"):
        flags.flag(solo_member, "guideline", declaration.pk, "wrong_data")
    flags.flag(people[0], "guideline", declaration.pk, "wrong_data", "They do not follow it")
    flags.flag(people[1], "guideline", declaration.pk, "wrong_data")
    assert Flag.objects.filter(target_type="guideline").count() == 2
    from apps.rules.services import get_param

    for extra in range(get_param("governance.flags.hide_after_flags") - 2):
        flags.flag(make_member(f"flagger{extra}@x.org", f"F{extra}"), "guideline", declaration.pk, "other")
    assert Hidden.objects.filter(target_type="guideline", target_id=declaration.pk).exists()
    assert consumers.declarations_for(offer) == []


def test_a_consumers_council_has_no_special_power_in_flags():
    council, people = council_of(4)
    solo, solo_member = one_person_unit("farm3", "farm3@x.org")
    offer = _offer(solo)
    first = flags.flag(people[0], "offer", offer.pk, "wrong_data")
    with pytest.raises(flags.FlagError, match="already reported"):
        flags.flag(people[0], "offer", offer.pk, "wrong_data")  # one flag per member, whatever council they sit in
    flags.flag(people[1], "offer", offer.pk, "wrong_data")
    assert Flag.objects.filter(ticket=first.ticket).count() == 2
    assert not Hidden.objects.filter(target_type="offer").exists()


def test_the_offer_page_shows_the_declaration(client):
    council, people = council_of(4)
    guideline = published_guideline(council, people)
    solo, solo_member = one_person_unit("farm4", "farm4@x.org")
    offer = _offer(solo)
    consumers.declare(solo_member, offer, guideline)
    client.force_login(people[0].user)
    page = client.get(f"/offers/{offer.pk}/").content.decode()
    assert "We follow the guideline Fresh and local" in page and "Good food" in page
