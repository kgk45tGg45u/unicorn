from apps.plan.check import CheckPoint, CheckResult, check


def test_stub_is_green():
    assert check({"type": "open_unit"}).color == "green"


def test_worst_colour_wins():
    assert CheckResult([CheckPoint("green", "a"), CheckPoint("amber", "b")]).color == "amber"
    assert CheckResult([CheckPoint("amber", "b"), CheckPoint("red", "c")]).color == "red"
