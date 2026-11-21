# 0. What Unicorn is for

*Sources: Bijan Sabbagh, "Unicorn: A Political Economic Model Based on Socialism", cited as "book p. N"; the owner's decisions of October and November 2026 (docs/11_decisions.md); the simulations in `../Unicorn-simulation`.*

## The problem the book answers

- In capitalism, the people who work produce all the value, but part of every working day goes to the owners of the means of production (book pp. 1–5, 35–37).
- Prices hide this. A price is one number in which profit, rent, interest and scarcity are mixed, so nobody can see how much work a thing really took (book p. 114).
- The planned economies of the 20th century failed for reasons the book lists, and the app must avoid each of them:
  - their data was slow and old;
  - units cheated with their numbers to get more resources;
  - plans came from people far from production;
  - workers' unions were shut out;
  - the state punished people instead of convincing them (book pp. 14–15, 124–126, 144–145).
- Hayek's objection stands: no small group of planners can know what millions of people know (book pp. 14, 69, 146). So the plan must be made by everyone, with the knowledge everyone has.

## The answer: Unicorn

**Unicorn is a computer system that all members can use, at the front line of production and consumption** (book pp. 58, 77). It is not the economy itself; it only shows the economic life of its members and does the arithmetic (book p. 59):

1. **Every hour of work earns one UNIQ, the same for everyone.** Effort, technology and the kind of work do not change this (book pp. 39–40, 72–75). Studying is work too (book p. 74).
2. **Everything costs the hours inside it.** A product's price is the hours worked on it directly, plus the hours inside its inputs and tools. The input-output table computes these hours (book pp. 38–47). Nobody sets a price, and no price moves because something is scarce or wanted (owner, 2026-11-21: "no changing price anywhere").
3. **UNIQ do not circulate.** They are paid out by Fund 2 for hours worked. When a member buys something, the UNIQ go to Fund 1, and at the end of each period Fund 1's balance is cancelled. UNIQ are like a theatre ticket, not like money (book pp. 40, 57–58).
4. **Units do not pay each other.** A bakery gets its flour from a mill through orders in Unicorn, without UNIQ changing hands. Only final buyers pay (book pp. 60–61, 63).
5. **Part of every hour goes to everyone** through one flat tax. It pays for social services, for building tools and workplaces, for the work that earns euros, and for people who cannot work (book pp. 84–88, 94–95).
6. **Workers decide.** Each unit's working council records and approves its hours and decides its production. Related councils form unions. The computer only proposes; people decide (book pp. 139–141, 147).
7. **Everyone can ask, criticise and propose through tickets.** Tickets cover opening and closing units, approving each other's requests, mediation, the plan, and the rules themselves. Answers are checked by randomly chosen members (book pp. 69–71, 79).

## How Unicorn starts: inside capitalism

The book describes Unicorn after a change of the whole economy. The owner's question for this app is different: **can Unicorn start small inside capitalism and grow until its members are independent of capitalist jobs?** The simulations (docs/02_simulation_results.md) say yes, under conditions:

- 25 founders run a trial year, then others join by word of mouth.
- Members keep their capitalist jobs at first, for rent and basic needs, and give their free time to Unicorn.
- They work with what they already own (home, kitchen, car, computer, tools). These things are free inputs: only Unicorn working hours have a price.
- Unicorn starts as a services network: care, teaching, repairs, IT, personal services, sport and culture.
- Some of its work is sold to outside customers for euros. The euros buy what Unicorn cannot yet make: first tools, then materials, then members' basic bills (rent, insurance), so that members can leave their jobs.
- As Unicorn owns more tools, new trades open: farms, food workshops, energy, furniture, clothes, health care, and in the end homes.

## The owner's four goals

Every run of the simulation, and every plan of the real Unicorn, is measured against these four goals (owner, 2026-10-08):

| Goal | Meaning |
|---|---|
| **Attractive** | An hour of work in Unicorn buys more than an hour of the member's capitalist job |
| **Growing** | Membership grows every year (until most people who might join have joined) |
| **Independent** | Within about 20 years, at least half of the members can live without a capitalist job |
| **Stable** | Members get what they order; the euro fund never runs dry; nobody is worse off on basic needs than without Unicorn; unspent UNIQ do not pile up |

## What the app is

- A **marketplace** where members order goods (made after the order), book services, and see each price split into hours.
- An **input-output table** that every unit fills in for its own products and services, and that computes all prices and orders all inputs.
- A **ticketing system** in which members decide everything, with random confirmers, panels, referendums and delegates.
- **Working councils** and **unions**, with their rules, rotation and records.
- The **books**: UNIQ accounts, Fund 1 and Fund 2, the flat tax, the euro trade fund, all open for everyone to check.
- A **planning engine** that proposes the yearly plan, checks requests against it, and shows warning lights.
- A **needs board** that shows what others need, so that members can start making it.

## What the app is not

- **Not a boss.** It never assigns work, orders anyone to work, ranks workers or punishes them (HF-10).
- **Not a bank.** It never holds, moves or exchanges money, and UNIQ are never sold for euros (HF-4, HF-12).
- **Not a central planner.** The engine proposes; councils, confirmers and votes decide (HF-15).
- **Not a blockchain.** The books are an ordinary database whose records are chained so that nothing can be changed unseen (HF-7, legal reasons in `../Unicorn-simulation/docs/real_world/4_legal_frame.md`).
- **Not finished.** Everything outside the hard frame is a default that members can change (docs/01_hard_frame_and_defaults.md).

## The legal frame in one paragraph

Unicorn is fully horizontal: no bank, cooperative or company sits on top (owner, 2026-11-21). A registered association (e.V.) acts only as a **post box**: it holds no money, sells nothing and acts only on members' votes. Every account holder becomes a member by signing one digital contract, which includes the statute, the trust agreement, the tax consent, the privacy notice and the rating rules. Deleting the account ends the membership. Euros stay in members' own bank accounts as parts of the trade fund. Members sell to outsiders in their own name. Taxes are paid as the law requires, after a binding ruling. The details and the open lawyer questions are in `../Unicorn-simulation/docs/real_world/4_legal_frame.md` and docs/12_open_questions.md.
