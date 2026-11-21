# Phase 03 — Units, working councils and hours

**Goal:** members open units, join units, form working councils with their own rules, rotate the responsible, record hours, and get paid when the council approves them.
**Read first:** docs/06 sections 1–3, docs/05 section 6, docs/01 rules HF-2, HF-9, HF-10, HF-17, HF-20.

---

### - [ ] P03.T01 — The unit

**Files:** `apps/units/` (new app), `apps/units/models.py`, `apps/units/migrations/0002_coordination_unit.py`, `apps/units/tests/test_unit.py`

**Do:**
1. **`Unit`:**
   - `name` (CharField(80)), `slug` (unique);
   - `kind`: `production`, `service`, `social`, `courier`, `coordination`;
   - `mode`: `continuous`, `on_order`, `seasonal`, `project`;
   - `status`: `trial`, `open`, `paused`, `dormant`, `closing`, `closed`, `merged`;
   - `trade_code` (CharField(16), blank), `description` (Text);
   - location: `town` (CharField(80)), `postcode` (CharField(12)), `country` (CharField(2)), `lat` and `lng` (Decimal(9,6), null; set in P12);
   - cover area: `cover_radius_km` (Decimal, default from `logistics.default_cover_radius_km`), `cover_postcodes` (JSON list);
   - `licence_kind_required` (CharField, blank: one of the `Licence.kind` values), `insurance_confirmed` (bool);
   - `created_by` (Member), `opened_at`, `trial_until`, `closed_at`, `merged_into` (FK self, null), `last_activity_at`.
2. **Data migration:** creates the single system unit "Unicorn coordination" (`kind = coordination`, `status = open`, slug `coordination`).
3. **`coordination_unit()`** service.

**Tests:** there is exactly one coordination unit; the slug is unique.

---

### - [ ] P03.T02 — Workers and the working council

**Read:** docs/05 section 6 ("Members", "Members of several units").
**Files:** `apps/units/models.py` (UnitMembership, JoinRequest), `apps/units/services.py`, `apps/units/views.py`, `apps/units/templates/units/*.html`, `apps/units/tests/test_workers.py`

**Do:**
1. **Models:**
   - `UnitMembership`: `unit`, `member`, `is_council` (bool, default True), `joined_at`, `left_at` (null). Active = `left_at` is null. Unique active (`unit`, `member`).
   - `JoinRequest`: `unit`, `member`, `message`, `status` (`open`, `accepted`, `declined`), `decided_by`, `decided_at`.
2. **Services:**
   - `workers(unit)` and `council_members(unit)` (active, `is_council`);
   - `has_council(unit)` is true when the unit has 2 or more active workers (HF-20);
   - `request_to_join(unit, member, message)`;
   - `decide_join(request, decider, accept)`: the decider must be a council member, or the single worker of a one-person unit. With admission `open` in the council rules, requests are accepted at once;
   - `leave_unit(member, unit)`.

   Only verified members can join units (HF-13).
3. **When the second worker joins,** call `council_rules.create_default(unit)` (T03).
4. **Pages:** the unit page lists its workers by display name, plus a "Request to join" button and the join requests (for council members).

**Tests:**
- `has_council` turns true with the second worker;
- a non-member cannot decide a join request;
- a member can work in two units at once.

---

### - [ ] P03.T03 — Council rules: the optional custom internal contract

**Read:** docs/05 section 6 (the table of rules).
**Files:** `apps/units/models.py` (CouncilRules), `apps/units/council_rules.py`, `apps/units/templates/units/rules.html`, `apps/units/tests/test_rules.py`

**Do:**
1. **`CouncilRules`:**
   - `unit`, `version` (int);
   - `decision_rule` (`consensus`, `majority`, `two_thirds`), `quorum` (Decimal), `vote_days` (int), `rotation_months` (int);
   - `hours_approval` (`any_other_member`, `two_members`, `responsible_or_other`), `admission` (`open`, `council_approves`);
   - `clauses_md` (Text: the free clauses);
   - `adopted_at`, `adopted_by` (FK CouncilDecision, null for version 1);
   - unique (`unit`, `version`).

   The current rules = the highest version.
