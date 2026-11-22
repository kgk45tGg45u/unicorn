"""A council's own rules: the optional custom internal contract (docs/05 section 6)."""

import re
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.members import services as member_services
from apps.members.models import ContractTemplate, Signature
from apps.rules.services import get_param

from .models import CouncilRules


class RulesError(ValueError):
    pass


def current(unit):
    return CouncilRules.objects.filter(unit=unit).order_by("-version").first()


def _pay_words(text: str) -> bool:
    low = text.lower()
    return bool(
        re.search(r"\bpay\b|\bpaid\b|\bpays\b", low) and ("bonus" in low or "extra uniq" in low or "per hour" in low)
    )


def validate_clauses(text) -> list[str]:
    """Refuse clauses that try to break the hard frame. A simple word check; people decide the rest through flags."""
    problems = []
    if _pay_words(text or ""):
        problems.append(_("Clauses cannot change pay: every hour pays the same (HF-2)"))
    return problems


def _body(rules) -> str:
    return (
        f"# {_('Council rules of')} {rules.unit.name}, {_('version')} {rules.version}\n\n"
        f"- {_('Decision rule')}: {rules.decision_rule}\n"
        f"- {_('Quorum')}: {rules.quorum}\n"
        f"- {_('Days a vote stays open')}: {rules.vote_days}\n"
        f"- {_('Rotation of the responsible (months)')}: {rules.rotation_months}\n"
        f"- {_('Hours approval')}: {rules.hours_approval}\n"
        f"- {_('Admission of new workers')}: {rules.admission}\n\n"
        f"{rules.clauses_md}\n"
    )


def _create(unit, version, values, adopted_by=None):
    rules = CouncilRules.objects.create(
        unit=unit, version=version, adopted_at=timezone.now(), adopted_by=adopted_by, **values
    )
    last = ContractTemplate.objects.filter(kind="council_rules").order_by("-version").first()
    rules.template = ContractTemplate.objects.create(
        kind="council_rules",
        version=(last.version + 1) if last else 1,
        title=f"Council rules of {unit.name}, version {version}",
        body_md=_body(rules),
        valid_from=rules.adopted_at,
    )
    rules.save(update_fields=["template"])
    audit.record("system", "council_rules.adopted", rules, unit=unit.pk, version=version)
    return rules


def create_default(unit):
    """Version 1, from the `governance.council.*` defaults. Safe to call twice."""
    with transaction.atomic():
        existing = current(unit)
        if existing:
            return existing
        values = {
            "decision_rule": get_param("governance.council.decision_rule"),
            "quorum": Decimal(str(get_param("governance.council.quorum"))),
            "vote_days": get_param("governance.council.vote_days"),
            "rotation_months": get_param("governance.council.rotation_months"),
            "hours_approval": get_param("governance.council.hours_approval"),
            "admission": get_param("governance.council.admission"),
            "clauses_md": "",
        }
        return _create(unit, 1, values)


FIELDS = ("decision_rule", "quorum", "vote_days", "rotation_months", "hours_approval", "admission", "clauses_md")


def new_version(unit, values, decision):
    """The next version. Only an approved council decision can create it."""
    if decision is None or decision.status != "approved" or decision.unit_id != unit.pk:
        raise RulesError(_("New rules need an approved council decision."))
    problems = validate_clauses(values.get("clauses_md", ""))
    if problems:
        raise RulesError(problems[0])
    with transaction.atomic():
        old = current(unit)
        merged = {f: getattr(old, f) for f in FIELDS}
        merged.update({k: v for k, v in values.items() if k in FIELDS})
        merged["quorum"] = Decimal(str(merged["quorum"]))
        return _create(unit, old.version + 1, merged, adopted_by=decision)


def sign_current(member, unit, method="click"):
    from .services import is_worker

    rules = current(unit)
    if rules is None or not is_worker(member, unit):
        raise RulesError(_("Only workers of the unit can sign its rules."))
    already = Signature.objects.filter(template=rules.template, member=member).exists()
    if already:
        return None
    return member_services.sign(member, rules.template, method, {"unit": unit.pk, "version": rules.version})


def signers(unit):
    """(signed, not_signed): lists of members who have and have not signed the current version."""
    from .services import workers

    rules = current(unit)
    signed_ids = set(Signature.objects.filter(template=rules.template).values_list("member_id", flat=True))
    people = [w.member for w in workers(unit)]
    return [m for m in people if m.pk in signed_ids], [m for m in people if m.pk not in signed_ids]
