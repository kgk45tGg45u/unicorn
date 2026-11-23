"""The restore test record and its warning (docs/08 section 6, P14.T09)."""

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

from .models import RestoreTest

OVERDUE_DAYS = 35


def last_ok():
    """The last restore test that worked, or None."""
    return RestoreTest.objects.filter(ok=True).order_by("-ran_at").first()


def overdue(now=None) -> bool:
    now = now or timezone.now()
    last = last_ok()
    return last is None or now - last.ran_at > timedelta(days=OVERDUE_DAYS)


def warn_if_overdue(now=None):
    """If there has been no successful restore test for 35 days, a ticket goes to the elected auditors. Safe twice."""
    from apps.tickets import briefs
    from apps.tickets import services as ticket_services
    from apps.tickets.models import Ticket

    if not overdue(now):
        return None
    if (
        Ticket.objects.filter(type="restore_overdue")
        .exclude(status__in=("done", "rejected", "withdrawn", "expired"))
        .exists()
    ):
        return None
    check = briefs._check(
        _("How many days may pass between two restore tests?"),
        str(OVERDUE_DAYS),
        ["7", "365"],
        _("the first sentence"),
    )
    text = _(
        "No restore test of the backups has worked for %(days)s days. A backup that was never restored may not work "
        "when it is needed. Please ask the operators to run the monthly restore test."
    ) % {"days": OVERDUE_DAYS}
    return ticket_services.create_ticket(
        "restore_overdue", None, _("The backups have not been tested for over a month"), text, brief=text, check=check
    )
