"""Instant-runoff counting for ranked ballots (docs/05 section 4, P07.T03)."""

import random

from apps.core.hashing import sha256_hex


def irv(ballots: list[list[str]], options: list[str], seed: str):
    """Count ranked ballots. Returns (winner or None, rounds).

    Each round counts every ballot for its highest-ranked option still in the race; a ballot with no option left is
    exhausted. An option with more than half of the non-exhausted ballots wins. Otherwise the option with the fewest
    votes goes out; a tie is broken by the first-round counts, then by a seeded random choice anyone can repeat.
    """
    remaining = list(options)
    first_round: dict[str, int] = {}
    rounds = []
    while remaining:
        counts = {o: 0 for o in remaining}
        exhausted = 0
        for ballot in ballots:
            pick = next((o for o in ballot if o in counts), None)
            if pick is None:
                exhausted += 1
            else:
                counts[pick] += 1
        if not first_round:
            first_round = dict(counts)
        live = sum(counts.values())
        entry = {"counts": dict(counts), "exhausted": exhausted, "eliminated": None}
        rounds.append(entry)
        leader = max(counts, key=lambda o: counts[o])
        if live and counts[leader] * 2 > live:
            return leader, rounds
        if len(remaining) == 1:
            return (remaining[0] if live else None), rounds
        lowest = min(counts.values())
        tied = [o for o in remaining if counts[o] == lowest]
        if len(tied) > 1:
            fewest_first = min(first_round[o] for o in tied)
            tied = [o for o in tied if first_round[o] == fewest_first]
        if len(tied) > 1:
            tied = sorted(tied)
            out = random.Random(int(sha256_hex(seed), 16)).choice(tied)
            entry["tie_broken_by_seed"] = True
        else:
            out = tied[0]
        entry["eliminated"] = out
        remaining.remove(out)
        if not live:
            return None, rounds
    return None, rounds
