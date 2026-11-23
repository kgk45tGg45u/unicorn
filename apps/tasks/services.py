"""Getting things done: a delegate with a mandate, or everyone together through tasks (docs/05 section 5)."""

import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.hashing import sha256_hex
from apps.core.notify import notify
from apps.members import services as member_services
from apps.rules.services import get_param
from apps.tickets import actions, briefs
from apps.tickets import services as ticket_services
from apps.tickets.models import Ticket

from .models import Mandate, MandateApplication, Task


class TaskError(ValueError):
    """A plain-words reason why something cannot be done."""


# Called with (mandate, amount, note) when a delegate spends within the limit. The trade fund builds it (P08).
PAYMENT_REQUEST_HOOK = None


def _units():
    from apps.units import services as unit_services

    return unit_services


# --- A delegate for one decision ---


def open_applications(ticket):
    """An approved ticket that needs a delegate asks for volunteers for `volunteer_days`."""
    from apps.members.models import Skill

    days = get_param("governance.delegation.volunteer_days")
    until = timezone.now() + timedelta(days=days)
    ticket.action_payload = {**ticket.action_payload, "applications_until": until.isoformat()}
    ticket.save(update_fields=["action_payload"])
    trade = ticket.action_payload.get("trade_code")
    if trade:
        for skill in Skill.objects.filter(trade_code=trade).select_related("member"):
            if member_services.is_verified(skill.member):
                notify(
                    skill.member,
                    _("%(number)s needs someone to carry it out. Your portfolio fits: %(title)s")
                    % {"number": ticket.number, "title": ticket.title},
                    f"/tasks/ticket/{ticket.number}/",
                )
    audit.record("system", "mandate.applications_opened", ticket, until=until.isoformat())


def applications_open(ticket, now=None) -> bool:
    until = ticket.action_payload.get("applications_until")
    return (
        bool(until) and (now or timezone.now()).isoformat() < until and not ticket.action_payload.get("delegate_ticket")
    )


def apply(ticket, member, statement):
    ticket.refresh_from_db()
    if not member_services.is_verified(member):  # HF-13
        raise TaskError(_("Only verified members can apply."))
    if not applications_open(ticket):
        raise TaskError(_("This ticket is not asking for volunteers now."))
    if not (statement or "").strip():
        raise TaskError(_("Please say why you would be a good delegate."))
    with transaction.atomic():
        row, _created = MandateApplication.objects.update_or_create(
            ticket=ticket, member=member, defaults={"statement": statement.strip()}
        )
        audit.record(member.number, "mandate.applied", row, ticket=ticket.number)
        return row


def close_applications(now=None) -> int:
    """After the volunteer days, ask random confirmers who should carry the decision out. Safe to run twice."""
    now = now or timezone.now()
    count = 0
    for ticket in Ticket.objects.filter(status__in=["approved", "in_action", "done"]):
        p = ticket.action_payload or {}
        if not p.get("applications_until") or p.get("delegate_ticket") or p.get("delegate_status"):
            continue
        if p["applications_until"] > now.isoformat():
            continue
        with transaction.atomic():
            ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
            if (ticket.action_payload or {}).get("delegate_ticket"):
                continue
            start_delegate_choice(ticket)
            count += 1
    return count


def start_delegate_choice(ticket):
    applicants = list(ticket.mandate_applications.select_related("member").order_by("id"))
    if not applicants:
        ticket.action_payload = {**ticket.action_payload, "delegate_status": "no_applicants"}
        ticket.save(update_fields=["action_payload"])
        if ticket.author_id:
            notify(
                ticket.author,
                _("Nobody applied to carry out %(number)s.") % {"number": ticket.number},
                f"/tickets/{ticket.number}/",
            )
        return None
    n = len(applicants)
    lines = [_("Who should carry out %(number)s: %(title)s?") % {"number": ticket.number, "title": ticket.title}]
    for a in applicants:
        lines.append(f"- {a.member.display_name} ({a.member.number}): {a.statement}")
    lines.append(
        _("Rank the people you would trust, best first, or say none of them.")
        if n > 1
        else _("Yes means this person carries it out.")
    )
    check = briefs._check(_("How many people applied?"), str(n), [str(n + 1), str(n + 2)], _("the list of people"))
    delegate = ticket_services.create_ticket(
        "delegate_choice",
        None,
        _("Choose who carries out %(number)s") % {"number": ticket.number},
        brief="\n".join(lines),
        check=check,
        action_payload={
            "parent": ticket.number,
            "applicants": [a.member_id for a in applicants],
            "members": [a.member.number for a in applicants] + ([ticket.author.number] if ticket.author_id else []),
            "units": [],
        },
    )
    ticket.action_payload = {**ticket.action_payload, "delegate_ticket": delegate.number}
    ticket.save(update_fields=["action_payload"])
    return delegate


