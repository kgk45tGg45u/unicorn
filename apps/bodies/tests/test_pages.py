from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bodies import consumers, duties, local, services
from apps.bodies.models import ExpertNomination
from apps.members.models import Member
from apps.tickets import services as ticket_services
from apps.units import services as unit_services

from .conftest import active_union, make_member
from .test_local import open_council, residents

pytestmark = pytest.mark.django_db


def test_the_index_lists_all_three_kinds_and_search_narrows_it(client):
    union, crew, people, solo, solo_member = active_union()
    council = consumers.create_council(people[0], "Good food", "food quality")
    people_in_berlin = residents(12)
    berlin = open_council(people_in_berlin)
    client.force_login(people[0].user)
    page = client.get("/bodies/").content.decode()
    assert union.name in page and council.name in page and berlin.name in page
    only = client.get("/bodies/?q=food").content.decode()
    assert "Good food" in only and union.name not in only and berlin.name not in only
    assert berlin.name in client.get("/bodies/?q=10").content.decode()


def test_a_union_page_shows_units_delegates_decisions_advice_and_nominations(client):
    union, crew, people, solo, solo_member = active_union()
    decision = services.open_decision(people[0], union, "A standard for oak", kind="other")
    ticket = ticket_services.create_ticket(
        "question", make_member("asker@x.org", "Asker"), "A wood question", scope="unit", scope_unit=crew
    )
    duties.give_advice(ticket, people[0], union, "Dry it well.")
    client.force_login(people[0].user)
    page = client.get(f"/bodies/unions/{union.slug}/").content.decode()
    assert crew.name in page and solo.name in page
    assert people[0].display_name in page and solo_member.display_name in page  # the delegates
    assert "A standard for oak" in page and 'name="choice"' in page  # an open decision and a vote form
    assert ticket.number in page and "Open a decision" in page
    client.post(f"/bodies/union-decisions/{decision.pk}/vote/", {"choice": "yes"})
    assert decision.votes.count() == 1
    other = make_member("other@x.org", "Other")
    client.force_login(other.user)
    assert 'name="choice"' not in client.get(f"/bodies/unions/{union.slug}/").content.decode()


def test_a_union_can_be_formed_and_invited_through_the_pages(client):
    from .conftest import one_person_unit

    a, ma = one_person_unit("woodshop-p", "p@x.org")
    b, mb = one_person_unit("woodshop-q", "q@x.org")
    client.force_login(ma.user)
    assert "Form a union" in client.get("/bodies/unions/new/").content.decode()
    response = client.post(
        "/bodies/unions/new/", {"unit": a.pk, "name": "Joiners", "trade_codes": "wood, joinery", "description": "x"}
    )
    assert response.status_code == 302
    client.post("/bodies/unions/joiners/invite/", {"unit": b.slug})
    client.force_login(mb.user)
    home = client.get("/").content.decode()
    assert "My bodies" in home and "joins the union Joiners" in home  # an invitation waits for the responsible


def test_a_local_council_page_shows_what_the_area_needs_and_who_is_responsible(client):
    people = residents(12)
    council = open_council(people)
    local.volunteer(people[0], council)
    from apps.market.models import SearchMiss

    SearchMiss.objects.create(area="10", text="oak chair", month=timezone.localdate().replace(day=1), count=3)
    client.force_login(people[1].user)
    page = client.get(f"/bodies/local/{council.pk}/").content.decode()
    assert council.name in page and people[0].display_name in page
    assert "oak chair" in page and "Pickup points" in page and "I volunteer" in page
    client.post(f"/bodies/local/{council.pk}/volunteer/", {"do": "volunteer"})
    assert len(local.active_volunteers(council)) == 2
    outsider = residents(1, postcode="80331", prefix="o")[0]
    client.force_login(outsider.user)
    assert "I volunteer" not in client.get(f"/bodies/local/{council.pk}/").content.decode()
    assert "Ask for a council in my area" in client.get("/bodies/").content.decode()


def test_a_local_council_can_be_asked_for_through_the_page(client):
    people = residents(12)
    client.force_login(people[0].user)
    response = client.post("/bodies/local/new/", {"name": "Berlin Mitte", "prefix": "10", "level": "district"})
    assert response.status_code == 302 and response["Location"].startswith("/tickets/T-")


def test_a_consumers_council_page_shows_members_guidelines_and_votes(client):
    members = [make_member(f"c{i}@x.org", f"Consumer{i}") for i in range(3)]
    council = consumers.create_council(members[0], "Good food", "food quality")
    consumers.join(members[1], council)
    guideline = consumers.propose_guideline(members[0], council, "Fresh and local", "Within 100 km.")
    client.force_login(members[1].user)
    page = client.get(f"/bodies/consumers/{council.pk}/").content.decode()
    assert "Consumer0" in page and "Fresh and local" in page and 'name="choice"' in page
    client.post(f"/bodies/guidelines/{guideline.pk}/vote/", {"choice": "yes"})
    assert guideline.votes.count() == 1
    client.force_login(members[2].user)
    page = client.get(f"/bodies/consumers/{council.pk}/").content.decode()
    assert 'name="choice"' not in page and "Join this council" in page
    client.post(f"/bodies/consumers/{council.pk}/membership/", {"do": "join"})
    assert consumers.is_member(members[2], council)


def test_my_bodies_on_the_dashboard_lists_the_bodies_and_what_waits(client):
    union, crew, people, solo, solo_member = active_union()
    services.open_decision(people[0], union, "Vote on this", kind="other")
    residents_ = residents(12)
    council = open_council(residents_)
    guideline_council = consumers.create_council(residents_[0], "Good food", "food")
    consumers.propose_guideline(residents_[0], guideline_council, "Fresh", "Local food")
    consumers.join(residents_[2], guideline_council)
    client.force_login(people[0].user)
    home = client.get("/").content.decode()
    assert "My bodies" in home and union.name in home and "Vote for your unit: Vote on this" in home
    client.force_login(residents_[2].user)
    home = client.get("/").content.decode()
    assert council.name in home and "Good food" in home and "Vote on the guideline: Fresh" in home
    nobody = make_member("nobody@x.org", "Nobody")
    client.force_login(nobody.user)
    assert "You do not belong to any union or council yet." in client.get("/").content.decode()


def test_an_expert_nomination_waits_on_the_nominations_page_and_on_the_dashboard(client):
    from apps.bodies import experts
    from apps.plan import services as plan_services
    from apps.plan.tests.conftest import drafting_group

    union, crew, people, solo, solo_member = active_union()
    today = plan_services.today()
    period, group, members = drafting_group(25, year=today.year + 1, on=today)
    seats = set(group.seats.values_list("member_id", flat=True))
    nominee = next(m for m in members if m.pk not in seats)
    decision = services.open_decision(
        people[0], union, "Name an expert", kind="nominate_expert", payload={"member": nominee.number}
    )
    services.vote(decision, people[0], "yes")
    services.vote(decision, solo_member, "yes")
    client.force_login(nominee.user)
    assert union.name in client.get("/bodies/nominations/").content.decode()
    assert "names you as an expert adviser" in client.get("/").content.decode()
    client.post(f"/bodies/nominations/{ExpertNomination.objects.get().pk}/answer/", {"answer": "accept"})
    assert experts.pending_for(nominee).count() == 0
    assert group.advisers.filter(member=nominee).exists()
    assert timedelta(0) == timedelta(0) and Member and unit_services
