# Phase 08 — The trade fund in members' own accounts

**Goal:** euros held by members for the group, with their own hash-chained books. Payment requests are confirmed by the payer and the receiver. Payers are few and take turns. Trust ratings set caps; there is a loss reserve. Members buy from capitalism through purchase requests, donate euros or dollars, and claim help with their bills. The fund follows the plan's priority order.
**Read first:** docs/07 (all), docs/01 rules HF-11, HF-12, HF-18. **The app never moves money (HF-12): every euro movement is a request that people carry out and confirm.**

---

### - [x] P08.T01 — Currencies and exchange rates

**Read:** docs/07 section 11.
**Files:** `apps/tradefund/` (new app), `apps/tradefund/models.py` (FxRate), `apps/tradefund/fx.py`, `apps/tradefund/jobs.py`, `apps/tradefund/tests/fixtures/eurofxref-daily.xml`, `apps/tradefund/tests/test_fx.py`

**Do:**
1. **`FxRate`:** `date`, `currency`, `per_eur` (Decimal(18,6): units of the currency per 1 EUR); unique (`date`, `currency`).
2. **Job `tradefund.fx`** (in `daily`): GET `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`, parse the `Cube` elements, and store the day's rates. EUR itself is always 1. On a network error, log it and keep the old rates. No personal data is sent.
3. **`to_eur(amount, currency, on=None)` and `from_eur(...)`:** use the latest rate on or before the date. Results are rounded with `cur()`.
4. **Tests use the fixture XML** (never the internet).

**Tests:** parsing the fixture; converting USD to EUR and back; a missing rate uses the previous day's.

---

### - [x] P08.T02 — Holders and the holder agreement

**Read:** docs/07 section 2.
**Files:** `apps/tradefund/models.py` (Holder), `apps/tradefund/services.py`, `apps/tradefund/views.py`, `apps/members/fixtures/contracts.json` (add `holder_agreement` v1), `apps/tradefund/tests/test_holders.py`

**Do:**
1. **`Holder`:** `member` (OneToOne), `status` (`active`, `paused`, `leaving`, `left`), `currency` (CharField(3)), `separate_account` (bool), `iban_shown_to_donors` (bool), `joined_at`, `left_at`.
2. **Fixture `holder_agreement` v1.** It starts with "DRAFT — to be written with lawyers" and summarises docs/07 sections 2–5 in plain words: the held euros belong to the group; send them on when a members' decision asks; keep them in a separate account; caps and trust; the loss reserve.
3. **`become_holder(member, currency, iban, bic, bank_name, separate_account)`** (`sensitive_action`):
   - verified members only (HF-13);
   - the member signs the agreement;
   - the IBAN goes into `MemberPrivate` (encrypted).
4. **A system key for outside parties:** `crypto.system_encrypt(bytes)` and `system_decrypt(bytes)` use a Fernet key derived from the master key with HKDF (context `b"unicorn-system-v1"`). They are used for outside payees' IBANs (sellers, landlords).
5. **Pages:** "Become a holder" and "My holding".

**Tests:** an unverified member cannot become a holder; the IBAN is stored encrypted; the agreement is signed.

---

### - [x] P08.T03 — The fund's books

**Read:** docs/07 section 4 ("The fund's books"); docs/08 section 5.
**Files:** `apps/tradefund/models.py` (FundEntry), `apps/tradefund/books.py`, `apps/tradefund/migrations/000X_fund_chain.py`, `apps/ledger/audit.py`, `apps/ledger/jobs.py`, `apps/tradefund/tests/test_books.py`

