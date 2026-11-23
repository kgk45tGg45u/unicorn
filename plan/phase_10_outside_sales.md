# Phase 10 — Selling to outsiders: the shop, invoices, set-asides

**Goal:** members sell to outside customers in their own name, at euro prices set by their unit's council. Products are made on order, with a tenth ahead. Customers pay the seller directly. The fund's set-aside is recorded, and the cap on outside-sales hours holds. Invoices and yearly statements support members' taxes.
**Read first:** docs/07 sections 6–7, docs/02 section 5 (outside sales are the condition for independence), docs/01 rules HF-3, HF-4, HF-12.

---

### - [x] P10.T01 — Becoming an outside seller; euro prices by the council

**Read:** docs/07 section 6 ("Who sells", "What and at what price").
**Files:** `apps/outside/` (new app), `apps/outside/models.py` (SellerProfile), `apps/members/fixtures/contracts.json` (add `outside_seller` v1), `apps/outside/services.py`, `apps/outside/views.py`, `apps/outside/tests/test_seller.py`

**Do:**
1. **`SellerProfile`:**
   - `member` (OneToOne), `active` (bool), `trader_name` (the name shown on invoices), `trader_address_enc` (`system_encrypt`; shown to customers on invoices and the imprint of the seller's offers);
   - `small_business` (bool: § 19 UStG), `vat_id` (blank), `tax_reserve_share` (Decimal, default `economy.tax_on_outside_sales_estimate`; a change needs a reason, kept in an `AuditEvent`);
   - `started_at`.
2. **`activate_seller(member, ...)`.** Requires: a verified member who is also an **active holder** (P08.T02), so that the set-aside has a place. Signs the `outside_seller` contract. Its fixture text starts "DRAFT — to be written with lawyers" and says:
   - you sell in your own name;
   - your name and address appear on invoices;
   - you pay your own taxes from the tax reserve;
   - the set-aside belongs to the group.
3. **Choosing what is sold outside.** For each offer, the council (by a council decision of kind `outside_prices`; a one-person unit decides directly) sets `sold_outside`, `outside_price`, `outside_currency`, and the **seller of record**: a worker of the unit with an active `SellerProfile`. Add the field `outside_seller` (FK Member, null) to `Offer`. UNIQ prices are untouched (HF-3).

**Tests:** activating without being a holder is refused; changing the tax reserve needs a reason; an offer can be sold outside only with a seller of record.

---

### - [x] P10.T02 — The outside shop and checkout

**Read:** docs/07 section 6 ("The outside shop").
**Files:** `apps/outside/models.py` (OutsideCustomer), `apps/market/models.py` (OrderLine: `price_eur`, `currency`, `seller`), `apps/outside/views.py`, `apps/outside/templates/outside/*.html`, `apps/outside/tests/test_shop.py`

**Do:**
1. **`/shop/`** (public, no login): the offers with `sold_outside`. Each shows the item, the unit's town, the euro price, the expected date or next slot, and the seller's trader name.
2. **`OutsideCustomer`:** `name_enc`, `email_enc`, `address_enc` (all `system_encrypt`), `country`, `privacy_consent_at`, `delete_contact_after` (delivery + 90 days; a daily job wipes the contact fields then, while the invoice keeps its own copy, T05).
3. **Checkout:**
   1. quantity and delivery mode (pickup; others in P12);
   2. contact details;
   3. the consumer information (T06);
   4. a button that reads **"Order with obligation to pay"**.

   This creates an `Order` of kind `outside`, with lines that store `price_eur` and `currency` (snapshots) and `seller`. Production orders get purpose `outside`, and the advance limit uses `economy.products.outside_advance_share`. Service offers sold outside use the same slots, with a booking for the outside customer (add `outside_customer` to `Booking`).
4. **The confirmation email** to the customer: what was ordered, the seller's payment details (IBAN shown with the seller's consent, or "pay in person"), the reference, and the withdrawal information.

**Tests:**
- the shop shows only offers sold outside;
- an outside order stores the euro price and the seller;
- `test_hf04_outside_orders_never_touch_uniq` (no ledger entry is created by an outside order or its payment).

---

### - [x] P10.T03 — Payment received and the set-aside

**Read:** docs/07 section 6 ("Payment", "The set-aside"); docs/07 section 5 (reserve).
**Files:** `apps/outside/services.py`, `apps/outside/tests/test_setaside.py`

**Do:**
1. **`confirm_customer_payment(order, seller, amount)`** (`sensitive_action`):
   - marks the lines paid, so production can start;
   - computes `tax_reserve = cur(amount × seller.tax_reserve_share)`;
   - computes `setaside = cur((amount − tax_reserve) × tradefund.setaside_share_of_net)`;
   - posts `post_fund(seller_holder, setaside, +setaside, reason="Set-aside of outside sale <invoice no.>", reason_kind="internal")`;
   - marks the loss reserve share (P08.T06);
   - checks the seller's cap and requests a transfer of any excess (P08.T06).
2. **Unpaid outside orders** are not produced. After 14 days without payment they are cancelled, and the customer is told.
3. **Refunds** (a withdrawal or a failed delivery): the seller refunds the customer from their own account. `post_fund(seller_holder, correction, −setaside)` reverses the set-aside, and the tax reserve stays with the seller.

