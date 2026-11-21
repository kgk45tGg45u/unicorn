# 5. Governance: tickets, confirmers, votes, councils and the plan

*Book pp. 69–71 and 79 (the ticketing system), pp. 99–105 (strategic planning), pp. 135–147 (political structure). Owner, 2026-11-21: "an app built with the Verein and a horizontal ticketing system that decides about everything … opening and closing businesses, approving each other's actions and requests … the working council of each production unit approves the working hours. The plan decides which things should be invested in … and has a period … created by the public using the ticketing system."*

## 1. Principles

1. **Everything is a ticket.** Every request, proposal, complaint, flag, decision and vote starts as a ticket and keeps its whole history: who asked, who decided, how, and why (HF-16).
2. **Horizontal.** No member, council, union or computer gives orders to another. Councils decide their own unit; members decide together what concerns everyone.
3. **The centre only proposes** (HF-15). The plan check, the secretariat and the warning lights inform; people decide.
4. **Deciding is work.** Time spent on councils, reviews, panels and the plan is paid like any other hour, from the social share (book p. 140), so that governance is not only for people with free time.
5. **Anyone can take part without a device.** A local helper may act for a member with written consent; every such action is marked "on behalf of" (book p. 68).

## 2. Tickets

**Every ticket has:**
- a number (T-000123), a type, a title and a text;
- an author and a **scope**: one unit, one union, one local area, or all of Unicorn;
- a **brief**: at most 500 words written for the people who will decide;
- a **check question**: one multiple-choice question about a key fact of the brief, for random confirmers;
- the result of the **plan check**, where the type needs one (green, amber or red, with reasons in plain words);
- its **decision method**, its status, its comments, and its **action**: what the app does when the ticket is approved.

**Statuses:** `draft` → `open` → (`confirming` → `panel` → `petition` → `referendum`) → `approved` or `rejected` → `in_action` → `done`. A ticket can also end as `withdrawn` or `expired`.

**Types and their default decision methods.** The table is kept in code (`apps/tickets/types.py`, task P06.T01); changing a type's decision method is a referendum matter:

| Type | Decided by | Action on approval |
|---|---|---|
| `question` / `idea` / `complaint` | nobody: answered and discussed | none |
| `open_unit` | automatic if the plan check is green; then random confirmers check it afterwards (amber) or before (red) | open the unit |
| `close_unit` | the unit's own council; or the plan; or a referendum | close the unit after its orders are done |
| `join_forces` | the councils of both units | merge the units, or share offers |
| `council_decision` | the unit's council, under its rules | record the decision (production affairs, admissions, rules) |
| `hours_review` | random confirmers (plausibility notices for units of one person) | confirm, or correct with a written reason |
| `purchase` | automatic up to €50 if the plan check is green; random confirmers up to €2,000; above that it must be in the plan or go to a referendum | create payment requests (docs/07) |
| `benefit_claim` / `guarantee_claim` / `pension_unable_to_work` | random confirmers | start the fund's payments or the transfer |
| `parameter_change` | the tier of that parameter (docs/01, section 3) | change the parameter |
| `plan_proposal` | goes into the yearly plan process (section 8) | none until a plan includes it |
| `flag` | random confirmers | hide, correct or keep the flagged thing; tell its author why |
| `mediation` | three mediators drawn from volunteers; if they find no agreement, a panel of 12 | record the agreement or the decision |
| `delegate` | see section 5 | give a mandate |
| `task_list` | the ticket's deciders | create tasks anyone can take (section 5) |
| `poll` | all members, without binding effect | none |
| `referendum_request` | a petition (section 4) | start the referendum |
| `hard_frame_change` | docs/01, section 4 | a new release |

**The secretariat** sends each ticket to the right deciders:
- unit scope → the unit's council;
- a trade → that trade's union (to advise);
- an area → that local council;
- everything else → random confirmers.

It also **suggests** members who might answer a question well, from their reputation (section 11). A suggestion is only a notification; the routing rules are public and are themselves defaults.

**Discussion.** Every ticket has threaded comments. Large topics (the plan, rules) get a forum page. Comments can be marked helpful.

## 3. Random confirmers, panels and petitions

**This is the default way members approve each other's actions** (owner, 2026-11-21: "by default up to 4 random members can confirm … by reading about the topic beforehand"; and on the same day: all 4 must say yes).

