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
        return self.get_response(request)
