# Phase 07 — Petitions, referendums, delegates, collective tasks, elections

**Goal:** members can force a vote of all by petition. Referendums use secret ballots, with yes/no or ranked (instant-runoff) ballots. Defaults change only at their tier. The hard frame changes only by its procedure. Decisions can be carried out by one delegate with a mandate, or by everyone through tasks. Auditors and the trust review group are elected.
**Read first:** docs/05 sections 3 (step 7), 4 and 5; docs/01 sections 3–4; HF-16.

---

### - [ ] P07.T01 — Petitions

**Read:** docs/05 section 3 (step 7).
**Files:** `apps/votes/` (new app), `apps/votes/models.py` (Petition, PetitionSignature), `apps/votes/services.py`, `apps/votes/views.py`, `apps/votes/tests/test_petitions.py`

**Do:**
1. **Models:**
   - `Petition`: `ticket` (the rejected ticket, or a `referendum_request` ticket), `question`, `opened_by`, `opens_at`, `closes_at` (`+ governance.petition.days`), `threshold` (fixed at opening: `max(governance.petition.min_signatures, ceil(governance.petition.share × active members))`), `status` (`open`, `succeeded`, `failed`).
   - `PetitionSignature`: `petition`, `member`, `signed_at`; unique pair. Verified members only (HF-13).
2. **`open_petition(ticket, member, question)`:** allowed while `ticket.petition_until` has not passed, or for a `referendum_request` ticket.
3. **`sign(petition, member)`:** when the count reaches the threshold, the status becomes `succeeded` and `schedule_referendum` (T02) runs. A daily job marks petitions past `closes_at` as `failed`.
4. **The page** shows the count, the threshold and the days left. It never shows signers' names.

**Tests:** the threshold is reached and the referendum is scheduled; an unverified member cannot sign; names are not shown.

---

### - [ ] P07.T02 — Referendums and secret ballots

**Read:** docs/05 section 4.
**Files:** `apps/votes/models.py` (Referendum, Ballot, VoterRecord), `apps/votes/services.py`, `apps/votes/views.py`, `apps/votes/templates/votes/*.html`, `apps/votes/migrations/000X_triggers.py`, `apps/votes/tests/test_referendum.py`

**Do:**
1. **Models:**
   - `Referendum`:
     - `ticket`, `question`, `method` (`yes_no`, `ranked_irv`), `options` (JSON list, for ranked votes);
     - `brief_for_md`, `brief_against_md`, `forecast` (FK PrivateFile, null; public attachment: store it with `kind="other"`, readable by all members);
     - `opens_at`, `closes_at`, `quorum_share`, `majority` (`simple`, `two_thirds`);
     - `eligible_count` (fixed at opening), `status` (`scheduled`, `open`, `closed`), `result` (JSON).
   - `Ballot`: `referendum`, `choice` (JSON: `"yes"`, `"no"`, `"abstain"`, or a ranked list), `receipt` (CharField(12), unique). **No member and no time.**
   - `VoterRecord`: `referendum`, `member`, `voted_on` (date only); unique pair.

   `Ballot` and `VoterRecord` are append-only, with triggers.
2. **`schedule_referendum(ticket, question, method=..., options=None, days=None, quorum=None, majority=None)`:** the defaults come from `governance.referendum.*`. The "for" brief is the ticket's brief; the "against" brief lists the panel's "no" reasons (or invites one random member to write it, as a task with paid minutes). It opens at 00:00 the next day.
3. **`cast(referendum, member, choice) -> receipt`:**
   - verified members only;
   - one `VoterRecord` and one `Ballot` in the same transaction;
   - the receipt is shown once, with "Keep this code to check your vote was counted";
   - behind `sensitive_action`.
4. **`/votes/check/`:** enter a receipt and see the stored choice.
5. **Closing** (a daily job):
   - turnout = voter records ÷ `eligible_count`;
   - the quorum is met when turnout ≥ `quorum_share` (abstentions count);
   - for `yes_no`, yes ÷ (yes + no) > 1/2 (or ≥ 2/3 with `two_thirds`);
   - for `ranked_irv`, T03.

   Store all counts in `result`, and publish them on the ticket and the open-books page.

**Tests:**
- a member cannot vote twice;
- `test_hf13_unverified_cannot_vote`;
- a ballot row has no member link (inspect the model fields);
- the quorum fails with low turnout;
- a two-thirds majority is computed correctly.

---

### - [ ] P07.T03 — Instant runoff

**Files:** `apps/votes/irv.py`, `apps/votes/tests/test_irv.py`

