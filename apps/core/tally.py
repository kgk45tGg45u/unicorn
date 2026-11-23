"""Counting votes the same way everywhere: working councils, unions and consumers' councils (P03.T04, P13.T01)."""

from dataclasses import dataclass
from fractions import Fraction

RULES = ("majority", "two_thirds", "consensus")


@dataclass(frozen=True)
class TallyResult:
    approved: bool
    quorum_met: bool
    yes: int
    no: int
    abstain: int
    turnout: float  # share of the people who may vote that did vote


def count(votes, rule, quorum, size) -> TallyResult:
    """Count "yes", "no" and "abstain" votes.

    `size` is the number of people who may vote and `quorum` the share of them that must vote. Without the quorum
    nothing is approved. Majority needs more yes than no; two thirds needs two thirds of the yes and no votes;
    consensus needs at least one yes and no "no".
    """
    votes = list(votes)
    yes, no, abstain = votes.count("yes"), votes.count("no"), votes.count("abstain")
    turnout = (len(votes) / size) if size else 0.0
    quorum_met = bool(votes) and Fraction(len(votes)) >= Fraction(str(quorum)) * size
    if not quorum_met:
        approved = False
    elif rule == "majority":
        approved = yes > no
    elif rule == "two_thirds":
        approved = yes + no > 0 and Fraction(yes, yes + no) >= Fraction(2, 3)
    else:
        approved = no == 0 and yes >= 1
    return TallyResult(approved, quorum_met, yes, no, abstain, turnout)
