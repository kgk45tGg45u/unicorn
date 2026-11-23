"""Elected roles: auditors and the trust review group, by approval voting with secret ballots (P07.T09)."""

import random
from collections import Counter
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.hashing import sha256_hex
from apps.members import services as member_services
from apps.members.models import Member
from apps.rules.services import get_param

from .models import Ballot, Candidate, Election, Term, VoterRecord
from .services import VoteError, eligible_now, new_receipt

AUDITOR_SEATS = 3
TERM_DAYS = 365
RENEW_BEFORE_DAYS = 30


def seats_for(role) -> int:
    return AUDITOR_SEATS if role == "auditor" else get_param("tradefund.trust_review_group_size")


def open_election(role, now=None) -> Election:
    now = now or timezone.now()
    with transaction.atomic():
        if Election.objects.filter(role=role, status="open").exists():
            raise VoteError(_("There is already an election for this role."))
        e = Election.objects.create(
            role=role,
            seats=seats_for(role),
            opens_at=now,
            closes_at=now + timedelta(days=get_param("governance.referendum.days")),
            eligible_count=eligible_now(),
        )
        audit.record("system", "election.opened", e, role=role)
        return e


def stand(election, member, statement=""):
    """Put oneself forward. Candidates for the trust review group must not hold more than the base cap (from P08)."""
    if not member_services.is_verified(member):  # HF-13
        raise VoteError(_("Only verified members can stand."))
    if election.status != "open" or timezone.now() >= election.closes_at:
        raise VoteError(_("This election is closed."))
    # OWNER-CHECK: trust-review candidates must hold no more than the base cap; the fund's records come in phase 8,
    # so until then the claim is recorded but not checked.
    try:
        with transaction.atomic():
            c = Candidate.objects.create(election=election, member=member, statement=(statement or "").strip())
    except IntegrityError:
        raise VoteError(_("You already stand in this election.")) from None
    audit.record(member.number, "election.stood", c)
    return c


def cast(election, member, approved_member_ids) -> str:
    """Approve any number of candidates, in secret. Returns the receipt (shown once)."""
    if not member_services.is_verified(member):  # HF-13
        raise VoteError(_("Only verified members can vote."))
    ids = sorted({int(i) for i in approved_member_ids})
    with transaction.atomic():
        election = Election.objects.select_for_update().get(pk=election.pk)
        if election.status != "open" or timezone.now() >= election.closes_at:
            raise VoteError(_("This election is closed."))
        if not set(ids) <= set(election.candidates.values_list("member_id", flat=True)):
            raise VoteError(_("Please approve only people who stand."))
        try:
            with transaction.atomic():
                VoterRecord.objects.create(election=election, member=member, voted_on=timezone.localdate())
        except IntegrityError:
            raise VoteError(_("You have already voted.")) from None
        for _attempt in range(5):
            receipt = new_receipt()
            try:
                with transaction.atomic():
                    Ballot.objects.create(election=election, receipt=receipt, choice=ids)
                break
            except IntegrityError:
                continue
        else:
            raise VoteError(_("Something went wrong. Please try again."))
        audit.record(member.number, "election.voted", election)
        return receipt


def _winners(counts, seats, seed):
    """The `seats` candidates with the most approvals. A tie at the edge is broken by a seeded random choice."""
    by_score = {}
    for member_id, n in counts.items():
        by_score.setdefault(n, []).append(member_id)
    chosen, tie_broken = [], False
    for score in sorted(by_score, reverse=True):
        group = sorted(by_score[score])
        room = seats - len(chosen)
        if room <= 0:
            break
        if len(group) <= room:
            chosen.extend(group)
        else:
            chosen.extend(random.Random(int(sha256_hex(seed), 16)).sample(group, room))
            tie_broken = True
    return chosen, tie_broken


def close_elections(now=None) -> int:
    from apps.tickets.draw import NO_FINGERPRINT, _fingerprint

    now = now or timezone.now()
    done = 0
    for e in Election.objects.filter(status="open", closes_at__lte=now):
        with transaction.atomic():
            e = Election.objects.select_for_update().get(pk=e.pk)
            if e.status != "open":
                continue
            counts = Counter({c.member_id: 0 for c in e.candidates.all()})
            for choice in e.ballots.values_list("choice", flat=True):
                counts.update(choice)
            fp = _fingerprint()
            seed = f"election:{e.pk}:{fp.hash if fp else NO_FINGERPRINT}"
            winners, tie_broken = _winners(dict(counts), e.seats, seed)
            numbers = dict(Member.objects.filter(pk__in=counts).values_list("pk", "number"))
            for member_id in winners:
                Term.objects.create(
                    role=e.role, member_id=member_id, starts_at=now, ends_at=now + timedelta(days=TERM_DAYS), election=e
                )
            e.status = "closed"
            e.result = {
                "voters": e.voters.count(),
                "eligible": e.eligible_count,
                "approvals": {numbers[i]: n for i, n in counts.items()},
                "winners": [numbers[i] for i in winners],
                "tie_broken_by_seed": tie_broken,
            }
            e.save(update_fields=["status", "result"])
            audit.record("system", "election.closed", e, winners=len(winners))
            done += 1
    return done


def current_members(role, now=None):
    now = now or timezone.now()
    ids = Term.objects.filter(role=role, starts_at__lte=now, ends_at__gt=now).values_list("member_id", flat=True)
    return Member.objects.filter(pk__in=list(ids), status=Member.MEMBER)


def yearly_elections(now=None) -> int:
    """Each year a new election opens, a month before the current terms end. The first ones are started by a vote."""
    now = now or timezone.now()
    opened = 0
    for role, _label in Election.ROLES:
        terms = Term.objects.filter(role=role)
        if not terms.exists() or Election.objects.filter(role=role, status="open").exists():
            continue  # the first election is started by the founders' vote
        if terms.filter(ends_at__gt=now + timedelta(days=RENEW_BEFORE_DAYS)).exists():
            continue
        open_election(role, now)
        opened += 1
    return opened


def start_first_elections(ticket):
    """Execute for `start_elections`: the founders' vote after launch opens the first elections."""
    opened = []
    for role in ticket.action_payload.get("roles", ["auditor", "trust_review"]):
        if not Election.objects.filter(role=role).exists():
            open_election(role)
            opened.append(role)
    return {"opened": opened}