def _give_mandate(delegate_ticket):
    """Execute for `give_mandate`: rank the seats' lists with instant runoff and start the mandate."""
    from apps.tickets import confirm, draw
    from apps.votes import irv

    p = delegate_ticket.action_payload
    parent = Ticket.objects.get(number=p["parent"])
    applicants = [str(i) for i in p["applicants"]]
    root = delegate_ticket.confirmations.filter(parent__isnull=True, status="approved").order_by("-id").first()
    if len(applicants) == 1:
        winner = applicants[0]
        rounds = []
    else:
        rankings = [[str(i) for i in s.ranking] for s in confirm.active_seats(root) if s.vote == "yes" and s.ranking]
        fp = draw._fingerprint()
        seed = f"{delegate_ticket.number}:{fp.hash if fp else draw.NO_FINGERPRINT}"
        winner, rounds = irv.irv(rankings, applicants, seed)
        if winner is None:
            raise TaskError(_("The seats did not rank anybody."))
    from apps.members.models import Member

    member = Member.objects.get(pk=int(winner))
    now = timezone.now()
    days = min(
        parent.action_payload.get("mandate_days") or get_param("governance.delegation.max_mandate_days"),
        get_param("governance.delegation.max_mandate_days"),
    )
    mandate = Mandate.objects.create(
        ticket=parent,
        delegate=member,
        scope_md=parent.brief_md or parent.body_md or parent.title,
        powers=parent.action_payload.get("powers", {}),
        starts_at=now,
        ends_at=now + timedelta(days=days),
    )
    parent.action_payload = {**parent.action_payload, "delegate_status": "chosen"}
    parent.save(update_fields=["action_payload"])
    notify(
        member,
        _("You were chosen to carry out %(number)s.") % {"number": parent.number},
        f"/tasks/mandates/{mandate.pk}/",
        email=True,
    )
    audit.record("system", "mandate.started", mandate, delegate=member.number)
    return {"mandate": mandate.pk, "delegate": member.number, "rounds": rounds}


def spend(mandate, amount_eur, note=""):
    """A payment request from a delegate must cite the mandate and stay within its limit (docs/05 section 5)."""
    from decimal import Decimal

    now = timezone.now()
    if mandate.status != "active" or now >= mandate.ends_at:
        raise TaskError(_("This mandate is not active."))
    limit = Decimal(str(mandate.powers.get("spend_limit_eur", 0)))
    if Decimal(str(amount_eur)) > limit:
        raise TaskError(_("This is more than the mandate allows (%(limit)s euros).") % {"limit": limit})
    audit.record(mandate.delegate.number, "mandate.spend_requested", mandate, amount=str(amount_eur))
    if PAYMENT_REQUEST_HOOK is not None:
        return PAYMENT_REQUEST_HOOK(mandate, amount_eur, note)
    return {"mandate": mandate.pk, "amount": str(amount_eur)}


