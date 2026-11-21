# 1. The hard frame and the democratic defaults

The owner's rule (2026-11-21): *"The real conditions of the world will be reacted to by democratic decision-making. The decision-making happens in the hard frame that the code has, and to change things even further, expert ideas and prognoses should be confirmed by everyone. … This is default, but nothing can't be changed democratically."*

So there are two layers:

1. **The hard frame:** about twenty rules that the code itself enforces. No council, confirmer or ordinary vote can break them. They change only through the hard-frame procedure (section 4): an expert proposal, a forecast, a vote of all members by a two-thirds majority, and a new release of the code.
2. **The democratic defaults:** every number and every switch in [config/defaults.yaml](../config/defaults.yaml). Members change them through tickets, at the tier written next to each one (section 3). Each default also has hard bounds, and a change beyond them is a hard-frame change.

## 1. The hard-frame rules

Each rule has an ID. The code cites it in comments (`# HF-5`), and tests cite it in their names (`test_hf05_...`).

| ID | Rule | Where the code enforces it |
|---|---|---|
| **HF-1** | **UNIQ come only from work.** New UNIQ are created only by Fund 2, and only (a) for approved hours of work, and (b) for transfers decided by the plan (pensions, care), which the flat tax covers. Never for euros, donations, or anything else. | `ledger.services.post()`: only transaction kinds `hours_pay` and `transfer` may debit Fund 2 |
| **HF-2** | **Equal pay.** Every approved hour pays 1 UNIQ before tax, for every member, in every country and every kind of work. The only exception is a temporary shortage bonus: at most +25%, for at most 3 months per decision, and only a referendum can switch it on (book p. 76). | `units.services.pay_hours()`; `rules` bounds on `economy.shortage_bonus.*` |
| **HF-3** | **Prices are hours.** The price of every good and service is its labour value: the Unicorn hours inside it, direct and indirect (docs/04_io_table.md). It is computed from recipes and measured hours. It never changes for scarcity, demand or any other reason, and it is fixed at the moment of ordering. | `catalogue.engine`; `market` stores the price on each order line; no code path sets a price by hand |
| **HF-4** | **No euro price for UNIQ.** UNIQ are never bought, sold, exchanged, lent for interest or paid out in any currency. The planning rate only compares costs; it is never offered as an exchange. | no model links UNIQ and currency amounts in one transaction; the ledger only knows UNIQ |
| **HF-5** | **Personal accounts.** UNIQ move only between a member and the funds: Fund 1, Fund 2 and the member's own retirement account. There are no transfers between members, and units hold no UNIQ (book pp. 60–61). | `ledger.services.post()` rejects any transaction with two different members' accounts |
| **HF-6** | **Fund 1 to Fund 2 only.** All UNIQ spent go to Fund 1. At every period close, Fund 1's balance is cancelled into Fund 2. Nothing flows from Fund 2 to Fund 1 (book pp. 57–58). | `ledger.services.post()`; `macro.services.close_period()` |
| **HF-7** | **Open books that cannot be changed.** The books are double-entry, append-only and hash-chained. Every transfer has a written reason, and a fingerprint of the books is published every day. The totals are public; personal data never is. | database triggers and model guards (P02.T05); nightly audit (P02.T07); public pages (P02.T08) |
| **HF-8** | **Never taken away.** Nobody's UNIQ expire or are cancelled, except through the flat tax at the moment of payment and through spending. A member who leaves keeps their UNIQ and can still spend them (owner, 2026-11-21). | there is no expiry code; `members.services.leave()` keeps the account |
| **HF-9** | **One flat tax.** It is one rate for everyone, between 0% and 68% of every hour. Transfers are paid from it and never printed. The hours of products nobody bought, and of idle shifts, are taken back through it, never left with Fund 1. | `macro.services.next_tax_rate()`; bounds in `rules` |
| **HF-10** | **Members choose their work.** The app proposes and shows needs. It never assigns, orders, ranks or punishes anyone in matters of work (EU platform-work directive 2024/2831). | no feature assigns work; the needs board and suggestions only inform |
| **HF-11** | **The trust rating only limits holding.** It sets only how many euros a member may hold for the trade fund. It never touches work, pay, votes or prices. It is computed from the records only, and each member can see theirs, contest it and get a human review. | `tradefund.trust`; no other app imports it |
| **HF-12** | **The app never moves money.** It shows payment requests, and the payer and the receiver confirm them. It never starts payments and never reads bank accounts. | no payment or banking integration exists |
| **HF-13** | **One person, one account, one vote.** Identity is checked (two vouches and one in-person check) before a member may vote, hold fund euros, confirm, or be drawn. | `members.services.is_verified()` guards these actions |
| **HF-14** | **Privacy.** Personal data is minimal, encrypted, kept apart from the hour accounts (which use member numbers), and deletable. No personal data appears in the public books. | `members.MemberPrivate`, per-member keys (P01.T04) |
| **HF-15** | **The centre only proposes.** The planning engine, the secretariat, the warning lights and the plan check recommend; people decide. An automatic check may say "nothing against it" or "people must decide", but it never rejects on its own. Only hard-frame rules block. | `plan.check` returns green, amber or red; red sends the request to people |
| **HF-16** | **Decisions follow the tiers.** Every decision is a ticket that records its method, its deciders and its reasons. Defaults change only at their tier (section 3), and the hard frame only by the procedure in section 4. | `rules.services.set_param()` requires a decided ticket of the right tier |
| **HF-17** | **The law first.** Licensed trades are open only to members with a verified licence; services need insurance; taxes are paid; illegal goods are never offered. | `units.services.open_unit()` and offer publishing check the licence and insurance |
| **HF-18** | **Donations earn no UNIQ.** | `tradefund.Donation` has no link to the ledger |
| **HF-19** | **Open code, common property.** The code is AGPL-3.0, the network belongs to its members, and nobody can sell it. | licence file; no paid-access feature |
| **HF-20** | **Working councils.** Every unit with two or more members has a working council, which approves the unit's hours and decides its production. Hours of such a unit cannot be paid without its council's approval (owner, 2026-11-21). | `units.services.approve_hours()` |

