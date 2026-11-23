"""The permission matrix (P14.T13): every page that accepts a POST says who may use it, and the test checks it.

The list of URLs comes from the project's URL configuration, so a new page that accepts a POST fails the test
until someone writes it into the table below and says who may use it. The levels:

- ``public``       anyone, also without an account (the shop, donations);
- ``public_read``  anyone may read the page; actions inside it need an account (the view checks);
- ``login``        any logged-in person, also someone who has not been verified yet (their own settings, joining);
- ``member``       verified members only (HF-13); an unverified person changes nothing.

Posts are sent with dummy numbers and empty forms, so a page that is allowed answers with a form or "not found",
and a page that must refuse answers with a redirect to the login page or "forbidden". What the test looks at is
(a) the answer, (b) no server error for anybody, and (c) what was written to the database: a refused person
writes nothing (apart from the session and the audit trail).
"""

import inspect
import re
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.urls import URLResolver, get_resolver

from apps.units.tests.conftest import make_member

PUBLIC, PUBLIC_READ, LOGIN, MEMBER = "public", "public_read", "login", "member"

MATRIX = {
    # --- members
    "members:join_about": LOGIN,  # an applicant takes the first step of joining
    "members:launch": MEMBER,
    "members:contract": PUBLIC_READ,  # anyone reads the contract; signing needs an account
    "members:mediator_toggle": LOGIN,  # own setting; mediators are drawn only from verified members
    "members:notify_toggle": LOGIN,
    "members:suggest_toggle": LOGIN,  # own setting
    "members:assist_start": MEMBER,
    "members:assist_sign": MEMBER,
    "members:assist_paper": MEMBER,
    "members:assist_witness": MEMBER,
    "members:assist_revoke": MEMBER,
    "members:assist_act": MEMBER,
    "members:assist_stop": LOGIN,
    "members:vouch": MEMBER,
    "members:identity_check": MEMBER,
    "members:portfolio": LOGIN,
    "members:leave": LOGIN,
    "members:delete": LOGIN,
    # --- the books and the hours
    "ledger:retirement": MEMBER,
    "units:my_hours": MEMBER,
    "units:timer": MEMBER,
    "units:submit_draft": MEMBER,
    "units:open": MEMBER,
    "units:decide_join": MEMBER,
    "units:decision_vote": MEMBER,
    "units:decisions": MEMBER,
    "units:join": MEMBER,
    "units:sign_rules": MEMBER,
    "units:decline_turn": MEMBER,
    "units:reopen": MEMBER,
    "units:approve": MEMBER,
    "units:leave": MEMBER,
    # --- the catalogue and the market
    "catalogue:join_forces": MEMBER,
    "catalogue:offer_new": MEMBER,
    "catalogue:add_input": MEMBER,
    "catalogue:add_tool": MEMBER,
    "catalogue:remove_row": MEMBER,
    "catalogue:publish": MEMBER,
    "catalogue:switch_input": MEMBER,
    "catalogue:confirm_free": MEMBER,
    "market:wait": MEMBER,
    "market:order": MEMBER,
    "market:book": MEMBER,
    "market:my_order_action": MEMBER,
    "market:work_action": MEMBER,
    "market:sell": MEMBER,
    # --- tickets, votes, tasks
    "tickets:flag": MEMBER,
    "tickets:hard_frame_new": MEMBER,
    "tickets:new_form": MEMBER,
    "tickets:comment_edit": MEMBER,
    "tickets:helpful": MEMBER,
    "tickets:mediation_new": MEMBER,
    "tickets:mediation_action": MEMBER,
    "tickets:release": MEMBER,
    "tickets:contest": MEMBER,
    "tickets:comment": MEMBER,
    "tickets:seat": MEMBER,
    "tickets:seat_vote": MEMBER,
    "tickets:seat_conflict": MEMBER,
    "tickets:notifications": LOGIN,
    "votes:open_petition": MEMBER,
    "votes:sign": MEMBER,
    "votes:cast": MEMBER,
    "tasks:apply": MEMBER,
    "tasks:task_action": MEMBER,
    "tasks:mandate_action": MEMBER,
    # --- the trade fund
    "tradefund:become_holder": MEMBER,
    "tradefund:mine": MEMBER,
    "tradefund:pay_detail": MEMBER,
    "tradefund:purchase_new": MEMBER,
    "tradefund:purchase_detail": MEMBER,
    "tradefund:donate": PUBLIC,  # anyone may donate; the page only shows where to pay
    "tradefund:my_donations": MEMBER,
    "tradefund:benefits": MEMBER,
    "tradefund:trust_contest": MEMBER,
    # --- the economy, the plan, the bodies
    "macro:my_world": LOGIN,  # optional facts about oneself
    "macro:retirement_payout": MEMBER,
    "plan:propose": MEMBER,
    "plan:group": MEMBER,
    "plan:variant": PUBLIC_READ,  # the plan is open to read; comments and votes need a seat
    "bodies:union_new": MEMBER,
    "bodies:union_invite": MEMBER,
    "bodies:union_leave": MEMBER,
    "bodies:union_decide": MEMBER,
    "bodies:union_vote": MEMBER,
    "bodies:give_advice": MEMBER,
    "bodies:consumer_membership": MEMBER,
    "bodies:consumer_new": MEMBER,
    "bodies:guideline_propose": MEMBER,
    "bodies:guideline_vote": MEMBER,
    "bodies:local_decide": MEMBER,
    "bodies:local_new": MEMBER,
    "bodies:local_volunteer": MEMBER,
    "bodies:nomination_answer": MEMBER,
    "reputation:hide": MEMBER,
    "rules:propose": MEMBER,
    "privacy:request_export": LOGIN,  # an applicant has data too, and may ask for it
    # --- outside customers (they have no account): protected by a rate limit and by secret tokens
    "outside:checkout": PUBLIC,
    "outside:withdraw": PUBLIC,
    "outside:received": PUBLIC,
    "outside:seller": MEMBER,
}

