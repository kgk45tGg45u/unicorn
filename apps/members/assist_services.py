"""Consents to be helped, and the monthly summary of what a helper did (P13.T10)."""

from datetime import timedelta

from django.core import mail
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import AuditEvent
from apps.rules.services import get_param

from . import services
from .models import AssistConsent, AssistSummary, ContractTemplate, Member

ALLOWED_SCOPES = tuple(key for key, _label in AssistConsent.SCOPES)


class AssistError(ValueError):
    """A plain-words reason why something cannot be done."""


def is_active(consent, now=None) -> bool:
    """Signed (in the app, or on paper with a witness), not revoked and not past its end date."""
    now = now or timezone.now()
    signed = consent.signature_id is not None or (consent.paper_copy_id is not None and consent.witnessed_by_id)
    return bool(signed) and consent.revoked_at is None and consent.valid_until > now


def is_open(consent, now=None) -> bool:
    """Not revoked and not past its end date, even if it is still waiting for a signature."""
    now = now or timezone.now()
    return consent.revoked_at is None and consent.valid_until > now


def consent_for_helper(helper, pk):
    consent = AssistConsent.objects.filter(pk=pk, helper=helper).select_related("member", "helper").first()
    if consent is None or not is_active(consent) or not services.is_verified(consent.member):
        return None
    return consent


def active_consents_of(helper):
    return [c for c in AssistConsent.objects.filter(helper=helper).select_related("member") if is_active(c)]


def open_consents_of(helper):
    return [c for c in AssistConsent.objects.filter(helper=helper).select_related("member") if is_open(c)]


def consents_about(member):
    return [c for c in AssistConsent.objects.filter(member=member).select_related("helper") if is_open(c)]


def start(helper, member, scopes, months=None):
    """The helper writes down who they will help, for what, and until when. The person must still sign."""
    scopes = [s for s in scopes if s in ALLOWED_SCOPES]
    longest = get_param("governance.assist.max_months")
    months = min(int(months or longest), longest)
    if not services.is_verified(helper) or not services.is_verified(member):  # HF-13
        raise AssistError(_("Both the helper and the person helped must be verified members."))
    if helper.pk == member.pk:
        raise AssistError(_("You cannot be your own helper."))
    if not scopes:
        raise AssistError(_("Please tick at least one thing the helper may do."))
    if months < 1:
        raise AssistError(_("Please choose how many months the consent lasts."))
    if len(open_consents_of(helper)) >= get_param("governance.assist.max_assisted_per_helper"):
        raise AssistError(_("A helper can help only a few members at the same time. This limit is full."))
    if any(c.helper_id == helper.pk for c in consents_about(member)):
        raise AssistError(_("You already have a consent from this person."))
    with transaction.atomic():
        consent = AssistConsent.objects.create(
            member=member,
            helper=helper,
            scopes=scopes,
            valid_until=services._add_months(timezone.now(), months),
        )
        audit.record(helper.number, "assist.started", consent, member=member.number, scopes=scopes)
        return consent


def sign_in_app(consent, member):
    """The person helped logged in with their own email code on the helper's device and signs."""
    if member.pk != consent.member_id:
        raise AssistError(_("Only the person who is helped can sign this consent."))
    if not is_open(consent):
        raise AssistError(_("This consent has ended."))
    if consent.signature_id is not None:
        return consent
    template = ContractTemplate.objects.filter(kind="assist_consent", is_current=True).first()
    if template is None:
        raise AssistError(_("The text of the consent is not available yet."))
    with transaction.atomic():
        consent = AssistConsent.objects.select_for_update().get(pk=consent.pk)
        consent.signature = services.sign(
            member, template, "code", {"assist_consent": consent.pk, "helper": consent.helper.number}
        )
        consent.save(update_fields=["signature"])
        audit.record(member.number, "assist.signed", consent, how="app")
        return consent


def attach_paper(consent, helper, uploaded_file):
    """The helper uploads a scan of the signed paper. It is kept as a private file of the person helped."""
    if helper.pk != consent.helper_id or not is_open(consent):
        raise AssistError(_("Only the helper can add the paper, and only while the consent is open."))
    with transaction.atomic():
        consent = AssistConsent.objects.select_for_update().get(pk=consent.pk)
        consent.paper_copy = services.store_private_file(consent.member, uploaded_file, "other")
        consent.save(update_fields=["paper_copy"])
        audit.record(helper.number, "assist.paper_added", consent)
        return consent