## 2. The defaults: where they live

- [config/defaults.yaml](../config/defaults.yaml) lists every democratic default. Each entry has:
  - its value;
  - its hard bounds (`min`, `max` or `choices`), which may not be crossed without a hard-frame change;
  - its tier (section 3);
  - its source: `sim` (the simulation's most successful world, docs/02), `book`, `owner` (with date), `legal`, or `proposal` (my proposal, not yet tested or decided).
- `python manage.py load_defaults` copies them into the `rules.Parameter` table. After that the **database** holds the live values, and every change is a row in `rules.ParameterChange` that points to the ticket that decided it.
- Code reads a value only through `rules.services.get_param("economy.flat_tax.method")`, never from the YAML file directly.

## 3. Who may change what: the tiers

| Tier | Who decides | Used for |
|---|---|---|
| `unit` | the unit's working council, under its own rules; in a one-person unit, that person | the unit's own affairs: offers and recipes, production, shifts, admission of workers, its internal contract, its euro prices for outside customers |
| `confirm` | a ticket and four random confirmers who must **all** say yes. A single "no" sends it to a panel of 12 random members (majority of 7). If it is still contested, a petition can force a referendum (docs/05_governance.md) | operational defaults (deadlines, cover radius, limits for automatic purchase approval); opening a unit when the plan check is not green; purchases above the automatic limit; flags |
| `plan` | the yearly plan: a random planning group drafts 2–3 whole plans and all members rank them; between plans, a referendum | economic shares, budgets, investments, focus, closures, the tax method, the pension amount, the services pay rule |
| `referendum` | a vote of all members: simple majority, at least 20% turnout | membership rules, voting rules, switches such as the shortage bonus |
| `hard` | the hard-frame procedure (section 4) | the rules HF-1 to HF-20 and every hard bound in defaults.yaml |

A higher tier can always decide what a lower tier may decide (a referendum can change a `confirm` default), never the other way round.

## 4. Changing the hard frame

The owner's rule: expert ideas and prognoses must be confirmed by everyone. The default procedure:

1. **Expert proposal.** A ticket of type `hard_frame_change` gives the rule's new text, why it is needed, what changes in the code, and who wrote it.
2. **Forecast.** A forecast from the simulation (or a written expert prognosis where no model exists) shows the expected effect on the four goals.
3. **Completeness check.** Four random confirmers check only that the proposal is complete and understandable, not whether they like it.
4. **Vote of all members.** Open for 21 days. It passes with at least two thirds "yes" and a turnout of at least 25% of members.
5. **Release.** The code is changed in the open repository. The release notes cite the ticket and the vote. Until the release, the old rule stays in force.

The procedure itself is part of the hard frame.

## 5. The starting defaults come from the most successful simulation

The owner's rule: the default is the successful world with the highest success rate **while many products go unused**, with products **ordered before they are made**. In the simulation, this world met all four goals: 95% of members could live without a capitalist job by year 20, and all of them by year 30 (docs/02_simulation_results.md, section 3).

The defaults copy that world's rules: Unicorn's choices ("tools first, early benefits"), the rules of the inflation check (products ordered ahead with a tenth made ahead, unsold products written off through the flat tax, a flat tax balanced every month, a retirement account, former members keeping their UNIQ), and the owner's later decisions (services paid only when performed; all four confirmers must agree; plans chosen from 2–3 complete variants; an equal pension after three active years).

Some defaults were never in the simulation: the governance numbers, the trust rating, the pension, deadlines, shipping. They are marked `source: proposal` in defaults.yaml, and docs/12_open_questions.md lists the ones that should be simulated or decided before the founders adopt them.

**The world itself is not a default.** The simulation's success depended on outside conditions Unicorn cannot choose: outside customers worth €100 a member a month at the start, growing 12.5% a year, services that need half the bought materials of German firms, and taxes on outside sales of 15%. The app measures these conditions every month and shows how close the real world is to them (docs/03_economics.md, section 10).