**Who can be drawn.** Active members whose identity is checked (HF-13), and who meet all of these:
- members for at least 3 months (founders exempt in the first year);
- not the author;
- not a worker of a unit the ticket concerns;
- not already seated on this ticket;
- drawn fewer than 4 times this month;
- not on a break (a member may pause being drawn for up to 3 months a year);
- for local tickets, living in that area.

A member can declare a conflict of interest on a ticket and is replaced.

**A draw anyone can check.**
1. The eligible members' numbers are sorted.
2. `seed = SHA-256(ticket number : round : draw number : the public book fingerprint of the previous day)`.
3. `random.Random(int(seed, 16)).sample(eligible, k)`.
4. The app stores the seed, the fingerprint date, the number of eligible members and a hash of their sorted list.

An auditor can repeat the draw exactly.

**The confirmers' steps.**
1. Four members are drawn and notified.
2. Each opens the brief, then answers the check question. A wrong answer shows the relevant part of the brief again; after a second wrong answer the seat is replaced.
3. Each answers **yes** or **no** within 72 hours. A "no" needs a short reason.
4. A seat without an answer after 72 hours is redrawn, at most twice. Reminders go out 24 hours before the deadline.
5. **All four say yes → approved.**
6. **Any single "no" → a panel of 12** new random members. They follow the same steps within 5 days; **7 or more "yes" → approved**, otherwise rejected.
7. **After the panel**, any member may start a **petition** within 14 days. If it gathers signatures from 2% of active members (at least 5) within 14 days, the question goes to a **referendum**, whose result is final for that ticket.
8. **Every seat that answers is paid** `governance.confirmers.review_minutes` (30 minutes; panels 45) as approved hours of the coordination unit.

## 4. Referendums

- **Started by:** a petition (above), the plan process, a hard-frame change, or a rule that requires one.
- **Ballot:** yes/no, or a ranked choice for plan variants (instant runoff).
- **Duration:** 14 days (21 for the hard frame).
- **Counts:** a quorum of 20% of active verified members must vote (abstentions count for the quorum). A simple majority of valid votes decides; for the hard frame, two thirds and a quorum of 25%.
- **Secret ballot:**
  - a `Ballot` row holds the choice and a receipt code, but no member;
  - a separate `VoterRecord` row says only that the member voted (and on which day);
  - each member gets their receipt code and can check that their ballot was counted.
- **The brief** has three parts: the proposal; the arguments for and against, written by the proposer and by the people who said no (or by a random member if none did); and the forecast, if any.
- **Results** are published at once with all counts.

## 5. Getting things done: tickets tied to tasks

The owner: *"tickets that are related to tasks, and confirmation leads to the thing getting done"*; *"handling the implementation of the decision by delegating power for only that decision from the public to someone, or just everyone does it collectively."*

1. **Automatic actions.** Many tickets carry an action the app performs on approval: opening a unit, changing a parameter, creating payment requests, starting a transfer. It runs in the same database transaction that records the approval, and its result is written on the ticket.
2. **A delegate for one decision.** When the work needs one person (signing a contract with a landlord, buying a machine at a fair, speaking for Unicorn at a meeting):
   - The ticket asks for volunteers for 7 days.
   - If one volunteer comes forward, the ticket's confirmers approve them (all yes, as usual). If several do, the confirmers rank them, and the first in the ranking is chosen.
   - The delegate gets a **mandate** stating:
     - the scope (only this decision);
     - the powers (for example: may sign, may spend up to €X through a payment request, may represent);
     - the deadline (at most 90 days);
     - the duty to report.
   - The mandate ends by itself when the task is confirmed done or the deadline passes. It can be withdrawn by the same confirmers, or by a petition. Hours spent on it are paid as coordination hours, with the report as evidence.
3. **Everyone together.** When many people can help (cleaning a space, collecting signatures, testing a recipe):
   - The ticket becomes a **task list**. Anyone can claim a task, mark it done and add evidence.
   - Each task is confirmed by one random member or by the ticket's author.
   - Hours are paid on confirmation, at the task's standard time, or at the time recorded and approved.
   - A claimed task that is not done in 7 days is free again.
4. **Done.** The ticket is `done` when its action has run, or its mandate or all its tasks are confirmed.

## 6. Working councils

**The owner's rule (2026-11-21):** decisions about the production affairs of a unit with more than one person belong to the working council of that unit, and the council approves the working hours (HF-20).

