from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
import yaml
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.rules.management.commands.load_defaults import walk
from apps.rules.models import Parameter, ParameterChange
from apps.rules.services import get_param, set_param

pytestmark = pytest.mark.django_db


@pytest.fixture
def loaded():
    call_command("load_defaults", stdout=StringIO())


def test_loading_creates_one_parameter_per_leaf(loaded):
    tree = yaml.safe_load((Path(settings.BASE_DIR) / "config" / "defaults.yaml").read_text())
    assert Parameter.objects.count() == len(list(walk(tree)))
    assert ParameterChange.objects.filter(decided_by="defaults-file").count() == Parameter.objects.count()


def test_get_param_typed(loaded):
    assert get_param("governance.confirmers.size") == 4
    assert get_param("economy.flat_tax.max") == Decimal("0.68")
    with pytest.raises(KeyError):
        get_param("no.such.key")


def test_set_param_above_max_raises(loaded):
    with pytest.raises(ValidationError):
        set_param("economy.flat_tax.fixed_rate", "0.9", decided_by="T-1", decided_tier="plan", reason="x")


def test_set_param_with_too_low_tier_raises(loaded):
    with pytest.raises(ValidationError):
        set_param("economy.flat_tax.fixed_rate", "0.4", decided_by="T-1", decided_tier="confirm", reason="x")


def test_set_param_at_tier_works_and_is_logged(loaded):
    set_param("economy.flat_tax.fixed_rate", "0.4", decided_by="T-1", decided_tier="plan", reason="members decided")
    assert get_param("economy.flat_tax.fixed_rate") == Decimal("0.4")
    assert ParameterChange.objects.filter(decided_by="T-1").count() == 1


def test_changed_value_survives_load_defaults(loaded):
    set_param("economy.flat_tax.fixed_rate", "0.4", decided_by="T-1", decided_tier="plan", reason="members decided")
    call_command("load_defaults", stdout=StringIO())
    assert get_param("economy.flat_tax.fixed_rate") == Decimal("0.4")


def test_broken_leaf_is_reported(tmp_path, settings, loaded):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "defaults.yaml").write_text(
        "a:\n  b: {value: 5, type: int, max: 3, tier: plan, source: x, help: y}\n"
    )
    settings.BASE_DIR = tmp_path
    with pytest.raises(CommandError, match="a.b"):
        call_command("load_defaults", stdout=StringIO())


def test_parameter_change_is_append_only(loaded):
    change = ParameterChange.objects.first()
    with pytest.raises(ValueError):
        change.delete()
