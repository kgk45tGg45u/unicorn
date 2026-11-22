# Phase 04 — The catalogue and the input-output table

**Goal:** items and placeholders, offers with working cycles for products and services, recipes whose inputs and tools have a source, and the engine that computes every labour value (direct and indirect) and every euro content.
**Read first:** docs/04 (all of it), docs/01 rules HF-3 and HF-15.

---

### - [x] P04.T01 — Units of measure, items and placeholders

**Read:** docs/04 sections 2 and 9.
**Files:** `apps/catalogue/` (new app), `apps/catalogue/models.py`, `apps/catalogue/migrations/0002_units_of_measure.py`, `apps/catalogue/services.py`, `apps/catalogue/views.py`, `apps/catalogue/tests/test_items.py`

**Do:**
1. **`UnitOfMeasure`:** `code` (primary key), `name`, `dimension` (`count`, `mass`, `volume`, `length`, `area`, `energy`, `time`, `service`, `distance`). The data migration loads: `pc` piece, `kg`, `g`, `l` litre, `ml`, `m`, `m2`, `m3`, `kwh`, `h` hour, `service` (one service to one customer), `km`.
2. **`Item`:**
   - `name` (CharField(120)), `kind` (`product`, `service`), `uom` (FK);
   - `trade_code` (CharField(16), blank), `description`, `shelf_life_days` (null = keeps; products only);
   - `status` (`active`, `placeholder`, `retired`), `created_by_unit` (FK Unit, null), `created_at`, `last_used_at`;
   - unique (`name`, `uom`).

   A service item must have `uom = service` or `h`.
3. **Services:**
   - `find_items(text)` (name contains, case-insensitive, at most 20);
   - `create_item(...)`;
   - `get_or_create_placeholder(name, uom, unit)` returns an `Item` with status `placeholder`, the docs/04 section 9 rule.
4. **Pages:** an item page (`/items/<id>/`) with its offers (P04.T06), and an item search used by the recipe editor (HTMX endpoint returning a list).

**Tests:**
- a placeholder is created once per name and uom;
- a service item with uom `kg` is refused.

---

### - [x] P04.T02 — Offers and working cycles

**Read:** docs/04 sections 3–4.
**Files:** `apps/catalogue/models.py` (Offer), `apps/catalogue/services.py`, `apps/catalogue/forms.py`, `apps/catalogue/tests/test_offers.py`

**Do:**
1. **`Offer`:**
   - `unit` (FK), `item` (FK), `status` (`draft`, `active`, `paused`, `retired`, `value_error`);
   - product cycle fields: `batch_size` (Decimal(14,4)), `min_batch` (Decimal, null → `batch_size`), `cycle_days` (int ≥ 0), `setup_minutes` (int ≥ 0), `direct_minutes_per_batch` (int > 0);
   - service fields: `duration_minutes` (int > 0), `capacity` (int ≥ 1), `travel_minutes` (int ≥ 0), `place` (`unit`, `customer`, `online`), `max_per_week` (int, null);
   - `advance_share` (Decimal(5,4), default `economy.products.advance_share`; 0 for services), `sold_outside` (bool), `outside_price` (Decimal(14,2), null) and `outside_currency` (CharField(3), default EUR) for P10;
   - computed: `declared_hours_per_unit`, `measured_hours_per_unit` (null), `value_direct`, `value_indirect`, `value_total`, `euro_content` (all Decimal(18,4), default 0), `values_computed_at`, `value_basis` (`declared`, `measured`);
   - `created_at`, `updated_at`.
2. **`Offer.clean()`:**
   - a product offer needs `batch_size > 0` and `direct_minutes_per_batch > 0` and no service fields;
   - a service offer needs `duration_minutes > 0` and `capacity >= 1` and no batch fields;
   - the item's kind must match.
3. **`declared_hours(offer)`** follows docs/04 section 6:
   - product: `(direct_minutes_per_batch + setup_minutes) / 60 / batch_size`;
   - service: `(duration_minutes + (travel_minutes if place == "customer" else 0)) / 60 / capacity`.

   Return a `Decimal` with `uniq()`.
4. **Who may edit:** only `units.services.can_edit_unit(member, offer.unit)`.

**Tests:**
- bread `(240 + 30)/60/40 = 0.1125`;
- haircut `(40 + 20)/60/1 = 1.0000`;
- a group lesson of 90 minutes for 10 people gives `0.1500`;
- a product offer with service fields is refused.

---

### - [ ] P04.T03 — Recipes: inputs and tools with their source