**Do:**
1. **`FundEntry`:**
   - `seq`, `holder` (FK Holder);
   - `kind`: `setaside`, `donation`, `transfer_in`, `transfer_out`, `payment_out`, `reserve_mark`, `reserve_unmark`, `correction`;
   - `amount` (Decimal(14,2), signed: + raises the holder's holding, − lowers it; `reserve_*` rows move an amount between "free" and "reserve" inside the holding), `currency`;
   - `reason` (required), `reason_kind` (`loan`, `group_purchase`, `gift`, `bill`, `internal`);
   - `ref_type`, `ref_id`, `created_at`, `prev_hash`, `hash`.

   Append-only, with triggers.
2. **A second `ChainHead`, named `fund`.** `books.post_fund(...)` locks it, checks the reason, checks that the holder's free holding stays ≥ 0, and chains the hash exactly like `ledger.post` (same `chain_hash`).
3. **Helpers:** `holding(holder, currency)`, `free(holder, currency)`, `reserve(holder, currency)`, and `fund_total_eur()` (via `to_eur`).
4. **Extend the nightly audit** (P02.T07) to check the `fund` chain and that no holding is below zero. **Extend the daily fingerprint** (P02.T08) with chain `fund`.

**Tests:**
- `test_hf07_fund_books_append_only`;
- `test_hf12_no_bank_integration` (the app has no outgoing call except the ECB rates: grep the code for `requests.`, `urllib` and `http.client`, and allow only `apps/tradefund/fx.py`);
- the hash chain links;
- holdings never go negative.

---

### - [x] P08.T04 — Payment requests

**Read:** docs/07 section 4.
**Files:** `apps/tradefund/models.py` (PaymentRequest, ExternalPayee), `apps/tradefund/payments.py`, `apps/tradefund/views.py`, `apps/tradefund/templates/tradefund/pay*.html`, `apps/tradefund/jobs.py`, `apps/tradefund/tests/test_payments.py`

**Do:**
1. **Models:**
   - `ExternalPayee`: `name`, `iban_enc` (BinaryField, `system_encrypt`), `country`, `created_by`.
   - `PaymentRequest`:
     - `ticket` (FK), `mandate` (FK, null), `payer` (Holder);
     - the payee: `payee_holder` (Holder, null), `payee_member` (Member, null), or `payee_external` (ExternalPayee, null), exactly one;
     - `amount`, `currency`, `reference` (always "Unicorn trade fund, ticket T-000214"), `reason_kind`, `due_date` (today + `tradefund.payment_deadline_days`);
     - `status` (`requested`, `sent`, `received`, `confirmed`, `mismatch`, `overdue`, `missed`, `cancelled`);
     - `sent_amount`, `sent_at`, `received_amount`, `received_at`, `confirmed_by_buyer` (Member, null: for outside payees).
2. **`request_payment(...)`** notifies the payer with exact instructions (amount, IBAN, reference, date). The IBAN is shown only to the payer.
3. **`confirm_sent(pr, payer, amount)` and `confirm_received(pr, member, amount)`** (`sensitive_action`).
   - For an outside payee, the buyer or requester confirms with the invoice (P08.T07).
   - When both amounts are equal: status `confirmed`, `post_fund(payer, payment_out, −amount)`, and if the payee is a holder, `transfer_in +amount` for them. Trust events follow (T06).
   - Different amounts → `mismatch` → a `flag` ticket with both statements.
4. **Job `tradefund.deadlines`:**
   - past `due_date` without "sent": `overdue` and a reminder;
   - after `tradefund.missed_after_extra_days` more days: `missed`, a trust event, and a new request to another payer (T05);
   - if no payer is available, the loss reserve covers it (T06).
5. **A mandate's requests:** the total must stay within `mandate.powers.spend_limit_eur`. Replace the stub of P07.T07 with this check.

**Tests:**
- matching confirmations write the fund entries;
- a mismatch opens a flag;
- an overdue payment becomes missed and is reassigned;
- a mandate cannot overspend.

---

### - [x] P08.T05 — Choosing few payers, in turn

**Read:** docs/07 section 3 ("Payers are few and take turns").
**Files:** `apps/tradefund/payers.py`, `apps/tradefund/tests/test_payers.py`

**Do:**
1. **`choose_payers(amount, currency, exclude=()) -> list[tuple[Holder, Decimal]]`:**
   1. The candidates are active holders in that currency, with free holding > 0, a trust score ≥ 0.2, and not in `exclude`.
   2. Sort them by `paid_share` = euros paid out in the last 12 months ÷ (average holding + 1), lowest first; then by free holding, highest first.
   3. If one candidate covers the amount, return them alone.
   4. Otherwise return the two with the largest free holdings, if together they cover it (never more than `tradefund.max_payers_per_request`).
   5. Otherwise return `[]`: "The fund cannot pay this now". The caller keeps the purchase waiting, and the ticket shows it.

**Tests:** one payer when possible; never more than 2; turns rotate across repeated requests; an excluded holder is never chosen.

---

### - [x] P08.T06 — Trust, caps, the loss reserve

**Read:** docs/07 section 5; HF-11.
**Files:** `apps/tradefund/trust.py`, `apps/tradefund/models.py` (TrustEvent), `apps/tradefund/jobs.py`, `apps/tradefund/views.py`, `apps/tradefund/tests/test_trust.py`

**Do:**
1. **`TrustEvent`:** `holder`, `kind` (`start`, `on_time`, `monthly`, `late`, `missed`, `mismatch`, `left_without_handover`, `annulled`), `delta`, `ref`, `created_at`. Append-only.
2. **The score and the cap:**
   - `score(holder)` = clamp(Σ deltas, 0, 1). The first event is `start`, with `tradefund.trust.start`, or `founders_start` for founders;
   - `cap(holder)` follows docs/07 section 5: `base + score × (max_cap − base)`, where `max_cap = max(base, fund_total_eur × holder_max_share)`.
3. **The events:**
   - on time → `on_time`; overdue but sent within the extra days → `late`; missed → `missed`; a mismatch decided against them → `mismatch`;
   - monthly job `tradefund.trust_monthly`: `monthly` for each active holder without a late, missed or mismatch event that month.
4. **Above the cap:** a holder holding more than their cap gets a payment request to move the excess to the holder with the most room (internal, reason `internal`).
5. **The loss reserve:**
   - each set-aside (P10) and each donation marks `tradefund.loss_reserve_share` as reserve, with `reserve_mark` on the holders with the highest trust that have room;
   - `cover_from_reserve(amount, currency, ticket)` pays a missed or stolen amount by payment requests from reserve holders.
6. **The member's trust page:** score, events with reasons, cap, and "Contest an event". Contesting opens a `trust_review` ticket decided by the elected trust review group (P07.T09) by majority. Action `annul_trust_event`: adds an `annulled` event with the opposite delta.
7. **HF-11 guard test:** no module outside `apps/tradefund/` imports `apps.tradefund.trust`. The test parses imports with `ast`.

**Tests:**
- `test_hf11_trust_used_only_by_tradefund`;
- the score grows by 0.02 per on-time payment and falls by 0.30 per missed one;
- the cap formula;
- contesting and annulling;
- the reserve covers a missed payment.

---

### - [x] P08.T07 — Buying from capitalism

**Read:** docs/07 section 3; docs/03 section 8 (make or buy).
**Files:** `apps/tradefund/models.py` (PurchaseRequest, GroupTool), `apps/tradefund/purchases.py`, `apps/tradefund/views.py`, `apps/tradefund/templates/tradefund/purchase*.html`, `apps/tradefund/jobs.py`, `apps/tradefund/tests/test_purchases.py`

**Do:**
1. **Models:**
   - `PurchaseRequest`:
     - `requester`, `unit` (null), `item` (null), `description`, `quantity`, `est_price`, `currency`, `seller` (text or link), `deliver_to_unit` (null), `deliver_to_member` (null);
     - `source` (`recipe_input`, `tool`, `adhoc`, `bill`, `operations`), `purchase_need` (FK market.PurchaseNeed, null), `offer_tool` (FK, null), `ticket`;
     - `pay_method` (`reimburse`, `holder_pays_seller`, `pooled_to_buyer`), `buyer` (Member, null);
     - `status` (`checking`, `approved`, `waiting_for_euros`, `paying`, `bought`, `delivered`, `closed`, `rejected`);
     - `receipt` (PrivateFile, null), `actual_price`, `change_due`.
   - `GroupTool`: `item`, `purchase_request`, `lent_to_unit`, `euro_price`, `currency`, `lifetime_uses`, `acquired_at`, `status` (`in_use`, `returned`, `broken`).
2. **Monthly job `tradefund.purchase_lists`:** for each unit, turn the open `PurchaseNeed` rows of the month into one purchase request per item (source `recipe_input`). A need with a due date sooner than `market.outside_input_days` becomes a request at once.
3. **`check_purchase(pr)`:**
   - the plan check (`plan.check.check({"type": "purchase", ...})`);
   - **make or buy:** if an active offer of the same item exists in Unicorn, add an amber point: "Unicorn makes this: <unit>, <value> UNIQ". The planning-rate comparison of docs/03 section 8 uses `macro.planning_rate()`, a stub returning `economy.planning_rate.fallback_eur_per_hour` until P09.
4. **Approval** (docs/07 section 3, step 3):
   - green and ≤ `governance.ticket_limits.purchase_auto_eur` → approved automatically;
   - ≤ `purchase_confirm_max_eur`, or any amber or red → 4 confirmers;
   - above it → only if a plan investment line covers it (P11; until then, a referendum).
5. **The payment plan** (docs/07 section 3, step 4):
   - `reimburse` if the requester is a holder whose score is ≥ `tradefund.reimburse_min_trust` and the amount is ≤ their cap;
   - else `holder_pays_seller` when one payer covers the amount and the seller takes bank transfers;
   - else `pooled_to_buyer`: a buyer chosen from volunteers (the ticket asks for 3 days; the highest trust wins) receives the parts from up to 2 holders.

   Create the payment requests (T04).
6. **The buyer's steps:** upload the receipt, enter the actual price, mark it bought (and later sent), and if there is change, a payment request from the buyer to a holder. The receiver marks it `delivered`. If the actual price is higher than estimated, a new small purchase request is needed for the difference.
7. **Tools:** a purchase with `source = tool` creates a `GroupTool` on delivery. The `OfferTool` (`to_buy`) becomes `unicorn_owned`, with `euro_price` and `lifetime_uses`, and the offer can be published (P04.T03).

**Tests:**
- monthly needs become one request per item;
- the auto-approval limit;
- each of the three payment methods creates the right requests;
- a delivered tool unblocks its offer;
- the make-or-buy point appears when Unicorn makes the item.

---

### - [ ] P08.T08 — Donations in euros or dollars

**Read:** docs/07 section 8; HF-18.
**Files:** `apps/tradefund/models.py` (Donation), `apps/tradefund/views.py`, `apps/tradefund/templates/tradefund/donate.html`, `apps/tradefund/tests/test_donations.py`

**Do:**
1. **`Donation`:** `donor_member` (null), `donor_name_enc` (for outside donors, `system_encrypt`), `holder`, `amount`, `currency` (one of `tradefund.donation_currencies`), `status` (`pledged`, `received`, `cancelled`), `pledged_at`, `received_at`.
2. **The page "Donate":**
   - choose an amount and a currency;
   - the app picks a holder in that currency with room under their cap who allows `iban_shown_to_donors`, and shows the IBAN and the reference "Unicorn donation D-000045";
   - it says plainly: "Donations earn no UNIQ. They are not tax-deductible."
3. **The holder confirms receipt** → `post_fund(holder, donation, +amount)`, and the reserve share is marked (T06).
4. **A holder may record a donation from their own money** (the same flow, with themselves as donor).

**Tests:**
- `test_hf18_donation_creates_no_uniq` (no ledger transaction after a received donation);
- USD donations go to a USD holder.

---

### - [ ] P08.T09 — Members' bills: benefit and guarantee claims

**Read:** docs/07 section 9.
**Files:** `apps/tradefund/models.py` (BenefitClaim, BenefitBill, GuaranteeClaim), `apps/tradefund/benefits.py`, `apps/tradefund/views.py`, `apps/tradefund/jobs.py`, `apps/tradefund/tests/test_benefits.py`

**Do:**
1. **Models:**
   - `BenefitClaim`: `member`, `status` (`draft`, `confirming`, `approved`, `active`, `paused`, `ended`, `rejected`), `approved_monthly_eur`, `burden_score` (Decimal: the monthly bills ÷ the member's own euro income, as stated), `ticket`, `documents` (M2M PrivateFile), `created_at`.
   - `BenefitBill`: `claim`, `kind` (`rent`, `health_insurance`, `care_insurance`, `basic_needs`, `other`), `amount_eur`, `payee_external` (FK ExternalPayee) or paid to the member.
   - `GuaranteeClaim`: `member`, `month`, `shortfall_eur`, `explanation`, `ticket`, `status`.
2. **Filing:**
   - a claim is a `benefit_claim` ticket (4 seats, who may view the claim's documents while it is open: extend `can_view_file`);
   - its brief is generated from the bills, without the member's name; only the seats see the documents.
3. **Monthly job `tradefund.benefits`** (after T10 has set the month's budget):
   1. approved guarantee claims first;
   2. then active benefit claims by `burden_score`, highest first, while the budget lasts;
   3. payment requests to each bill's payee (`reason_kind = bill`) or to the member;
   4. claims that do not fit wait, and the member is told why.
4. **The budget rule** (docs/07 section 9; simulation `trade.benefits.*`):
   - `target` = (euros received in the last 12 months − other outgoings in the last 12 months) ÷ 12;
   - the budget moves 1/`economy.benefits.adjust_months` of the way toward `target` each month;
   - if the reserve is below `tradefund.reserve_min_months`, it is cut by `economy.benefits.cut_per_month_below_min_reserve`;
   - it grows only while `macro.attractiveness()` ≥ `economy.benefits.min_attractiveness`. `macro.attractiveness()` is a stub returning None until P09; None counts as satisfied, marked `# OWNER-CHECK`.

**Tests:**
- the guarantee is paid before benefits;
- the heaviest burden first;
- the budget cuts below the minimum reserve;
- only seated confirmers see the documents.

---

### - [ ] P08.T10 — Priorities, the reserve, pausing euro-hungry offers

**Read:** docs/07 section 10.
**Files:** `apps/tradefund/allocation.py`, `apps/tradefund/jobs.py`, `apps/catalogue/models.py` (add `paused_for_euros` to Offer), `apps/tradefund/tests/test_allocation.py`

**Do:**
1. **`monthly_outgoings_eur()`:** the average of the last 12 months of confirmed payments out (or of the months so far).
2. **`reserve_months()`** = free holdings in EUR ÷ `monthly_outgoings_eur()`. It feeds the euro-reserve light (P09).
3. **Monthly job `tradefund.allocate`**, in this order, each step only with what is left:
   1. **payments already approved;**
   2. **approved tool purchases** (sources `tool`, or plan investment lines);
   3. **materials** (source `recipe_input`). If they do not fit, pause offers in order of `euro_content ÷ value_total`, highest first (`paused_for_euros = True`, with a notice to their unit), until they fit or until the paused offers reach `1 − economy.min_offer_share_when_euros_short` of members' usual purchases (measured in UNIQ of orders over the last 3 months);
   4. **guarantee claims, then benefits** (T09's budget);
   5. **the reserve** up to `tradefund.reserve_target_months`;
   6. **extras:** tools and land from the plan's lists, only above a full reserve.

   With `economy.euro_priority = goods`, swap steps 2 and 3.
4. **When euros allow,** unpause offers in reverse order, and tell the units.
5. **The marketplace** shows paused offers as "Paused: the trade fund is short of euros".

**Tests:**
- with too few euros, the most euro-hungry offer pauses first, and at least 44% of usual purchases stay on offer;
- with `euro_priority = goods`, the order of steps 2 and 3 swaps;
- the reserve months are computed right.

---

### - [ ] P08.T11 — Fund pages, leaving holders, the yearly statement

**Read:** docs/07 sections 2 ("Leaving") and 6 ("The yearly statement").
**Files:** `apps/tradefund/views.py`, `apps/tradefund/templates/tradefund/*.html`, `apps/tradefund/services.py`, `apps/tradefund/tests/test_pages.py`

**Do:**
1. **The public page `/fund/`** (no names, no member numbers):
   - totals by currency and in EUR, and reserve months;
   - euros in and out over the last 12 months by kind (set-asides, donations, materials, tools, benefits, operations);
   - the number of holders and the largest share any single holder holds.
2. **"My holding":** what I hold (free and reserve), requests to pay and to confirm, history, trust and cap.
3. **Leaving.** Add to `LEAVE_CHECKS`: a holder with a holding above 0 must hand it over.
   - The button "Hand over my holding" creates payment requests to holders with room (reason `internal`), and status `leaving`.
   - When all are confirmed, status `left`.
   - Leaving or deleting the account while still holding is blocked. A holder who disappears gets a `left_without_handover` event (score 0), and the loss reserve covers the amount (docs/07 section 5).
4. **Yearly statement** `/fund/statement/<year>/`: for a member, what they set aside (from P10), held, sent on and received, with dates and ticket numbers, as HTML and CSV for their tax adviser.

**Tests:** the public page has no names; leaving is blocked while holding; the statement sums match the fund entries.

---

## Acceptance check for phase 08

1. Two founders become holders.
2. A donation of €100 is recorded, and 2% of it is marked reserve.
3. The bakery's salt purchase need becomes a purchase request: auto-approved, paid by a reimbursement, and closed with a receipt.
4. A €300 tool purchase is approved by 4 confirmers and pooled to a buyer from 2 holders. On delivery, the woodshop's chair offer is unblocked.
5. A missed payment lowers the trust score and is covered from the reserve.
6. `test_hf11_`, `test_hf12_` and `test_hf18_` tests pass.
7. Add a line to PLAN.md "Progress".
