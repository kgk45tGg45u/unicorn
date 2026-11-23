"""The ticket types (docs/05 section 2).

Changing a type's decision method is a referendum matter (docs/05).
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class TicketType:
    key: str
    label: str
    method: str  # none | auto | council | confirmers | panel | referendum | plan | mediation
    action: str | None = None  # what the app does on approval (apps/tickets/actions.py)
    reject_action: str | None = None  # what the app does when the ticket is finally rejected
    confirmers: int | None = None  # seats; None = governance.confirmers.size
    needs_brief: bool = False  # a brief and a check question are required
    creatable: bool = True  # shown in the "New ticket" form (internal types are made by the app)
    unit_scope: bool = False  # the member must name a unit


_T = TicketType

TYPES: dict[str, TicketType] = {
    t.key: t
    for t in [
        _T("question", _("Ask a question"), "none"),
        _T("idea", _("Share an idea"), "none"),
        _T("complaint", _("Make a complaint"), "none"),
        _T("open_unit", _("Open a unit"), "auto", action="open_unit", needs_brief=True, creatable=False),
        _T("close_unit", _("Close a unit"), "council", action="close_unit", unit_scope=True),
        _T("join_forces", _("Join two units"), "council", unit_scope=True),
        _T("council_decision", _("A decision of a working council"), "council", unit_scope=True, creatable=False),
        _T("hours_review", _("Review hours"), "confirmers", action="hours_confirm", needs_brief=True, creatable=False),
        _T(
            "purchase",
            _("Buy something from outside"),
            "auto",
            action="create_payment_requests",
            reject_action="purchase_rejected",
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "benefit_claim",
            _("Claim a benefit"),
            "confirmers",
            action="start_benefit",
            reject_action="benefit_rejected",
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "guarantee_claim",
            _("Claim a guarantee"),
            "confirmers",
            action="start_guarantee",
            reject_action="guarantee_rejected",
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "pension_unable_to_work",
            _("Ask for a pension because of illness"),
            "confirmers",
            action="recognise_unable_to_work",
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "recognised_month",
            _("Recognise a month of care or illness"),
            "confirmers",
            action="record_active_month",
            confirmers=1,
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "parameter_change",
            _("Change a rule"),
            "confirmers",
            action="change_parameter",
            needs_brief=True,
            creatable=False,
        ),
        _T("plan_proposal", _("Propose something for the yearly plan"), "plan"),
        _T(
            "plan_adoption",
            _("Adopt a yearly plan"),
            "none",
            action="adopt_plan",
            reject_action="plan_vote_failed",
            creatable=False,
        ),
        _T("plan_group", _("The planning group"), "none", creatable=False),
        _T("plan_hearing", _("A hearing before a closure in the plan"), "none", creatable=False),
        _T(
            "plan_emergency",
            _("An emergency change of the plan"),
            "confirmers",
            action="apply_emergency",
            confirmers=4,
            creatable=False,
        ),
        _T(
            "flag",
            _("Report something"),
            "confirmers",
            action="flag_remove",
            reject_action="flag_keep",
            creatable=False,
        ),
        _T(
            "flag_contest",
            _("Contest the removal of something"),
            "panel",
            action="flag_keep",
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "mediation",
            _("Ask for mediation"),
            "mediation",
            action="mediation_decided",
            reject_action="mediation_decided",
            needs_brief=True,
            creatable=False,
        ),
        _T("delegate", _("Ask for a delegate"), "confirmers", needs_brief=True),
        _T(
            "delegate_choice",
            _("Choose who carries out a decision"),
            "confirmers",
            action="give_mandate",
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "mandate_report",
            _("Check a delegate's report"),
            "confirmers",
            action="approve_report",
            reject_action="report_rejected",
            confirmers=1,
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "revoke_mandate",
            _("Take a mandate back"),
            "confirmers",
            action="revoke_mandate",
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "task_check",
            _("Check that a task is done"),
            "confirmers",
            action="confirm_task",
            confirmers=1,
            needs_brief=True,
            creatable=False,
        ),
        _T("task_list", _("Make a list of tasks"), "confirmers", action="create_tasks", needs_brief=True),
        _T("poll", _("Ask all members"), "referendum"),
        _T("referendum_request", _("Ask for a vote of all members"), "none"),
        _T(
            "hard_frame_change",
            _("Change the hard frame"),
            "confirmers",
            action="await_release",
            needs_brief=True,
            creatable=False,
        ),
        # Internal types, made by the app for earlier flows.
        _T(
            "verify_licence",
            _("Check a licence"),
            "confirmers",
            action="verify_licence",
            reject_action="reject_licence",
            confirmers=2,
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "one_person_check",
            _("Check the hours of a one-person unit"),
            "confirmers",
            action="hours_confirm",
            confirmers=1,
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "trust_review",
            _("Review an event in a trust rating"),
            "confirmers",
            action="annul_trust_event",
            confirmers=3,
            needs_brief=True,
            creatable=False,
        ),
        _T("audit_failure", _("The books failed an audit"), "confirmers", needs_brief=True, creatable=False),
        _T(
            "post_check_unit",
            _("Review a unit that opened with an amber check"),
            "confirmers",
            reject_action="pause_unit",
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "duplicate_suspected",
            _("Two accounts may belong to one person"),
            "confirmers",
            action="suspend_member",
            needs_brief=True,
            creatable=False,
        ),
        _T(
            "offer_red_check",
            _("Review an offer before it is published"),
            "confirmers",
            action="publish_offer",
            needs_brief=True,
            creatable=False,
        ),
    ]
}

METHODS = ("none", "auto", "council", "confirmers", "panel", "referendum", "plan", "mediation")
SCOPES = ("unit", "union", "local", "all")
STATUSES = (
    "draft",
    "open",
    "confirming",
    "panel",
    "petition",
    "referendum",
    "approved",
    "rejected",
    "in_action",
    "done",
    "withdrawn",
    "expired",
)
FINAL = ("approved", "rejected", "done", "withdrawn", "expired")


def creatable_types():
    return [t for t in TYPES.values() if t.creatable]