**Read:** docs/04 section 5.
**Files:** `apps/catalogue/models.py` (OfferInput, OfferTool, OwnFreeConfirmation), `apps/catalogue/services.py`, `apps/catalogue/templates/catalogue/recipe_editor.html`, `apps/catalogue/tests/test_recipes.py`

**Do:**
1. **`OfferInput`:**
   - `offer`, `item`, `quantity_per_batch` (Decimal(14,4) > 0);
   - `source` (`unicorn`, `own_free`, `buy_outside`);
   - `preferred_supplier` (FK Offer, null; only with `unicorn`);
   - `euro_price_estimate` (Decimal(14,4), per uom of the input, needed with `buy_outside`), `currency` (CharField(3), default EUR);
   - `provided_by` (FK Member, needed with `own_free`), `note`.
2. **`OfferTool`:**
   - `offer`, `tool_item` (FK Item of kind product);
   - `source` (`unicorn_owned`, `own_free`, `to_buy`);
   - `uses_per_batch` (Decimal > 0), `lifetime_uses` (Decimal > 0);
   - `value_uniq` (Decimal, the tool's labour value: for a Unicorn-made tool, its offer's `value_total` at acquisition), `euro_price` (Decimal, for a tool bought with euros), `currency`, `provided_by` (Member, with `own_free`).
3. **Rules** (`validate_recipe(offer) -> list[str]`, plain sentences):
   - a `unicorn` input whose item has no active offer: "Nobody in Unicorn makes <item> yet. Choose 'I provide it free' or 'Buy it from outside'." (docs/04 section 6);
   - a placeholder item may only be `own_free` or `buy_outside`;
   - `buy_outside` needs a price estimate;
   - `own_free` needs `provided_by`, who must be a worker of the unit;
   - a tool `to_buy` blocks publishing: "Buy the tool first: ask the trade fund" (the purchase request comes in P08).
4. **`publish_offer(offer, member)`:**
   1. run `validate_recipe` (block on any message);
   2. run the licence and insurance checks of the unit (HF-17);
   3. run `plan.check.check({"type": "offer", "euros_per_month": ...})`; if red, keep the offer `draft` with the note "waiting for random confirmers" (P06);
   4. set `status = active`;
   5. enqueue `catalogue.recompute`.
