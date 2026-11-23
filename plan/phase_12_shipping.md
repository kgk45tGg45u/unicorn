# Phase 12 — Shipping and fulfilment

**Goal:** units have cover areas measured in kilometres. Orders can be picked up, delivered by Unicorn couriers (whose hours are priced like any service), or sent by capitalist carriers paid by the trade fund. Deliveries are confirmed.
**Read first:** docs/06 section 8, docs/04 section 6 (service values), docs/03 section 8 (make or buy), docs/01 rule HF-3.

---

### - [x] P12.T01 — Postcode coordinates

**Files:** `apps/logistics/` (new app), `apps/logistics/models.py` (PostcodePoint), `apps/logistics/management/commands/load_postcodes.py`, `apps/logistics/tests/fixtures/DE_sample.txt`, `apps/logistics/tests/test_postcodes.py`, `THIRD_PARTY.md` (the attribution)

**Do:**
1. **`PostcodePoint`:** `country`, `postcode`, `town`, `lat`, `lng` (Decimal(9,6)); unique (`country`, `postcode`). When a postcode has several places, keep the first, and average the coordinates if they differ.
2. **`load_postcodes <file> --country DE`** reads the GeoNames postal-code format: tab-separated, with columns country, postal code, place name, admin1–3 names and codes, latitude, longitude, accuracy.
   - The operator downloads `https://download.geonames.org/export/zip/DE.zip` once. Its licence is CC BY 4.0: add the line "Postcode data © GeoNames, CC BY 4.0" to `THIRD_PARTY.md` (create the file if it does not exist yet; P14.T07 shows it on the third-party page).
   - The command never runs at request time, and tests use the small fixture.
3. **When a unit or member postcode is saved,** set the unit's `lat` and `lng` from the table. Members keep only their postcode; their coordinates are looked up when needed.

**Tests:** the fixture loads; a unit gets coordinates from its postcode; an unknown postcode leaves them empty and shows "We could not place this postcode".

---

### - [x] P12.T02 — Cover areas

**Read:** docs/06 section 8 ("Cover area of a unit").
**Files:** `apps/logistics/geo.py`, `apps/market/views.py`, `apps/logistics/tests/test_cover.py`

**Do:**
1. **`haversine_km(lat1, lng1, lat2, lng2)`** (Earth radius 6,371 km).
2. **`covers(unit, country, postcode) -> bool`:** true if the postcode is in `unit.cover_postcodes`, or its point lies within `unit.cover_radius_km` of the unit. Without coordinates, fall back to the same town.
3. **The marketplace** marks offers as "deliverable to you" or "pickup only", using the member's postcode. Search can be filtered to "deliverable to me".
4. **The units' "near" rule** in P04.T08 (join forces) and P11.T02 (demand nearby) now uses kilometres (`units.join_forces_km`, and the unit's radius).

**Tests:** the distance between two known points; inside or outside the radius; the explicit postcode list.

---

### - [x] P12.T03 — Pickup points

**Files:** `apps/logistics/models.py` (PickupPoint), `apps/logistics/views.py`, `apps/market/services.py`, `apps/logistics/tests/test_pickup.py`

**Do:**
1. **`PickupPoint`:** `name`, `address_public` (a public place: a shop, a community room), `postcode`, `country`, `opening_notes`, `managed_by_unit` (FK, null), `managed_by_local_council_id` (int, null; the FK comes in P13), `active`.
2. **The delivery options** of an order line become: pickup at the unit, or pickup at a point within the unit's cover area. Units choose which points they serve.
3. **When the unit hands an order to a point,** the point's manager confirms it, and the buyer confirms pickup (P05.T05).

**Tests:** only points inside the cover area are offered; the hand-over steps.

---

### - [x] P12.T04 — Unicorn couriers

**Read:** docs/06 section 8 (the table, row `unicorn_courier`).
**Files:** `apps/logistics/models.py` (CourierOffer), `apps/logistics/quotes.py`, `apps/market/services.py`, `apps/logistics/tests/test_courier.py`

**Do:**
1. **A courier unit** (`kind = courier`) publishes a service offer for the item "Delivery" (uom `service`). Its recipe has:
   - `CourierOffer` (OneToOne to Offer): `speed_kmh` (default `logistics.courier_speed_kmh`), `stop_minutes` (default `logistics.stop_minutes`), `max_km`;
   - tools: the bicycle or van as `unicorn_owned` or `own_free`, with uses per delivery;
   - inputs: fuel or power as `buy_outside` or `own_free`.
2. **`courier_quote(courier_offer, from_point, to_point) -> (uniq, eur)`:**
   - minutes = `distance_km / speed_kmh × 60 + stop_minutes`;
   - `l = minutes / 60`, plus the offer's depreciation per use;
   - euros from its inputs per delivery.

   This is the delivery's **labour value**, computed by the same rules as every service (HF-3). It is not a price set by anyone.