def report(mandate, member, text, minutes):
    """The delegate's report and hours. A 1-seat confirmation checks them; on 'yes' the hours are paid."""
    now = timezone.now()
    if member.pk != mandate.delegate_id:
        raise TaskError(_("Only the delegate can report."))
    if mandate.status != "active" or now >= mandate.ends_at:
        raise TaskError(_("This mandate is over, so no new hours can be reported."))
    if not (text or "").strip() or not isinstance(minutes, int) or minutes < 1:
        raise TaskError(_("Please write the report and the minutes you worked."))
    if mandate.report_at is not None and mandate.hours_entry_id:
        raise TaskError(_("The report was already sent and is being checked."))
    units = _units()
    with transaction.atomic():
        entry = units.create_draft(
            member, units.coordination_unit(), timezone.localdate(), minutes, activity="coordination",
            note=_("Mandate %(number)s") % {"number": mandate.ticket.number}, ref_type="mandate", ref_id=mandate.pk,
        )  # fmt: skip
        mandate.report_md, mandate.report_at, mandate.hours_entry = text.strip(), now, entry
        mandate.save(update_fields=["report_md", "report_at", "hours_entry"])
        check = briefs._check(
            _("How many minutes does the delegate report?"),
            str(minutes),
            [str(minutes + 30), str(minutes + 60)],
            _("the hours"),
        )
        brief = "\n".join(
            [
                _("The delegate reports on %(number)s: %(title)s.")
                % {"number": mandate.ticket.number, "title": mandate.ticket.title},
                text.strip(),
                _("The delegate worked %(minutes)s minutes. Do the report and the hours look right?")
                % {"minutes": minutes},
            ]
        )
        return ticket_services.create_ticket(
            "mandate_report",
            member,
            _("Report on %(number)s") % {"number": mandate.ticket.number},
            brief=brief,
            check=check,
            action_payload={"mandate_id": mandate.pk, "units": [], "members": [member.number]},
        )


def _approve_report(ticket):
    mandate = Mandate.objects.get(pk=ticket.action_payload["mandate_id"])
    units = _units()
    entry = units.submit_hours(mandate.hours_entry)  # coordination hours are approved by the system and paid
    mandate.status = "done"
    mandate.save(update_fields=["status"])
    audit.record("system", "mandate.done", mandate)
    return {"mandate": mandate.pk, "entry": entry.pk}


def _report_rejected(ticket):
    mandate = Mandate.objects.get(pk=ticket.action_payload["mandate_id"])
    mandate.report_at, mandate.hours_entry = None, None
    mandate.save(update_fields=["report_at", "hours_entry"])
    notify(
        mandate.delegate,
        _("Your report on %(number)s was not accepted. You can write it again.") % {"number": mandate.ticket.number},
        f"/tasks/mandates/{mandate.pk}/",
    )
    return {}


def open_revocation(member, mandate, reason):
    """Any member can ask random confirmers to take a mandate back."""
    if not member_services.is_verified(member):
        raise TaskError(_("Only verified members can do this."))
    if mandate.status != "active":
        raise TaskError(_("This mandate is not active."))
    check = briefs._check(
        _("Whose mandate is it?"), mandate.delegate.number, ["M-0000-0000", "M-1111-1111"], _("the first sentence")
    )
    return ticket_services.create_ticket(
        "revoke_mandate",
        member,
        _("Take back the mandate for %(number)s") % {"number": mandate.ticket.number},
        brief=_("Member %(number)s was given a mandate for %(ticket)s. Reason to take it back: %(reason)s")
        % {"number": mandate.delegate.number, "ticket": mandate.ticket.number, "reason": reason},
        check=check,
        action_payload={"mandate_id": mandate.pk, "units": [], "members": [mandate.delegate.number]},
    )


def _revoke(ticket):
    mandate = Mandate.objects.get(pk=ticket.action_payload["mandate_id"])
    mandate.status = "revoked"
    mandate.save(update_fields=["status"])
    notify(
        mandate.delegate,
        _("Your mandate for %(number)s was taken back.") % {"number": mandate.ticket.number},
        f"/tasks/mandates/{mandate.pk}/",
    )
    audit.record("system", "mandate.revoked", mandate, ticket=ticket.number)
    return {"mandate": mandate.pk}


def expire_mandates(now=None) -> int:
    now = now or timezone.now()
    count = 0
    for m in Mandate.objects.filter(status="active", ends_at__lte=now):
        m.status = "expired"
        m.save(update_fields=["status"])
        notify(
            m.delegate,
            _("Your mandate for %(number)s has ended.") % {"number": m.ticket.number},
            f"/tasks/mandates/{m.pk}/",
        )
        audit.record("system", "mandate.expired", m)
        count += 1
    return count


