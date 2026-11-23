from datetime import timedelta

from django.utils import timezone

from .models import Member


class CurrentMemberMiddleware:
    """Set request.member to the logged-in user's Member, or None.

    Views and templates use request.member, never request.user.member.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.member = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            request.member = Member.objects.filter(user=user, deleted=False).first()
            if request.member is not None:
                from apps.core import logging as unicorn_logging

                unicorn_logging.set_member(request.member.number)
        return self.get_response(request)


class LastActiveMiddleware:
    """Set Member.last_active_at, at most once an hour. Place it after CurrentMemberMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        member = getattr(request, "member", None)
        if member is not None:
            now = timezone.now()
            if member.last_active_at is None or now - member.last_active_at >= timedelta(hours=1):
                Member.objects.filter(pk=member.pk).update(last_active_at=now)
                member.last_active_at = now
        return self.get_response(request)
