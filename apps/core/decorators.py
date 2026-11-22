from allauth.account.decorators import reauthentication_required


def sensitive_action(view=None, **kwargs):
    """Require a login within the last 15 minutes (ACCOUNT_REAUTHENTICATION_TIMEOUT).

    Use it for approving hours, confirming payments, voting, signing, changing bank details
    and holder actions (docs/08 section 3).
    """
    if view is None:
        return reauthentication_required(**kwargs)
    return reauthentication_required(view, **kwargs)