def _leave_check(member):
    if Mandate.objects.filter(delegate=member, status="active").exists():
        return [_("You have an active mandate: finish or hand it back first.")]
    return []


# --- Everyone together: tasks ---


def _validate_tasks(payload):
    rows = payload.get("tasks")
    if not rows or not isinstance(rows, list):
        return [_("A task list needs at least one task.")]
    bad = [
        r
        for r in rows
        if not isinstance(r, dict)
        or not str(r.get("title", "")).strip()
        or not isinstance(r.get("minutes"), int)
        or r["minutes"] < 1
    ]
    return [_("Every task needs a title and a standard time in minutes.")] if bad else []


def _create_tasks(ticket):
    rows = ticket.action_payload["tasks"]
    for r in rows:
        Task.objects.create(
            ticket=ticket,
            title=r["title"].strip()[:160],
            description=r.get("description", ""),
            standard_minutes=r["minutes"],
        )
    return {"tasks": len(rows)}


def claim(task, member):
    if not member_services.is_verified(member):  # HF-13
        raise TaskError(_("Only verified members can claim a task."))
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task.pk)
        if task.status != "open":
            raise TaskError(_("This task is already taken."))
        task.status, task.claimed_by, task.claimed_at = "claimed", member, timezone.now()
        task.save(update_fields=["status", "claimed_by", "claimed_at"])
        audit.record(member.number, "task.claimed", task)
        return task


def mark_done(task, member, evidence_text="", evidence_file=None):
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task.pk)
        if task.status != "claimed" or task.claimed_by_id != member.pk:
            raise TaskError(_("Only the member who claimed a task can finish it."))
        if not (evidence_text or "").strip() and evidence_file is None:
            raise TaskError(_("Please add a few words or a file to show that it is done."))
        task.status, task.done_at, task.evidence_text, task.evidence_file = (
            "done",
            timezone.now(),
            evidence_text.strip(),
            evidence_file,
        )
        task.save(update_fields=["status", "done_at", "evidence_text", "evidence_file"])
        audit.record(member.number, "task.done", task)
        if task.kind == "against":
            _finish_against(task)
        return task


def confirm(task, member):
    """The ticket's author confirms a done task. Never one's own task."""
    task.refresh_from_db()
    if task.claimed_by_id == member.pk:
        raise TaskError(_("You cannot confirm your own task."))
    if task.ticket.author_id != member.pk:
        raise TaskError(_("Only the ticket's author can confirm this directly. Or ask one random member."))
    return _confirm(task, member)


def _confirm(task, by):
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task.pk)
        if task.status != "done":
            raise TaskError(_("This task is not waiting for confirmation."))
        entry = _units().record_coordination(
            task.claimed_by,
            task.standard_minutes,
            _("Task: %(title)s") % {"title": task.title},
            ref_type="task",
            ref_id=task.pk,
        )
        task.status, task.confirmed_by, task.confirmed_at, task.paid_entry = "confirmed", by, timezone.now(), entry
        task.save(update_fields=["status", "confirmed_by", "confirmed_at", "paid_entry"])
        audit.record("system", "task.confirmed", task)
        ticket = task.ticket
        if not ticket.tasks.exclude(status="confirmed").exists() and ticket.status == "in_action":
            ticket_services.set_status(ticket, "done", "")
        return task


def request_random_check(task):
    """Ask one random member (a 1-seat draw) to confirm a done task."""
    with transaction.atomic():
        task = Task.objects.select_for_update().get(pk=task.pk)
        if task.status != "done" or task.check_ticket_id:
            raise TaskError(_("This task cannot be sent for a check now."))
        check = briefs._check(
            _("What is the task?"), task.title, [_("Another task"), _("No task")], _("the first sentence")
        )
        t = ticket_services.create_ticket(
            "task_check",
            None,
            _("Check the task: %(title)s") % {"title": task.title},
            brief=_("A member says this task is done: %(title)s. Their evidence: %(evidence)s. Is it done?")
            % {"title": task.title, "evidence": task.evidence_text or _("a file")},
            check=check,
            action_payload={"task_id": task.pk, "members": [task.claimed_by.number], "units": []},
        )
        task.check_ticket = t
        task.save(update_fields=["check_ticket"])
        return t


