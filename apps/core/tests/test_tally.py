from decimal import Decimal

from apps.core.tally import count


def test_majority_needs_more_yes_than_no():
    assert count(["yes", "yes", "no"], "majority", Decimal("0.5"), 3).approved
    assert not count(["yes", "no"], "majority", Decimal("0.5"), 2).approved


def test_two_thirds_ignores_abstentions():
    assert count(["yes", "yes", "no", "abstain"], "two_thirds", Decimal("0.5"), 4).approved
    assert not count(["yes", "no", "no"], "two_thirds", Decimal("0.5"), 3).approved


def test_consensus_needs_no_objection_and_one_yes():
    assert count(["yes", "abstain"], "consensus", Decimal("0.5"), 2).approved
    assert not count(["yes", "no"], "consensus", Decimal("0.5"), 2).approved
    assert not count(["abstain"], "consensus", Decimal("0.5"), 1).approved


def test_without_the_quorum_nothing_is_approved():
    result = count(["yes"], "majority", Decimal("0.6"), 3)
    assert not result.quorum_met and not result.approved
    assert result.yes == 1 and round(result.turnout, 2) == 0.33


def test_no_votes_is_never_approved():
    result = count([], "majority", Decimal("0"), 3)
    assert not result.approved and not result.quorum_met