2. **`create_default(unit)`:** version 1 from `governance.council.*` parameters.
3. **`validate_clauses(text) -> list[str]`:** refuses clauses that try to break the hard frame. A simple word check is enough here: the words "pay", "bonus", "extra UNIQ" and "per hour" together trigger the message "Clauses cannot change pay: every hour pays the same (HF-2)". Other hard-frame questions are decided by people through flags (P06).
4. **Signing:** every worker signs the current version (a `Signature` with the `council_rules` template, `context={"unit": id, "version": n}`). The rules page shows who has signed, and reminds those who have not.
5. **Changing the rules** happens through a council decision (T04) whose action creates the next version.

**Tests:**
- default rules come from the parameters;
- `test_hf02_clause_cannot_change_pay`;
- a new version needs an approved council decision.

---

### - [ ] P03.T04 — Council decisions

**Read:** docs/05 section 6 ("Decisions").
**Files:** `apps/units/models.py` (CouncilDecision, CouncilVote), `apps/units/services.py`, `apps/units/templates/units/decision*.html`, `apps/units/tests/test_decisions.py`

**Do:**
1. **Models:**
   - `CouncilDecision`: `unit`, `title`, `text`, `kind` (`production`, `admission`, `rules_change`, `outside_prices`, `close_unit`, `other`), `payload` (JSON, e.g. the new rules for `rules_change`), `status` (`open`, `approved`, `rejected`), `opens_at`, `closes_at` (`opens_at + vote_days`), `result` (JSON).
   - `CouncilVote`: `decision`, `member`, `vote` (`yes`, `no`, `abstain`), `voted_at`; unique (`decision`, `member`).
2. **`tally(decision)`.** Run it when all council members have voted, or when `closes_at` has passed (a daily job `units.close_decisions`).
   - The quorum is turnout ≥ `quorum` × council size.
   - `majority`: yes > no.
   - `two_thirds`: yes ≥ 2/3 of yes + no.
   - `consensus`: no "no" votes and at least one "yes".

   Then run the decision's action: `rules_change` creates the new `CouncilRules` version; `close_unit` calls `close_unit` (T06); the other kinds just record the result.
3. **In a one-person unit**, decisions are not needed: its member's choices take effect directly.
4. Phase 06 wraps these decisions in tickets of scope "unit". Keep the services independent of tickets.

**Tests:**
- majority, two-thirds and consensus cases;
- a failed quorum is rejected;
- a non-council member cannot vote.

---

### - [ ] P03.T05 — The responsible and rotation

**Read:** docs/05 section 6 ("The responsible").
**Files:** `apps/units/models.py` (Responsibility), `apps/units/services.py`, `apps/units/jobs.py`, `apps/units/tests/test_rotation.py`

**Do:**
1. **`Responsibility`:** `unit`, `member`, `starts_at`, `ends_at` (null while current), `how` (`founder`, `rotation`, `vote`, `handover`), `declined_by` (JSON list of member ids who declined this turn).
2. **The first responsible** is the unit's creator (`how = founder`).
3. **Job `units.rotate`** (in `daily`). For every unit with a council whose current responsibility started more than `rotation_months` ago:
   1. the next responsible is the active council member with the fewest total days as responsible in this unit (ties: earliest `joined_at`), skipping anyone who declined this turn;
   2. end the current responsibility, start the new one, and notify both.
4. **Declining:** a member can decline the turn on their unit page; then the next one is chosen at once.
5. **Leaving:** when the responsible leaves the unit or Unicorn, hand over at once (`how = handover`). Add a `LEAVE_CHECKS` entry that performs this handover instead of blocking.
6. **`responsible(unit)`** service. The responsible's special rights (editing the unit profile, offers and recipes) are checked with `can_edit_unit(member, unit)`: the responsible, or any worker if the council rules say so (default: the responsible and any council member).

**Tests:**
- rotation after 6 months picks the member with the fewest days;
- declining passes the turn on;
- leaving hands over.

