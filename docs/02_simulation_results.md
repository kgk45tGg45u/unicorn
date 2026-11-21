# 2. What the simulations found

*All numbers come from the sister repository `../Unicorn-simulation`. Main sources:*
- *`docs/seed_review.md` (8 October 2026);*
- *`docs/seed_review_v2.md` (9 October 2026, the owner's new assumptions);*
- *`docs/real_world/1_the_numbers.md` (14 October 2026);*
- *`docs/seed_review_v3.md` (21 November 2026, the inflation check);*
- *`outputs/seed/inflation_v3/tables.md`.*

*Each setting ran 2 to 30 times over 20 to 30 years, so differences of a few points can be chance.*

## 1. The question and the model

**Question (owner):** members keep their capitalist jobs for years and give their free time to Unicorn. Can they become independent of capitalist income within 10 to 20 years, while Unicorn stays attractive, grows and stays stable?

**The seed model:**

- **Simulated members.** A fixed sample of 1,000 households stands for all members. Up to 2 million people in Germany might consider joining.
- **Each month in the model:**
  1. people join or leave;
  2. members decide how many capitalist hours to keep;
  3. the plan divides members' offered hours between goods for members, social services, outside sales and building tools;
  4. the flat tax pays for everything but members' goods;
  5. prices are the measured hours;
  6. the euro fund pays materials, tools and members' bills;
  7. every account is checked (hours, UNIQ and euros must add up exactly).
- **Recipe and world.** A **recipe** is Unicorn's own choices. A **world** is what Unicorn cannot choose: the outside customers, the materials a service needs, German taxes. (The farmer's picture: the recipe is what the farmer plants and how; the world is the weather and the soil.)

## 2. The main findings, in order of discovery

1. **Unicorn is wanted almost everywhere** (8 and 9 October, 14 October):
   - An hour in Unicorn buys more than an hour of the typical member's job in every run without a tax on UNIQ income.
   - Membership grows to 1.7–1.9 million by year 30, from 25 founders, by word of mouth.
   - For a person at the average German net wage (€17.35 an hour), an hour in Unicorn buys €24–30 of goods and services in year 1, and €43–56 later.
