# Phase 11 — The yearly plan

**Goal:**
- The public creates the plan through tickets.
- A randomly drawn planning group, advised by union experts, drafts 2–3 whole plans that the engine checks.
- All members rank them, and the winner sets the shares, budgets, investments, focus and closures for the period.
- The full plan check replaces the stub.

**Read first:** docs/05 section 8, docs/06 section 2, docs/03 sections 4 and 11, docs/01 rules HF-15 and HF-16.

---

### - [x] P11.T01 — Plan periods and the default plan

**Read:** docs/05 section 8 ("The first plan"); `config/defaults.yaml` (`plan.*`, `economy.*`).
**Files:** `apps/plan/models.py` (PlanPeriod, PlanVariant, BudgetLine, InvestmentItem, FocusItem, ClosureItem), `apps/plan/defaults.py`, `apps/plan/tests/test_periods.py`

**Do:**
1. **Models:**
   - `PlanPeriod`: `starts_on`, `ends_on` (`plan.period_years` later), `status` (`proposals`, `drafting`, `comments`, `voting`, `adopted`, `running`, `closed`), `adopted_variant` (FK, null), `referendum` (FK, null).
   - `PlanVariant`:
     - `period`, `name`, `summary_md`;
     - `parameters` (JSON: plan-tier keys → values);
     - `planned_hours_per_month` (JSON list, one per month), `expected_euros_in_per_month` (JSON);
     - `check` (JSON: the engine's result), `forecast` (FK macro.Forecast, null), `is_default` (bool).
   - `BudgetLine`: `variant`, `category`, `trade_code` (blank), `hours`, `eur`. The categories are the book's list (p. 94) plus Unicorn's own: `public_services`, `education_research_culture`, `social_security`, `health_environment_sport`, `housing_regional`, `food_agriculture`, `water_energy_trade`, `transport_communication`, `financial_management`, `tools`, `materials`, `benefits`, `operations`, `reserve`.
   - `InvestmentItem`: `variant`, `title`, `item` (null), `trade_code`, `unit` (null), `eur`, `hours`, `priority` (int).
   - `FocusItem`: `variant`, `item` (null), `trade_code`, `text`.
   - `ClosureItem`: `variant`, `item` (null), `trade_code`, `unit` (null), `from_date`, `hearing_until`.
2. **`defaults.build_default_variant(period)`:**
   - `parameters` = the current values of all `plan`-tier parameters;
   - budget lines from the trailing 12 months (or zeros at launch);
   - empty investment, focus and closure lists;
   - `is_default = True`.
3. **The founders' first plan:** a command `start_first_plan` creates the first period and the default variant, and schedules a yes/no referendum among members ("Adopt the default plan from the simulation?"). On yes, the period is adopted and its parameters are applied (T07).

**Tests:** the default variant copies the plan-tier parameters; the first-plan referendum adopts it.

---

### - [x] P11.T02 — The full plan check

**Read:** docs/06 section 2 (the table of points).
**Files:** `apps/plan/check.py`, `apps/plan/tests/test_check.py`

**Do:**
1. **Replace the stub with the real points.** Each returns a `CheckPoint` with one plain sentence:
   - **Closure list:** the request's item, trade or unit is on the running plan's closure list → red.
   - **Euros:** the request's euros (one-off plus 12 × monthly) compared with what is left of the relevant budget line this year (by `trade_code`, then by category):
     - fits → green;
     - fits, but `reserve_months()` is below `alarms.euro_reserve_amber_months` → amber;
     - does not fit, or the reserve is red → red.
   - **Scarce inputs:** any Unicorn input whose supplier offer has a red item light → amber.
   - **Demand nearby (services):** a matching `SearchMiss`, waiting list or "wanted" mark in the area → green; none → amber with "No visible demand yet; it may still be worth trying".
   - **Plan focus:** the item or trade is on the focus list → a green point "This is a focus of the plan".
2. **Without a running plan,** keep the stub's single green point.
3. **Callers stay unchanged:** open unit, publish offer, purchase.

**Tests:**
- a closure-list trade is red;
- a request beyond its budget line is red;
- a request that fits with a low reserve is amber;
- `test_hf15_check_never_rejects` (`check()` never raises and never changes data).

---

### - [x] P11.T03 — Plan proposals

**Read:** docs/05 section 8 (the calendar, "Proposals").
**Files:** `apps/plan/models.py` (PlanProposal), `apps/tickets/types.py`, `apps/plan/views.py`, `apps/plan/templates/plan/proposals.html`, `apps/plan/tests/test_proposals.py`

**Do:**
1. **`PlanProposal`:**
   - `ticket` (type `plan_proposal`), `period`;
   - `kind` (`invest`, `focus`, `close`, `share_change`, `budget_change`, `parameter_change`);
   - `payload` (JSON: the fields of the matching plan item, or `{key, value}`);
   - `quick_check` (JSON), `status` (`open`, `included`, `left_out`), `left_out_reason`.
2. **Proposals are accepted** only between `plan.calendar.proposals_open` and `proposals_close` (each year's dates). Outside that window the form explains when the window opens, and offers a `referendum_request` for urgent matters.
3. **The quick check** on creation: the hours and euros involved, and the plan check (T02). An expert may attach a `Forecast` (P09.T09).
4. **`/plan/`** shows the period's status and dates, and the proposals by kind, with their checks and forecasts.

**Tests:** outside the window, proposals are refused with the dates; a proposal stores its quick check.

---

### - [x] P11.T04 — The planning group

**Read:** docs/05 section 8 (the row for 1 September).
**Files:** `apps/plan/models.py` (PlanningGroup, GroupSeat, ExpertAdviser), `apps/plan/services.py`, `apps/plan/jobs.py`, `apps/plan/tests/test_group.py`

**Do:**
1. **Models:**
   - `PlanningGroup`: `period`, `confirmation` (FK tickets.Confirmation: reuse the verifiable draw), `created_at`.
   - `GroupSeat`: `group`, `member`, `accepted` (bool, null), `replaced` (bool).
   - `ExpertAdviser`: `group`, `member`, `nominated_by_union_id` (int; the FK comes in P13), `statement`.
2. **On `plan.calendar.group_drawn`** (a daily job checks the date):
   - size = `plan.group_size`, or, with fewer than 3 × `group_size` active members, `max(plan.group_min, ceil(plan.group_share_if_small × members))`;
   - draw with `tickets.draw.draw` on a system ticket `plan_group <year>`;
   - members have 7 days to accept or decline; those who decline are replaced;
   - members of the previous year's group are excluded.
3. **Expert advisers:** until unions exist (P13), any member may volunteer as an adviser for 14 days. The group approves at most `plan.experts_max` advisers by majority. Advisers can post analyses and answer questions, and **cannot vote** in the group.
4. **Group work is paid:** members record hours in the coordination unit (`ref = planning group`), approved by the system up to `plan.group_hours_cap_per_week` per member and week.

**Tests:**
- the size rule for 25 members (9) and for 1,000 members (15);
- last year's members are excluded;
- an adviser's vote is refused;
- hours above the weekly cap are not approved.

---

### - [x] P11.T05 — Drafting 2–3 whole plans, checked by the engine

**Read:** docs/05 section 8 ("A whole plan contains"); docs/03 section 4.
**Files:** `apps/plan/engine.py`, `apps/plan/views.py`, `apps/plan/templates/plan/variant_editor.html`, `apps/plan/tests/test_variants.py`

**Do:**
1. **The group's workspace** (seats only):
   - a forum thread;
   - a list of all proposals, each with "include in variant A, B or C";
   - a variant editor for the parameters (only `plan`-tier keys, within their bounds), the budget lines, and the investment, focus and closure lists;
   - "Copy variant" and "Compare variants".
2. **The group's decisions** (which proposals go in, which variant is final) are made by majority of the seats, through council-style votes stored as `CouncilDecision`-like rows on the group. A small generic `GroupDecision` model is enough.
3. **`engine.check_variant(variant) -> dict`:**
   - **hours:** Σ budget hours and investment hours per month ≤ the expected hours (members' offered hours trend: the 3-month average of paid hours × 1.1);
   - **euros:** Σ euro lines and investments ≤ expected euros in (12-month trend of set-asides and donations) + the reserve above target;
   - **bounds:** every parameter is within its hard bounds (HF-16);
   - **budget shares:** the shares match the parameters (social, accumulation, outside cap);
   - **expected flat tax:** the result of the tax balance formula with the variant's shares, shown so members see the tax each plan implies;
   - **issues:** a list of plain sentences.

   A variant with issues cannot be submitted.
4. **At `plan.calendar.drafting_close`,** the group must submit between `plan.variants_min` and `plan.variants_max` variants (HF: 2–3, owner's decision). Proposals left out get `left_out_reason`.
5. **Forecasts:** each variant should get a `Forecast` from experts before the vote. Missing forecasts are shown as "no forecast" (they do not block).

**Tests:**
- a variant over the euro limit has an issue;
- fewer than 2 variants cannot be submitted;
- a parameter outside its bounds is refused;
- the implied tax is shown.

---

### - [x] P11.T06 — Comments and the ranked vote

**Read:** docs/05 section 8 (16 October to 15 November).
**Files:** `apps/plan/services.py`, `apps/plan/templates/plan/vote.html`, `apps/plan/tests/test_plan_vote.py`

**Do:**
1. **From `drafting_close` + 1 to `comments_close`:** every member can comment on the variants, and the group may revise them (each revision is checked again).
2. **On `vote_open`:** `votes.schedule_referendum(method="ranked_irv", options=[variant names], days=…, quorum=governance.referendum.quorum)`. The referendum brief shows, per variant:
   - its summary;
   - its implied flat tax;
   - its main budget lines and its lists;
   - its forecast;
   - the differences from the current plan.
3. **On `adoption`:**
   - the IRV winner becomes `adopted_variant`;
   - if the quorum failed, the current plan continues for `plan.quorum_fail_extension_months` months, and a new vote is scheduled.

**Tests:** three variants and the IRV winner; a failed quorum extends the current plan.

---

### - [x] P11.T07 — Applying the adopted plan

**Read:** docs/05 section 8 ("A whole plan contains", "During the year", "Closing what the plan closes").
**Files:** `apps/plan/apply.py`, `apps/plan/jobs.py`, `apps/plan/tests/test_apply.py`

**Do:**
1. **On `period_start`,** `apply_plan(period)`:
   - for each key in `adopted_variant.parameters`, call `set_param(key, value, decided_by=<the referendum's ticket>, decided_tier="plan", reason="Yearly plan <year>")`;
   - set each `Period.planned_hours` from `planned_hours_per_month`;
   - status `running`.
2. **Investment items** become approved purchase requests or `project` units, as each item says, ordered by priority. They are funded through the allocation order (P08.T10, step 2 or 6).
3. **Focus items** fill the needs board's "Plan focus" section (P05.T12).
4. **Closure items:**
   - on `hearing_until − 30 days`, notify the affected councils and open a `close_unit` hearing ticket for comments;
   - on `from_date`, the units go `closing` (their orders finish), and offers of closed items are retired;
   - workers get "Needs that match your skills" highlighted.
5. **Emergency changes:** a red light lasting `plan.emergency_red_months` allows the planning group to propose an emergency change, approved by 4 confirmers (all yes). Other mid-year changes go by referendum.

**Tests:**
- applying sets the parameters with the plan tier and the referendum ticket;
- a closure item closes its unit after the hearing;
- an emergency change needs the red light.

---

### - [x] P11.T08 — Three-year plans (switch only)

**Read:** docs/05 section 8 ("Later: three-year plans").
**Files:** `apps/plan/services.py`, `apps/plan/tests/test_three_year.py`

**Do:**
1. **When `plan.period_years` is above 1** (changed by referendum), new periods span that many years, and `planned_hours_per_month` covers all of their months.
2. **A second "long-term group"** is drawn for the multi-year part, with no member in common with the yearly group (book p. 105: those who approve long-term plans are not those who draft short-term plans). In this phase only: the model fields and the draw rule. The drafting UI is the same as for one year.

**Tests:** with `period_years = 3`, the period spans 36 months; the two groups share no member.

---

## Acceptance check for phase 11

1. Run the first-plan referendum: the default plan is adopted.
2. Advance the clock with `freezegun` through one plan year:
   - 3 proposals are filed;
   - a group of 9 is drawn (25 members);
   - 2 variants are drafted and pass the engine check;
   - a ranked vote picks one;
   - on 1 January its parameters apply, with history rows that cite the referendum ticket.
3. A proposal to close a trade adds the trade to the closure list, and opening a unit in that trade gives a red check.
4. Add a line to PLAN.md "Progress".
