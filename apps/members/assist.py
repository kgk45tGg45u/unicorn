"""Acting for a member without a device: the "Acting for" mode (P13.T10, docs/05 section 1 principle 5).

A helper with the person's written consent can place orders, book services, record hours, open tickets and write
comments for them. Every such action is marked "on behalf of". Some things can never be done for someone else:
voting, sitting as a confirmer, approving hours, holder actions and payments, signing contracts, changing bank
details and deleting the account. Those views carry no `@assist_allowed`, so the middleware refuses them.
"""

from functools import wraps

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import acting

SESSION_KEY = "assist_consent_id"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def assist_allowed(scope):
    """Mark a view as something a helper may do for the person helped, if the consent has this scope."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            return view(*args, **kwargs)

        wrapper.assist_scope = scope
        return wrapper

    return decorator


def assist_exempt(view):
    """Pages of the "Acting for" mode itself (starting and stopping it, and the helper's own list)."""
    view.assist_exempt = True
    return view


def assist_never(view):
    """Pages that show private data and are never opened in "Acting for" mode, even for reading."""
    view.assist_never = True
    return view


def _refused(request, message):
    body = render_to_string("members/assist_refused.html", {"message": message}, request=request)
    return HttpResponse(body, status=403)


class ActingForMiddleware:
    """Place after CurrentMemberMiddleware.

    While a helper acts for a member, `request.member` is the person helped, `request.acting_helper` the helper and
    `request.real_member` the person who is logged in. Outside this mode `acting_helper` is None.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.real_member = request.member
        request.acting_helper = None
        request.acting_consent = None
        token = None
        consent = self._consent(request)
        if consent is not None:
            request.acting_helper = request.real_member
            request.acting_consent = consent
            request.member = consent.member
            token = acting.set_helper(request.real_member)
        try:
            return self.get_response(request)
        finally:
            if token is not None:
                acting.reset(token)

    def _consent(self, request):
        from . import assist_services

        pk = request.session.get(SESSION_KEY) if hasattr(request, "session") else None
        if not pk or request.real_member is None:
            return None
        consent = assist_services.consent_for_helper(request.real_member, pk)
        if consent is None:  # revoked, expired or not the helper's: it stops at once
            request.session.pop(SESSION_KEY, None)
        return consent

    def process_view(self, request, view_func, view_args, view_kwargs):
        consent = request.acting_consent
        if consent is None or getattr(view_func, "assist_exempt", False):
            return None
        if request.path.startswith("/accounts/"):
            return None  # logging out ends the session and the mode with it
        if request.method in SAFE_METHODS:
            if getattr(view_func, "assist_never", False):
                return _refused(request, _("This page shows private data. The person must open it themselves."))
            return None
        scope = getattr(view_func, "assist_scope", None)
        if scope is not None and scope in consent.scopes:
            return None
        if scope is not None:
            return _refused(request, _("The consent does not allow this. The person can give a new consent."))
        return _refused(
            request,
            _(
                "This cannot be done on behalf of someone else. Voting, sitting as a confirmer, approving hours, "
                "money for the trade fund, signing, bank details and deleting an account must be done by the person."
            ),
        )


def stamp_acted_by(sender, instance, **kwargs):
    """A new order, booking, hours entry, ticket or comment made in "Acting for" mode remembers the helper."""
    helper = acting.current_helper()
    if helper is not None and instance._state.adding and instance.acted_by_id is None:
        instance.acted_by = helper


def connect_stamps():
    from django.apps import apps
    from django.db.models.signals import pre_save

    for label in ("market.Order", "market.Booking", "units.HoursEntry", "tickets.Ticket", "tickets.Comment"):
        pre_save.connect(stamp_acted_by, sender=apps.get_model(label), dispatch_uid=f"assist.stamp.{label}")


def now():
    return timezone.now()
