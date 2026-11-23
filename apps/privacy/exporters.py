"""What is exported for a member: one declaration per table that holds data about them (P14.T03).

Each entry is (model, [lookups]). A row is exported when the member is the value of any of the lookups. When a new
model keeps personal data about a member, add it here and in `docs/privacy/data_map.md`.
"""

from django.apps import apps
from django.db.models import Q

from . import export

TABLES = [
    ("members.Member", ["pk"]),
    ("members.Signature", ["member"]),
    ("members.PrivateFile", ["owner"]),
    ("members.Vouch", ["voucher", "vouchee"]),
    ("members.InPersonCheck", ["member", "helper"]),
    ("members.Skill", ["member"]),
    ("members.Licence", ["member"]),
    ("members.AssistConsent", ["member", "helper"]),
    ("members.AssistSummary", ["member"]),
    ("ledger.Account", ["member"]),
    ("units.UnitMembership", ["member"]),
    ("units.JoinRequest", ["member"]),
    ("units.CouncilVote", ["member"]),
    ("units.Responsibility", ["member"]),
    ("units.HoursEntry", ["member"]),
    ("units.HoursApproval", ["approver"]),
    ("plan.GroupSeat", ["member"]),
    ("plan.ExpertAdviser", ["member"]),
    ("plan.PlanComment", ["member"]),
    ("market.Order", ["buyer"]),
    ("market.Booking", ["customer"]),
    ("market.StandingOrder", ["member"]),
    ("market.Sale", ["buyer", "seller"]),
    ("market.Review", ["author"]),
    ("market.WaitingListEntry", ["member"]),
    ("tickets.Ticket", ["author"]),
    ("tickets.Comment", ["author"]),
    ("tickets.HelpfulMark", ["member"]),
    ("tickets.Notification", ["member"]),
    ("tickets.Conflict", ["member"]),
    ("tickets.Seat", ["member"]),
    ("tickets.Flag", ["created_by"]),
    ("tickets.MediationMessage", ["author"]),
    ("votes.PetitionSignature", ["member"]),
    ("votes.VoterRecord", ["member"]),
    ("votes.Candidate", ["member"]),
    ("votes.Term", ["member"]),
    ("tasks.MandateApplication", ["member"]),
    ("tasks.Mandate", ["delegate"]),
    ("tasks.Task", ["claimed_by"]),
    ("tradefund.Holder", ["member"]),
    ("tradefund.PaymentRequest", ["payee_member", "confirmer", "confirmed_by_buyer"]),
    ("tradefund.PurchaseRequest", ["requester", "deliver_to_member"]),
    ("tradefund.Donation", ["donor_member"]),
    ("tradefund.BenefitClaim", ["member"]),
    ("tradefund.GuaranteeClaim", ["member"]),
    ("macro.ActiveMonth", ["member"]),
    ("macro.TransferPlan", ["member"]),
    ("macro.Forecast", ["author"]),
    ("macro.PensionRecognition", ["member"]),
    ("outside.SellerProfile", ["member"]),
    ("outside.Invoice", ["seller"]),
    ("bodies.UnionDelegate", ["member"]),
    ("bodies.UnionVote", ["member"]),
    ("bodies.ExpertNomination", ["member"]),
    ("bodies.LocalVolunteer", ["member"]),
    ("bodies.LocalResponsibility", ["member"]),
    ("bodies.ConsumerMembership", ["member"]),
    ("bodies.GuidelineVote", ["member"]),
    ("reputation.ReputationScore", ["member"]),
    ("reputation.Recognition", ["member"]),
    ("reputation.SuggestionLog", ["member"]),
]

# Tables reached through another table (the member's own rows only).
THROUGH = [
    ("ledger.Entry", "account__member"),
    ("ledger.Hold", "account__member"),
    ("market.OrderLine", "order__buyer"),
    ("tradefund.FundEntry", "holder__member"),
    ("tradefund.TrustEvent", "holder__member"),
]


def _table_name(label: str) -> str:
    return label.split(".")[1].lower()


def tables(member) -> dict:
    numbers: dict = {}
    data: dict = {}
    for label, lookups in TABLES:
        model = apps.get_model(label)
        query = Q()
        for lookup in lookups:
            query |= Q(**{lookup: member.pk})
        data[_table_name(label)] = [export.row_of(o, numbers) for o in model.objects.filter(query).order_by("pk")]
    for label, lookup in THROUGH:
        model = apps.get_model(label)
        data[_table_name(label)] = [
            export.row_of(o, numbers) for o in model.objects.filter(**{lookup: member.pk}).order_by("pk")
        ]
    return data


def private_data(member) -> dict:
    """The member's own personal details, in plain text, because they are theirs."""
    from apps.members import crypto, services
    from apps.members.models import PrivateFile

    try:
        details = services.get_private(member)
    except crypto.KeyDestroyed:
        details = {}
    files = []
    for pf in PrivateFile.objects.filter(owner=member):
        try:
            name = crypto.decrypt_for(member, pf.name_enc).decode("utf-8")
        except crypto.KeyDestroyed:
            name = ""
        files.append({"id": pf.pk, "kind": pf.kind, "file_name": name, "size": pf.size})
    return {"private_data": [dict(details)] if details else [], "private_files": files}


def account(member) -> dict:
    """Login data: the email address and the passkeys (their names, never their secrets)."""
    from allauth.account.models import EmailAddress
    from allauth.mfa.models import Authenticator

    user = member.user
    return {
        "login": [{"email": user.email, "date_joined": export.plain(user.date_joined)}],
        "email_addresses": [
            {"email": e.email, "verified": e.verified, "primary": e.primary}
            for e in EmailAddress.objects.filter(user=user)
        ],
        "authenticators": [
            {"type": a.type, "created_at": export.plain(a.created_at)} for a in Authenticator.objects.filter(user=user)
        ],
    }


def audit_events(member) -> dict:
    from apps.core.models import AuditEvent

    rows = AuditEvent.objects.filter(actor_ref=member.number).order_by("pk")
    return {"audit_events": [export.row_of(o, {}) for o in rows]}


def register_all():
    for fn in (tables, private_data, account, audit_events):
        export.register(fn)
