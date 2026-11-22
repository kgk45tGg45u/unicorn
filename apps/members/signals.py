from allauth.account.signals import user_logged_in
from django.core import mail
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext as _


@receiver(user_logged_in)
def send_login_notice(sender, request, user, **kwargs):
    """Tell the member about every new login. No IP address is stored or sent."""
    when = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    mail.send_mail(
        _("New login to your Unicorn account"),
        _(
            "There was a new login to your Unicorn account on %(when)s.\n\n"
            "If this was you, you do not need to do anything.\n"
            "If this was not you, please log in, remove your passkeys and tell the people who run Unicorn."
        )
        % {"when": when},
        None,
        [user.email],
    )
