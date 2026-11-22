# Phase 02 — The UNIQ books

**Goal:** double-entry, append-only, hash-chained books for UNIQ, with Fund 1, Fund 2, member and retirement accounts, holds, a nightly audit, a daily public fingerprint and the open-books page.
**Read first:** docs/03 sections 1–2, docs/08 section 5, docs/01 rules HF-1, HF-4 to HF-8.

---

### - [x] P02.T01 — Accounts and periods

**Files:** `apps/ledger/` (new app), `apps/ledger/models.py`, `apps/ledger/services.py`, `apps/ledger/migrations/0002_funds.py` (data migration), `apps/ledger/tests/test_accounts.py`

**Do:**
1. **`Account`:**
   - `kind`: `member`, `retirement`, `fund1`, `fund2`;
   - `member` (FK Member, PROTECT, null), `created_at`.

   Constraints: `member` is required for `member` and `retirement` and must be null for the funds; unique (`kind`, `member`).
2. **Data migration:** creates exactly one `fund1` and one `fund2` account.
3. **`AccountBalance`:** `account` OneToOne, `balance` Decimal(18,4) default 0. It is a cache, updated only by `post()` (T03) and checked by the audit (T07).
4. **`Period`:** `year`, `month`, `status` (`open`, `closing`, `closed`), `tax_rate` Decimal(6,4), `planned_hours` Decimal(18,4) default 0, `opened_at`, `closed_at`; unique (`year`, `month`).
5. **Services:**
   - `fund1()`, `fund2()`;
   - `member_account(member)` and `retirement_account(member)`;
   - `open_member_accounts(member)` (idempotent);
   - `current_period(now=None)` returns the period of `now` in Europe/Berlin, creating it with status `open` if missing. Its `tax_rate` is the previous period's `next_tax_rate` if P09 set one, otherwise `get_param("economy.flat_tax.start_rate")`.
6. Add `open_member_accounts` to `members.services.VERIFIED_HOOKS`.

**Tests:**
- verifying a member opens both accounts;
- only one `fund1` and one `fund2` exist;
- `current_period` creates the month once.

---

### - [x] P02.T02 — Transactions, entries and the chain head

**Files:** `apps/ledger/models.py`, `apps/ledger/tests/test_models.py`

**Do:**
1. **`Transaction`:**
   - `seq` (BigInteger, unique), `period` (FK, PROTECT);
   - `kind`: `hours_pay`, `tax`, `purchase`, `rent`, `transfer`, `retirement_in`, `retirement_out`, `cancel`, `correction`;
   - `reason` (Text, required), `ref_type` (CharField(40), blank), `ref_id` (CharField(40), blank), `actor_ref` (CharField(32)), `created_at`;
   - `prev_hash` and `hash` (CharField(64)).