2. **Independence depends on euros, that is, on outside sales that grow:**
   - With €50 of outside customers a member and no growth (the owner's own guess), Unicorn becomes a large care and services network, but nobody can leave a job in 30 years. The euros pay only the materials of the services members trade among themselves.
   - Independence comes when outside sales reach about **€1,500–2,000 per member and month**.
   - With 10% yearly growth from €100, half of the members can live without a job by year 20–28; with 15% growth, by year 17–21.
3. **One world passes all three tests by year 20** (14 October). Its conditions:
   - outside customers worth €100 a member a month at the start, growing 12.5% a year;
   - services that need half the bought materials of German firms;
   - German taxes on outside sales of 15%.

   In it, half of the members can live without a capitalist job from year 17. By year 30, 1.9 million members get goods and services worth about €4,950 a month at shop prices; 72% live in Unicorn homes, and Unicorn makes 92% of their basic needs. Self-sufficient does not mean cut off: Unicorn still sells 13% of its hours outside, to buy what it cannot make.
4. **The best recipe is "tools first, early benefits"** (9 October):
   - Unicorn's own tools keep the euros first (the book's order: the share for building is decided first);
   - it starts with 14 lighter services;
   - the tax is light at the start;
   - benefits may start at any time.

   Across 60 wide worlds it met all four goals in 27% (members' goods first: 8%), and in 63% most members could live without a job by year 30.
5. **A tax on UNIQ income is the biggest legal risk** (14 October). If the tax office taxes the shop value of what UNIQ buy at 15–35%, an hour in Unicorn buys a fifth to two fifths less, and up to 60% of members can end up worse off. A binding tax ruling is needed before the start.
6. **A flat tax fixed by the members at 30–40%** builds tools and homes earlier and did better in growing worlds. In the world that passes all tests, half of the members could live without a job from year 14 at a fixed 30%. At 60–68% members keep too little of each hour (14 October).
7. **Unsold products and hidden inflation** (21 November): see section 4.

## 3. The default world of the app

The owner's rule (21 November): the app's defaults are the conditions of the successful world with the highest success rate **while many products go unused**, with products **ordered before they are made**.

That is the world that passed all three tests, with the rules of the inflation check:

- **Unsold products:** 70% of the products made ahead go unsold.
- **Ordering ahead:** members order products ahead, and only a tenth is made before an order.
- **Outside customers:** their products too are made mostly on order, with a tenth made ahead.
- **The mixed rule:** hours of products that go unsold are written off and taken back through the flat tax.
- **Tax balance:** the flat tax balances every month what members can buy with what is made.
- **Retirement fund:** members' savings above what they want to keep can go into a retirement fund.
- **Leavers:** former members keep their UNIQ.

Results (2 runs of 30 years, `outputs/seed/inflation_v3/tables.md`, row "70% unsold, members order ahead, loss through the flat tax"):

| Measure | Result |
|---|---|
| Goals met | **all four**, in both runs |
| Members who can live without a capitalist job | **95% in year 20, 100% in year 30** |
| Members | 1.71 million in year 20, 1.92 million in year 30 (from 25 founders) |
| Share of all hours spent on products nobody bought | 1% |
| Flat tax, highest month | 60% (around the years when most members leave their jobs) |
| What an hour in Unicorn buys, worst month | 0.87 times an hour at the average German wage (goods only; more with the fund's payments of bills) |
| Unspent UNIQ, worst month | 4.9 months of members' spending (members want to keep 6) |
| Months with a red warning light (unspent UNIQ, shelves, street price) | 0, 0, 0 |
| Trades running in year 30 | all 49 |

**The recipe "tools first, early benefits"** (`config/seed_recipes_v2.yaml`), now the app's economic defaults:

| Choice | Value |
|---|---|
| Joining | open door (after the founders' trial year of 12 months, with 25 founders) |
| Share of hours for building Unicorn's own tools (accumulation) | 2% |
| Share of hours for social services | 3% at the start, rising to 17% as members leave their jobs |
| Largest share of hours sold to outside customers | 53% |
| Share of planned tool purchases earned by extra outside sales | 50% |
| When euros are short | Unicorn's tools keep their euros first; at least 44% of members' usual purchases (those needing the fewest euros) stay on offer |
| Members' bills paid by the fund | by need (heaviest burden first), may start at any time, grow only while an hour in Unicorn buys at least 1.15 times a capitalist hour |
| Euro reserve | 5.4 months of outgoings |
| Guarantee | the fund tops up any member who would be worse off on basic needs than without Unicorn |
| New capital that opens new trades | 57% |
| Share of new capital that becomes homes (later) | 24%, rent 0.59 UNIQ per m² a month |
| Starting services | the 14 lighter ones (docs/06, section 1) |

## 4. The inflation check (21 November 2026)

**The danger.** Suppose Unicorn pays every planned hour, and the hours spent on products nobody buys stay paid, with nothing taking them back. Then members hold UNIQ with no goods behind them. With fixed prices, this does not show as rising prices. It shows as:
- empty shelves;
- piles of unspent UNIQ;
- a UNIQ worth less and less "in the street".

Then members leave. In the world that passed all tests, with 70% unsold and the loss left with Fund 1, membership peaked at about 3,400 in year 11 and was gone by year 18. **This is superinflation when prices never move, and it is a no-go.**

| Rule for unsold products (world that passed all tests) | Result |
|---|---|
| Loss left with Fund 1: 10% unsold | all four goals (small leaks fill members' wish to save) |
| Loss left with Fund 1: 30% unsold | unstable: shelves short in 23 months, membership about a third |
| Loss left with Fund 1: 50% or more | **collapse** |
| Mixed rule (written off through the flat tax), made before ordering: 10% | all four goals |
| Mixed rule, made before ordering: 30–50% | attractive, growing, stable; only 26–27% can live without a job by year 20 (all by year 30) |
| Mixed rule, made before ordering: 70% | only stable: a fifth of all hours wasted, flat tax up to 83%, 830,000 members instead of 1.9 million |
| **Members order ahead, 30–70% of what is still made ahead goes unsold (either rule)** | **all four goals; 95–99% in year 20** |

**What protects Unicorn, strongest first:**
1. ordering ahead;
2. the mixed rule (a cost instead of a collapse);
3. a flat tax that balances what members buy with what is made (book p. 88);
4. never exchanging UNIQ for euros.

Keeping former members' UNIQ is honest but weighs a little under stress (about 5–10% fewer members in the worst cases). The retirement fund was rarely needed.

**A fault found and fixed:** the earlier model stored about 5% of service hours "in stock" every month, as if a haircut could be kept. In the app, services cannot be stored; they are paid only when performed (owner, 21 November).

## 5. The conditions for success, for the app to watch

| Condition | Needed for success | The owner's own guess ("your world") |
|---|---|---|
| Outside customers at the start | about €100 a member a month | €50 |
| Their growth | 10–15% a year for 20 years or more | none |
| Bought materials per hour of work | about half of German firms' | as German firms (until measured) |
| German taxes on outside sales | about 15% | 25% |
| Products nobody buys | at most about 10% of what is made, or products ordered ahead | does not matter while Unicorn makes few products |
| The loss of unsold products | taken back through the flat tax, never left with Fund 1 | |
| UNIQ income | not taxed in euros (binding ruling) | unknown |

The app measures each of these every month and shows them on the public "Are we on track?" page (docs/03_economics.md, section 10).

## 6. What the simulations do not cover

These parts of the app have no simulated evidence yet:
- **People.** Real people (trust, conflict, effort, fraud) and how outside customers are actually found.
- **Holders and theft.** The trade fund held in many members' accounts, the trust rating and theft: the model keeps one euro balance.
- **Governance and services.** Governance costs (hours spent on tickets, councils, confirmers, planning groups), the pension, shifts for services, and shipping.
- **The law.** A tax on UNIQ income, and benefits rules.
- **Bad products.** The plan does not learn which products fail.

The first 25 founders should record from day one:
- the euros of bought materials per hour of each service;
- what members bring themselves;
- outside sales;
- hours spent on governance.

These are the numbers the simulations most need (`docs/seed_review_v2.md`, section 11).

## 7. What this means for the app's design

1. **Products are made after an order**, with at most a tenth made ahead (the `advance_share`). Own-initiative products are paid only when sold.
2. **Services are paid only when performed** (owner, 2026-11-21); shifts are a switch for later.
3. **The flat tax is recomputed every month** so that what members can buy equals what is made (docs/03_economics.md, section 4), within 0–68%.
4. **Three warning lights** (unspent UNIQ, shelves, street price) plus the unsold-products light are always visible.
5. **The "Are we on track?" page** compares the real world with the success conditions above.
6. **The euro side matters most.** Outside sales, the trade fund, and buying tools first are core features of the first version, not extras.
7. **Every plan proposal gets a forecast.** The simulation can be rerun with live numbers, so that members vote with the expected effect on the four goals in front of them.

## 8. How to reproduce

From `../Unicorn-simulation`:

```
python -m unicorn_sim seed-run --scenario config/seed_v3.yaml --set products.members_rule=on_order \
    --set trade.outside_market_eur=100 --set trade.outside_market_growth=0.125 \
    --set technology.materials_scale=0.5 --set trade.tax_on_sales=0.15
.venv/bin/python scripts/seed_v3_inflation.py grid      # the 126 runs behind section 4
.venv/bin/python scripts/seed_v3_tables.py              # tables and figures
```

The exact recipe values are in `config/seed_recipes_v2.yaml` (`tools_first_early_benefits`). The command line above shows the world. The recipe is applied by the scripts, or by `seed-explore robust` with `--assumptions v3`.
