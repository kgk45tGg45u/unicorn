"""The checks behind `manage.py launch_check` (P15.T09). Each check answers OK, WARN or FAIL, and says why.

OK     in order.
WARN   not a blocker, but somebody must look (a text that still says DRAFT, a thing that is not built yet).
FAIL   the founders cannot launch until this is fixed.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from django.conf import settings
from django.utils import timezone

OK, WARN, FAIL = "OK", "WARN", "FAIL"

#: The warnings of `check --deploy` that the owner keeps on purpose (docs/12, P14.T06).
KEPT_DEPLOY_WARNINGS = {"security.W005", "security.W021"}

#: The contracts every member meets. Council rules and mandates are made per unit and per mandate, so they have no
#: single "current" text to look for.  # OWNER-CHECK: should these two be checked per unit and per mandate? (docs/12)
GLOBAL_CONTRACTS = ["membership", "holder_agreement", "assist_consent", "outside_seller"]


@dataclass
class Line:
    status: str
    name: str
    detail: str = ""


def _flatten(tree, prefix=""):
    from apps.rules.management.commands.load_defaults import walk

    return {key: leaf["value"] for key, leaf in walk(tree, prefix)}


def check_defaults():
    from apps.rules.models import Parameter

    name = "The democratic defaults"
    path = Path(settings.BASE_DIR) / "config" / "defaults.yaml"
    wanted = _flatten(yaml.safe_load(path.read_text()))
    live = {p.key: p for p in Parameter.objects.all()}
    if not live:
        return Line(FAIL, name, "not loaded: run `deploy/manage.sh load_defaults` (first_setup.sh does it once)")
    missing = sorted(set(wanted) - set(live))
    if missing:
        return Line(FAIL, name, f"{len(missing)} are missing, for example {missing[0]}")
    changed = []
    for key, value in wanted.items():
        parameter = live[key]
        if parameter.value == value:
            continue
        last = parameter.changes.exclude(decided_by="defaults-file").first()
        if last is None or last.new_value != parameter.value:
            changed.append(key)
    if changed:
        return Line(FAIL, name, f"{len(changed)} differ from the file without a recorded change, e.g. {changed[0]}")
    return Line(OK, name, f"{len(wanted)} loaded, every difference from the file has a recorded change")


def check_contracts():
    from apps.members.models import ContractTemplate

    name = "The contracts"
    missing, drafts = [], []
    for kind in GLOBAL_CONTRACTS:
        current = ContractTemplate.objects.filter(kind=kind, is_current=True).first()
        if current is None:
            missing.append(kind)
        elif "DRAFT" in current.body_md:
            drafts.append(kind)
    if missing:
        return Line(FAIL, name, "no current version of: " + ", ".join(missing))
    if drafts:
        return Line(WARN, name, "still say DRAFT (lawyers must write them): " + ", ".join(drafts))
    return Line(OK, name, "all have a current version")


def check_legal_pages():
    name = "The legal pages and contact addresses"
    problems = []
    for page in sorted((Path(settings.BASE_DIR) / "content" / "legal").glob("*.md")):
        text = page.read_text()
        if "DRAFT" in text or "<to fill in" in text:
            problems.append(f"{page.stem} is a draft")
    source = settings.SOURCE_URL
    if not source or source == "/third-party/":
        problems.append("SOURCE_URL is not the repository's address (HF-19)")
    if not settings.SECURITY_CONTACT:
        problems.append("SECURITY_CONTACT is empty")
    if problems:
        return Line(WARN, name, "; ".join(problems))
    return Line(OK, name, "filled in")


def check_founders():
    from apps.members.models import InPersonCheck, Member
    from apps.rules.services import get_param

    name = "The founders"
    founders = list(Member.objects.filter(is_founder=True, status=Member.MEMBER))
    if not founders:
        return Line(FAIL, name, "none yet: run `deploy/manage.sh bootstrap_founders --emails ...` after the meeting")
    target = get_param("membership.founders_target")
    problems = []
    if len(founders) < target:
        problems.append(f"{len(founders)} of {target} founders are verified")
    unchecked = [
        m.number
        for m in founders
        if InPersonCheck.objects.filter(member=m).exclude(helper=m).values("helper").distinct().count() < 2
    ]
    if unchecked:
        problems.append(f"not yet checked in person by two others: {', '.join(unchecked[:5])}")
    if problems:
        return Line(FAIL, name, "; ".join(problems))
    return Line(OK, name, f"{len(founders)} verified, each checked in person by two others")


def check_coordination_unit():
    from apps.units import services as unit_services
    from apps.units.models import Unit

    name = "The coordination unit"
    try:
        unit_services.coordination_unit()
    except Unit.DoesNotExist:
        return Line(FAIL, name, "does not exist")
    return Line(OK, name, "exists")


def check_starter_services():
    from apps.rules.services import get_param

    name = "The starter services on the needs board"
    try:
        services = get_param("sectors.starter_services")
    except KeyError:
        return Line(FAIL, name, "the list `sectors.starter_services` is not loaded")
    # OWNER-CHECK: nothing in the app shows this list on the needs board yet (docs/12, P15.T09).
    return Line(WARN, name, f"the list of {len(services)} starter services exists, but no page shows it yet")


def check_first_plan():
    from apps.plan.models import PlanPeriod

    name = "The first plan vote"
    if PlanPeriod.objects.filter(referendum__isnull=False).exists():
        return Line(OK, name, "started")
    return Line(FAIL, name, "not started: run `deploy/manage.sh start_first_plan` at the launch")


def check_trial_year():
    from apps.members import services as member_services
    from apps.members.models import SiteState

    name = "The trial year"
    state = SiteState.objects.filter(pk=1).first()
    if state is None or not state.launched_at:
        return Line(FAIL, name, 'Unicorn has not launched: every founder must click "Unicorn launches"')
    if not member_services.in_trial_year():
        return Line(WARN, name, "the trial year is over")
    return Line(OK, name, f"on until {member_services.trial_ends_at():%Y-%m-%d}")


def check_holders():
    from apps.members.models import Signature
    from apps.tradefund.models import Holder

    name = "The holders"
    holders = Holder.objects.filter(status=Holder.ACTIVE).select_related("member")
    signed = [
        h for h in holders if Signature.objects.filter(member=h.member, template__kind="holder_agreement").exists()
    ]
    if len(signed) < 2:
        return Line(FAIL, name, f"{len(signed)} active holder(s) with a signed holder agreement; at least 2 are needed")
    return Line(OK, name, f"{len(signed)} active holders with a signed agreement")


def check_rates():
    from apps.tradefund.models import FxRate

    name = "The ECB exchange rates"
    latest = FxRate.objects.order_by("-date").first()
    if latest is None:
        return Line(FAIL, name, "none fetched yet")
    age = (timezone.localdate() - latest.date).days
    # The ECB publishes on working days only, so a weekend or a holiday leaves the newest rate a few days old.
    if age > 4:
        return Line(FAIL, name, f"the newest rate is from {latest.date}, {age} days ago")
    return Line(OK, name, f"the newest rate is from {latest.date}")


def check_backups():
    from . import health, restore

    name = "Backups and the restore test"
    problems = []
    when = health.backup_time()
    if settings.BACKUP_EXPECTED and (when is None or timezone.now() - when > health.BACKUP_MAX_AGE):
        problems.append("last night's backup is missing")
    if restore.overdue():
        problems.append("no restore test has worked in the last 35 days")
    if problems:
        return Line(FAIL, name, "; ".join(problems))
    if not settings.BACKUP_EXPECTED:
        return Line(WARN, name, "this server does not expect backups (BACKUP_EXPECTED is off); production must")
    return Line(OK, name, "last night's backup exists and a restore test is less than 35 days old")


def check_hard_frame_tests():
    name = "The hard-frame tests"
    script = Path(settings.BASE_DIR) / "scripts" / "hf_coverage.py"
    if not script.exists():
        return Line(WARN, name, "scripts/hf_coverage.py is not on this server (it is a development file)")
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        return Line(FAIL, name, done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "a rule has no test")
    return Line(OK, name, "every rule HF-1 to HF-20 has a test")


def check_deploy_settings():
    from django.core.checks import run_checks

    name = "check --deploy"
    found = [m for m in run_checks(include_deployment_checks=True) if m.id not in KEPT_DEPLOY_WARNINGS]
    if found:
        return Line(FAIL, name, "; ".join(sorted({m.id for m in found})) + " (run `manage.py check --deploy`)")
    return Line(OK, name, "clean (apart from the two warnings the owner keeps, docs/12)")


CHECKS = [
    check_defaults,
    check_contracts,
    check_legal_pages,
    check_founders,
    check_coordination_unit,
    check_starter_services,
    check_first_plan,
    check_trial_year,
    check_holders,
    check_rates,
    check_backups,
    check_hard_frame_tests,
    check_deploy_settings,
]


def run_all():
    lines = []
    for check in CHECKS:
        try:
            lines.append(check())
        except Exception as e:  # a broken check must show up, not hide the others
            lines.append(
                Line(
                    FAIL,
                    check.__name__.removeprefix("check_").replace("_", " "),
                    f"could not be checked: {type(e).__name__}",
                )
            )
    return lines
