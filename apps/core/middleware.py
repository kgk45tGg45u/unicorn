"""Small middlewares for the session and the admin (P14.T06)."""

import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils.translation import gettext as _


class IdleSessionMiddleware:
    """A member who has done nothing for 12 hours is logged out. The last activity is kept in the session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            now = time.time()
            last = request.session.get("last_activity")
            if last is not None and now - last > settings.SESSION_IDLE_SECONDS:
                logout(request)
            else:
                request.session["last_activity"] = now
        return self.get_response(request)


def has_passkey(user) -> bool:
    from allauth.mfa.models import Authenticator

    return Authenticator.objects.filter(user=user, type=Authenticator.Type.WEBAUTHN).exists()


class AdminGateMiddleware:
    """Only staff with a passkey open the admin. Django's own login page sends people to the normal login."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        prefix = f"/{settings.ADMIN_PATH}/"
        if request.path.startswith(prefix):
            user = request.user
            if request.path == f"{prefix}login/" or not user.is_authenticated:
                return redirect(f"/accounts/login/?next={prefix}")
            if not user.is_staff or not user.is_active:
                return self._refused(request, _("This page is only for the people who run Unicorn."))
            if not has_passkey(user):
                return self._refused(
                    request,
                    _("Operators need a passkey to open this page. Please add one under My account, Passkeys."),
                )
        return self.get_response(request)

    def _refused(self, request, message):
        body = render_to_string("403.html", {"message": message}, request=request)
        return HttpResponse(body, status=403)
