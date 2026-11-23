from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tasks import services
from apps.tasks.models import Task
from apps.tickets import services as ticket_services

from .conftest import CHECK, answer, make_member, open_seats, pool

pytestmark = pytest.mark.django_db

TASKS = [
    {"title": "Clean the room", "minutes": 60},
    {"title": "Collect signatures", "minutes": 120, "description": "At the market"},
]


def open_list():
    members = pool(40)
    author = make_member("author@x.org", "Author")
    ticket = ticket_services.create_ticket(
        "task_list", author, "Spring cleaning", brief="Two jobs.", check=CHECK, action_payload={"tasks": TASKS}
    )
    for s in open_seats(ticket):
        answer(s, "yes")
    ticket.refresh_from_db()
    return members, author, ticket


def test_a_task_list_needs_tasks():
    with pytest.raises(ticket_services.TicketError):
        ticket_services.create_ticket("task_list", make_member(), "Empty", brief="b", check=CHECK)


def test_an_approved_task_list_makes_tasks_anyone_can_take():
    members, author, ticket = open_list()
    assert ticket.status == "in_action" and Task.objects.filter(ticket=ticket).count() == 2
    assert all(t.status == "open" for t in Task.objects.all())


def test_claim_done_confirm_and_paid():
    members, author, ticket = open_list()
    task = Task.objects.get(title="Clean the room")
    services.claim(task, members[1])
    with pytest.raises(services.TaskError):
        services.claim(task, members[2])
    with pytest.raises(services.TaskError):
        services.mark_done(task, members[2], "I did it")
    with pytest.raises(services.TaskError):
        services.mark_done(task, members[1], "")
    services.mark_done(task, members[1], "Photo sent")
    task.refresh_from_db()
    assert task.status == "done"
    services.confirm(task, author)
    task.refresh_from_db()
    assert task.status == "confirmed" and task.paid_entry.minutes == 60 and task.paid_entry.status == "paid"
    ticket.refresh_from_db()
    assert ticket.status == "in_action"
    other = Task.objects.get(title="Collect signatures")
    services.claim(other, members[2])
    services.mark_done(other, members[2], "Signed")
    services.confirm(other, author)
    ticket.refresh_from_db()
    assert ticket.status == "done"


def test_one_cannot_confirm_ones_own_task_and_only_the_author_confirms_directly():
    members, author, ticket = open_list()
    task = Task.objects.get(title="Clean the room")
    services.claim(task, author)
    services.mark_done(task, author, "Done")
    with pytest.raises(services.TaskError, match="your own"):
        services.confirm(task, author)
    other = Task.objects.get(title="Collect signatures")
    services.claim(other, members[1])
    services.mark_done(other, members[1], "Done")
    with pytest.raises(services.TaskError):
        services.confirm(other, members[2])


def test_one_random_member_can_confirm_instead():
    members, author, ticket = open_list()
    task = Task.objects.get(title="Clean the room")
    services.claim(task, members[1])
    services.mark_done(task, members[1], "Done")
    check = services.request_random_check(task)
    seats = open_seats(check)
    assert len(seats) == 1 and seats[0].member != members[1]
    answer(seats[0], "yes")
    task.refresh_from_db()
    assert task.status == "confirmed" and task.paid_entry.minutes == 60


def test_the_timeout_frees_a_claimed_task():
    members, author, ticket = open_list()
    task = Task.objects.get(title="Clean the room")
    services.claim(task, members[1])
    assert services.release_stale() == 0
    assert services.release_stale(now=timezone.now() + timedelta(days=8)) == 1
    task.refresh_from_db()
    assert task.status == "open" and task.claimed_by is None


def test_hf13_an_unverified_member_cannot_claim():
    from apps.members.models import Member

    members, author, ticket = open_list()
    Member.objects.filter(pk=members[5].pk).update(status=Member.APPLICANT)
    members[5].refresh_from_db()
    with pytest.raises(services.TaskError):
        services.claim(Task.objects.first(), members[5])


def test_the_against_brief_task_is_written_by_a_random_member_and_paid():
    from apps.tickets.models import Ticket
    from apps.votes import services as vote_services

    members = pool(40)
    ticket = ticket_services.create_ticket("idea", members[0], "An idea", brief="Do it.")
    Ticket.objects.filter(pk=ticket.pk).update(status="rejected", petition_until=timezone.now() + timedelta(days=5))
    ticket.refresh_from_db()
    r = vote_services.schedule_referendum(ticket, "Do it?")
    task = Task.objects.get(kind="against")
    assert task.claimed_by is not None and task.claimed_by != members[0] and r.brief_against_md == ""
    services.mark_done(task, task.claimed_by, "It costs too much.")
    r.refresh_from_db()
    task.refresh_from_db()
    assert r.brief_against_md == "It costs too much." and task.status == "confirmed" and task.paid_entry.minutes == 60


def test_the_pages(client):
    from django.urls import reverse

    members, author, ticket = open_list()
    client.force_login(members[1].user)
    assert client.get(reverse("tasks:list")).status_code == 200
    page = client.get(reverse("tasks:ticket", args=[ticket.number])).content.decode()
    assert "Clean the room" in page
    task = Task.objects.get(title="Clean the room")
    client.post(reverse("tasks:task_action", args=[task.pk, "claim"]))
    task.refresh_from_db()
    assert task.claimed_by == members[1]