2. **`Entry`:** `transaction` (FK, PROTECT, related_name `entries`), `account` (FK, PROTECT), `amount` (Decimal(18,4), never 0). Index on `account`.
3. **`ChainHead`:** `name` (CharField(16), primary key: `uniq`; P08 adds `fund`), `last_seq` (BigInteger, 0), `last_hash` (CharField(64), default `"0" * 64`). A data migration creates the `uniq` row.
4. **`Transaction` and `Entry`** inherit from `core.models.AppendOnlyModel`, a new abstract base:
   - `save()` refuses updates;
   - `delete()` raises;
   - its manager's queryset raises on `update()` and `delete()`.

   Move `AuditEvent` and `ParameterChange` (and the members' append-only models) onto this base too.

**Tests:** creating a transaction directly through the ORM works only once; `.update()` and `.delete()` raise.

---

### - [ ] P02.T03 — `post()`: the only way to move UNIQ

**Read:** docs/03 section 2 (the table of events); docs/01 HF-1, HF-5, HF-6.
**Files:** `apps/ledger/services.py`, `apps/ledger/tests/test_post.py`

**Do:**
1. `@dataclass(frozen=True) class Leg: account: Account; amount: Decimal`.
2. `post(kind, reason, legs, *, ref=None, actor_ref="system", period=None, capturing_hold=None) -> Transaction`, inside `transaction.atomic()`:
   1. **`reason`** stripped must not be empty (`LedgerError("Every transfer needs a written reason")`).
   2. **Legs:** at least 2 legs; every amount is `uniq(...)` and not zero; the sum is exactly zero.
   3. **The period:** `period or current_period()` must be `open`. A `cancel` may also use a `closing` period.
   4. **HF-5:** collect the member of every `member` or `retirement` account in the legs. More than one distinct member raises `LedgerError("UNIQ never move between members")`.
   5. **Allowed patterns** (debit = negative leg, credit = positive leg). Anything else raises:

      | kind | debit | credit |
      |---|---|---|
      | `hours_pay` | fund2 | member |
      | `transfer` | fund2 | member |
      | `tax` | member | fund2 |
      | `purchase`, `rent` | member | fund1 |
      | `retirement_in` | member | retirement (same member) |
      | `retirement_out` | retirement | member (same member) |
      | `cancel` | fund1 | fund2 |
      | `correction` | the exact negation of the legs of the transaction given in `ref` (which must exist and must not already be corrected) | |

      This enforces HF-1 (only `hours_pay` and `transfer` debit Fund 2), HF-6 (Fund 1 is debited only by `cancel`) and HF-4 (no kind involves any currency).
   6. **Lock the head:** `ChainHead.objects.select_for_update().get(name="uniq")`. This serialises all postings.
   7. **No overdraft:** for each debited `member` or `retirement` account, the new balance must be ≥ 0. Unless `capturing_hold` covers the amount, the **available** balance (balance − active holds) must also be ≥ 0: "Not enough UNIQ available".
   8. **Write:**
      - `seq = head.last_seq + 1`;
      - build `payload = {"seq", "period": "YYYY-MM", "kind", "reason", "ref_type", "ref_id", "actor_ref", "created_at", "entries": [{"account": id, "amount": "x.xxxx"} sorted by account id]}`;
      - `hash = chain_hash(head.last_hash, payload)`;
      - save the transaction and its entries, update `AccountBalance` for each leg, update the head.
3. **Helpers that later phases use:**
   - `balance(account)`, `available(account)`;
   - `pay_hours_legs(member, minutes, tax_rate) -> (gross_legs, tax_legs)` returns the two leg lists for `hours_pay` and `tax`.

**Tests** (one per rule; the names matter):
- `test_hf01_only_hours_and_transfers_debit_fund2` (a `purchase` debiting fund2 is refused);
- `test_hf05_no_transfer_between_members`;
- `test_hf06_fund1_only_debited_by_cancel`;
- `test_hf07_reason_required`;
- `test_hf04_ledger_knows_no_currency` (no field of `Transaction`, `Entry` or `Account` holds a currency or a euro amount, and no `kind` means exchange);
- `test_sum_must_be_zero`;
- `test_no_overdraft`;
- `test_correction_must_negate_original`;
- `test_hash_chain_links` (two posts, the second's `prev_hash` equals the first's `hash`);
- a `hypothesis` test: random valid sequences of hours, purchases and transfers keep Σ of all balances = 0, and no member balance below 0.

---

### - [ ] P02.T04 — Holds

**Read:** docs/06 sections 4–5 (UNIQ held at order or booking).
**Files:** `apps/ledger/models.py` (Hold), `apps/ledger/services.py`, `apps/ledger/tests/test_holds.py`

**Do:**
1. **`Hold`:** `account` (a member account), `amount` Decimal(18,4) > 0, `status` (`active`, `captured`, `released`), `reason`, `ref_type`, `ref_id`, `created_at`, `closed_at`. A hold is not part of the chain; it is mutable.
2. **Services:**
   - `place_hold(member, amount, reason, ref)` requires `available >= amount`;
   - `capture_hold(hold, reason, kind="purchase")` posts `purchase` (member → fund1) with `capturing_hold=hold`, and marks the hold `captured`;
   - `release_hold(hold, reason)` marks it `released`.

   Every hold action records an `AuditEvent`.

**Tests:**
- a hold lowers `available`, not `balance`;
- capturing posts a purchase and ends the hold;
- you cannot hold more than is available;
- a captured or released hold cannot be captured again.

---

### - [ ] P02.T05 — Append-only in the database

**Read:** docs/08 section 5; docs/09 section 2 (the trigger privilege).
**Files:** `apps/core/sql.py`, `apps/ledger/migrations/0003_append_only_triggers.py`, `apps/ledger/tests/test_triggers.py`

**Do:**
1. **`apps/core/sql.py`:** `append_only_statements(table) -> list[str]` returns two statements:

   ```sql
   CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table}
     FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'append-only table';
   CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
     FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'append-only table';
   ```

2. **A `RunPython` migration** (not `RunSQL`, so a missing privilege does not break `migrate`):
   - it creates the triggers for `ledger_transaction`, `ledger_entry`, `core_auditevent`, `rules_parameterchange`, `members_signature`, `members_vouch` and `members_inpersoncheck`;
   - it first drops existing triggers of the same name;
   - on an `OperationalError` it prints a clear warning ("Triggers not created: <error>. The model guards still apply; ask the server admin for the TRIGGER privilege or log_bin_trust_function_creators=1.") and continues.
3. **A helper `triggers_present(tables) -> dict[str, bool]`** that reads `information_schema.TRIGGERS`. Later apps reuse `append_only_statements` in their own migrations for their append-only tables.

**Tests:**
- `test_hf07_raw_update_refused` (a raw `UPDATE ledger_entry SET amount = 0` raises a database error; skip with a reason if `triggers_present` says no);
- `test_triggers_present_reports`.

---

### - [ ] P02.T06 — My UNIQ account page

**Files:** `apps/ledger/views.py`, `apps/ledger/urls.py`, `apps/ledger/templates/ledger/my_account.html`, `apps/ledger/tests/test_views.py`

**Do:**
1. **`/me/uniq/`** shows:
   - balance, held, available, retirement balance;
   - this period's flat tax rate;
   - the entries, newest first, 50 per page: date (member's time zone), kind in words ("Paid for hours", "Flat tax", "Purchase", "Rent", "Pension", "Into retirement account", "From retirement account", "Correction"), the reason, the amount (green for +, red for −), and the running balance.
2. **A "Download CSV" link** for the member's own entries.
3. **Words:** the page explains in two sentences that UNIQ are earned only by working, cannot be given to others, and are never exchanged for euros (HF-4, HF-5).

**Tests:** a member sees only their own entries; the CSV has the right columns.

---

### - [ ] P02.T07 — The nightly audit

**Read:** docs/08 section 5 ("Nightly audit").
**Files:** `apps/ledger/models.py` (AuditRun), `apps/ledger/audit.py`, `apps/ledger/management/commands/audit_books.py`, `apps/ledger/tests/test_audit.py`

**Do:**
1. **`AuditRun`:** `started_at`, `finished_at`, `ok` (bool), `last_seq`, `last_hash`, `full` (bool), `findings` (JSON list of plain sentences).
2. **`run_audit(full=False)`.** It starts after the last successful run's `last_seq` (or from the beginning when `full`, or when there is no earlier run), and:
   1. recomputes every transaction's hash from `prev_hash` and its payload, and checks the links;
   2. checks each transaction's entries sum to 0;
   3. checks each `AccountBalance` equals the sum of its entries;
   4. checks Σ(member + retirement + fund1 balances) = −fund2 balance;
   5. checks no member or retirement balance is below 0;
   6. reports any table without triggers (via `triggers_present`) as a warning finding;
   7. (from P09 on) checks every closed period has its cancellation.
3. **Scheduling:** register the job `ledger.audit` and add it to `daily`. Each Sunday it runs with `full=True`. A failed audit records `AuditEvent(verb="audit_failed")`; from P06 it also opens a ticket for the elected auditors.
4. **`audit_books [--full]`:** prints the findings.

**Tests:**
- an untouched ledger passes;
- a deliberately broken `AccountBalance` (changed in the test with raw SQL on that non-append-only table) is found.

---

### - [ ] P02.T08 — Daily fingerprint and the open-books page

**Read:** docs/08 section 5 ("Daily public fingerprint", "Open books").
**Files:** `apps/ledger/models.py` (DailyFingerprint), `apps/ledger/jobs.py`, `apps/ledger/views.py`, `apps/ledger/templates/ledger/open_books.html`, `apps/ledger/tests/test_open_books.py`

**Do:**
1. **`DailyFingerprint`:** `date`, `chain` (`uniq`; P08 adds `fund`), `seq`, `hash`, `created_at`; unique (`date`, `chain`). Append-only (add its triggers in this app's migration with `append_only_statements`).
2. **Job `ledger.fingerprint`**, in `daily`, for yesterday (Europe/Berlin): the last transaction created before midnight gives its `seq` and `hash`. If there were no transactions, the previous fingerprint's values are repeated.
3. **Public page `/open-books/`** (no login needed). No personal data, no member numbers:
   - UNIQ outstanding;
   - this period's issued, tax, spent and Fund 1 balance so far;
   - a table of closed periods (filled from P09);
   - the last 30 fingerprints;
   - the result of the last audit (a green "Books checked on <date>", or a red banner with the findings);
   - a CSV of period totals.

**Tests:**
- a fingerprint is made once per day and chain;
- the page shows the last audit result;
- the page contains no member numbers.

---

### - [ ] P02.T09 — The retirement account

**Read:** docs/03 section 5.
**Files:** `apps/ledger/services.py`, `apps/ledger/views.py`, `apps/ledger/templates/ledger/retirement.html`, `apps/ledger/tests/test_retirement.py`

**Do:**
1. **`to_retirement(member, amount)`** posts `retirement_in` with the reason "Moved into my retirement account".
2. **`from_retirement(member, amount)`** posts `retirement_out`.
   - Before pension age, refuse if this month's withdrawals would exceed `economy.retirement.early_withdrawal_max_share_per_month` × the retirement balance at the start of the month.
   - Pension age is checked by `members.services.has_reached_pension_age(member)`: a stub returning False until P09, with `# OWNER-CHECK` if the birth date is missing.
3. **Page** `/me/retirement/` with both forms (`sensitive_action`) and a plain explanation.

**Tests:**
- moving in and out works;
- the early-withdrawal limit holds;
- `test_hf08_retirement_balance_is_still_the_members` (the balance shows on "My UNIQ account" and in the audit sums).

---

## Acceptance check for phase 02

1. Every test named `test_hf01_`, `test_hf04_`…`test_hf08_` that this phase defines passes.
2. `audit_books --full` reports no findings, and triggers exist on the local MySQL.
3. `/open-books/` shows totals and a fingerprint after `daily`.
4. Add a line to PLAN.md "Progress".