def witness_paper(consent, identity_helper):
    """An identity helper who met the person confirms the paper copy."""
    if not services.is_verified(identity_helper) or not identity_helper.is_identity_helper:
        raise AssistError(_("Only an identity helper can confirm a paper consent."))
    if identity_helper.pk in (consent.helper_id, consent.member_id):
        raise AssistError(_("The helper and the person helped cannot confirm their own consent."))
    if consent.paper_copy_id is None or not is_open(consent):
        raise AssistError(_("There is no paper copy to confirm."))
    with transaction.atomic():
        consent = AssistConsent.objects.select_for_update().get(pk=consent.pk)
        consent.witnessed_by = identity_helper
        consent.save(update_fields=["witnessed_by"])
        audit.record(identity_helper.number, "assist.witnessed", consent)
        return consent


def waiting_for_witness(identity_helper):
    rows = AssistConsent.objects.filter(
        paper_copy__isnull=False, witnessed_by__isnull=True, signature__isnull=True, revoked_at__isnull=True
    ).select_related("member", "helper")
    return [
        c
        for c in rows
        if is_open(c) and identity_helper.pk not in (c.helper_id, c.member_id) and identity_helper.is_identity_helper
    ]


def revoke(consent, by):
    """The person helped or the helper can end it at any time; "Acting for" mode stops at once."""
    if by.pk not in (consent.member_id, consent.helper_id):
        raise AssistError(_("Only the person helped or the helper can end this consent."))
    with transaction.atomic():
        consent = AssistConsent.objects.select_for_update().get(pk=consent.pk)
        if consent.revoked_at is None:
            consent.revoked_at = timezone.now()
            consent.save(update_fields=["revoked_at"])
            audit.record(by.number, "assist.revoked", consent)
        return consent


# --- Done for me, and the monthly summary ---


def done_for(member, limit=200):
    """Everything a helper did for this member, newest first."""
    return list(AuditEvent.objects.filter(actor_ref=member.number).exclude(acted_by="").order_by("-id")[:limit])


def _month_start(day):
    return day.replace(day=1)


def summary_lines(member, month):
    end = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    events = AuditEvent.objects.filter(
        actor_ref=member.number, created_at__date__gte=month, created_at__date__lt=end
    ).exclude(acted_by="")
    return [f"{e.created_at:%Y-%m-%d %H:%M} {e.acted_by}: {e.verb}" for e in events.order_by("id")]


def send_monthly_summaries(today=None) -> int:
    """For last month: email each helped member what was done for them, or mark it for paper. Safe to run twice."""
    today = today or timezone.localdate()
    month = _month_start(_month_start(today) - timedelta(days=1))
    end = _month_start(today)
    sent = 0
    people = (
        AuditEvent.objects.filter(created_at__date__gte=month, created_at__date__lt=end)
        .exclude(acted_by="")
        .values_list("actor_ref", flat=True)
        .distinct()
    )
    for number in people:
        member = Member.objects.filter(number=number, deleted=False).first()
        if member is None or AssistSummary.objects.filter(member=member, month=month).exists():
            continue
        lines = summary_lines(member, month)
        address = member.user.email if member.user_id else ""
        if address and "@" in address:
            mail.send_mail(
                _("What was done for you in Unicorn in %(month)s") % {"month": f"{month:%B %Y}"},
                _("A helper did this for you:\n\n%(lines)s\n\nYou can see all of it under My account, Done for me.")
                % {"lines": "\n".join(lines)},
                None,
                [address],
            )
        AssistSummary.objects.create(member=member, month=month, on_paper=not address)
        sent += 1
    return sent


def paper_summaries_for(helper, today=None):
    """Summaries the helper hands over on paper, for members whose consent they hold and who have no email."""
    month = _month_start(_month_start(today or timezone.localdate()) - timedelta(days=1))
    rows = AssistSummary.objects.filter(month=month, on_paper=True, member__assist_consents_received__helper=helper)
    return [(row.member, summary_lines(row.member, month)) for row in rows.distinct().select_related("member")]
