"""Who is next in a rotation (P03.T05, P13.T01): the one who has held the role for the fewest days."""


def next_in_rotation(candidates, days_held, declined=()):
    """Pick the next member.

    `candidates` is a list of (member, joined_at) pairs, `days_held` a function from a member to the days they have
    held the role, and `declined` the ids of members who said no this turn. The fewest days win; a tie goes to the
    earliest `joined_at`, then to the lowest id. Returns None when nobody is left.
    """
    skip = set(declined)
    left = [(m, joined) for m, joined in candidates if m.pk not in skip]
    if not left:
        return None
    left.sort(key=lambda pair: (days_held(pair[0]), pair[1], pair[0].pk))
    return left[0][0]
