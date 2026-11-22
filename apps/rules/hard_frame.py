from dataclasses import dataclass


@dataclass(frozen=True)
class HardFrameRule:
    id: str
    title: str
    text: str


RULES = (
    HardFrameRule(
        id="HF-1",
        title="UNIQ come only from work",
        text="New UNIQ are created only by Fund 2, and only (a) for approved hours of work, and (b) for transfers decided by the plan (pensions, care), which the flat tax covers. Never for euros, donations, or anything else.",
    ),
    HardFrameRule(
        id="HF-2",
        title="Equal pay",
        text="Every approved hour pays 1 UNIQ before tax, for every member, in every country and every kind of work. The only exception is a temporary shortage bonus: at most +25%, for at most 3 months per decision, and only a referendum can switch it on.",
    ),
    HardFrameRule(
        id="HF-3",
        title="Prices are hours",
        text="The price of every good and service is its labour value: the Unicorn hours inside it, direct and indirect. It is computed from recipes and measured hours. It never changes for scarcity, demand or any other reason, and it is fixed at the moment of ordering.",
    ),
    HardFrameRule(
        id="HF-4",
        title="No euro price for UNIQ",
        text="UNIQ are never bought, sold, exchanged, lent for interest or paid out in any currency. The planning rate only compares costs; it is never offered as an exchange.",
    ),
    HardFrameRule(
        id="HF-5",
        title="Personal accounts",
        text="UNIQ move only between a member and the funds: Fund 1, Fund 2 and the member's own retirement account. There are no transfers between members, and units hold no UNIQ.",
    ),
    HardFrameRule(
        id="HF-6",
        title="Fund 1 to Fund 2 only",
        text="All UNIQ spent go to Fund 1. At every period close, Fund 1's balance is cancelled into Fund 2. Nothing flows from Fund 2 to Fund 1.",
    ),
    HardFrameRule(
        id="HF-7",
        title="Open books that cannot be changed",
        text="The books are double-entry, append-only and hash-chained. Every transfer has a written reason, and a fingerprint of the books is published every day. The totals are public; personal data never is.",
    ),
    HardFrameRule(
        id="HF-8",
        title="Never taken away",
        text="Nobody's UNIQ expire or are cancelled, except through the flat tax at the moment of payment and through spending. A member who leaves keeps their UNIQ and can still spend them.",
    ),
    HardFrameRule(
        id="HF-9",
        title="One flat tax",
        text="It is one rate for everyone, between 0% and 68% of every hour. Transfers are paid from it and never printed. The hours of products nobody bought, and of idle shifts, are taken back through it, never left with Fund 1.",
    ),
    HardFrameRule(
        id="HF-10",
        title="Members choose their work",
        text="The app proposes and shows needs. It never assigns, orders, ranks or punishes anyone in matters of work.",
    ),
    HardFrameRule(
        id="HF-11",
        title="The trust rating only limits holding",
        text="It sets only how many euros a member may hold for the trade fund. It never touches work, pay, votes or prices. It is computed from the records only, and each member can see theirs, contest it and get a human review.",
    ),
    HardFrameRule(
        id="HF-12",
        title="The app never moves money",
        text="It shows payment requests, and the payer and the receiver confirm them. It never starts payments and never reads bank accounts.",
    ),
    HardFrameRule(
        id="HF-13",
        title="One person, one account, one vote",
        text="Identity is checked (two vouches and one in-person check) before a member may vote, hold fund euros, confirm, or be drawn.",
    ),
    HardFrameRule(
        id="HF-14",
        title="Privacy",
        text="Personal data is minimal, encrypted, kept apart from the hour accounts (which use member numbers), and deletable. No personal data appears in the public books.",
    ),
    HardFrameRule(
        id="HF-15",
        title="The centre only proposes",
        text='The planning engine, the secretariat, the warning lights and the plan check recommend; people decide. An automatic check may say "nothing against it" or "people must decide", but it never rejects on its own. Only hard-frame rules block.',
    ),
    HardFrameRule(
        id="HF-16",
        title="Decisions follow the tiers",
        text="Every decision is a ticket that records its method, its deciders and its reasons. Defaults change only at their tier (section 3), and the hard frame only by the procedure in section 4.",
    ),
    HardFrameRule(
        id="HF-17",
        title="The law first",
        text="Licensed trades are open only to members with a verified licence; services need insurance; taxes are paid; illegal goods are never offered.",
    ),
    HardFrameRule(id="HF-18", title="Donations earn no UNIQ", text="A donation never creates UNIQ for the giver."),
    HardFrameRule(
        id="HF-19",
        title="Open code, common property",
        text="The code is AGPL-3.0, the network belongs to its members, and nobody can sell it.",
    ),
    HardFrameRule(
        id="HF-20",
        title="Working councils",
        text="Every unit with two or more members has a working council, which approves the unit's hours and decides its production. Hours of such a unit cannot be paid without its council's approval.",
    ),
)