def _confirm_task(ticket):
    task = Task.objects.get(pk=ticket.action_payload["task_id"])
    _confirm(task, None)
    return {"task": task.pk}


def release_stale(now=None) -> int:
    """A claimed task not done in `claim_timeout_days` is free again."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=get_param("governance.tasks.claim_timeout_days"))
    count = 0
    for task in Task.objects.filter(status="claimed", claimed_at__lte=cutoff):
        task.status, task.claimed_by, task.claimed_at = "open", None, None
        task.save(update_fields=["status", "claimed_by", "claimed_at"])
        audit.record("system", "task.released", task)
        count += 1
    return count


# --- The "against" brief of a vote, written by one random member as a paid task (P07.T02) ---

AGAINST_MINUTES = 60  # OWNER-CHECK: how many paid minutes writing the case against a proposal is worth


def invite_against_brief(referendum):
    """Nobody said no, so one random eligible member is asked to write the case against."""
    from apps.tickets import draw

    ticket = referendum.ticket
    members = draw.eligible(ticket)
    if not members:
        return None
    fp = draw._fingerprint()
    seed = sha256_hex(f"against:{referendum.pk}:{ticket.number}:{fp.hash if fp else draw.NO_FINGERPRINT}")
    chosen = random.Random(int(seed, 16)).choice(members)
    task = Task.objects.create(
        ticket=ticket,
        title=_("Write the case against: %(question)s") % {"question": referendum.question[:100]},
        description=ticket.brief_md,
        standard_minutes=AGAINST_MINUTES,
        status="claimed",
        claimed_by=chosen,
        claimed_at=timezone.now(),
        kind="against",
        referendum_id=referendum.pk,
    )
    notify(
        chosen,
        _("You were drawn to write the case against a proposal for the vote on %(number)s.")
        % {"number": ticket.number},
        f"/tasks/ticket/{ticket.number}/",
        email=True,
    )
    return task


def _finish_against(task):
    from apps.votes.models import Referendum

    r = Referendum.objects.filter(pk=task.referendum_id).first()
    if r is not None and r.status in ("scheduled", "open"):
        r.brief_against_md = task.evidence_text
        r.save(update_fields=["brief_against_md"])
    entry = _units().record_coordination(
        task.claimed_by,
        task.standard_minutes,
        _("Case against %(number)s") % {"number": task.ticket.number},
        ref_type="task",
        ref_id=task.pk,
    )
    task.status, task.confirmed_at, task.paid_entry = "confirmed", timezone.now(), entry
    task.save(update_fields=["status", "confirmed_at", "paid_entry"])


def register():
    """Connect to the tickets and the votes (called when the app starts)."""
    from apps.members import services as ms
    from apps.votes import services as vote_services

    actions.register("give_mandate", _give_mandate)
    actions.register("approve_report", _approve_report)
    actions.register(
        "revoke_mandate",
        _revoke,
        lambda p: [] if p.get("mandate_id") else [_("This ticket does not say what it is about.")],
    )
    actions.register("report_rejected", _report_rejected)
    actions.register("create_tasks", _create_tasks, _validate_tasks, finishes=False)
    actions.register("confirm_task", _confirm_task)
    if _leave_check not in ms.LEAVE_CHECKS:
        ms.LEAVE_CHECKS.append(_leave_check)
    if invite_against_brief not in vote_services.AGAINST_BRIEF_HOOKS:
        vote_services.AGAINST_BRIEF_HOOKS.append(invite_against_brief)
    if _on_approved not in actions.APPROVED_HOOKS:
        actions.APPROVED_HOOKS.append(_on_approved)


def _on_approved(ticket):
    if (ticket.action_payload or {}).get("needs_delegate") and not ticket.action_payload.get("applications_until"):
        open_applications(ticket)
