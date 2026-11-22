import random
import time

import pytest

from apps.catalogue.engine import OfferData, solve

TOL = 1e-9


def offer(id, item, q, l, d=0.0, m=0.0, inputs=()):  # noqa: E741
    return OfferData(id, item, q, l, d, m, list(inputs))


def test_flour_and_bread():
    mill = offer(1, 100, 1, 0.05)
    bread = offer(2, 200, 40, 0.1125, m=(0.30 + 2.00 + 3.00) / 40 * 40 / 40 * 1, inputs=[(100, 24, None)])
    bread.m = (0.30 + 2.00 + 3.00) / 40
    r = solve([mill, bread], {100: {1: 1.0}})
    assert r[2].total == pytest.approx(0.1425, abs=TOL)
    assert r[2].direct == pytest.approx(0.1125, abs=TOL)
    assert r[2].indirect == pytest.approx(0.03, abs=TOL)
    assert r[2].euro == pytest.approx(0.1325, abs=TOL)
    assert r[1].total == pytest.approx(0.05, abs=TOL)


def test_haircut():
    cut = offer(1, 1, 1, 60 / 60, m=15 * 0.02)
    r = solve([cut], {})
    assert r[1].total == pytest.approx(1.0, abs=TOL)
    assert r[1].euro == pytest.approx(0.30, abs=TOL)


def test_chair():
    oil = offer(1, 10, 1, 0.5)
    chair = offer(2, 20, 4, (960 + 60) / 60 / 4, m=(144 + 8 + 1.20) / 4, inputs=[(10, 0.4, None)])
    r = solve([oil, chair], {10: {1: 1.0}})
    assert r[2].total == pytest.approx(4.30, abs=TOL)
    assert r[2].euro == pytest.approx(38.30, abs=TOL)


def test_two_suppliers_share_the_input():
    a = offer(1, 10, 1, 0.04)
    b = offer(2, 10, 1, 0.06)
    user = offer(3, 20, 1, 0.0, inputs=[(10, 1, None)])
    r = solve([a, b, user], {10: {1: 0.5, 2: 0.5}})
    assert r[3].total == pytest.approx(0.05, abs=TOL)


def test_a_preferred_supplier_overrides_the_weights():
    a = offer(1, 10, 1, 0.04)
    b = offer(2, 10, 1, 0.06)
    user = offer(3, 20, 1, 0.0, inputs=[(10, 1, 2)])
    r = solve([a, b, user], {10: {1: 0.5, 2: 0.5}})
    assert r[3].total == pytest.approx(0.06, abs=TOL)


def test_depreciation_enters_the_value():
    saw = offer(1, 1, 1, 0.1, d=0.002)
    assert solve([saw], {})[1].total == pytest.approx(0.102, abs=TOL)


def test_a_loop_is_reported():
    a = offer(1, 10, 1, 1.0, inputs=[(20, 2, None)])  # A needs 2 units of B per unit
    b = offer(2, 20, 1, 1.0, inputs=[(10, 1, None)])  # B needs 1 unit of A per unit
    c = offer(3, 30, 1, 0.5)
    info = {}
    r = solve([a, b, c], {10: {1: 1.0}, 20: {2: 1.0}}, info)
    assert r[1].error == "loop" and r[2].error == "loop"
    assert r[3].error is None and r[3].total == pytest.approx(0.5, abs=TOL)
    assert info["converged"] is False


def test_a_harmless_cycle_still_solves():
    a = offer(1, 10, 1, 1.0, inputs=[(20, 0.1, None)])
    b = offer(2, 20, 1, 1.0, inputs=[(10, 0.1, None)])
    r = solve([a, b], {10: {1: 1.0}, 20: {2: 1.0}})
    assert r[1].error is None and r[1].total == pytest.approx(1.1 / 0.99, abs=1e-9)


def test_missing_weights_are_an_error():
    user = offer(1, 20, 1, 0.0, inputs=[(10, 1, None)])
    with pytest.raises(ValueError):
        solve([user], {})


def test_5000_random_offers_solve_fast():
    rng = random.Random(1)
    n = 5000
    offers = []
    for i in range(n):
        inputs = [(rng.randrange(0, i), rng.random(), None) for _ in range(10)] if i else []
        offers.append(offer(i, i, 10.0, rng.random(), inputs=inputs))
    weights = {i: {i: 1.0} for i in range(n)}
    start = time.perf_counter()
    r = solve(offers, weights)
    assert time.perf_counter() - start < 5
    assert all(x.error is None and x.total >= x.direct for x in r.values())