---

### - [ ] P03.T06 — Opening, pausing and closing a unit

**Read:** docs/06 section 2; docs/05 section 9 ("Opening a unit"); docs/01 HF-15, HF-17.
**Files:** `apps/plan/` (new app, only `check.py` for now), `apps/units/services.py`, `apps/units/forms.py`, `apps/units/views.py`, `apps/units/templates/units/open.html`, `apps/units/tests/test_open_close.py`

**Do:**
1. **The plan check stub `apps/plan/check.py`:**

   ```python
   @dataclass
   class CheckPoint: color: str; text: str          # "green" | "amber" | "red"
   @dataclass
   class CheckResult:
       points: list[CheckPoint]
       @property
       def color(self): return "red" if any(p.color == "red" for p in self.points) else \
                               "amber" if any(p.color == "amber" for p in self.points) else "green"
   def check(request: dict) -> CheckResult:
       # Phase 11 replaces this with the full plan check (docs/06 section 2).
       return CheckResult([CheckPoint("green", _("There is no yearly plan yet, so nothing in it is against this."))])
   ```

2. **`open_unit(member, data) -> Unit`.** Hard-frame checks come first and **block** (HF-17, HF-13):
   - the member is verified;
   - if `licence_kind_required` is set, the member has that verified licence;
   - if the kind is `service` or `social`, `insurance_confirmed` is true.

   Then run `plan.check.check({"type": "open_unit", ...})`:
   - **green or amber:** status `trial`, `trial_until = now + units.trial_months`, and the creator becomes the first worker and responsible. Record an `AuditEvent` with the check result.
   - **red:** status `paused` with the note "waiting for random confirmers" (the confirmers are added in P06).

   The automatic check never refuses (HF-15).
3. **Trial ends:** a daily job `units.end_trials` moves `trial` units to `open` after `trial_until`.
4. **`close_unit(unit, reason)`:**
   - allowed by an approved `close_unit` council decision, or by the single worker of a one-person unit;
   - before closing it calls `CLOSE_CHECKS` (P05 adds "open production orders must be finished or moved");
   - status `closing`, then `closed` when the checks pass.
5. **Dormant:** a daily job `units.dormant` sets units with no hours, orders or bookings for `units.dormant_after_months` to `dormant`; any worker can reopen with one click.
6. **The form** follows docs/06 section 2, with plain help texts. "Does this trade need a licence?" is a list of the licence kinds, with "No".

**Tests:**
- `test_hf17_licensed_trade_needs_verified_licence`;
- `test_hf17_service_needs_insurance`;
- `test_hf15_red_check_does_not_refuse` (status paused, not an error);
- a green check opens the unit at once as `trial`.

---

### - [ ] P03.T07 — Recording hours

**Read:** docs/06 section 3 ("Recording").
**Files:** `apps/units/models.py` (HoursEntry, TimerSession), `apps/units/services.py`, `apps/units/forms.py`, `apps/units/views.py`, `apps/units/templates/units/hours*.html`, `apps/units/tests/test_hours_record.py`

**Do:**
1. **`HoursEntry`:**
   - `member`, `unit`, `date`, `minutes` (PositiveInteger, 1–1440);
   - `activity`: `order`, `booking`, `shift`, `project`, `coordination`, `learning`, `own_initiative`, `other`;
   - `ref_type` and `ref_id` (blank), `note`;
   - `status`: `draft`, `submitted`, `approved`, `rejected`, `pending_sale`, `paid`;
   - `needs_extra_approval` (bool), `rejection_reason`;
   - `period` (FK, set from `date`), `transaction` (FK ledger Transaction, null), `created_at`, `submitted_at`.
2. **`TimerSession`:** `member`, `unit`, `started_at`. "Stop" creates a draft `HoursEntry` with the rounded minutes.
3. **`submit_hours(entry)`:**
   - the member must be an active worker of the unit;
   - the date must not be in the future, and its period must be `open`;
   - if the member's Unicorn minutes in that ISO week, over all units, would exceed `membership.max_unicorn_hours_per_week × 60`, set `needs_extra_approval` (docs/06 section 3, "Weekly limit").

   Status becomes `submitted`. In a one-person unit, `approve_hours` (T08) is called at once.