**Do:**
1. **`irv(ballots: list[list[str]], options: list[str], seed: str) -> (winner, rounds)`:**
   1. Count each ballot for its highest-ranked option still in the race. Ballots with no remaining option are exhausted.
   2. If an option has more than half of the non-exhausted ballots, it wins.
   3. Otherwise eliminate the option with the fewest votes. For a tie among the lowest, first compare their first-round counts; if still tied, pick with `random.Random(int(sha256_hex(seed), 16))`, where `seed` is the referendum number plus the latest public fingerprint.
   4. Record each round's counts in `rounds`, and repeat.
2. **Ballots may rank** only some options.

**Tests:** the textbook examples with 3 options; a tie at elimination; ballots that rank only one option.

---

### - [ ] P07.T04 — Outcomes and actions of referendums

**Files:** `apps/votes/services.py`, `apps/tickets/actions.py`, `apps/votes/tests/test_outcomes.py`

**Do:**
1. **When a referendum closes:**
   - approved → `tickets.actions.approve(ticket)` (its action runs);
   - rejected or quorum failed → the ticket becomes `rejected`, with the counts.

   A petition-forced referendum decides the original ticket **finally** (docs/05 section 3, step 7).
2. **A `referendum_request` ticket** (a new question raised by petition) has the action `none` unless it names a parameter change (T05).

**Tests:** an approved referendum runs the ticket's action; a failed quorum rejects it.

---

### - [ ] P07.T05 — Changing a default through its tier

**Read:** docs/01 section 3; HF-16.
**Files:** `apps/tickets/types.py`, `apps/rules/views.py`, `apps/tickets/actions.py`, `apps/rules/tests/test_change_by_ticket.py`

**Do:**
1. **Ticket type `parameter_change`:** payload `{key, new_value, reason}`. Its form starts from the parameter's row on `/rules/` ("Propose a change"). It shows the bounds and the tier in words, and validates the value with `set_param`'s checks before the ticket opens.
2. **Routing by the parameter's tier:**

   | Tier | Route |
   |---|---|
   | `unit` (defaults for new councils) | confirmers |
   | `confirm` | confirmers |
   | `plan` | rejected with "This is decided in the yearly plan (docs/05 section 8), or by a referendum" and the offer to turn it into a `referendum_request` or a `plan_proposal` |
   | `referendum` | a referendum, after 4 confirmers check that the brief is complete and fair (a completeness question) |
   | `hard` | rejected with "This needs a hard-frame change" and a link to T06 |

3. **The action `change_parameter`** calls `rules.services.set_param(key, value, decided_by=ticket.number, decided_tier=<the tier that decided>, reason=...)`.
4. **The `/rules/` history** shows each change with a link to its ticket.

**Tests:**
- `test_hf16_confirm_tier_needs_confirmers` (no change without an approved ticket);
- `test_hf16_referendum_tier_needs_referendum`;
- `test_hf16_hard_tier_refused`;
- the change is recorded with the ticket number.

---

### - [ ] P07.T06 — The hard-frame change procedure

**Read:** docs/01 section 4.
**Files:** `apps/tickets/types.py`, `apps/tickets/actions.py`, `apps/votes/services.py`, `apps/tickets/templates/tickets/hard_frame.html`, `apps/tickets/tests/test_hard_frame_change.py`

**Do:**
1. **Ticket type `hard_frame_change`.** Its required fields:
   - the rule (an HF id) or the hard bound (a parameter key);
   - the new text or value;
   - why it is needed;
   - what changes in the code;
   - the authors, and their expertise in one sentence each;
   - a **forecast** attachment (required).
2. **The steps:**
   1. **completeness check** by 4 confirmers (the question: "Is this proposal complete and understandable?", not "do you agree");
   2. **referendum** with `governance.hard_frame_change.days` (21), quorum 25% and a two-thirds majority, taken from the hard parameters, never from the ordinary referendum defaults;
   3. **approved** → status `in_action`, "waiting for a new release".
3. **Action `record_release`:** an operator records the release tag and the commit, and the ticket becomes `done`. Parameter bounds of type `hard` may then be changed by a data migration in that release, which writes a `ParameterChange` with `decided_tier="hard"` and the ticket number.
4. **The app never changes its own code.**

**Tests:**
- without a forecast the ticket cannot open;
- the referendum uses 21 days, 25% and two thirds;
- `test_hf16_hard_change_needs_release` (approval alone does not change the hard bound).

---

### - [ ] P07.T07 — A delegate for one decision

**Read:** docs/05 section 5 item 2.
**Files:** `apps/tasks/` (new app), `apps/tasks/models.py` (Mandate, MandateApplication), `apps/tasks/services.py`, `apps/tasks/views.py`, `apps/tasks/templates/tasks/*.html`, `apps/tasks/tests/test_mandates.py`