- **Members.** By default, every worker of the unit is in its council (a general assembly; book p. 139: councils may be general assemblies, hierarchies or unions). The council's own rules may choose a smaller elected council.
- **Its own rules: the optional custom internal contract.** When the second member joins, the unit gets the default council rules. The council may change them by its own decision rule, and every worker signs the current version in the app. Rules a council can set:

  | Rule | Default |
  |---|---|
  | decision rule | majority of the votes cast |
  | quorum | half of the council |
  | how long a vote stays open | 3 days |
  | rotation of the responsible | every 6 months |
  | hours approval | any other council member approves (never one's own hours) |
  | admission of new workers | the council approves |
  | free clauses | anything else the workers agree, in plain text |

  The rules cannot break the hard frame. For example, a clause that pays some workers more is void (HF-2).
- **The responsible.** One member holds the council's responsibility at a time (book p. 139: by rotation or by vote):
  - **Duties:** keeps the unit's profile, offers and recipes up to date; receives proposals and messages from other bodies; opens council decisions; speaks for the unit.
  - **Rotation:** every 6 months the role passes to the worker who has held it least, by default; a worker may decline.
  - **Not a boss:** the responsible decides nothing alone that the rules give to the council.
- **Decisions.** Production matters are `council_decision` tickets: what to make, batch sizes, advance share, weekly production, shifts, outside prices, admissions, recipe changes. Hours are approved on the hours page, one entry at a time or in batches (docs/06, section 3).
- **A one-person unit** has no council. Its member decides alone, and its hours are approved automatically, subject to the checks in docs/06, section 3.
- **Members of several units.** A member can work in any number of units. Each unit's council approves only the hours worked for that unit.
- **Council work is paid** as hours of that unit, use "coordination" (book p. 140).

## 7. Unions, local councils, consumers' councils

**Unions** (book p. 140; owner: "Unions = group of related working councils"):
- **Forming.** Two or more councils of related trades form a union. Each council approves a `union_join` ticket, and the union adopts rules (same template as councils).
- **Delegates.** Each member council sends one delegate, rotating every 6 months.
- **Duties (advisory, never commanding):**
  - trade standards and recipe templates;
  - first answers to tickets about their trade;
  - mediation between councils of the trade;
  - training;
  - **expert advisers** for the planning group (section 8).
- **No power over councils.** A union cannot command its councils (HF-15, HF-20). Union decisions bind only the union's own work.

**Local councils** (book p. 141):
- **Who.** Open assemblies of the members who live in an area: a district, town, region or country.
- **Their matters:** local service gaps, pickup points, assisted access, local events, and later local housing.
- **How they decide.** Through tickets of local scope, confirmed by random members from that area. A responsible rotates every 6 months.

**Consumers' councils** (book p. 141): any members can form one around a topic (food quality, accessibility). They file tickets and flags, and propose guidelines; they have no special power.

## 8. The yearly plan

**The owner's rules (2026-11-21):**
- the plan decides what is invested in, what needs focus and what is closed;
- it has a period: annual first, later for example three-yearly;
- the public creates it through the ticketing system;
- a randomly drawn planning group turns the proposals into 2–3 whole plans, and all members rank them.

**The default calendar** (plan year = calendar year; dates in `plan.calendar`):

| When | What |
|---|---|
| 1 July – 31 August | **Proposals.** Any member files `plan_proposal` tickets: invest in a tool or workplace, focus on a trade or item, close a trade or item, change a share or a budget line, change a `plan`-tier default. Each gets a quick check (hours, euros) and, if experts provide one, a forecast. |
| 1 September | **Planning group drawn:** 15 random verified members (one third of all members if there are fewer than 45, at least 5). Unions name up to 5 **expert advisers**, who write analyses and answer questions but do not decide the group's choices. Group work is paid, up to 6 hours a week each. |
| 1 September – 15 October | **Drafting.** The group writes **2 or 3 whole plans**, each starting from the current default plan plus chosen proposals. The engine checks each one: it fits the expected hours and euros, keeps the hard frame, and gets a forecast of the four goals. Proposals left out are listed with the reason. |
| 16 – 31 October | **Public comments.** The group may revise its plans. |
| 1 – 14 November | **Ranked vote of all members** (instant runoff, 20% quorum). |
| 15 November | **Adoption.** The winning plan's parameters, budgets, investment list, focus list and closure list take effect on 1 January. If the quorum fails, the current plan runs on for 3 months and the vote is repeated in February. |

**A whole plan contains:**
- **the shares:** social share (start and end), accumulation, the cap on outside sales, the share of tool purchases earned by extra outside sales, the share of new capital that opens new trades, the share that becomes homes;
- **the tax method** (and the rate, if fixed);
- **euro budget lines:** materials, tools by trade, benefits, operations, the reserve target, the loss reserve;
- **the investment list:** what, for which unit or trade, euros, hours, priority;
- **the focus list:** shown on the needs board as "plan focus";
- **the closure list:** what, when, and the hearing date of each affected council;
- **other `plan`-tier defaults:** the services pay rule, the pension amount, the benefit rules;
- **forecasts.**

**The first plan.** At launch, the founders adopt the default plan of config/defaults.yaml (the simulation's most successful world) by a yes/no referendum.

**During the year:**
- Warning lights are watched.
- A red light lasting two months lets the planning group propose an emergency change, which random confirmers approve as usual.
- Any other change needs a referendum.

**Later: three-year plans.** A referendum can switch `plan.period_years` to 3. The book wants long-term plans approved by different people than those who draft short-term ones (p. 105). With three-year plans, a second group drafts the long-term part, and all members vote on it.

**Closing what the plan closes** (book p. 105: closing a unit goes against its workers' will, so it needs care):
- The council of every affected unit gets a hearing of 30 days.
- Its open orders are finished.
- Its workers see, on the needs board, where their skills are needed.
- No one loses income: an hour pays the same everywhere.

## 9. Opening units, flags and mediation

**Opening a unit** (owner: "They can easily open their unit if nothing against it in the budget plan and can start immediately"):
1. A member fills in the unit form.
2. The hard-frame checks run (HF-17: licence for licensed trades, insurance for services, nothing illegal).
3. The **plan check** runs (docs/06, section 2).
4. **Green:** the unit opens at once with status `trial` (3 months).
5. **Amber:** it opens at once, and four random confirmers review it within 14 days. A "no" goes to a panel, which may pause the unit.
6. **Red:** four random confirmers decide before it opens.

**Flags** (the Digital Services Act's notice-and-action):
- Any member can flag an offer, profile, comment, ticket, hours entry or payment, with a reason: illegal, wrong data or fraud, harassment, privacy, other.
- Three flags from different members hide the content until the review.
- Random confirmers review it as usual.
- The affected member gets a statement of reasons and can contest it through the panel and petition steps.

**Mediation and judgement** (book p. 70: "a call for mediation or judgment on a subject, person or institution"):
- Three mediators are drawn from members who volunteered for the mediator pool.
- They seek an agreement within 14 days.
- If there is none, a panel of 12 decides, and the decision binds within Unicorn's rules.
- Nothing in Unicorn replaces the courts.

## 10. Trust and reputation: two separate things

| | Trust rating | Reputation |
|---|---|---|
| What it is for | how many euros a member may hold for the trade fund (HF-11) | which members the secretariat suggests for answering tickets (book p. 70) |
| Computed from | the fund's records only: payments made when asked, speed, matching confirmations, returning a part on leaving, time as a member (docs/07, section 5) | "helpful" marks on a member's answers in the last 12 months, fading with time |
| Never used for | work, pay, votes, prices, draws | work, pay, votes, prices, draws, trust |
| Visible | to the member, with reasons; contestable; human review by a small elected group | as "helpful answers: N" on the profile |

The book ranks members by how well they answer requests, but adds that "having the minimum rank doesn't hurt an individual's life" (p. 70). The app keeps reputation only for routing and recognition.

## 11. Incentives

- **No extra UNIQ.** An hour is an hour (HF-2).
- **What does motivate:**
  - the needs board shows who needs what and how many hours of work it would give (docs/06, section 7);
  - recognition: "first maker of X", "filled a need", thanks from the people served;
  - the public record of what each unit makes.
- **The shortage bonus** (book p. 76) exists only as a switch, off by default, under HF-2:
  - only a referendum can turn it on;
  - it applies to one named trade with a red shortage;
  - at most +25%, for at most 3 months per decision.

## 12. Measuring the cost of governance

Every hour paid for councils, reviews, panels, mediation, delegates and the planning group is recorded under use "coordination". The open-books page shows governance hours as a share of all hours. The simulations did not include this cost, and it is one of the first numbers to watch (docs/02, section 6).
