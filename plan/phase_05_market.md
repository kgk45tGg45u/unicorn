# Phase 05 — The marketplace: orders, bookings, production, stock, the needs board

**Goal:** members order products (made after the order, a tenth ahead), book services (paid when performed), and buy in person. Orders turn into production orders and input requests down the chain. Unsold products are written off. The needs board shows what is missing.
**Read first:** docs/06 sections 4–7, docs/04 section 8, docs/03 section 9, docs/01 rules HF-3, HF-5, HF-8, HF-9, HF-10.

**Owner decision 2026-11-22 (docs/11):** hours of a person working alone in a unit are confirmed by the person who received the service (if in Unicorn); for production, 2 random members audit the worker's profile and confirm. Replace the automatic approval of one-person units (P03.T08) when bookings exist allows it.


---

### - [x] P05.T01 — Orders for products

**Read:** docs/06 section 5 ("Orders").
**Files:** `apps/market/` (new app), `apps/market/models.py` (Order, OrderLine), `apps/market/services.py`, `apps/market/tests/test_orders.py`

**Do:**
1. **Models:**
   - `Order`: `buyer` (Member), `kind` (`member`; `outside` comes in P10), `delivery_mode` (`pickup`; more in P12), `note`, `created_at`.
   - `OrderLine`:
     - `order`, `offer`, `quantity` (Decimal > 0);
     - `price_uniq` (Decimal(18,4): the offer's `value_total` at ordering, HF-3), `total_uniq`;
     - `hold` (FK ledger Hold, null);
     - `status`: `placed`, `from_stock`, `in_production`, `ready`, `delivered`, `refused`, `cancelled`;
     - `due_date`, `production_order` (FK, null), `stock_lot` (FK, null), `delivered_at`.
2. **`place_order(member, offer, quantity) -> OrderLine`:**
   - The buyer's status must be `member` or `former`: former members may spend (HF-8). Applicants may not.
   - The offer must be `active` and a product.
   - `total = uniq(price × quantity)`; `place_hold(member, total, ...)` fails with "Not enough UNIQ available".
   - **Shortage cap:** if `macro.lights.item_red(offer.item)` is true (a stub returning False until P09), the member's lines for this item this month must stay ≤ `market.shortage_cap_per_member`.
   - Then: from stock if a lot is available (T04), else into production (T02). `due_date = today + lead_time_days(offer)`.
3. **`cancel_line(line, member)`:** free while the line's production order has not started (`economy.products.cancel_rule`), which releases the hold. After that, refuse with "This order is already being made".

**Tests:**
- `test_hf03_price_fixed_at_ordering` (recompute values after ordering; the line keeps its price);
- `test_hf08_former_member_can_order`;
- an applicant cannot order;
- cancelling releases the hold.

---

### - [x] P05.T02 — Production orders and batches

**Read:** docs/04 sections 4 and 8; docs/06 section 5 ("Continuous units").
**Files:** `apps/market/models.py` (ProductionOrder, WeeklyPlan), `apps/market/services.py`, `apps/market/tests/test_production.py`

**Do:**
1. **Models:**
   - `ProductionOrder`: `offer`, `quantity` (Decimal), `origin` (`orders`, `advance`, `own_initiative`, `input_request`), `status` (`open`, `started`, `done`, `cancelled`), `due_date`, `started_at`, `done_at`, `quantity_done`.
   - `WeeklyPlan`: `offer`, `quantity_per_week`, `set_by` (FK CouncilDecision, null for one-person units), `valid_from`.
2. **`assign_to_batch(line)`:**
   - **`continuous` units:** use this week's production order (create it from the `WeeklyPlan` if missing) while its quantity minus the already-assigned quantity covers the line; otherwise next week's.
   - **Other modes:** use an `open` production order of the offer whose quantity is below a multiple of `batch_size` and whose due date is at most 7 days after the line's due date; otherwise create one.

   Then add the quantity and link the line (status `in_production`).
3. **`start_production(po, member)`** (a worker) → `started`. From now on, its lines cannot be cancelled for free.
4. **`complete_production(po, member, quantity_done)`:**
   - Lines are served in the order placed and become `ready`, and their buyers are notified.
   - Any remainder becomes a stock lot (T04) with origin `advance`, or `own_initiative` if the order's origin was `own_initiative`.
5. **Hours link:** workers record hours with `activity = order`, `ref_type = "production_order"`, `ref_id = po.id`.

**Tests:**
- two orders for the same offer share one batch;
- a continuous unit fills its weekly plan;
- starting a batch blocks free cancellation;
- the extra output of a batch goes to stock.

---

### - [x] P05.T03 — Inputs down the chain

**Read:** docs/04 section 8.
**Files:** `apps/market/models.py` (InputRequest, PurchaseNeed), `apps/market/services.py`, `apps/market/tests/test_explode.py`

**Do:**
1. **Models:**
   - `InputRequest`:
     - `production_order` (the one that needs the input), `item`, `quantity`, `source`;
     - `supplier_offer` (FK Offer, null), `child_production_order` (FK, null), `provided_by` (Member, null);
     - `status` (`open`, `confirmed`, `delivered`, `received`, `cancelled`), `due_date`.
   - `PurchaseNeed`: `unit`, `item`, `month` (date), `quantity`, `euro_estimate`, `currency`, `status` (`open`, `requested`, `covered`). P08 turns these into purchase requests.
2. **`explode(po)`.** Runs when a production order is created or grows. For each recipe input, `need = quantity_per_batch × (po.quantity / batch_size)`; subtract what earlier input requests of this order already cover. Then by source:
   - **`unicorn`:** choose the supplier offer:
     1. the preferred supplier;
     2. else an active offer of that item in the same town;
     3. else the one with the fewest open production orders;
     4. else the lowest id.

     Create an `InputRequest`, and in the supplier unit call `assign_to_batch` with an internal line (origin `input_request`), linking `child_production_order`. Recursion stops at depth 10 with an `AuditEvent` "input chain too deep". **No UNIQ move** (HF-5; book pp. 60–61).
   - **`own_free`:** an `InputRequest` addressed to `provided_by`, who confirms it.
   - **`buy_outside`:** add the quantity to the unit's `PurchaseNeed` for this month and item.
3. **Dates:** `due_date = po.due_date − the input's own lead time`.
4. **Delivery between units:** the supplier marks the request `delivered`, and the receiving unit's worker marks it `received`. Both actions are recorded.

**Tests:**
- an order for bread creates a flour input request at the mill, which creates a mill production order;
- salt goes to a `PurchaseNeed`;
- an `own_free` input waits for its provider's confirmation;
- `test_hf05_units_exchange_no_uniq` (no ledger transaction is created by the whole chain).

---

### - [x] P05.T04 — Stock, made ahead, own initiative, written off

**Read:** docs/06 section 5 ("Made ahead", "Own initiative"); docs/03 section 3 (Waste); HF-9.
**Files:** `apps/market/models.py` (StockLot, WasteRecord), `apps/market/services.py`, `apps/market/jobs.py`, `apps/market/tests/test_stock.py`

**Do:**
1. **Models:**
   - `StockLot`: `offer`, `quantity`, `quantity_left`, `made_at`, `expires_at` (from `shelf_life_days`, null), `origin` (`advance`, `own_initiative`, `refused`), `status` (`available`, `sold_out`, `written_off`), `production_order` (FK, null).
   - `WasteRecord`: `lot`, `quantity`, `hours` (Decimal: `quantity × offer.value_total` at writing off), `period`, `created_at`. Append-only.
2. **Advance production.** `start_advance(offer, quantity, member)` creates a production order with origin `advance` when `quantity ≤ allowed_advance(offer)`:
   - `allowed_advance(offer) = advance_share × (average monthly ordered quantity over the last 3 months)`;
   - in the first 3 months, the council's estimate entered on the form.

   More than that is possible only as `own_initiative`.
3. **Own initiative:**
   - hours recorded with `activity = own_initiative` and `ref` to the production order are approved but stay `pending_sale` (P03.T08);
   - `pay_pending_sale(lot, units_sold)` pays each pending entry's minutes × `units_sold / lot.quantity`, posting `hours_pay` and `tax` like `pay_hours`, and tracking the paid fraction on the entry (`paid_fraction` Decimal field, added now);
   - when the lot is sold out, any rounding remainder is paid.
4. **Daily job `market.write_offs`:** lots that are `available` with `quantity_left > 0` and either `expires_at` passed or `made_at` older than `economy.products.unsold_after_days` become `written_off`, with a `WasteRecord`.
   - Advance lots: their hours were already paid; the waste is taken back by the next tax balance (P09, HF-9).
   - Own-initiative lots: the remaining pending hours stay unpaid. Notify the unit.

**Tests:**
- `test_hf09_unsold_advance_becomes_waste` (a `WasteRecord` with hours = quantity × value);
- own-initiative hours are paid only as units sell;
- the advance limit is enforced.

---

### - [x] P05.T05 — Handing over and paying

**Read:** docs/06 section 5 (items 4–5).
**Files:** `apps/market/services.py`, `apps/market/jobs.py`, `apps/market/tests/test_delivery.py`

**Do:**
1. **`hand_over(line, worker)`** marks the line handed over (pickup in this phase).
2. **`confirm_received(line, buyer)`** calls `capture_hold` (member → Fund 1, reason "Bought <qty> <item> from <unit>"), sets `delivered`, and draws stock (`quantity_left −=`) if the line came from stock.
3. **Job `market.auto_confirm`:** handed-over lines without an answer after `market.delivery_confirm_hours` are confirmed.
4. **`refuse(line, buyer)`** after production started: the hold is captured anyway (the order was binding), the item goes into a lot with origin `refused`, and the buyer is told why.
5. **Disputes:** "Not received" or "Damaged" open a flag ticket (from P06; until then, record an `AuditEvent`), and the hold stays.

**Tests:**
- confirming captures the hold into Fund 1;
- auto-confirm after 48 hours;
- refusing after the start still charges the buyer.

---

### - [x] P05.T06 — Services: bookings, performed, confirmed, paid

**Read:** docs/06 section 4; docs/04 section 3 (services cannot be stored).
**Files:** `apps/market/models.py` (ServiceSlot, Booking), `apps/market/services.py`, `apps/market/jobs.py`, `apps/market/tests/test_bookings.py`

**Do:**
1. **Models:**
   - `ServiceSlot`: `offer` (a service offer), `provider` (Member, a worker of the unit), `starts_at`, `ends_at` (= `starts_at + duration`), `capacity_left`, `status` (`open`, `full`, `cancelled`, `done`).
   - `Booking`:
     - `slot`, `customer` (Member);
     - `price_uniq` (the snapshot, HF-3), `hold` (null for free social services);
     - `status` (`booked`, `performed`, `confirmed`, `disputed`, `no_show`, `cancelled`), `performed_at`, `confirmed_at`, `dispute_text`.
2. **Providers create slots** one by one, or "every Tuesday 10:00 for 8 weeks".
3. **`book(customer, slot)`:**
   - holds the price, unless the offer's unit is `social`, in which case it is free;
   - `capacity_left −= 1`.
4. **`mark_performed(slot, provider)`:** each booking of the slot becomes `performed`; `no_show` can be set per booking.
5. **`confirm_performed(booking, customer)`**, or the job `market.auto_confirm_bookings` after `economy.services.customer_confirm_hours`:
   - captures the hold;
   - when the **first** booking of a slot is confirmed, creates the provider's `HoursEntry`: `activity = booking`, `minutes = duration + travel (if place == customer)`, `ref = slot`. It goes to `submit_hours`, and is approved at once in a one-person unit, or by the council's batch in others. **The provider is paid only for performed sessions** (`economy.services.pay_rule = when_performed`, owner 2026-11-21).
   - For a group session with empty seats: the provider is still paid the session time, and the empty share `(capacity − confirmed)/capacity × duration` is recorded as idle time for the warning light (P09).
6. **`no_show`:** nothing is paid, unless `economy.services.no_show_paid` is true; the provider can note it.
7. **Disputes** go to a flag ticket (P06).
8. **The other pay rules** (`planned_shifts`, `by_type`) are **not built now**. `pay_rule` must be `when_performed`, otherwise the code raises `NotImplementedError("see plan/phase_16_later.md")`.

**Tests:**
- booking holds, confirming pays the provider once per slot;
- a no-show pays nothing;
- a social service costs the customer nothing but pays the provider;
- `test_hf09_services_cannot_be_stored` (no stock lot can be created for a service offer).

---

### - [x] P05.T07 — Standing orders

**Read:** docs/06 section 5 ("Standing orders").
**Files:** `apps/market/models.py` (StandingOrder), `apps/market/jobs.py`, `apps/market/tests/test_standing.py`

**Do:**
1. **`StandingOrder`:** `member`, `offer`, `quantity`, `every` (`week`, `month`), `next_date`, `status` (`active`, `paused`, `ended`).
2. **Daily job `market.standing_orders`:** for each active standing order due today, call `place_order` (at today's price). If UNIQ are not available, skip this time and notify; then set `next_date`.
3. **Pages:** pause and end from "My orders".

**Tests:**
- a weekly order creates a line every week at that day's price;
- not enough UNIQ skips and notifies.

---

### - [x] P05.T08 — Paying in person with a QR code

**Read:** docs/06 section 6 ("Buying in person").
**Files:** `apps/market/models.py` (Sale), `apps/market/views.py`, `apps/market/templates/market/sale*.html`, `apps/market/tests/test_sale.py`

**Do:**
1. **`Sale`:** `offer`, `quantity`, `seller` (a worker of the unit), `code` (10 random characters), `amount_uniq`, `status` (`open`, `paid`, `expired`), `expires_at` (now + 10 minutes), `buyer` (null), `stock_lot` (null).
2. **The seller's page** "Sell in person": choose an offer and quantity. The page shows a QR code (SVG made with the `qrcode` package, which allauth's mfa already installs) for the URL `/pay/<code>/`.
3. **`/pay/<code>/`:** the buyer sees what, how much, and from whom, and confirms. Re-authentication (`sensitive_action`) is needed above 10 UNIQ. A purchase is posted directly (member → Fund 1), and for products the stock lot is drawn.
4. **Expired codes** show a friendly message.

**Tests:** paying works once; an expired code cannot be paid; a seller cannot pay their own sale.

---

### - [x] P05.T09 — Measured hours, supply weights, plausibility, close checks

**Read:** docs/04 section 6 ("Declared and measured hours"), section 10 ("Plausibility checks"); docs/06 section 3 ("Checks").
**Files:** `apps/market/measure.py`, `apps/market/jobs.py`, `apps/market/tests/test_measure.py`

**Do:**
1. **`measured_hours(offer)`:**
   - approved minutes of hours entries linked to the offer's production orders (or slots), over the last `catalogue.measure_window_months`, divided by the units delivered (or customers served) in that window;
   - it returns `None` unless at least `catalogue.measure_min_hours` hours and `catalogue.measure_min_units` units exist.

   `catalogue.recompute_values` uses it (set `measured_hours_per_unit` and `value_basis`).
2. **`supply_weights()`** replaces the equal weights: per item, each offer's share of the quantity delivered in the same window (equal shares if nothing was delivered). Register it as `catalogue.SUPPLY_WEIGHTS_HOOK`.
3. **Monthly job `market.plausibility`:**
   - **Hours against output:** per offer, approved hours ÷ units delivered compared with `value_direct`. A gap above `governance.plausibility.deviation` for `governance.plausibility.months` months creates a notice (`AuditEvent`). P06 turns it into an `hours_review` ticket.
   - **Inputs against output:** input requests received ÷ the inputs the delivered output should have needed. Above 1.3, a notice.
4. **Close checks:** add to `units.CLOSE_CHECKS` the check that no production order is `open` or `started` and no future slot has bookings.

**Tests:**
- measured hours replace declared hours after the thresholds;
- the weights follow the deliveries;
- a 40% hours gap for 2 months creates a notice;
- closing is blocked while orders are open.

---

### - [ ] P05.T10 — Reviews

**Read:** docs/06 section 6 ("Reviews").
**Files:** `apps/market/models.py` (Review), `apps/market/views.py`, `apps/market/tests/test_reviews.py`

**Do:**
1. **`Review`:** `order_line` or `booking` (exactly one), `author`, `stars` (1–5), `text`, `created_at`. One review per delivered line or confirmed booking.
2. **Shown on the offer page:** the average and the latest 10. The unit's council sees them all.
3. **Reviews never change** prices, pay or listing order (HF-3, HF-10). Add a test that the offer list order does not change with reviews.
4. **A tick box** "Also show my words as a thank-you on the unit page" adds the field `as_thanks` (bool). When it is ticked, call `RECOGNITION_HOOK(author, "thanks", review)` (see P05.T12; it does nothing until P13).

**Tests:** only the buyer can review, and once; `test_hf10_reviews_do_not_change_order`.

---

### - [ ] P05.T11 — The marketplace pages

**Read:** docs/06 section 6.
**Files:** `apps/market/views.py`, `apps/market/urls.py`, `apps/market/templates/market/*.html`, `apps/market/tests/test_pages.py`

**Do:**
1. **`/market/`:** search by text; filters for product or service, trade and town. Results are offer cards: item, unit and town, price with the direct/indirect split, euro content, the expected date or next free slot, and the average stars. Order: same town first, then alphabetical; never by price or stars.
2. **The order form** on the offer page (quantity, pickup) and **the booking calendar** for services (the open slots of the next 4 weeks).
3. **"My orders":** lines and bookings with their status, and the buttons cancel, confirm, refuse, dispute and review.
4. **The unit's "Work" page** for its workers:
   - production orders (start, complete);
   - input requests to confirm or deliver;
   - slots and bookings (mark performed);
   - ready lines (hand over);
   - purchase needs.

**Tests:** the search finds by item name; "My orders" shows only the member's own lines.

---

### - [ ] P05.T12 — The needs board

**Read:** docs/06 section 7.
**Files:** `apps/market/models.py` (WaitingListEntry, SearchMiss, DemandSignal), `apps/market/jobs.py`, `apps/market/views.py`, `apps/market/templates/market/needs.html`, `apps/market/tests/test_needs.py`

**Do:**
1. **Models:**
   - `WaitingListEntry`: `member`, `item`, `quantity`, `created_at`, `fulfilled_at`. "Tell me when available" is offered when no active offer can deliver within 30 days.
   - `SearchMiss`: `area` (the first 2 digits of the searcher's postcode), `text` (normalised: lower case, trimmed), `month`, `count`. Only searches with no result are counted, and the searcher is never stored.
   - `DemandSignal`: `offer`, `month`, `demand` (ordered + waiting), `supply` (made ahead + made), `ratio`.
2. **Monthly job `market.demand_signals`** (docs/03 section 9):
   - compute `ratio` per offer;
   - `ratio > 1.1` for 2 months: notify the unit's council "Members want more than you make: consider a larger batch or weekly plan", and mark the item "wanted";
   - `ratio < 0.9` for 2 months: "Consider making less ahead".

   **Only suggestions** (HF-15).
3. **`/needs/`**, four sections (docs/06 section 7):
   - **Wanted now:** items with waiting lists or a "wanted" mark; people, quantity, hours per month it would give (quantity × the item's average value).
   - **Bought from outside:** `PurchaseNeed` grouped by item over the last 3 months (euros per month, number of units buying it, "placeholder" badge).
   - **Plan focus:** empty with the text "The first yearly plan will fill this" (P11).
   - **Missing near you:** `SearchMiss` for the member's area, top 10.

   Each card has the button **"I can make this"**: it opens the unit form (P03.T06) or "Add an offer" in one of the member's units, with the item prefilled.
4. **"Needs that match your skills":** cards whose item `trade_code` matches one of the member's skills.
5. **When an offer for a "wanted" or "bought from outside" item is published,** call `RECOGNITION_HOOK(member, "filled_need", item)`. Define it in `apps/core/hooks.py` as a function that calls every function in the list `RECOGNITION_HANDLERS`. The list is empty until P13, so the call does nothing yet, and the market never imports the app that fills it.

**Tests:**
- a waiting list shows under "Wanted now";
- a `PurchaseNeed` shows under "Bought from outside" with its euros;
- `SearchMiss` never stores a member;
- `test_hf10_needs_board_assigns_nothing` (no needs-board action creates hours, orders or obligations for anyone).

---

## Acceptance check for phase 05

1. A member orders 2 loaves: the bakery's batch, the mill's input request and the salt purchase need appear.
2. The bakery completes the batch; the member confirms receipt, and Fund 1 receives 0.2850 UNIQ.
3. A haircut is booked, performed and confirmed; the hairdresser's 1-hour entry is paid.
4. An advance lot expires and becomes waste.
5. The needs board shows salt under "Bought from outside".
6. Add a line to PLAN.md "Progress".