**Tests:**
- €100 with a 15% reserve and a 100% share → €85 set aside, of which €1.70 is reserve;
- an unpaid order is cancelled after 14 days;
- a refund reverses the set-aside.

---

### - [x] P10.T04 — The cap on outside-sales hours

**Read:** docs/07 section 6 ("The cap on outside sales"); `economy.outside_sales_cap_share`.
**Files:** `apps/outside/cap.py`, `apps/outside/tests/test_cap.py`

**Do:**
1. **`outside_hours_this_month()`:** Σ over outside order lines of the month of `quantity × the offer's value_total` (the hours inside them).
2. **`cap_hours()`:** `economy.outside_sales_cap_share × expected hours of the month` (the tax balance's `H`, P09.T03).
3. **When a new outside order would pass the cap,** the shop offers the earliest date in the next month instead ("Available from <date>"). The unit's council is told. This applies a limit the plan already decided (docs/07 section 6).

**Tests:** below the cap, orders are taken for this month; above it, they move to next month.

---

### - [x] P10.T05 — Invoices and the small-business limit

**Read:** docs/07 section 6 ("Who sells"); legal frame section 4 (VAT).
**Files:** `apps/outside/models.py` (Invoice), `apps/outside/invoices.py`, `apps/outside/templates/outside/invoice.html`, `apps/outside/tests/test_invoices.py`

**Do:**
1. **`Invoice`:**
   - `order`, `seller` (Member), `number` (unique per seller: `<member number>-<year>-<4-digit seq>`), `issued_on`;
   - `customer_snapshot_enc` (`system_encrypt` of the name and address at issue);
   - `lines` (JSON: item, quantity, unit price, total), `total`, `currency`;
   - `vat_note` ("No VAT is charged under § 19 UStG (small business)" when `small_business`; else the VAT rate and amount fields), `paid_at`;
   - `keep_until` (issue date + 8 years, `# OWNER-CHECK: legal keeping period`).
2. **`issue_invoice(order)`** runs on payment confirmation, with gap-free numbering per seller (a counter row locked with `select_for_update`).
3. **The printable HTML** (A4 print CSS) shows the trader name and address, the customer, the lines, the VAT note and the number. The seller and the customer can download it.
4. **The small-business limit:** each seller's turnover this year and last year. At 80% of €25,000 (last year) or €100,000 (this year), notify the seller with a plain explanation.

**Tests:** numbering is gap-free per seller; the VAT note follows the setting; the turnover warning triggers at 80%.

---

### - [x] P10.T06 — Consumer information and withdrawal

**Read:** docs/07 section 6; docs/08 section 8 (legal pages).
**Files:** `apps/outside/templates/outside/consumer_info.html`, `.../withdrawal.html`, `apps/outside/services.py`, `apps/outside/tests/test_withdrawal.py`

**Do:**
1. **Consumer information** (every page starts "DRAFT — to be checked by lawyers"):
   - the trader's identity and address;
   - the main features and the total price;
   - payment and delivery;
   - the 14-day right of withdrawal for goods bought at a distance, and its exceptions (goods made to the customer's specification);
   - for services, the customer's request to start within the withdrawal period, with the consequence explained.
2. **A withdrawal form page** for customers. Submitting it notifies the seller and starts the refund steps of T03.
3. **Tick box at checkout:** "I have read the consumer information".

**Tests:** a withdrawal within 14 days creates the seller's task; after 14 days the form explains that the period has ended.

---

### - [x] P10.T07 — Outside deliveries in the books of hours

**Read:** docs/03 sections 3 (Trade) and 8 (planning rate).
**Files:** `apps/macro/accounts.py`, `apps/macro/world.py`, `apps/outside/tests/test_macro_link.py`

**Do:**
1. **When an outside line is delivered** (pickup confirmed by the seller, or a delivery confirmed in P12), record its hours (`quantity × value_total` at ordering; add the field `value_at_order` to `OrderLine`) for the period's `trade` use.
2. **Replace the zeros** in P09.T06's world metrics with real data:
   - `outside_sales_per_member_eur` = confirmed outside payments this month (in EUR) ÷ active members;
   - the planning rate = (payments − tax reserves) ÷ the hours of the delivered outside lines, over the measuring window;
   - `tax_on_outside_sales_share` = the tax reserves ÷ the payments.

**Tests:** an outside sale raises `trade` by its hours; the planning rate after three sales equals the hand calculation.

---

### - [x] P10.T08 — The yearly statement, now with sales

**Files:** `apps/tradefund/views.py`, `apps/tradefund/templates/tradefund/statement.html`, `apps/outside/tests/test_statement.py`

**Do:**
1. **Extend the yearly statement of P08.T11** with each invoice (number, date, total, currency), the tax reserve kept, and the set-aside.
2. **Totals per currency,** and in EUR at the ECB rates of the invoice dates.

**Tests:** the statement's totals equal the sum of the invoices and set-asides.

---

## Acceptance check for phase 10

1. The woodshop sells an oak chair to an outside customer for €180.
2. The customer pays, the seller confirms, and an invoice is issued with the § 19 note.
3. €153 is set aside (15% tax reserve), and €3.06 of it is marked reserve.
4. The chair is made on order and handed over, and the month's `trade` hours rise by 4.30.
5. `/on-track/` shows outside sales per member.
6. Add a line to PLAN.md "Progress".
