"""Tell a member something: a note under the bell, and an email when they asked for it or it matters."""

from django.conf import settings
from django.core import mail


def notify(member, text, url="", email=False):
    """Create a notification. Plain text only. Sends an email if `email` is true or the member chose it."""
    from apps.tickets.models import Notification

    note = Notification.objects.create(member=member, text=text[:300], url=url)
    wants_mail = email or member.email_all_notifications
    if wants_mail and not member.deleted and member.status in ("member", "former"):
        link = f"\n\n{settings.SITE_URL}{url}" if url else ""
        mail.send_mail("Unicorn", f"{text}{link}", None, [member.user.email])
    return note