4. **Pages:** "My hours" (timer, a quick entry form, the list by week with statuses); a unit's hours page for council members.

**Tests:**
- hours in a closed period are refused;
- the weekly limit sets `needs_extra_approval`;
- a non-worker cannot record hours for the unit.

---

### - [ ] P03.T08 — Approving and paying hours

**Read:** docs/06 section 3 ("Approving", "Paying"); docs/03 section 2; docs/01 HF-2, HF-20.
**Files:** `apps/units/models.py` (HoursApproval), `apps/units/services.py`, `apps/units/views.py`, `apps/units/templates/units/approve.html`, `apps/units/tests/test_hours_pay.py`

**Do:**
1. **`HoursApproval`:** `entry`, `approver` (Member), `approved_at`, `reason` (needed when `needs_extra_approval`).
2. **`approve_hours(entry, approver=None)`**, inside `transaction.atomic()`:
   - **Coordination unit:** approved by the system (`approver=None`), only when called by the code that recorded the act (reviews, tasks).
   - **One-person unit:** approved by the system.
   - **Unit with a council** (HF-20): the approver must be an active council member and **not the entry's member**. Rules:
     - `any_other_member`: one approval is enough;
     - `two_members`: two approvals from two different members;
     - `responsible_or_other`: one approval from the responsible, or two from others.
     - With `needs_extra_approval`, two approvals with reasons are needed under every rule.
   - Once enough approvals exist: if `activity == own_initiative`, the status becomes `pending_sale` (paid in P05 when the products sell). Otherwise call `pay_hours(entry)`.
3. **`pay_hours(entry)`:**
   1. `gross = minutes_to_uniq(entry.minutes) × get_param("economy.uniq_per_hour")`;
   2. post `hours_pay` (fund2 → member, reason "Paid for <h:mm> at <unit name> on <date>");
   3. post `tax` (member → fund2, `uniq(gross × period.tax_rate)`, reason "Flat tax <rate>%");
   4. set `entry.transaction` and status `paid`.
4. **`reject_hours(entry, approver, reason)`:** status `rejected`, and the member is notified with the reason.
5. **Batch approval page** for council members: submitted entries with tick boxes, behind `sensitive_action`.
6. **The shortage bonus stays off:** `pay_hours` reads `economy.shortage_bonus.enabled`. When it is false (the default), there is no bonus. Bonus code is not written now (phase 16), so the branch only asserts that it is false.

**Tests:**
- `test_hf20_own_hours_cannot_be_self_approved`;
- `test_hf20_unapproved_hours_are_not_paid`;
- `test_hf02_same_pay_per_hour_in_every_unit` (two units, two members, same minutes, same gross);
- `test_hf09_tax_is_one_rate_for_everyone`;
- `two_members` needs two approvers;
- one-person units are paid at once;
- own-initiative hours become `pending_sale` without a payment.

---

### - [ ] P03.T09 — Hours pages and reports

**Files:** `apps/units/views.py`, `apps/units/templates/units/report.html`, `apps/units/tests/test_reports.py`

**Do:**
1. **A unit's monthly report** (council members): hours by worker, activity and status, with a CSV.
2. **"My hours":** totals per month (gross, tax, net) and per unit.
3. **The public unit page:** total approved hours per month (no names), the number of workers, and the open offers (P04).

**Tests:** the report sums match the entries; the public page shows no names next to hours.

---

## Acceptance check for phase 03

1. Two verified members open a unit: the first opens it, and the second joins and is accepted.
2. The council gets default rules, and both sign them.
3. Member A records 2 h 30 min, and member B approves.
4. Member A's UNIQ page shows +2.5000 gross and the tax at the period's rate.
5. A's own approval is refused.
6. All `test_hf02_`, `test_hf09_`, `test_hf15_`, `test_hf17_` and `test_hf20_` tests pass.
7. Add a line to PLAN.md "Progress".