5. **`OwnFreeConfirmation`:** `input`, `month` (date, the first of the month), `confirmed_at`. A monthly job `catalogue.ask_own_free` asks each `provided_by` member to confirm that they still provide the input. Inputs not confirmed for 2 months pause the offer, and the responsible is told.
6. **The recipe editor:**
   - an HTMX page: a row per input (search an item or type a new name, which makes a placeholder; quantity; the item's uom; source as three radio buttons labelled "Made in Unicorn", "I provide it free", "Buy it from outside"; the price estimate or the preferred supplier, depending on the source);
   - the same for tools;
   - a live **price preview** (T05) under the form.

**Tests:**
- each message of `validate_recipe`;
- a `to_buy` tool blocks publishing;
- an unconfirmed `own_free` input pauses the offer after 2 months.

---

### - [ ] P04.T04 — The labour-value engine

**Read:** docs/04 sections 6–7 (formulas and worked examples).
**Files:** `apps/catalogue/engine.py`, `apps/catalogue/tests/test_engine.py`

**Do:**
1. **Pure functions, with no database access,** so that they are easy to test:

   ```python
   @dataclass
   class OfferData:
       id: int
       item_id: int
       q: float  # batch_size (products) or capacity (services)
       l: float  # hours per unit (declared or measured)
       d: float  # depreciation hours per unit (unicorn_owned tools)
       m: float  # euros per unit (buy_outside inputs + euro-bought tools)
       inputs: list[tuple[int, float, int | None]]  # (item_id, quantity_per_batch, preferred_supplier_offer_id)


   @dataclass
   class ValueResult:
       direct: float
       indirect: float
       total: float
       euro: float
       error: str | None


   def solve(offers: list[OfferData], weights: dict[int, dict[int, float]]) -> dict[int, ValueResult]:
       """weights[item_id][offer_id] = share of that offer in the item's supply (sums to 1 per item)."""
   ```

2. **Build `M`** (`scipy.sparse.lil_matrix`, n × n, then `.tocsr()`). For each offer j and input `(i, a, pref)`:
   - with `pref`: `M[idx[pref], j] += a / q_j`;
   - otherwise: for each `(k, w)` in `weights[i]`, `M[idx[k], j] += (a / q_j) * w`.

   Missing weights for an item mean a validation error upstream: raise `ValueError`.
3. **Solve:**
   - `A = (I - M).T`, `v = spsolve(A, l + d)`, `e = spsolve(A, m)`;
   - if `spsolve` raises, or the result has NaN, inf or negative values, fall back to Jacobi: `v ← (l + d) + v @ M`, until `max|Δv| < 1e-6`, at most 1,000 rounds;
   - if Jacobi does not converge either, find the strongly connected components of `M` (`scipy.sparse.csgraph.connected_components`, `connection="strong"`) and give every offer in a component with more than one node (or with a self-loop) `error = "loop"`;
   - solve again without them, treating their values as 0, and report them.
4. **Results:** `direct = l_j`, `total = v_j`, `indirect = v_j - l_j`, `euro = e_j`.

**Tests** (the worked examples of docs/04 section 7, with tolerance 1e-9):
- **flour and bread:** mill `l = 0.05`, bread `l = 0.1125`, input flour 24 kg per batch of 40 → bread `total = 0.1425`, `indirect = 0.03`, `euro = 0.1325`;
- **haircut:** `total = 1.0`, `euro = 0.30`;
- **chair:** `total = 4.30`, `euro = 38.30`;
- **two suppliers with weights 0.5/0.5 and values 0.04 and 0.06** → the input costs 0.05;
- **a loop** (A needs 2 units of B per unit, and B needs 1 unit of A per unit) is reported as `error = "loop"`;
- **speed:** 5,000 random offers with 10 inputs each solve in under 5 seconds.

---

### - [ ] P04.T05 — Value runs: computing and storing prices

**Read:** docs/04 section 6 ("Declared and measured hours", "When values are computed"); HF-3.
**Files:** `apps/catalogue/models.py` (ValueRun, OfferValueHistory), `apps/catalogue/services.py`, `apps/catalogue/jobs.py`, `apps/catalogue/migrations/000X_value_history_triggers.py`, `apps/catalogue/tests/test_values.py`

**Do:**
1. **Models:**
   - `ValueRun`: `started_at`, `finished_at`, `offers` (int), `method` (`spsolve`, `jacobi`), `converged` (bool), `errors` (JSON).
   - `OfferValueHistory`: `run`, `offer`, `direct`, `indirect`, `total`, `euro`, `basis`. Append-only, with triggers via `append_only_statements`.
2. **`recompute_values()`:**
   1. **Load the active offers** and build `OfferData` for each:
      - `l` = measured hours if `measured_hours_per_unit` is set, else declared;
      - `d` from `unicorn_owned` tools: `value_uniq / lifetime_uses × uses_per_batch / q`;
      - `m` from `buy_outside` inputs (`quantity × euro_price_estimate / q`, converted to EUR; until P08 only EUR is accepted) plus tools bought with euros (`euro_price / lifetime_uses × uses_per_batch / q`).
   2. **Weights:** by default each active offer of an item has an equal share. P05 replaces this with the delivered quantities of the last 3 months, through `SUPPLY_WEIGHTS_HOOK`.
   3. **Run `engine.solve`.**
   4. **Store** a `ValueRun` and one `OfferValueHistory` row per offer, and update the offer's value fields and `values_computed_at`.
   5. **Errors:** offers with an error get status `value_error` and keep their last good values. Record an `AuditEvent`; P06 adds a ticket to their councils.
3. **Job `catalogue.recompute`** (with a dedupe key, so many edits make one run). The monthly close (P09) also calls it.
4. **`preview(offer_draft) -> ValueResult`:** the same formula, one level deep, using the current `value_total` and `euro_content` of the inputs' offers (or the weighted average per item), for the recipe editor.
5. **HF-3:** no other code may write an offer's value fields. Add a test that fails if `Offer.value_total` is assigned anywhere except in `services.py` (grep the source in the test).

**Tests:**
- `test_hf03_price_only_from_engine` (the grep test);
- after a recompute, the bread offer shows 0.1425;
- a loop sets `value_error` and keeps the old values;
- `preview` equals the full run for a simple chain.

---

### - [ ] P04.T06 — Offer and item pages

**Read:** docs/06 section 6 ("Each offer shows"); docs/04 section 4 (lead time).
**Files:** `apps/catalogue/views.py`, `apps/catalogue/templates/catalogue/offer.html`, `.../item.html`, `apps/catalogue/services.py` (lead time), `apps/catalogue/tests/test_pages.py`

**Do:**
1. **The public offer page:**
   - item, unit (and town), price `value_total` with 2 decimals and the split "direct x.xx h + indirect y.yy h";
   - euro content ("€0.13 of this is bought from outside");
   - the basis ("from the recipe" or "measured from the last 3 months");
   - the recipe (inputs with their source in words, tools);
   - the expected lead time;
   - a short "How is this price made?" text (docs/04 section 1 in three sentences).
2. **`lead_time_days(offer)`:** `cycle_days` + the longest `lead_time_days` of `unicorn` inputs (recursively, maximum depth 10) + `market.outside_input_days` if any `buy_outside` input exists. Stock is ignored until P05.
3. **The item page:** all active offers of the item, ordered by name (distance comes in P12). Never ordered by price or rating (docs/06 section 6).

**Tests:**
- the offer page shows the direct and indirect split;
- the lead time adds up;
- the item page order is by name.

---

### - [ ] P04.T07 — The input-output table as open data

**Read:** docs/04 section 10 ("Open data").
**Files:** `apps/catalogue/views.py`, `apps/catalogue/templates/catalogue/io_table.html`, `apps/catalogue/tests/test_open_data.py`

**Do:**
1. **`/open-books/io-table/`:**
   - counts of items, placeholders and active offers;
   - total euro content of all offers;
   - the date of the last value run.
2. **Three CSV downloads:**
   - offers (id, unit slug, item, kind, uom, basis, direct, indirect, total, euro);
   - inputs (offer id, item, quantity per batch, source, preferred supplier);
   - tools (offer id, tool item, source, uses per batch, lifetime uses).

   No member numbers, no `provided_by`.

**Tests:** the CSVs have the right headers and contain no member numbers.

---

### - [ ] P04.T08 — "Join forces" suggestions

**Read:** docs/04 section 2 (the last point); owner, 2026-11-21.
**Files:** `apps/catalogue/models.py` (JoinForcesSuggestion), `apps/catalogue/jobs.py`, `apps/catalogue/templates/catalogue/join_forces.html`, `apps/catalogue/tests/test_join_forces.py`

**Do:**
1. **`JoinForcesSuggestion`:** `offer_high`, `offer_low` (same item), `gap` (Decimal: high/low − 1), `status` (`new`, `seen`, `dismissed`, `discussed`), `created_at`.
2. **Monthly job `catalogue.join_forces`:** for each item with 2 or more active offers in different units, a pair gets a suggestion when:
   - `high.value_total ≥ low.value_total × (1 + units.join_forces_value_gap)`;
   - the units are near each other: until P12 adds coordinates, near means the same town or the same first two postcode digits; then `units.join_forces_km`.

   At most one open suggestion per pair.
3. **Both councils see the suggestion** on their unit page. The text is neutral: "Woodshop and Oak Corner both make oak chairs; Oak Corner needs 3.1 h, Woodshop 4.3 h. You might share recipes, tools or workers, or join." Buttons: "Start a conversation" (opens a council decision of kind `other` in both units, P06 turns it into a `join_forces` ticket) and "Not now".
4. **Never automatic** (HF-10, HF-15).

**Tests:**
- a 30% gap creates a suggestion;
- a 20% gap does not;
- dismissing it stops repeats for 6 months.

---

### - [ ] P04.T09 — When a placeholder starts being made

**Read:** docs/04 section 9.
**Files:** `apps/catalogue/services.py`, `apps/catalogue/jobs.py`, `apps/catalogue/tests/test_placeholder_life.py`

**Do:**
1. **In `publish_offer`:** if the item is a `placeholder`, set it `active`, and then:
   - for every active offer of another unit that uses this item as `own_free` or `buy_outside`, notify its council: "<unit> now makes <item> (<value> UNIQ per <uom>, €<euro>). Switch your input to Unicorn?";
   - the button "Switch" calls `switch_input_source(input, "unicorn", member)`. For a unit with a council, this creates a council decision (kind `production`) that switches the input when approved; for a one-person unit, it switches at once.
2. **Monthly job `catalogue.retire_placeholders`:** placeholders with `last_used_at` older than `catalogue.placeholder_retire_months` become `retired`.

**Tests:**
- publishing an offer for a placeholder activates it and notifies its users;
- the switch goes through a council decision in a council unit.

---

## Acceptance check for phase 04

1. Build the docs/04 section 7 examples in the app: a mill, a bakery using its flour, a hairdresser, a woodshop.
2. The offer pages show exactly 0.1425, 1.00 and 4.30 UNIQ, with the right direct and indirect split and euro content.
3. The IO-table CSVs download.
4. `test_hf03_price_only_from_engine` passes.
5. Add a line to PLAN.md "Progress".
