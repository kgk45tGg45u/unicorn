# Phase 09 — The monthly close: tax balance, identities, warning lights, pension

**Goal:**
- Every month: cancel Fund 1, account the hours by use, check the book's identities, and set the next month's flat tax by the tax balance.
- Show the warning lights and "Are we on track?".
- Pay the equal pension.
- Suggest retirement saving.

**Read first:** docs/03 (all of it), docs/02 sections 3–5, docs/01 rules HF-1, HF-6, HF-8, HF-9.

---

### - [ ] P09.T01 — The macro snapshot and hours by use

**Read:** docs/03 section 3.
**Files:** `apps/macro/` (new app), `apps/macro/models.py` (MacroSnapshot), `apps/macro/accounts.py`, `apps/market/models.py` (ProductionOrder `purpose`), `apps/macro/tests/test_accounts.py`

**Do:**
1. **Production purpose.** Add to `ProductionOrder` the field `purpose`: `members` (default), `outside` (P10), `accumulation` (tools and workplaces for Unicorn itself: set when the production order serves a `GroupTool`, or a unit of mode `project` linked to a plan investment).
2. **`MacroSnapshot`** (one per period). All values are Decimal(18,4) in hours (= UNIQ) unless named `_eur`:
   - `hours_paid`, `tax`, `net_issued`, `transfers`, `spent` (members' purchases and rents into Fund 1), `cancelled`;
   - `outstanding` (after cancelling), `months_of_spending`;
   - hours by use: `consumption`, `social`, `accumulation`, `trade`, `waste`, `depreciation`, `inventory_change`, `hours_residual`;
   - `tax_rate_used`, `tax_rate_next`;
   - `lights` (JSON), `world` (JSON), `identities` (JSON), `created_at`.
3. **`accounts.hours_by_use(period)`:**
   - `consumption` = UNIQ spent by members on goods and services this period (Fund 1 inflows of kinds `purchase` and `rent`);
   - `social` = paid hours of units of kind `social` + paid hours of the coordination unit;
   - `trade` = the labour value of outside deliveries this period (0 until P10);
   - `accumulation` = the labour value of delivered production orders with purpose `accumulation`, plus paid hours of `project` units linked to investments;
   - `waste` = Σ `WasteRecord.hours` of the period + idle service minutes ÷ 60 (P05.T06);
   - `depreciation` = Σ over deliveries of quantity × the offer's depreciation hours per unit (`d_j`);
   - `inventory_change` = (Σ available stock lots × value + Σ approved hours on unfinished production orders) at the period's end, minus the same at its start.
4. **The hours identity (book 4-1 and 4-10):**
   `hours_residual = hours_paid + depreciation − (consumption + social + accumulation + trade + waste + inventory_change)`.

   It is **not exactly zero**: prices use declared or measured hours, not the exact hours of each item. Store it, and warn if `|residual| > 2% of hours_paid` ("the recipes and the real hours have drifted apart").

**Tests:**
- a small month with one bakery, one haircut and one written-off lot gives the expected uses;
- the residual is within 2% when recipes match the recorded hours.

---

### - [ ] P09.T02 — The UNIQ identities that must be exact

**Read:** docs/03 sections 2–3 (4-6, 4-7).
**Files:** `apps/macro/identities.py`, `apps/macro/tests/test_identities.py`

**Do:**
1. **`check_uniq_identities(period) -> dict[str, Decimal]`.** Each value must be exactly 0:
   - **households (4-6):** (gross hours pay + transfers) − (Δ member and retirement balances + spent + tax) for all members and former members together;
   - **Fund 2:** (hours pay + transfers) − tax − cancelled − Δ(−fund2 balance) = 0;
   - **Fund 1:** inflows − cancelled − end balance (after the close, the end balance must be 0: HF-6);
   - **conservation:** outstanding = Σ member + retirement balances (after the close).
2. **Any non-zero value** is stored in `identities`, opens an `audit_failure` ticket for the auditors, and blocks the next period from opening until an auditor acknowledges it on the ticket. The block is an explicit state, `Period.status = "closing"` kept, with a banner. Payments keep working in the new month, dated in a temporary open period; `# OWNER-CHECK` if this proves awkward.

**Tests:**
- `test_hf06_fund1_zero_after_close`;
- `test_hf01_issued_equals_hours_plus_transfers`;
- a forced inconsistency (a correction transaction posted by a test helper that bypasses `post()` through raw SQL on a test database **without** triggers) is detected.

---

### - [ ] P09.T03 — The tax balance

**Read:** docs/03 section 4 (formula and alternatives).
**Files:** `apps/macro/tax.py`, `apps/macro/tests/test_tax.py`

**Do:**
1. **`next_tax_rate(period) -> Decimal`**, by `economy.flat_tax.method`:
   - **`balance_monthly`** (default): τ = 1 − (C + S* − T) / H, rounded to 4 decimals and clipped to [`economy.flat_tax.min`, `economy.flat_tax.max`]:
     - **`H`:** the average gross hours paid over the last 3 closed periods; in the first 3 months, `Period.planned_hours`, or else the last period's hours.
     - **`C`:**
       - the UNIQ value of member order lines due next month and not yet delivered;
       - plus the 3-month average of UNIQ spent on bookings and stock purchases;
       - plus the 3-month average of rents.
     - **`S*`:** the expected change in savings:
       - for members whose balance is below `economy.savings_target_months` × their 6-month average spending: + 5% of their average monthly net income (the simulation's `members.savings.rate`, in code as `SAVING_RATE = Decimal("0.05")` with `# from ../Unicorn-simulation config/seed.yaml members.savings`);
       - for members above the target: − 10% of the amount above it;
       - for former members: − 5% of their balances (the simulation's `ex_spend_share`).
     - **`T`:** pensions and other transfers due next month.
     - If `H` is 0, keep the current rate.
   - **`balance_yearly`:** on the December close only, the same formula over 12-month averages; in other months, keep the rate.
   - **`fixed`:** `economy.flat_tax.fixed_rate`.
2. **Store** both the result and its inputs (H, C, S*, T) in the snapshot, so that anyone can redo the calculation. The open-books page explains it in one paragraph.

**Tests:**
- the worked case: H = 1,000, C = 700, S* = 50, T = 20 → τ = 1 − (700 + 50 − 20)/1,000 = 0.27;
- clipping at 0.68;
- the fixed method;
- `test_hf09_waste_raises_the_tax` (adding written-off hours to H but not to C raises τ).

---

### - [ ] P09.T04 — `close_period`

**Read:** docs/03 section 7 (steps 1–10).
**Files:** `apps/macro/close.py`, `apps/macro/management/commands/close_period.py`, `apps/macro/jobs.py`, `apps/macro/tests/test_close.py`

**Do:**
1. **`close_period(year, month)`** runs the steps of docs/03 section 7 in order:
   1. status `closing`;
   2. hours by use (T01);
   3. the UNIQ flows;
   4. post `cancel` (fund1 → fund2) for Fund 1's whole balance, with reason "Period <YYYY-MM> closed: Fund 1 cancelled";
   5. outstanding UNIQ and months of spending;
   6. identities (T02);
   7. `catalogue.recompute_values()`;
   8. the next tax rate (T03);
   9. lights (T05) and world (T06);
   10. save the `MacroSnapshot`, set status `closed`, create or update the next period with `tax_rate = tax_rate_next` and `planned_hours` (from the plan, P11; until then the 3-month average), and publish.
2. **Idempotent:** if a snapshot exists and the period is `closed`, do nothing.
3. **`manage.py close_period [--period YYYY-MM]`:** by default, the month before today. Cron runs it on the 1st (docs/09).
4. **Payments posted on the 1st before the close runs** belong to the new period already (`current_period()` uses the date), so the old period is frozen by date.

**Tests:**
- a full month closes;
- running it twice changes nothing;
- the next period gets the computed tax rate;
- Fund 1 is 0 after the close.

---

### - [ ] P09.T05 — Warning lights

**Read:** docs/03 section 10 (the lights table).
**Files:** `apps/macro/lights.py`, `apps/macro/jobs.py`, `templates/partials/lights.html`, `apps/macro/tests/test_lights.py`

**Do:**
1. **`compute_lights(period) -> dict`.** For each light: `value`, `color` (`green`, `amber`, `red`, `grey`) and `text` (one plain sentence). The parameters are in `alarms.*`:
   - **unspent UNIQ:** (members' + former members' balances, without retirement accounts) ÷ members' average monthly spending over 6 months. Amber above `unspent_uniq_amber_months`, red above that × `unspent_uniq_red_multiple`.
   - **shelves:** order lines delivered by their due date ÷ lines due in the period. Waiting-list entries count as not served. Amber below `shelves_amber`, red below `shelves_red`.
   - **unsold products:** written-off value ÷ the value of advance and own-initiative lots made in the last 3 months. Amber above `unsold_amber`, red above `unsold_red`.
   - **euro reserve:** `tradefund.allocation.reserve_months()`. Amber below `euro_reserve_amber_months`, red below `euro_reserve_red_months`.
   - **idle shifts:** idle minutes ÷ session minutes. Amber and red at `idle_shifts_*`.
   - **street price:** `grey` with the text "Not measured yet: members have not decided what it is based on" while `alarms.street_price_enabled` is false.
2. **Per item:** `item_red(item)` is true when the item's own shelves ratio this period is below `shelves_red`. Replace the stub used by P05.T01 for the shortage cap.
3. **Update daily** too (a cheaper partial update for shelves and unspent UNIQ), so that the lights do not wait for the month's end.
4. **`lights.html`** shows the lights with colour words for colour-blind members. It appears on the home dashboard, `/open-books/` and the market.
5. **The credit line** (docs/03 section 2; book p. 58). At each close, compare the gross hours paid in the period with `Period.planned_hours`. If they are more than `planned_hours × (1 + economy.issue_tolerance_share)`:
   - open a `question` ticket of scope `all`, titled "More hours were paid than planned in <month>", with the two numbers and the five units whose hours grew most;
   - notify the elected auditors (P07.T09) and, from P11, the current planning group;
   - stop nothing: paying continues (HF-15).

   Skip the check while `planned_hours` is 0.

**Tests:**
- each light's thresholds; the street light stays grey; `item_red` turns on the shortage cap in `place_order`;
- `test_hf15_credit_line_warns_but_never_blocks`: 130 hours paid against 100 planned opens the ticket, and every hours entry is still paid; 115 hours opens nothing.

---

### - [ ] P09.T06 — "Are we on track?", the planning rate, attractiveness

**Read:** docs/03 sections 8 and 10; docs/02 section 5; `config/benchmarks/default_world_path.csv`.
**Files:** `apps/macro/world.py`, `apps/macro/views.py`, `apps/macro/templates/macro/on_track.html`, `apps/members/models.py` (Member `has_capitalist_job`, MemberPrivate `net_hourly_wage_eur`), `apps/macro/tests/test_world.py`

**Do:**
1. **Members can state, optionally,** "I have a capitalist job: yes/no" (on Member) and "My net hourly wage in euros" (private, in `MemberPrivate`).
2. **`world_metrics(period) -> dict`:**
   - **`outside_sales_per_member_eur`:** confirmed outside sales this month ÷ active members (0 until P10);
   - **`outside_growth_12m`;**
   - **`materials_eur_per_hour`:** euros paid for `recipe_input` purchases ÷ paid hours of production and service units;
   - **`tax_on_outside_sales_share`** (P10);
   - **`unsold_share`;**
   - **`can_live_without_job_share`:** members who say they have no capitalist job, or whose active benefit claim covers their basic bills, ÷ active members;
   - **`planning_rate_eur_per_hour`:** euros earned per outside-sales hour after the sellers' tax reserves, over `economy.planning_rate.measure_months`. Until 3 months of data exist, use `economy.planning_rate.fallback_eur_per_hour`. Replace the stub `macro.planning_rate()`.
   - **`attractiveness_estimate`:** the median, over members who stated a wage, of `(net UNIQ per hour × the € value of a UNIQ) ÷ wage`.
     - The € value of a UNIQ is estimated from offers that have an `outside_price`: Σ outside_price ÷ Σ value_total over those offers, weighted by members' purchases.
     - With fewer than 10 such members or 5 such offers, return None and mark it "not enough data".
     - Replace the stub `macro.attractiveness()`, marked `# OWNER-CHECK: estimate method`.
3. **The page `/on-track/`.** One row per condition of docs/02 section 5 and `targets.*`, with:
   - the real value;
   - the target;
   - the default world's value for the same month since launch (from `default_world_path.csv`, columns `export_revenue_per_member`, `tau`, `fill`, `can_live_without_job`, `overhang_months`, `members`, `reserve_months`). The file starts with three comment lines beginning with `#`: read it with `csv.DictReader` over the lines that do not start with `#`;
   - a word: "on track", "behind", or "far behind" (behind = below 75% of the default world's value; far behind = below 40%).

   A plain introduction explains the farmer picture (docs/02 section 1).

**Tests:**
- the planning-rate fallback, and then the measured rate;
- attractiveness returns None with too few data;
- the page reads the benchmark CSV and shows month 12's values.

---

### - [ ] P09.T07 — The equal pension and other transfers

**Read:** docs/03 section 6.
**Files:** `apps/macro/transfers.py`, `apps/macro/models.py` (TransferPlan, ActiveMonth), `apps/members/services.py` (`has_reached_pension_age`), `apps/macro/jobs.py`, `apps/macro/tests/test_pension.py`

**Do:**
1. **`ActiveMonth`:** `member`, `month`, `kind` (`hours`, `care`, `illness`).
   - The monthly close records `hours` for every member with at least `economy.pension.active_month_min_hours` approved hours that month.
   - `care` and `illness` months are added by an approved `recognised_month` ticket (1 confirmer; minimal evidence, never a diagnosis).
2. **`has_reached_pension_age(member)`:** uses the birth date in `MemberPrivate` and `economy.pension.age`. A missing birth date → False, and the member is asked to add it.
3. **`pension_eligible(member)`:** status `member` (or `former`? No: only members; `# OWNER-CHECK` for former members); `economy.pension.enabled`; at least `economy.pension.qualifying_active_months` active months; and (pension age reached, or an approved `pension_unable_to_work` ticket).
4. **`pension_amount(period)`:** `economy.pension.share_of_median_net` × the median monthly net UNIQ income of members with an `hours` active month in the last 12 months. The yearly plan may store an explicit amount instead (P11).
5. **Monthly job `macro.pay_pensions`** (after the close): post `transfer` fund2 → member, with reason "Equal pension for <YYYY-MM>", for each eligible member. The total feeds `T` in the next tax balance.
6. **`TransferPlan`:** for other transfers decided by tickets (care): `member`, `monthly_amount`, `from_month`, `to_month`, `ticket`. The same monthly job posts them.
7. **The `pension_unable_to_work` ticket:** 4 confirmers; the evidence file is viewable by the seats only, and is shredded 30 days after the decision.

**Tests:**
- 35 active months → not eligible; 36 → eligible;
- the amount is 60% of the median;
- `test_hf01_transfers_only_from_fund2`;
- the evidence file is unreadable after 30 days.

---

### - [ ] P09.T08 — Retirement suggestions and payouts

**Read:** docs/03 section 5.
**Files:** `apps/macro/jobs.py`, `apps/ledger/services.py`, `apps/macro/tests/test_retirement_suggest.py`

**Do:**
1. **When the unspent-UNIQ light is amber or red** at a close, and `economy.retirement.suggest_on_alarm` is true, notify each member whose savings are above their target: "Unspent UNIQ are piling up. You could move <suggest_share × excess> UNIQ into your retirement account; it stays yours." The notice has a one-click button that goes through `sensitive_action`. **Nothing moves without the member's click.**
2. **Payouts:**
   - after pension age, a member can start a payout plan: each month, a `retirement_out` of the balance ÷ the remaining months (out of `economy.retirement.payout_months`);
   - they may stop or restart it at any time;
   - P02.T09's early-withdrawal limit no longer applies after pension age.

**Tests:**
- suggestions go out only when the light is amber or red;
- the payout plan pays equal parts;
- `test_hf08_nothing_moves_without_the_member`.

---

### - [ ] P09.T09 — Open books per period, dashboard, data for forecasts

**Read:** docs/03 section 11.
**Files:** `apps/macro/views.py`, `apps/ledger/templates/ledger/open_books.html`, `templates/core/home.html`, `apps/macro/models.py` (Forecast), `apps/macro/tests/test_open_books_periods.py`

**Do:**
1. **`/open-books/`, per closed period:**
   - hours by use, issued, tax rate (with its H, C, S*, T);
   - spent, cancelled, outstanding, months of spending;
   - lights, identities (all zero, or a red mark);
   - a CSV of all snapshots.
2. **The home dashboard** for a member:
   - "My month": hours, gross, tax and net;
   - "My orders";
   - "Tickets for me";
   - the lights.
3. **`/open-books/forecast-data.csv`:**
   - months since launch, members, outside sales per member, materials per hour, unsold share, tax rates, lights, the world metrics;
   - all current parameter values.

   No personal data. Experts use it to run `../Unicorn-simulation`.
4. **`Forecast`:**
   - `ticket`, `file` (PrivateFile, public to members), `author`;
   - `goals` (JSON: attractive, growing, independent, stable, each true or false), `can_live_y10`, `can_live_y20`, `can_live_y30`;
   - `note`, `created_at`.

   Plan proposals and hard-frame tickets show their forecasts in a small table.

**Tests:** the CSV has no member numbers; a forecast attaches to a ticket and is shown.

---

## Acceptance check for phase 09

1. Simulate a month with the phase 05 example data plus one pension.
2. `close_period` cancels Fund 1, stores a snapshot with all identities at 0, computes the next tax rate by the formula, and shows it on `/open-books/` with its inputs.
3. The lights show, and the street light is grey.
4. `/on-track/` compares with the default world's month 1.
5. Add a line to PLAN.md "Progress".
6. **The founders' pilot can start here:** do plan/phase_14_security_privacy.md tasks T01, T03, T04 and T06–T09, then plan/phase_15_deploy_virtualmin.md tasks T01–T07 on the staging server (PLAN.md).