**Do:**
1. **Models:**
   - `MandateApplication`: `ticket`, `member`, `statement`, `created_at`.
   - `Mandate`:
     - `ticket`, `delegate` (Member), `scope_md`;
     - `powers` (JSON: `spend_limit_eur`, `may_sign`, `may_represent`, `other`);
     - `starts_at`, `ends_at` (at most `governance.delegation.max_mandate_days`);
     - `status` (`active`, `done`, `revoked`, `expired`), `report_md`, `report_at`.
2. **An approved ticket marked `needs_delegate`** (a tick box on the ticket form) opens applications for `governance.delegation.volunteer_days`, and notifies members whose portfolio matches the ticket's trade.
3. **Choosing the delegate:**
   - one applicant: a confirmers round "Should <name> carry out this decision?";
   - several: a confirmers round in which each seat **ranks** the applicants, or marks "none of them". Any "none of them" counts as a "no" and goes to a panel, which ranks.

   The winner is computed with `irv` over the seats' rankings.
4. **The mandate starts** with its scope and powers shown on the ticket. Spending happens only through payment requests (P08) that cite the mandate and stay within `spend_limit_eur`.
5. **The report:** the delegate writes it and records hours in the coordination unit (`ref = mandate`). A 1-seat confirmation checks the report and the hours, and on "yes" the hours are approved and paid, and the mandate is `done`.
6. **Revocation:** a confirmers round on a `revoke_mandate` ticket (any member can open it), or a petition. A daily job sets expired mandates.
7. **Add to `LEAVE_CHECKS`:** "You have an active mandate: finish or hand it back first."

**Tests:**
- a single applicant approved by 4 yes votes;
- three applicants ranked;
- a mandate's spending above its limit is refused (test through a stub payment-request function until P08);
- an expired mandate cannot report new hours.

---

### - [ ] P07.T08 — Collective tasks

**Read:** docs/05 section 5 item 3.
**Files:** `apps/tasks/models.py` (Task), `apps/tasks/services.py`, `apps/tasks/views.py`, `apps/tasks/tests/test_tasks.py`

**Do:**
1. **`Task`:**
   - `ticket`, `title`, `description`, `standard_minutes`;
   - `status` (`open`, `claimed`, `done`, `confirmed`);
   - `claimed_by`, `claimed_at`, `done_at`, `evidence_text`, `evidence_file` (PrivateFile, null);
   - `confirmed_by`, `confirmed_at`.
2. **A `task_list` ticket.** Once approved, its tasks are listed publicly. Any verified member can claim an open task. After `governance.tasks.claim_timeout_days` without "done", the task is free again.
3. **Confirmation:** the ticket's author, or one random member (a 1-seat draw), confirms each done task. On confirmation, an `HoursEntry` is created in the coordination unit with `standard_minutes` and approved by the system.
4. **The ticket is `done`** when all tasks are confirmed.

**Tests:** claim, done, confirm, paid; the timeout frees the task; one cannot confirm one's own task.

---

### - [ ] P07.T09 — Elected roles: auditors and the trust review group

**Read:** docs/08 section 5 ("Nightly audit": elected auditors); docs/07 section 5 (the trust review group).
**Files:** `apps/votes/models.py` (Election, Candidate, Term), `apps/votes/services.py`, `apps/votes/tests/test_elections.py`

**Do:**
1. **Models:**
   - `Election`: `role` (`auditor`, `trust_review`), `seats` (auditors 3; trust review `tradefund.trust_review_group_size`), `opens_at`, `closes_at`, `status`.
   - `Candidate`: `election`, `member`, `statement`.
   - `Term`: `role`, `member`, `starts_at`, `ends_at` (1 year).
2. **Approval voting with secret ballots.** Reuse `Ballot` with `choice` = the list of approved candidate ids. The candidates with the most approvals win; a tie is broken with the seeded random of T03.
3. **Candidates for `trust_review`** must hold no more than the base cap (enforced after P08; until then, recorded).
4. **The first elections** are started by a founders' referendum after launch, and again every year by a scheduled job.
5. **Rewire `audit_failure` tickets** to the members with an active `auditor` term.

**Tests:** the top-N approvals win; a term ends after a year; audit failures go to the auditors.

---

## Acceptance check for phase 07

1. A rejected ticket gets a petition; it reaches its threshold, and a referendum opens and closes.
2. The result decides the ticket, and the member can check their ballot by receipt.
3. A `parameter_change` of tier `confirm` changes `logistics.default_cover_radius_km` after 4 yes votes, and the `/rules/` history links the ticket.
4. A delegate is chosen, reports and is paid.
5. All `test_hf16_` tests pass.
6. Add a line to PLAN.md "Progress".
