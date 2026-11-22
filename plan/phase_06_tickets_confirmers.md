# Phase 06 — Tickets, random confirmers, panels, flags and mediation

**Goal:** every request and decision becomes a ticket. Random confirmers, all four of whom must say yes, approve actions after reading a brief. A single "no" goes to a panel of 12. Flags and mediation work. The earlier flows (red plan checks, licences, hours reviews, disputes, council decisions) move onto tickets.
**Read first:** docs/05 sections 1–3, 5, 9; docs/01 rules HF-13, HF-15, HF-16.

**Owner decision 2026-11-22 (docs/11):** hours of a person working alone in a unit are confirmed by the person who received the service (if in Unicorn); for production, 2 random members audit the worker's profile and confirm. Replace the automatic approval of one-person units (P03.T08) when random confirmers exist allows it.


---

### - [x] P06.T01 — Tickets and their types

**Read:** docs/05 section 2.
**Files:** `apps/tickets/` (new app), `apps/tickets/models.py` (Ticket), `apps/tickets/types.py`, `apps/tickets/services.py`, `apps/tickets/tests/test_tickets.py`

**Do:**
1. **`Ticket`:**
   - `number` (CharField(9), unique, `T-000001`…), `type` (a key of `types.TYPES`), `title`, `body_md`;
   - `author` (Member, null for system tickets);
   - scope: `scope` (`unit`, `union`, `local`, `all`), `scope_unit` (FK Unit, null), `scope_union_id` (int, null; the FK comes in P13), `scope_area` (CharField(12), blank);
   - `brief_md` (at most 500 words, checked), `check_question`, `check_choices` (JSON list of 3), `check_correct` (int 0–2);
   - `plan_check` (JSON), `decision_method` (`none`, `auto`, `council`, `confirmers`, `panel`, `referendum`, `plan`, `mediation`);
   - `status` (`draft`, `open`, `confirming`, `panel`, `petition`, `referendum`, `approved`, `rejected`, `in_action`, `done`, `withdrawn`, `expired`);
   - `action` (CharField(40), blank), `action_payload` (JSON), `action_result` (JSON);
   - `petition_until` (null), `created_at`, `decided_at`.
2. **`types.py`:** a dict `TYPES` with one entry per row of the table in docs/05 section 2: `key`, a plain-English `label`, the default `decision_method`, the `action` name (or None), `confirmers` (seat count; default `governance.confirmers.size`, 2 for `verify_licence`, 1 for `one_person_check`), and whether a brief and check question are required.

   Add the internal types used by earlier phases: `verify_licence`, `one_person_check`, `audit_failure`, `post_check_unit`, `duplicate_suspected`, `offer_red_check`.
3. **`create_ticket(type, author, title, body, scope=..., brief=..., check=..., action_payload=...)`:**
   - validates the brief and check question where required;
   - gives the next number in a transaction (`select_for_update` on a `TicketCounter` single-row table);
   - records an `AuditEvent`.
4. **`types.py` says at the top:** "Changing a type's decision method is a referendum matter (docs/05)."

**Tests:**
- numbers are consecutive;
- a type that needs a check question refuses a ticket without one;
- a brief over 500 words is refused.

---

### - [x] P06.T02 — Comments, notifications, ticket pages

**Files:** `apps/tickets/models.py` (Comment, HelpfulMark, Notification), `apps/tickets/views.py`, `apps/tickets/templates/tickets/*.html`, `apps/core/notify.py`, `apps/tickets/tests/test_pages.py`

**Do:**
1. **Models:**
   - `Comment`: `ticket`, `author`, `parent` (null), `body_md`, `created_at`, `edited_at`. Editing is allowed within 15 minutes, and edits are recorded as `AuditEvent`s.
   - `HelpfulMark`: `comment`, `member`, `created_at`; unique pair; not on one's own comment.
   - `Notification`: `member`, `text`, `url`, `created_at`, `read_at`.
