from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def unread_notifications(context):
    """How many notifications the logged-in member has not read yet."""
    from apps.tickets.models import Notification

    member = getattr(context.get("request"), "member", None)
    if member is None:
        return 0
    return Notification.objects.filter(member=member, read_at__isnull=True).count()


@register.filter
def is_hidden(obj):
    """True while members review a report about this thing: `{% if not obj|is_hidden %}`."""
    from apps.tickets import flags

    target = flags.CLASS_TO_TARGET.get(obj.__class__.__name__)
    return bool(target) and flags.is_hidden(target, obj.pk)
