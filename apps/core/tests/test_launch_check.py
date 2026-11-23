"""launch_check (P15.T09): FAIL on an empty database, OK (no FAIL) on a fully set-up one."""

from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core import launch
from apps.units.tests.conftest import make_member

pytestmark = pytest.mark.django_db

IBAN = "DE89370400440532013000"


def by_name(lines):
    return {line.name: line for line in lines}


def run_command():
    out = StringIO()
    try:
        call_command("launch_check", stdout=out)
        code = 0
    except SystemExit as e:
        code = e.code
    return code, out.getvalue()


def test_launch_check_reports_fail_on_an_empty_database():
    lines = by_name(launch.run_all())
    for name in (
        "The democratic defaults",
        "The contracts",
        "The founders",
        "The first plan vote",
        "The trial year",
        "The holders",
        "The ECB exchange rates",
        "Backups and the restore test",
    ):
        assert lines[name].status == launch.FAIL, (name, lines[name])
    code, text = run_command()
    assert code == 1 and "FAIL" in text and "to fix" in text


def set_up_everything(settings, tmp_path, monkeypatch):
    """What the founders' meeting and the operators leave behind."""
    from apps.members.models import InPersonCheck, Member, SiteState
    from apps.plan import services as plan_services
    from apps.rules.services import set_param
    from apps.tradefund import services as fund
    from apps.tradefund.models import FxRate

    call_command("load_defaults", stdout=StringIO())
    call_command("loaddata", "contracts", stdout=StringIO())
    set_param(
        "membership.founders_target",
        3,
        decided_by="T-000001",
        decided_tier="referendum",
        reason="The founders' meeting chose a small start.",
    )
    founders = [make_member(f"f{i}@x.org", f"Founder {i}") for i in range(3)]
    Member.objects.filter(pk__in=[m.pk for m in founders]).update(is_founder=True)
    for m in founders:
        for helper in founders:
            if helper != m:
                InPersonCheck.objects.create(helper=helper, member=m, seen_on=date.today(), town="Leipzig")
    SiteState.objects.update_or_create(pk=1, defaults={"launched_at": timezone.now()})
    plan_services.start_first_plan()
    for m in founders[:2]:
        fund.become_holder(m, "EUR", IBAN)
    FxRate.objects.create(date=timezone.localdate(), currency="USD", per_eur="1.08")
    settings.BACKUP_EXPECTED = True
    settings.BACKUP_RUN_DIR = str(tmp_path)
    (tmp_path / "last_backup").write_text(timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    from apps.core.models import RestoreTest

    RestoreTest.objects.create(backup_date=timezone.localdate(), ok=True)
    monkeypatch.setattr("django.core.checks.run_checks", lambda **kw: [])  # the server settings are not a test matter


def test_launch_check_shows_no_fail_on_a_fully_set_up_database(settings, tmp_path, monkeypatch):
    set_up_everything(settings, tmp_path, monkeypatch)
    lines = launch.run_all()
    failed = [(line.name, line.detail) for line in lines if line.status == launch.FAIL]
    assert failed == []
    named = by_name(lines)
    assert named["The contracts"].status == launch.WARN  # the texts still say DRAFT (the lawyers write them)
    assert named["The founders"].status == launch.OK and named["The holders"].status == launch.OK
    code, text = run_command()
    assert code == 0 and "FAIL" not in text.replace("0 to fix", "")


def test_a_default_that_was_changed_without_a_record_is_a_fail(settings, tmp_path):
    from apps.rules.models import Parameter

    call_command("load_defaults", stdout=StringIO())
    assert by_name(launch.run_all())["The democratic defaults"].status == launch.OK
    Parameter.objects.filter(key="membership.trial_months").update(value=6)  # behind the back of the rules
    line = by_name(launch.run_all())["The democratic defaults"]
    assert line.status == launch.FAIL and "membership.trial_months" in line.detail


def test_a_default_changed_by_a_decision_is_in_order():
    from apps.rules.services import set_param

    call_command("load_defaults", stdout=StringIO())
    set_param("membership.trial_months", 6, decided_by="T-000002", decided_tier="referendum", reason="A vote said so.")
    assert by_name(launch.run_all())["The democratic defaults"].status == launch.OK


def test_a_founder_needs_two_others_who_saw_them():
    from apps.members.models import InPersonCheck, Member
    from apps.rules.services import set_param

    call_command("load_defaults", stdout=StringIO())
    set_param("membership.founders_target", 3, decided_by="T-000001", decided_tier="referendum", reason="Small start.")
    founders = [make_member(f"g{i}@x.org", f"G{i}") for i in range(3)]
    Member.objects.filter(pk__in=[m.pk for m in founders]).update(is_founder=True)
    a, b, c = founders
    InPersonCheck.objects.create(helper=a, member=b, seen_on=date.today(), town="X")
    InPersonCheck.objects.create(
        helper=b, member=b, seen_on=date.today(), town="X"
    )  # checking oneself counts for nothing
    line = by_name(launch.run_all())["The founders"]
    assert line.status == launch.FAIL and "not yet checked" in line.detail


def test_the_rates_may_be_a_weekend_old_but_not_a_week():
    from apps.tradefund.models import FxRate

    assert by_name(launch.run_all())["The ECB exchange rates"].status == launch.FAIL
    FxRate.objects.create(date=timezone.localdate() - timedelta(days=3), currency="USD", per_eur="1.1")
    assert by_name(launch.run_all())["The ECB exchange rates"].status == launch.OK
    FxRate.objects.all().delete()
    FxRate.objects.create(date=timezone.localdate() - timedelta(days=8), currency="USD", per_eur="1.1")
    assert by_name(launch.run_all())["The ECB exchange rates"].status == launch.FAIL


def test_drafts_and_missing_addresses_are_warnings_not_failures(settings):
    settings.SECURITY_CONTACT = ""
    settings.SOURCE_URL = "/third-party/"
    line = by_name(launch.run_all())["The legal pages and contact addresses"]
    assert line.status == launch.WARN and "SOURCE_URL" in line.detail and "SECURITY_CONTACT" in line.detail
    settings.SECURITY_CONTACT = "security@example.org"
    settings.SOURCE_URL = "https://example.org/unicorn"
    assert "SOURCE_URL" not in by_name(launch.run_all())["The legal pages and contact addresses"].detail


def test_a_check_that_breaks_shows_up_as_a_fail_and_hides_nothing(monkeypatch):
    def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(launch, "CHECKS", [broken, launch.check_coordination_unit])
    lines = launch.run_all()
    assert [line.status for line in lines] == [launch.FAIL, launch.OK]
    assert "RuntimeError" in lines[0].detail and "boom" not in lines[0].detail


def test_the_hard_frame_check_passes_in_the_repository():
    assert launch.check_hard_frame_tests().status == launch.OK