2. **`core.notify.notify(member, text, url, email=False)`:** creates a `Notification`, and sends an email if `email` is true or the member chose "email me everything". Plain text only.
3. **Pages:**
   - `/tickets/`: tabs "For me" (seats to answer, my tickets, my units' tickets), "All", "Search", plus filters by type and status;
   - `/tickets/T-000123/`: brief, body, plan check (colours and sentences), status history, seats (anonymised as "Confirmer 1–4" until decided, then display names unless the member chose to stay anonymous), comments with helpful marks;
   - the "New ticket" form: choose a type in plain words, then a type-specific form.
4. **The nav bell** shows unread notifications.

**Tests:** comments thread; a helpful mark on one's own comment is refused; notifications are created.

---

### - [x] P06.T03 — The secretariat: routing

**Read:** docs/05 section 2 ("The secretariat").
**Files:** `apps/tickets/routing.py`, `apps/tickets/tests/test_routing.py`

**Do:**
1. **`route(ticket)`.** Runs when a ticket is opened. It sets `decision_method` from the type, then by scope:
   - **`unit` scope with method `council`:** create a `CouncilDecision` in that unit (P03.T04) and link it (`action_payload["council_decision"]`). The decision's tally later sets the ticket to `approved` or `rejected`.
   - **`confirmers`:** start the draw (T04).
   - **`auto`:** run the type's automatic rule (for example a green purchase up to the limit). If it is satisfied, approve (T07); otherwise switch to `confirmers`.
   - **`none`:** stay `open` for discussion.
2. **`suggest_answerers(ticket) -> list[Member]`:** returns `[]` until P13 (reputation). The ticket page shows the suggestions, if any, as "Members who might know".

**Tests:** a unit-scope council ticket creates a council decision; a `question` stays open.

---

### - [x] P06.T04 — A random draw anyone can check

**Read:** docs/05 section 3 ("Who can be drawn", "A draw anyone can check").
**Files:** `apps/tickets/models.py` (Confirmation, Seat), `apps/tickets/draw.py`, `apps/tickets/tests/test_draw.py`

**Do:**
1. **Models:**
   - `Confirmation`: `ticket`, `round` (`confirmers`, `panel`, `mediation`, `replacement`), `size`, `seed` (CharField(64)), `fingerprint_date`, `eligible_count`, `eligible_hash`, `created_at`, `status` (`open`, `approved`, `rejected`, `timed_out`).
   - `Seat`:
     - `confirmation`, `member`, `drawn_order`, `notified_at`, `opened_at`;
     - `check_attempts`, `check_passed` (bool);
     - `vote` (`yes`, `no`, null), `reason`, `voted_at`, `deadline`;
     - `replaced` (bool), `paid_entry` (FK HoursEntry, null).
2. **`eligible(ticket, round) -> list[Member]`**, applying docs/05 section 3 exactly:
   - verified (HF-13), at least `governance.confirmers.min_member_months` months a member (founders exempt while `SiteState.launched_at` is less than a year ago);
   - not the author; not an active worker of `scope_unit` (or of any unit named in `action_payload["units"]`);
   - not already seated on this ticket in any round;
   - fewer than `governance.confirmers.max_draws_per_month` seats this month;
   - no `draw_pause_until` in the future;
   - for `local` scope, `postcode` starting with `scope_area`;
   - no declared conflict (a `Conflict(ticket, member)` row, created by the member's "I have a conflict of interest" button).
3. **`draw(ticket, round, k) -> Confirmation`:**
   1. `members = sorted(eligible(...), key=lambda m: m.number)`;
   2. `fp` = the latest `DailyFingerprint` of chain `uniq` before today;
   3. `seed = sha256_hex(f"{ticket.number}:{round}:{draw_no}:{fp.hash}")`, where `draw_no` counts this ticket's earlier draws;
   4. `chosen = random.Random(int(seed, 16)).sample(members, min(k, len(members)))`;
   5. store the seed, `fp.date`, `len(members)` and `sha256_hex(",".join(m.number for m in members))`;
   6. create the seats, each with `deadline = now + governance.confirmers.deadline_hours` (panels: `governance.panel.deadline_hours`);
   7. notify each seat by email.

   If fewer than `k` are eligible, seat all of them and write that on the ticket.
4. **`reproduce(confirmation, member_numbers) -> list[str]`** lets an auditor repeat a draw from a list of numbers they were given.

**Tests:**
- the same inputs give the same seats;
- the author and the unit's workers are never drawn;
- the monthly limit holds;
- `reproduce` matches;
- `test_hf13_unverified_never_drawn`.

---

### - [x] P06.T05 — The confirmers' steps

**Read:** docs/05 section 3 ("The confirmers' steps"); owner 2026-11-21: all 4 must say yes.
**Files:** `apps/tickets/services.py`, `apps/tickets/views.py`, `apps/tickets/templates/tickets/seat.html`, `apps/tickets/jobs.py`, `apps/tickets/tests/test_confirmers.py`

**Do:**
1. **The seat page `/seat/<id>/`** (only for the seated member):
   1. The brief.
   2. The check question: 3 choices in random order.
   3. A wrong answer shows the brief again with the hint "Read the part about …" (the author writes the hint with the question). After 2 wrong answers the seat is replaced.
   4. After a correct answer: the "Yes" and "No" buttons. "No" requires a reason of at least 20 characters.

   Voting is a `sensitive_action`.
2. **`cast(seat, vote, reason)`.** After each vote, `evaluate(confirmation)` runs:
   - with `governance.confirmers.rule == "all_yes"`, **all seats yes → `approved`**;
   - **any "no" → `rejected` for this round**, and the panel starts (T06);
   - the other rules (`all_but_one`, `majority`) follow their names.
3. **Job `tickets.seat_deadlines`** (in `run_jobs`, every 10 minutes through `dedupe_key` by quarter hour):
   - seats without a vote after their deadline are marked `replaced`, and one new member is drawn for each (round `replacement`), at most `governance.confirmers.max_replacements` times per original seat;
   - after that, a missing vote counts as "no" (the matter goes to the panel);
   - reminders go out 24 hours before each deadline.
4. **Pay for the review:** when a seat votes, create an `HoursEntry` in the coordination unit (`activity = coordination`, `minutes = governance.confirmers.review_minutes`, or `governance.panel.review_minutes` for panels, `ref = seat`) and call `approve_hours(entry, approver=None)` (system approval for coordination, P03.T08).
5. **On approval**, run the ticket's action (T07).

**Tests:**
- four yes votes approve;
- one no starts a panel;
- a wrong check answer twice replaces the seat;
- a silent seat is redrawn, then counts as no;
- each vote creates a paid 30-minute coordination entry.

---

### - [x] P06.T06 — The panel of 12

**Read:** docs/05 section 3 (steps 6–7).
**Files:** `apps/tickets/services.py`, `apps/tickets/tests/test_panel.py`

**Do:**
1. **When a confirmers round is rejected:** draw `governance.panel.size` new members (all earlier seats are excluded), with round `panel`, and set the ticket to `panel`.
2. **Same steps as T05**, but `evaluate` approves when the yes votes reach `governance.panel.majority` (7), and rejects when that can no longer happen or the deadline has passed.
3. **The outcome:**
   - `approved` → run the action;
   - `rejected` → set `petition_until = now + governance.petition.days` and tell the author and all seats: "Anyone can start a petition for a vote of all members until <date>." The petition and the referendum come in P07.
4. **Every "no" reason** from both rounds is listed on the ticket (without names unless the member chose to show them). These reasons become the "against" side in a referendum brief (P07).

**Tests:**
- 7 of 12 approve;
- 6 of 12 reject and set `petition_until`;
- earlier confirmers are never on the panel.

---

### - [x] P06.T07 — Actions, and moving earlier flows onto tickets

**Read:** docs/05 section 5 item 1 ("Automatic actions").
**Files:** `apps/tickets/actions.py`, `apps/units/services.py`, `apps/catalogue/services.py`, `apps/members/services.py`, `apps/market/services.py`, `apps/ledger/audit.py`, `apps/tickets/tests/test_actions.py`

**Do:**
1. **`actions.py`:** a registry `ACTIONS[name] = Action(validate=callable(payload) -> list[str], execute=callable(ticket) -> dict)`.
   - `approve(ticket)` runs `execute` inside the same `transaction.atomic()` as the status change, and stores the result in `action_result`. If `execute` raises, the ticket becomes `in_action` with the error in plain words, and the operators are notified.
2. **Actions now:**
   - `open_unit` (sets a paused unit to `trial`);
   - `close_unit`;
   - `publish_offer` (a red-check offer becomes active);
   - `verify_licence` (sets the licence `verified`, `decided_by` = ticket number);
   - `hours_confirm` (marks a review as confirmed) and `hours_correct` (posts a correcting transaction with the ticket's reason, then the right one);
   - `flag_remove` and `flag_keep`;
   - `suspend_member` (only for a proven duplicate; status `suspended`);
   - `none`.
3. **Rewire the earlier flows to create tickets:**
   - **P03.T06,** a red check when opening a unit → ticket `open_unit` with the unit's data as brief.
   - **P04.T03,** a red check when publishing an offer → ticket `offer_red_check` with the action `publish_offer`.
   - **P01.T07,** a licence upload → ticket `verify_licence` (2 seats). Add the two seats' members to `can_view_file` for that document while the ticket is open.
   - **P01.T05,** a duplicate suspected → ticket `duplicate_suspected`: the confirmers decide "these are two different people" (keep) or "one person, two accounts" (`suspend_member` on the newer).
   - **P05.T09,** plausibility notices → ticket `hours_review` (4 seats). The brief is generated from the numbers.
   - **P05.T05 and P05.T06,** disputes → ticket `flag` (reason "not received", "damaged", "not performed").
   - **P02.T07,** a failed audit → ticket `audit_failure` (4 seats, informative; until P07 elects auditors).
   - **P03.T04,** each new `CouncilDecision` also creates a `council_decision` ticket of `unit` scope. The tally updates the ticket.
4. **A monthly job `tickets.one_person_checks`:** draws `governance.one_person_units.sample_share_per_month` of the one-person units, and opens a `one_person_check` ticket (1 seat, `check_minutes` paid) for each.

**Tests:**
- an approved `open_unit` ticket opens the unit;
- an approved `hours_correct` posts a correction with the ticket number in the reason;
- a licence ticket's seats can view the document while it is open, and not afterwards;
- `test_hf15_checks_route_to_people` (each red path creates a ticket instead of an error).

---

### - [ ] P06.T08 — Flags

**Read:** docs/05 section 9 ("Flags").
**Files:** `apps/tickets/models.py` (Flag, Hidden), `apps/tickets/services.py`, `templates/partials/flag_button.html`, `apps/tickets/tests/test_flags.py`

**Do:**
1. **Models:**
   - `Flag`: `target_type` (`offer`, `comment`, `ticket`, `profile`, `hours`, `payment`, `review`), `target_id`, `reason` (`illegal`, `wrong_data`, `harassment`, `privacy`, `other`), `text`, `created_by`, `created_at`, `ticket` (FK).
   - `Hidden`: `target_type`, `target_id`, `since`, `ticket`, `until` (null).
2. **`flag(member, target, reason, text)`:**
   - the first flag on a target opens a `flag` ticket (4 seats; the question: "Should this be removed or corrected?"); later flags join it;
   - when `governance.flags.hide_after_flags` different members have flagged, create a `Hidden` row.
3. **Templates** use `{% if not obj|is_hidden %}`. A hidden thing shows "Hidden while members review a report" to others, and in full to its author with the reasons.
4. **The outcome:**
   - **`flag_remove`:** stays hidden; the author gets a **statement of reasons**: the flag reasons and the confirmers' reasons. The DSA requires it.
   - **`flag_keep`:** the `Hidden` row ends, and the flaggers are told.
   - **The author can contest it** through the panel and petition steps.

**Tests:**
- three flags hide;
- removal sends the statement of reasons;
- keeping unhides.

---

### - [ ] P06.T09 — Mediation

**Read:** docs/05 section 9 ("Mediation and judgement").
**Files:** `apps/tickets/services.py`, `apps/tickets/templates/tickets/mediation.html`, `apps/members/models.py` (`is_mediator` on Member), `apps/tickets/tests/test_mediation.py`

**Do:**
1. **Members can volunteer** as mediators (`Member.is_mediator`) on "My account".
2. **A `mediation` ticket** names the parties (members or units). The draw takes `governance.mediation.mediators` (3) from the mediator pool, excluding the parties; if the pool is too small, it draws from all eligible members.
3. **The mediators' page:**
   - a private thread with the parties;
   - the field "Agreement reached" (the agreement text, which both parties confirm);
   - or "No agreement".

   Deadline: `governance.mediation.days`.
4. **"No agreement" or the deadline passing** → a panel of 12 decides between the parties' positions (each party writes one at most 300 words long). The decision is recorded and binds within Unicorn's rules. Paid minutes: the mediators record their actual time (approved by the system up to 6 hours per mediation).

**Tests:** an agreement closes the ticket; no agreement starts a panel; the parties are never mediators.

---

### - [ ] P06.T10 — The check after an amber opening

**Read:** docs/05 section 9 ("Opening a unit", amber).
**Files:** `apps/units/services.py`, `apps/tickets/tests/test_post_check.py`

**Do:**
1. **When `open_unit` had an amber check,** create a `post_check_unit` ticket. Its brief is the unit's data and the amber points; its question is "Should this unit keep working?"; the deadline is `units.post_check_days`.
2. **The outcome:**
   - **approved:** nothing changes;
   - **after a panel rejects:** the unit becomes `paused`, its open orders are released, and the workers are told the reasons and how to start a petition.

**Tests:** the amber path creates the ticket; panel rejection pauses the unit and releases its holds.

---

## Acceptance check for phase 06

1. Open a unit whose trade is on a (test) red list, so that a ticket is created.
2. Four seats each answer the check question and vote yes: the unit opens, and each seat got 30 paid minutes.
3. Repeat with one "no": a panel of 12 is drawn, 7 yes votes open the unit.
4. `reproduce` gives the same seats.
5. `test_hf13_` and `test_hf15_` tests pass.
6. Add a line to PLAN.md "Progress".
