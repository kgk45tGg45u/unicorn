from apps.votes.irv import irv

OPTIONS = ["A", "B", "C"]


def test_a_first_round_majority_wins():
    winner, rounds = irv([["A", "B"], ["A"], ["A", "C"], ["B"], ["C"]], OPTIONS, "seed")
    assert winner == "A" and len(rounds) == 1 and rounds[0]["counts"] == {"A": 3, "B": 1, "C": 1}


def test_the_lowest_goes_out_and_its_votes_move():
    ballots = [["A", "B"]] * 4 + [["B", "A"]] * 3 + [["C", "B"]] * 2
    winner, rounds = irv(ballots, OPTIONS, "seed")
    assert winner == "B" and rounds[0]["eliminated"] == "C"
    assert rounds[1]["counts"] == {"A": 4, "B": 5}


def test_a_tie_at_elimination_is_broken_by_a_seed_anyone_can_repeat():
    ballots = [["A"]] * 3 + [["B", "A"]] * 2 + [["C", "A"]] * 2
    winner, rounds = irv(ballots, OPTIONS, "seed")
    assert winner == "A" and rounds[0].get("tie_broken_by_seed") is True
    again, again_rounds = irv(ballots, OPTIONS, "seed")
    assert again_rounds == rounds


def test_a_tie_is_broken_by_the_first_round_counts_when_they_differ():
    # round 1: A 3, B 4, C 5, D 1. D goes out and its vote moves to A, so A and B tie on 4.
    # A had fewer first-round votes (3 against 4), so A goes out, without any chance involved.
    ballots = [["A"]] * 3 + [["B"]] * 4 + [["C"]] * 5 + [["D", "A"]]
    winner, rounds = irv(ballots, ["A", "B", "C", "D"], "seed")
    assert rounds[0]["eliminated"] == "D" and rounds[1]["eliminated"] == "A"
    assert "tie_broken_by_seed" not in rounds[1] and winner == "C"


def test_ballots_that_rank_only_one_option_run_out():
    ballots = [["A"]] * 3 + [["B"]] * 3 + [["C", "B"]] * 2
    winner, rounds = irv(ballots, OPTIONS, "seed")
    assert winner == "B"
    assert rounds[-1]["counts"] == {"A": 3, "B": 5} and rounds[-1]["exhausted"] == 0
    other, rounds = irv([["A"]] * 3 + [["B"]] * 2 + [["C"]] * 2, OPTIONS, "seed")
    assert other == "A" and rounds[-1]["exhausted"] == 2  # the ballots of the option that went out ran out


def test_no_ballots_means_no_winner():
    assert irv([], OPTIONS, "seed")[0] is None
