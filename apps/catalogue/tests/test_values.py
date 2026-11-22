import re
from decimal import Decimal
from pathlib import Path

import pytest

from apps.catalogue import services
from apps.catalogue.models import Offer, OfferValueHistory, ValueRun
from apps.units import services as us
from apps.units.tests.conftest import make_member, make_unit

pytestmark = pytest.mark.django_db
D = Decimal


def world():
    m = make_member()
    mill_unit, bakery_unit = make_unit("mill"), make_unit("bakery")
    us.add_first_worker(mill_unit, m)
    us.add_first_worker(bakery_unit, m)
    flour = services.create_item("Flour", "product", "kg")
    bread = services.create_item("Bread", "product", "pc")
    mill = services.create_offer(m, mill_unit, flour, batch_size=D(1), direct_minutes_per_batch=3)  # 0.05 h per kg
    bake = services.create_offer(
        m, bakery_unit, bread, batch_size=D(40), cycle_days=1, setup_minutes=30, direct_minutes_per_batch=240
    )
    services.publish_offer(mill, m)
    services.add_input(m, bake, "Flour", "kg", D(24), "unicorn")
    services.add_input(m, bake, "Salt", "kg", D("0.5"), "buy_outside", euro_price_estimate=D("0.6"))
    services.add_input(m, bake, "Yeast", "kg", D("0.4"), "buy_outside", euro_price_estimate=D(5))
    services.add_input(m, bake, "Oven power", "kwh", D(1), "buy_outside", euro_price_estimate=D(3))
    services.publish_offer(bake, m)
    return m, mill, bake


def test_after_a_recompute_the_bread_offer_shows_0_1425():
    m, mill, bake = world()
    run = services.recompute_values()
    bake.refresh_from_db()
    assert (bake.value_total, bake.value_direct, bake.value_indirect) == (D("0.1425"), D("0.1125"), D("0.0300"))
    assert bake.euro_content == D("0.1325")
    assert run.offers == 2 and run.errors == {} and run.converged
    assert OfferValueHistory.objects.filter(run=run).count() == 2
    assert bake.values_computed_at is not None


def test_preview_equals_the_full_run_for_a_simple_chain():
    m, mill, bake = world()
    services.recompute_values()
    p = services.preview(Offer.objects.get(pk=bake.pk))
    full = Offer.objects.get(pk=bake.pk)
    assert (p.total, p.direct, p.indirect, p.euro) == (
        full.value_total,
        full.value_direct,
        full.value_indirect,
        full.euro_content,
    )


def test_a_loop_sets_value_error_and_keeps_the_old_values():
    m, mill, bake = world()
    services.recompute_values()
    # the mill now needs bread, and the bakery needs flour: a loop that consumes more than it makes
    services.add_input(m, Offer.objects.get(pk=mill.pk), "Bread", "pc", D(2), "unicorn")
    Offer.objects.filter(pk=mill.pk).update(status="active")
    run = services.recompute_values()
    mill.refresh_from_db()
    bake.refresh_from_db()
    assert str(mill.pk) in run.errors and mill.status == "value_error"
    assert mill.value_total == D("0.0500")  # the last good value is kept
    assert bake.value_total == D("0.1425")


def test_a_supplier_that_goes_away_marks_the_user():
    m, mill, bake = world()
    services.recompute_values()
    Offer.objects.filter(pk=mill.pk).update(status="paused")
    run = services.recompute_values()
    bake.refresh_from_db()
    assert run.errors[str(bake.pk)] == "no_supplier" and bake.status == "value_error"


def test_history_is_append_only():
    m, mill, bake = world()
    services.recompute_values()
    row = OfferValueHistory.objects.first()
    with pytest.raises(ValueError):
        row.total = 1
        row.save()
    with pytest.raises(ValueError):
        OfferValueHistory.objects.all().delete()
    assert ValueRun.objects.count() == 1


def test_hf03_price_only_from_engine():
    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"(?:\.|\b)(value_total|value_direct|value_indirect|euro_content)\s*=(?!=)")
    allowed = {root / "catalogue" / "services.py", root / "catalogue" / "models.py"}
    offenders = []
    for path in root.rglob("*.py"):
        if "/tests/" in str(path) or "/migrations/" in str(path) or path in allowed:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(root)}:{number}")
    assert offenders == []
    with pytest.raises(services.CatalogueError):
        m, mill, bake = world()
        services.update_offer(m, bake, value_total=D(1))
