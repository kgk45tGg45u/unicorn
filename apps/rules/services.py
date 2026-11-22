from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from .models import Parameter, ParameterChange

TIER_ORDER = ["unit", "confirm", "plan", "referendum", "hard"]


def _typed(param_type, value):
    if param_type == "decimal":
        return Decimal(str(value))
    if param_type == "int":
        return int(value)
    if param_type == "bool":
        return bool(value)
    if param_type in ("choice", "text"):
        return str(value)
    return list(value)


def get_param(key):
    """The live, typed value of a default. Raises KeyError for an unknown key."""
    try:
        p = Parameter.objects.get(key=key)
    except Parameter.DoesNotExist:
        raise KeyError(key) from None
    return _typed(p.type, p.value)


def validate_value(*, key, type, value, min_value=None, max_value=None, choices=None):
    """Check a value against its type, bounds and choices. Returns the JSON form to store."""
    bad = ValidationError(_("The value for %(key)s is not allowed.") % {"key": key})
    if type in ("decimal", "int"):
        if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
            raise bad
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise bad from None
        if type == "int" and number != number.to_integral_value():
            raise bad
        if min_value is not None and number < Decimal(str(min_value)):
            raise ValidationError(_("%(key)s may not be lower than %(limit)s.") % {"key": key, "limit": min_value})
        if max_value is not None and number > Decimal(str(max_value)):
            raise ValidationError(_("%(key)s may not be higher than %(limit)s.") % {"key": key, "limit": max_value})
        return int(number) if type == "int" else float(number)
    if type == "bool":
        if not isinstance(value, bool):
            raise bad
        return value
    if type == "choice":
        if value not in (choices or []):
            raise ValidationError(
                _("%(key)s must be one of: %(choices)s.") % {"key": key, "choices": ", ".join(choices or [])}
            )
        return value
    if type == "text":
        if not isinstance(value, str):
            raise bad
        return value
    if type == "list":
        if not isinstance(value, list):
            raise bad
        return value
    raise bad


def set_param(key, value, *, decided_by, decided_tier, reason):
    """Change a default. HF-16: only at the parameter's tier or higher."""
    if decided_tier not in TIER_ORDER:
        raise ValidationError(_("Unknown decision tier."))
    if not reason:
        raise ValidationError(_("A change needs a written reason."))
    with transaction.atomic():
        try:
            p = Parameter.objects.select_for_update().get(key=key)
        except Parameter.DoesNotExist:
            raise KeyError(key) from None
        if TIER_ORDER.index(decided_tier) < TIER_ORDER.index(p.tier):
            raise ValidationError(
                _("This default can only be changed by a decision at tier '%(tier)s' or higher.") % {"tier": p.tier}
            )
        new = validate_value(
            key=key, type=p.type, value=value, min_value=p.min_value, max_value=p.max_value, choices=p.choices
        )
        ParameterChange.objects.create(
            parameter=p,
            old_value=p.value,
            new_value=new,
            decided_by=decided_by,
            decided_tier=decided_tier,
            reason=reason,
        )
        p.value = new
        p.save(update_fields=["value", "updated_at"])
        return p