#: Pages of other packages that are not ours to table: the admin (locked by its own gate, tested in
#: test_security_headers) and the login pages of allauth (they are the way in).
FOREIGN = ("django.", "allauth.")

#: Writes that any request may cause: the session, the audit trail, the cache, and the one-row site state
#: that is created the first time somebody looks at it.
INCIDENTAL = ("django_session", "core_auditevent", "unicorn_cache", "members_sitestate")
WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\s+(?:INTO\s+|FROM\s+)?`?(\w+)`?", re.I)


def walk(patterns, prefix="", namespace=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from walk(
                p.url_patterns, prefix + str(p.pattern), namespace + (p.namespace + ":" if p.namespace else "")
            )
        else:
            yield namespace + (p.name or str(p.pattern)), prefix + str(p.pattern), p.callback


def accepts_post(callback):
    view = getattr(callback, "view_class", None) or callback
    try:
        source = inspect.getsource(view)
    except (OSError, TypeError):
        return True  # cannot look inside: assume it does, so that somebody has to write it down
    return bool(re.search(r"POST|require_http_methods|request\.method", source))


def post_urls():
    found = {}
    for name, pattern, callback in walk(get_resolver().url_patterns):
        if getattr(callback, "__module__", "").startswith(FOREIGN) or not getattr(callback, "__module__", ""):
            continue
        if accepts_post(callback):
            found[name] = pattern
    return found


def dummy(pattern):
    values = {"int": "999999", "slug": "nothing", "str": "nothing"}
    return "/" + re.sub(r"<(?:(\w+):)?\w+>", lambda m: values.get(m.group(1) or "str", "nothing"), pattern)


def test_every_post_url_is_in_the_permission_matrix():
    found = post_urls()
    missing = sorted(set(found) - set(MATRIX))
    assert not missing, f"These pages accept a POST but are not in MATRIX (say who may use them): {missing}"
    stale = sorted(set(MATRIX) - set(found))
    assert not stale, f"These entries of MATRIX no longer match a page that accepts a POST: {stale}"
    assert set(MATRIX.values()) <= {PUBLIC, PUBLIC_READ, LOGIN, MEMBER}


class Recorder:
    """Remembers every statement that writes to the database while it is in use."""

    def __init__(self):
        self.writes = []

    def __call__(self, execute, sql, params, many, context):
        match = WRITE.match(sql)
        if match and match.group(2) not in INCIDENTAL:
            self.writes.append(f"{match.group(1).upper()} {match.group(2)}")
        return execute(sql, params, many, context)


def post(client, url):
    recorder = Recorder()
    with connection.execute_wrapper(recorder):
        response = client.post(url, {})
    return response, recorder.writes


def refused(response):
    """A refusal: sent to the login page, or told "forbidden" (never a page, never an error)."""
    return response.status_code == 403 or (response.status_code == 302 and "login" in response["Location"])


@pytest.fixture
def people(db):
    call_command("load_defaults", stdout=StringIO())
    applicant = make_member("applicant@x.org", "Applicant", verified=False)
    member = make_member("member@x.org", "Member")
    clients = {"anonymous": Client(raise_request_exception=False)}
    for label, person in (("unverified", applicant), ("member", member)):
        client = Client(raise_request_exception=False)
        client.force_login(person.user)
        client.get("/offline/")  # the session and "last active" are written now, not in the test
        clients[label] = client
    return clients


def test_the_permission_matrix(people):
    urls = post_urls()
    problems = []
    for name, level in sorted(MATRIX.items()):
        url = dummy(urls[name])
        has_object = "<" in urls[name]
        for who, client in people.items():
            response, writes = post(client, url)
            where = f"{name} ({url}) as {who}"
            if response.status_code >= 500:
                problems.append(f"{where}: a server error ({response.status_code})")
                continue
            if who == "anonymous" and level in (LOGIN, MEMBER) and not refused(response):
                problems.append(f"{where}: should be sent to the login page, got {response.status_code}")
            if who == "anonymous" and writes and level != PUBLIC:
                problems.append(f"{where}: wrote to the database: {sorted(set(writes))}")
            if who == "unverified" and level == MEMBER and writes:
                problems.append(f"{where}: an unverified person changed data: {sorted(set(writes))}")
            if who == "member" and level in (LOGIN, MEMBER) and has_object and writes:
                problems.append(f"{where}: someone unrelated changed data: {sorted(set(writes))}")
    assert not problems, "\n".join(problems)


def test_a_refusal_is_a_redirect_to_login_or_forbidden_and_nothing_else():
    """The test itself must notice an open door."""

    class Answer:
        def __init__(self, status, location=""):
            self.status_code, self.location = status, location

        def __getitem__(self, key):
            return self.location

    assert refused(Answer(403)) and refused(Answer(302, "/accounts/login/?next=/x/"))
    assert not refused(Answer(200)) and not refused(Answer(404)) and not refused(Answer(302, "/me/"))