3. **The delivery as an order line:** `place_order` adds a separate order line for the courier offer, quantity 1, with the quoted price snapshot. Its hold, confirmation and pay follow the services' rules (P05.T06): the courier records the delivery time and is paid when the delivery is confirmed.

**Tests:** a 3 km delivery at 15 km/h with 5 stop minutes costs (12 + 5)/60 = 0.2833 UNIQ plus depreciation; the delivery line is held and paid like a service.

---

### - [x] P12.T05 — Capitalist carriers

**Read:** docs/06 section 8 (row `capitalist_carrier`); docs/07 section 3.
**Files:** `apps/logistics/models.py` (Carrier, Shipment), `apps/logistics/quotes.py`, `apps/logistics/services.py`, `apps/logistics/tests/test_carrier.py`

**Do:**
1. **`Carrier`:** `name` (for example "DHL parcel", entered by members), `countries` (JSON list), `rate_rules` (JSON: `{"base_eur": 5.49, "per_kg_eur": 0.0, "max_kg": 31.5}`), `currency`, `active`. Carriers are added by a `confirm`-tier ticket.
2. **`choose_mode(line, destination) -> mode`** (docs/06 section 8; HF-15: the app proposes, the selling unit's responsible confirms):
   - pickup, if the buyer chose it;
   - a Unicorn courier, if one covers both ends and the make-or-buy rule of docs/03 section 8 favours it: use the courier when `courier_uniq + courier_eur / r < carrier_eur / r`, where `r` is the planning rate (P09.T06);
   - otherwise a capitalist carrier.
3. **With a carrier:**
   - **the buyer pays nothing in UNIQ** for shipping (HF-3: prices are Unicorn hours only);
   - a `PurchaseRequest` with source `operations` is created for the carrier's euros. Small amounts are auto-approved under the usual limit. The sender is usually reimbursed (P08.T07);
   - `Shipment`: `order`, `mode`, `courier_line` (null), `carrier` (null), `tracking`, `eur_cost`, `status` (`planned`, `sent`, `delivered`, `failed`), `delivered_at`, `confirmed_by`.
4. **Carrier euros** add to the month's euro outgoings. They count in the offer's euro-content statistics and in the "Are we on track?" materials figure (as shipping), never in any offer's UNIQ price.

**Tests:**
- with no courier covering, a carrier is proposed and the buyer is charged 0 UNIQ for shipping;
- the carrier's purchase request is created;
- the make-or-buy comparison picks the courier when it is cheaper in hour-equivalents.

---

### - [x] P12.T06 — Delivery choice and confirmation

**Files:** `apps/market/views.py`, `apps/market/templates/market/checkout.html`, `apps/logistics/services.py`, `apps/logistics/tests/test_delivery_flow.py`

**Do:**
1. **Checkout** for members and outside customers: "Pick up" or "Deliver to me". For delivery, the proposed mode and its cost are shown (UNIQ for couriers, "paid by the trade fund" for carriers).
2. **The selling unit's responsible** confirms or changes the proposed mode on the unit's "Work" page.
3. **On "delivered"** (the courier marks it, or the tracking number is entered and the buyer confirms), the order's lines are confirmed (P05.T05). "Damaged" and "missing" open a flag ticket (P06.T08), and the hold stays. The selling unit's responsible then chooses:
   - **replace:** a new production order or a new delivery; the hold stays;
   - **refund:** the hold is released, or, if the line was already paid, a correction is posted with a reason (P02.T03).
4. **Outside customers** confirm through a link in their email.

**Tests:** the full flow for courier and carrier deliveries; a damaged delivery opens a flag.

---

### - [x] P12.T07 — Sending abroad

**Read:** docs/07 section 11.
**Files:** `apps/logistics/services.py`, `apps/logistics/templates/logistics/abroad_notice.html`, `apps/logistics/tests/test_abroad.py`

**Do:**
1. **Other countries:** for destinations in another country, only carriers that list that country are offered. For destinations outside the EU, the seller also sees the notice "Customs declaration needed; VAT and duties may apply in the destination country (ask a tax adviser)" (`# OWNER-CHECK`).
2. **Couriers** never deliver across a national border in this phase.

**Tests:** a destination abroad shows only carriers for that country; outside the EU, the notice appears.

---

## Acceptance check for phase 12

1. With the fixture postcodes loaded, a member 3 km from the bakery sees "deliverable to you".
2. A courier delivery is quoted at 0.2833 UNIQ plus depreciation, held, delivered, confirmed and paid.
3. A member 200 km away gets a carrier proposal with 0 UNIQ shipping, and a purchase request is created for the carrier's euros.
4. Add a line to PLAN.md "Progress".
