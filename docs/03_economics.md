# 3. The economics: UNIQ, the funds, the tax and the monthly close

*Book chapters "Unicorn Supply and Demand System" (pp. 56–80), "Macroeconomic Planning and Budgeting" (pp. 82–97) and "Microeconomic Planning" (pp. 114–133); simulation rules from docs/02. Formulas use the book's numbering (4-1 … 4-12).*

## 1. UNIQ

- **1 approved hour = 1 UNIQ** before tax, for everyone (HF-2). Hours are recorded in minutes; UNIQ have four decimals.
- UNIQ exist only as balances in personal accounts. They have no paper form, no euro price, and cannot be given to another member (HF-4, HF-5).
- A member's account shows:
  - their **balance**;
  - what is **held** for orders they placed;
  - what is **available** (balance minus holds);
  - their **retirement account**;
  - every entry with its reason.

## 2. Fund 1 and Fund 2 (book pp. 57–58)

| | Fund 2 | Fund 1 |
|---|---|---|
| Job | pays: hours worked, transfers (pensions, care) | receives: every UNIQ spent on goods, services and rent |
| Direction | issues UNIQ to members | collects UNIQ from members |
| End of period | receives Fund 1's balance, which is cancelled | balance set to zero |

**In the ledger** (double-entry; every transaction's entries sum to zero):

| Event | Entries |
|---|---|
| Hours paid (gross) | Fund 2 −h, member +h |
| Flat tax on those hours | member −τh, Fund 2 +τh |
| Purchase, rent | member −p, Fund 1 +p |
| Transfer (pension, care) | Fund 2 −x, member +x |
| Into the retirement account | member −x, member's retirement +x |
| Out of the retirement account | retirement −x, member +x |
| Period close (cancellation) | Fund 1 −B, Fund 2 +B (B = Fund 1's balance) |

So at any moment:

**UNIQ outstanding = −(Fund 2 balance) = Σ members' balances + Σ retirement balances + Fund 1 balance.**

After the close, Fund 1 is zero, and the outstanding UNIQ are what the simulation calls **Fund 1's deficit**: UNIQ paid for work whose goods members have not bought yet. They are members' savings, and they are harmless as long as goods exist when members spend them (docs/02, section 4).

**The credit line (book p. 58).** At the start of each period the plan sets the hours it expects to pay (`Period.planned_hours`). Paying more than this plus 20% does not stop anything (HF-15). It opens a warning ticket for the members to look at.

## 3. The macro accounts (book pp. 83–87)

Every month the close (section 7) fills the following accounts. All are measured in hours; UNIQ and hours are the same unit.

- **(4-1)** Gross product = depreciation + current labour.
- **(4-2)** Net product = gross product − depreciation.
- **(4-3, 4-4)** Current labour tokens = current labour = net product.
- **(4-5)** Net product = Trade + Accumulation + Social + Consumption.
  - *Trade* = hours for outside customers;
  - *Accumulation* = hours building Unicorn's tools, workplaces and (later) homes;
  - *Social* = hours of free social services and coordination (councils, confirmers, planning);
  - *Consumption* = hours inside the goods and services members buy.
  - The app adds **Waste**: the hours of products written off and, if shifts are switched on, of idle shift time. They are part of the hours worked but of no use.
- **(4-6)** Households: Transfers + Current tokens = Savings + Consumption + Taxes.
- **(4-7)** Fund 2: Savings + Taxes = Trade + Accumulation + Social + Transfers.
- **(4-8, 4-9)** With net taxes = taxes − transfers:
  - Current tokens − Net taxes = Savings + Consumption;
  - Savings + Net taxes = Trade + Accumulation + Social (+ Waste in the app).
- **(4-10)** Current tokens = Trade + Accumulation + Social + Consumption (+ Waste).

The close checks these identities with the real numbers and stores the residuals. A residual other than zero (beyond rounding of 0.0001 UNIQ per transaction) is an error. It opens a ticket for the auditors and is shown on the open-books page.

## 4. The flat tax and the tax balance (book pp. 88, 94–95)

**One rate τ for everyone**, taken from every paid hour (HF-9). The book's rule (p. 88): the tax must take back from members' tokens exactly what is not available for them to buy. Too little tax gives "tokens inflation": queues, empty shelves. Too much gives goods nobody can buy.

**Default method: `balance_monthly`** (the simulation's successful setting). At each monthly close, the rate for the **next** month is set:

```
H  = hours expected to be paid next month (trend of the last 3 months, or the plan's figure in the first months)
C  = hours inside the goods and services members are expected to buy next month
     (orders on hand + expected bookings + expected purchases from stock)
T  = transfers due next month (pensions, care)
S* = expected change in members' savings next month:
     + members saving toward their target (economy.savings_target_months of spending)
     − members and former members spending savings above it
Balance:  (1 − τ)·H + T = C + S*
So:       τ = 1 − (C + S* − T) / H,   clipped to [economy.flat_tax.min, economy.flat_tax.max] (0% and 68%)
```

- **While members save**, τ is a little lower: in effect Fund 1 lends their savings to social services, tools and outside sales.
- **While savings are spent**, τ is higher for a while (the owner's "higher flat tax for a while").
- **Waste is taken back:** hours of products nobody buys are in H but not in C, so τ rises (the mixed rule, HF-9).
- **Real time differs from the model:** the simulation solved τ inside the same month. The app cannot tax hours already paid, so it sets the next month's rate from forecasts (the book: "in the next period", p. 131).

**Alternatives** (tier `plan`):
- `balance_yearly`: the same calculation once a year on 12-month figures; a steadier rate.
- `fixed`: the members set a rate between 30% and 68% (owner, 2026-10-14). What social services and outside sales leave of it pays tools and homes.

**The tax pays** (book p. 94; the plan's budget categories): social services and coordination; Unicorn's tools and workplaces; the work that earns euros; transfers; and the waste of unsold products.

## 5. Savings, the retirement account, former members

- **Savings** are simply UNIQ left in the account. There is no interest (book p. 93). UNIQ never expire (HF-8; the owner rejected expiry).
- **Savings target:** `economy.savings_target_months` (default 6) months of a member's own average spending. It is used by the tax balance and the warning lights.
- **Retirement account** (book p. 91; owner, 2026-11-21):
  - Any member may move UNIQ into their own retirement account at any time.
  - While the unspent-UNIQ light is amber or red, the app **suggests** moving half of the savings above the target; it never moves anything by itself. (The simulation moved them automatically; the app asks.)
  - Payouts: in equal monthly parts over `economy.retirement.payout_months` (default 240), or on request after pension age.
  - Withdrawing early is allowed, at most 1/12 of the balance per month (book p. 93: conditions on withdrawals instead of new tokens).
- **Former members** keep their UNIQ and can buy goods and services like members, but earn no new UNIQ (HF-8). Their holdings appear in the unspent-UNIQ light.

## 6. Transfers: the equal pension and care (book pp. 85–86)

Transfers are paid by Fund 2 and covered by the tax (HF-1, HF-9).

**Equal pension** (owner, 2026-11-21):

- **Who.** A member past pension age (the country's statutory age, default 67 for Germany), or a member unable to work, confirmed by a ticket with random confirmers and minimal health data.
- **Qualifying.** At least `economy.pension.qualifying_active_months` (default **36**, "2 or 3 years") **active months**. An active month has at least `economy.pension.active_month_min_hours` (default 10) approved hours, or is a recognised month of care or illness.
- **Amount.** The same for everyone: `economy.pension.share_of_median_net` (default 0.6) × the median monthly net UNIQ income of active members over the last 12 months. The yearly plan may set another amount.
- **Not in the simulation.** The pension was never simulated. Its cost shows in the forecast of the first plan, and docs/12 asks for a run with pensions before the founders adopt it.
- **The German pension.** Members who leave capitalist jobs stop building it. Whether the trade fund should pay voluntary German pension contributions (about €100 a month) is an open question (docs/12).

**Care and other transfers:** decided by the plan, paid the same way.

## 7. The monthly close

Run by `python manage.py close_period` on the first day of each month (cron, phase 15), for the month that ended:

1. **Freeze:** period status `closing`; no new payments are dated in it.
2. **Hours by use:** sum the approved, paid hours by use: consumption, social, accumulation, trade, waste (section 3).
3. **UNIQ flows:** issued (gross), tax, net issued, spent (Fund 1 inflow), transfers.
4. **Cancel:** post the cancellation of Fund 1's balance into Fund 2 (HF-6).
5. **Outstanding UNIQ:** compute them and their size in months of members' spending (6-month average).
6. **Identities:** check 4-5 to 4-10 and store the residuals (section 3).
7. **Labour values:** recompute all prices from measured hours (docs/04, section 6).
8. **Next tax rate:** set it (section 4).
9. **Warning lights and "Are we on track?":** compute them (sections 9 and 10).
10. **Store and open:** store a `MacroSnapshot`; open the next period with its tax rate and planned hours; publish the totals on the open-books page.

The close is idempotent: running it twice for the same period does nothing the second time.

## 8. The planning rate ("exchange rate")

The law and the hard frame forbid any exchange between UNIQ and euros (HF-4). The book's foreign-trade rule (p. 154) still needs a way to compare: *if a thing costs more hours to make than the hours it takes to earn the euros to buy it, buy it; if less, make it.*

- **Planning rate r** = euros Unicorn earns per hour of outside sales, after German taxes. It is measured over the last 12 months from outside sales and their hours. Until enough data exists, the fallback is `economy.planning_rate.fallback_eur_per_hour` (€17.35, the average German net wage, docs/02).
- **Make or buy:** making X costs `v_X` hours plus `e_X` euros of bought inputs; buying X costs `P_X` euros. Make X when `v_X + e_X / r < P_X / r`.
- **Other currencies:** r is converted with the European Central Bank's daily reference rate (`tradefund.FxRate`). Later, each country can measure its own r.
- **On screen** it is always called the **planning rate**, with the note "for comparing only; UNIQ are never exchanged".

## 9. Micro adjustment without changing any price

The book (pp. 128–132) allows temporary price changes to clear shortages and surpluses. The owner forbids any price change (HF-3). The app keeps the **order-adjustment half** of the book's algorithm and replaces the price signal with signals from orders:

1. **Each month, for each offer:**
   - `demand` = units ordered + units asked for while sold out (waiting list);
   - `supply` = units made ahead + units the unit could make within its cycle.
2. **Signal** `A = demand / supply` (the book's A, measured in quantities instead of prices):
   - `A > 1.1` for two months: the unit's council gets a suggestion to make more or open a shift, and the item appears on the needs board ("wanted");
   - `A < 0.9` for two months: a suggestion to make fewer ahead (lower the unit's advance share) or to pause;
   - otherwise nothing.
3. **Aggregate pressure** `D` = UNIQ members tried to spend ÷ hours in the goods available. `D > 1` means hidden inflation; it raises the next tax rate through the balance (section 4) and lights the shelves light.
4. **Shortages are shared out, never priced** (constitution draft rule 2):
   - Orders are served in the order placed.
   - While the shelves light is red, each member may order at most `market.shortage_cap_per_member` units of a short item a month.
5. **Scarce intermediate inputs** (a mill that cannot supply all bakeries) are shared by the **harmony algorithm** (book pp. 118–124): u = (output − goal)/goal, harmony = −u² if u < 0, else √u; iterate as in the book with the deviation variable B (later phase, plan/phase_16). Until then, input requests are served in order and the shortage shows on the needs board.

The book's suggestions are always suggestions (HF-15). Councils decide (HF-20).

## 10. Warning lights and "Are we on track?"

**Warning lights**: always visible on the dashboard, and computed at each close.

| Light | Amber | Red | What it means |
|---|---|---|---|
| Unspent UNIQ (members and former members, without retirement accounts) | above the savings target (6 months of spending) | above 2 × the target | UNIQ are piling up without goods to buy |
| Shelves (share of what members ordered or tried to buy that they got in time) | below 95% | below 80% | goods are short at fixed prices |
| Unsold products (share of products made ahead that were written off) | above 10% | above 30% | work is wasted; the tax rises |
| Street price of a UNIQ | not measured yet | | the simulation's rough indicator; its real basis is an open question (docs/12) |
| Euro reserve (months of outgoings the trade fund holds) | below 5.4 | below 2 | the fund may soon fail to pay materials or bills |
| Idle shifts (only when shifts are switched on) | above 10% | above 30% | paid shift time without customers |

**"Are we on track?"**: the success conditions of docs/02, section 5, measured monthly:
- outside sales per member and month, and their growth over 12 months (target €100 at the start, +10–15% a year);
- bought materials in euros per hour, by trade (compared with German firms, from the simulation's data);
- taxes paid on outside sales as a share of their revenue (target about 15%);
- unsold share of products;
- share of members who could live without a capitalist job (members whose basic euro bills the fund covers, or who report no capitalist job);
- an hour in Unicorn compared with an hour at the average net wage.

Each row shows the real value, the simulation's value for the same year in the default world, and a colour (on track / behind / far behind).

## 11. Forecasts

Plan proposals, plan variants and hard-frame proposals need a forecast (owner, 2026-11-21).

- **Version 1:** experts run the simulation in `../Unicorn-simulation` with the app's live numbers. The export comes from the page "Data for forecasts", a CSV of the world-tracker values and the current defaults. They attach the result to the ticket: a PDF or image plus five numbers, namely the four goals met or not and the share able to live without a job in years 10, 20 and 30.
- **Later (phase 16):** the app runs the seed model itself as a background job, from a copy of the simulation's `seed` package.
