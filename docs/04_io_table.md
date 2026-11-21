# 4. The input-output table: items, recipes, cycles and labour values

*Book pp. 38–47 (labour values, the input-output table), pp. 59–64 (Unicorn orders inputs from the table), p. 78 (the unit profile). Owner, 2026-11-21: "The input-output table is very important and should be well thought. When someone is creating a product or service, the system should be aware of working cycles and the difference between products and services." Ideas kept from the owner's earlier code (Unicorn2): placeholders for missing inputs, and prices split into direct and indirect hours.*

## 1. What the table does

The table does two jobs at once (book pp. 46–47):

1. **It computes every price.** The labour value of each product or service is the hours worked on it directly, plus the hours inside everything used to make it.
2. **It is the ordering system.** When a member orders bread, Unicorn knows from the bakery's recipe how much flour the bakery needs, and orders it from the mill. Units never pay each other (book pp. 60–61); they supply each other through orders.

A unit fills in **only its own recipes**. Nobody needs to know the whole table. Unicorn puts the rows together, like the book's shoe factory that knows its own hours but not the dye factory's (book p. 42).

## 2. Items and offers

- An **item** is a kind of thing: "rye bread, 750 g", "haircut", "oak chair", "flour, type 1050". It has:
  - a **kind**, product or service;
  - a **unit of measure** (piece, kg, g, litre, ml, m, m², kWh, hour, or "service" for one service to one customer);
  - an optional trade code (CPA/NACE) for statistics;
  - for products, a shelf life in days (empty = keeps).
- An **offer** is one unit's way of making an item: its recipe, its cycle, its price. **Each offer is its own row and column of the table** (book p. 44; owner, 2026-11-21: "each unit's own hours"). Two bakeries making the same bread are two offers with two prices.
- If two units make the same item and one needs many more hours, both councils get a suggestion to **join forces**: share recipes, tools or members, or merge (owner, 2026-11-21). The suggestion is made when one value is at least 30% above the other and the units are within 50 km. It is never an order (HF-10).

## 3. Products and services are different

| | Product | Service |
|---|---|---|
| Can be stored | yes, until its shelf life ends | no: an hour not used is gone |
| Made when | **after an order** (owner, 2026-11-21); at most the unit's **advance share** (default 10%) made ahead for the shop shelf | when performed for a booking |
| Hours paid | ordered or planned work: when the council approves them; own-initiative work beyond orders and advance: **only when sold** (mixed rule) | **only when performed** (owner, 2026-11-21); a switch allows planned shifts or "by type" later (docs/06, section 4) |
| What can go unsold | made-ahead and own-initiative products; written off when the shelf life ends or after `economy.products.unsold_after_days` (90); their hours are taken back through the flat tax (HF-9) | nothing, while paid only when performed; idle shift time if shifts are switched on |
| Price per | unit of measure (a loaf, a kg, a chair) | one service to one customer |
| Cycle fields | batch size, cycle days, setup time, direct time per batch | duration, capacity (customers at once), travel time, place |
| Delivery | pickup, Unicorn courier, capitalist carrier | at the unit, at the customer's place, online |

## 4. Working cycles and how a unit works

**How a unit works** (`Unit.mode`):

| Mode | Example | How orders are handled |
|---|---|---|
| `continuous` | bakery, kitchen | produces every week at a rate its council sets; members order from the coming batches |
| `on_order` | carpenter, tailor | makes only after orders; batches collect orders until full or until the latest due date |
| `seasonal` | farm, preserves | works in seasons; members subscribe ahead (vegetable box) |
| `project` | building a workshop | a one-off job with an end date, usually an accumulation project of the plan |

**Cycle fields of a product offer:**

- `batch_size`: how many units of the item one cycle makes (40 loaves, 4 chairs, 500 kg of flour).
- `cycle_days`: days from the start of a batch until it is ready (1 for bread, 10 for chairs).
- `setup_minutes`: time per batch that does not depend on its size (heating the oven, setting up a machine).
- `direct_minutes_per_batch`: working time per batch, all workers together.
- `min_batch`: the smallest batch worth starting (defaults to `batch_size`).

**Cycle fields of a service offer:**

- `duration_minutes`: time per session.
- `capacity`: customers served at once (1 for a haircut, 10 for a class).
- `travel_minutes`: added when the service happens at the customer's place.
- `place`: at the unit, at the customer, or online.
- `max_per_week`: how many sessions the providers offer.

**Lead time of an order** = the offer's `cycle_days` + the longest lead time of its Unicorn-made inputs that are not in stock + 7 days for buying outside inputs (`market.outside_input_days`) where they are not in stock. The marketplace shows it as the expected delivery date.

## 5. Inputs and tools: where each comes from

Every input row of a recipe has a **source**. This is the owner's rule for inputs and tools that Unicorn does not make: *"maybe the user himself has the tool … the user should choose if they provide the input because they have it already and it is available to them with no charge, or it should be bought from capitalism."*

| Source | Meaning | Hours in the price | Euros | What happens on an order |
|---|---|---|---|---|
| `unicorn` | made by a Unicorn unit | the input's labour value | its euro content | Unicorn orders it from a supplier offer (section 8) |
| `own_free` | "**I provide it free**": the member has it (flour from their garden, their oven's power, their car) | 0 | 0 | the member confirms each month that they still provide it; if they stop, the offer pauses and the council is told |
| `buy_outside` | "**buy it from capitalism**" | 0 | the estimated euro price | a purchase request goes to the trade fund, which checks the plan and pays a member to buy it (docs/07, section 3) |

**Tools** (durable things used again and again) have the same three sources:

| Tool source | In the price |
|---|---|
| `unicorn_owned` (made in Unicorn, or bought by the trade fund and owned by the group) | depreciation: its labour value (or its euro price) ÷ its lifetime in uses × uses per batch |
| `own_free` (the member's own oven, scissors, computer, garage) | nothing; recorded, so that Unicorn knows how much rests on members' own things |
| `to_buy` (not there yet) | the recipe can be saved but not published until the tool is bought: a purchase request for the tool goes to the trade fund (an accumulation request) |

Members' homes, kitchens, cars and workshops used for Unicorn work count as `own_free` tools (the simulation's "free inputs", docs/02).

## 6. Labour values: the calculation

**For each active offer j**, all per unit of the item:

```
q_j  = batch_size (products) or capacity (services)
l_j  = (direct_minutes_per_batch + setup_minutes) / 60 / q_j            products, declared
l_j  = (duration_minutes + travel_minutes) / 60 / capacity               services, declared
d_j  = Σ over unicorn_owned tools t:  (V_t / L_t) · u_t / q_j             depreciation in hours
         V_t = the tool's labour value, L_t = its lifetime in uses, u_t = uses per batch or session
m_j  = Σ over buy_outside inputs r:   a_r · p_r / q_j                     euros of bought inputs
     + Σ over tools bought with euros: (P_t / L_t) · u_t / q_j            euro depreciation
```

**Unicorn-made inputs** link the offers into a matrix `M` (offers × offers):

```
For an input row r of offer j with source unicorn, item i, quantity a_r per batch:
   if the row names a preferred supplier offer k:   M[k, j] += a_r / q_j
   else, for every active offer k of item i:        M[k, j] += (a_r / q_j) · w_k
w_k = share of offer k in the item's delivered quantity over the last 3 months (equal shares if no data yet)
```

**Values** (the book's formula, with depreciation as past labour transferred, book p. 83):

```
v_j = l_j + d_j + Σ_k v_k · M[k, j]        that is     v = (l + d) · (I − M)⁻¹
e_j = m_j +       Σ_k e_k · M[k, j]        that is     e = m · (I − M)⁻¹       (euro content)
direct hours = l_j        indirect hours = v_j − l_j
```

**Solving** (`apps/catalogue/engine.py`):
- Build `M` as a `scipy.sparse.csr_matrix`. Solve `(I − M)ᵀ vᵀ = (l + d)ᵀ` with `scipy.sparse.linalg.spsolve`; do the same for `e`.
- If `spsolve` fails, use Jacobi iteration `v ← (l + d) + v·M` (book p. 45), at most 1,000 rounds, until the largest change is below 0.000001.
- 10,000 offers with 20 inputs each take well under a second.

**Errors:**
- **A loop that consumes more than it makes** (for example, electricity needing more electricity than it produces) has no solution. The engine marks the offers of that loop `value_error`, keeps their last good values, and opens a ticket to their councils.
- **A `unicorn` input with no active offer.** Publishing the recipe is refused with the message: "Nobody in Unicorn makes *flour* yet. Choose 'I provide it free' or 'Buy it from outside'."

**Declared and measured hours:**
- Until an offer has data, `l_j` uses the declared recipe.
- Once it has at least `catalogue.measure_min_hours` (40) approved hours and `catalogue.measure_min_units` (10) units delivered, both over the last 3 months, `l_j` uses the **measured** value: approved hours linked to the offer ÷ units delivered (book p. 61: "the latest data from the hours worked").
- Both values are shown. A gap above 30% for two months opens a plausibility notice to the council (docs/06, section 3).

**When values are computed:**
- At every monthly close.
- As a preview when a unit edits a recipe ("this recipe would cost 0.14 UNIQ a loaf").
- When a new offer is published (all values are recomputed; it is fast).

**Prices never move for any other reason** (HF-3). A new value applies to orders placed after the computation; each order line keeps the price it was placed at.

**Rounding:** values are stored with 4 decimals and shown with 2. Euro content is stored in EUR with 4 decimals.

## 7. Worked examples

**Bread** (continuous unit "Linden Bakery", product, 1 loaf of 750 g):
- Batch of 40 loaves, cycle 1 day, setup 30 min (heating the oven), direct 4 h per batch.
- Inputs per batch:
  - flour 24 kg, `unicorn` (the mill's value 0.05 h/kg);
  - salt 0.5 kg, `buy_outside` at €0.60/kg;
  - yeast 0.4 kg, `buy_outside` at €5/kg;
  - oven power, `buy_outside` at €3 a batch.
- Tools: the member's own oven, `own_free`.
- The calculation:
  - `l = (240 + 30)/60/40 = 0.1125 h`;
  - flour `24 × 0.05 / 40 = 0.03 h`;
  - **price 0.1425 UNIQ a loaf** (direct 0.11, indirect 0.03);
  - euro content `(0.30 + 2.00 + 3.00)/40 = €0.13`.

**Haircut at home** (service, 1 haircut):
- Duration 40 min, travel 20 min, capacity 1. Inputs: shampoo 15 ml, `buy_outside` at €0.02/ml. Tools: the member's scissors, `own_free`.
- **Price 1.00 UNIQ** (direct 1.00); euro content €0.30.
- The hairdresser is paid 1.00 UNIQ gross when the customer confirms the haircut was done.

**Oak chair** (on-order unit "Woodshop", product, 1 chair):
- Batch of 4, cycle 10 days, setup 60 min, direct 16 h per batch.
- Inputs per batch:
  - oak boards 0.16 m³, `buy_outside` at €900/m³ (€144);
  - screws and glue, `buy_outside` (€8);
  - finishing oil 0.4 l, `unicorn` (0.5 h/l).
- Tools:
  - a table saw bought by the trade fund for €1,200, lifetime 2,000 uses, 2 uses per batch (€1.20 a batch);
  - the member's garage, `own_free`.
- The calculation:
  - `l = (960 + 60)/60/4 = 4.25 h`;
  - oil `0.4 × 0.5 / 4 = 0.05 h`;
  - **price 4.30 UNIQ a chair**;
  - euro content `(144 + 8 + 1.20)/4 = €38.30`.
- **Make or buy** at the planning rate of €17.35 an hour (docs/03, section 8):
  - making costs `4.30 + 38.30/17.35 = 6.5` hour-equivalents;
  - a similar oak chair bought for €180 costs `180/17.35 = 10.4`;
  - **so make it.**

## 8. From an order to all its inputs

When an order for a product cannot be served from stock (`market.services.place_order`):

1. **Production order.** The order line is added to a **production order** of the offer: an open batch that is not full and is due in time, or a new batch.
2. **Input needs.** For each recipe input, the need is `quantity per batch × batches`. By source:
   - `unicorn`: an **input request** to a supplier offer (the preferred one, otherwise the active offer with the most free capacity within the cover area, otherwise the nearest). If the supplier has no stock, the input request becomes a production order there, and the steps repeat down the chain. No UNIQ move between the units (book p. 60).
   - `own_free`: the member who provides it confirms the batch.
   - `buy_outside`: the need is added to the unit's **monthly purchase list**. The list becomes one purchase request to the trade fund per item and month, or at once if the input is needed sooner than its lead time.
3. **Dates.** Each request carries its due date: the batch's start date minus its own lead time.
4. **Problems.** If a supplier cannot deliver in time, the member who ordered sees the new date, and the shortage appears on the needs board.

**Continuous units** run a weekly production order that their council sets. Member orders take places in it until it is full.

## 9. Placeholders

(Idea kept from Unicorn2, owner, 2026-11-21.)

- When a unit names an input that no item describes yet, the app creates a **placeholder item** with that name and unit of measure, marked "not made in Unicorn".
- A placeholder can only be used with the sources `own_free` or `buy_outside`.
- The **needs board** lists every placeholder that Unicorn buys from outside, with:
  - the euros spent on it per month;
  - how many units use it;
  - the button "**I can make this**" (docs/06, section 7).
- When someone publishes an offer for a placeholder item, it becomes a normal item. The councils of units that buy it outside are told: "Linden Mill now makes flour type 1050 (0.05 UNIQ/kg, €0.00). Switch your input to Unicorn?" Each council decides (HF-10, HF-20).
- Placeholders that nobody used for 12 months are retired.

## 10. Keeping the table honest

- **Plausibility checks:**
  - measured hours against declared hours (above);
  - hours paid against output delivered, every month (docs/06, section 3);
  - inputs ordered against output made: a unit that orders twice the flour its bread needs gets a notice, because extra inputs give it no advantage (book p. 61) and usually mean a wrong recipe.
- **Anyone can flag an offer** ("wrong hours", "wrong inputs", "not available"). The flag becomes a ticket for random confirmers (docs/05, section 9). The book's "volunteers and relevant departments" (p. 78) become these random checks.
- **Open data:**
  - every offer's recipe, values (direct, indirect, euro) and measured hours are public;
  - the whole table can be downloaded as CSV (offers, inputs, values), without personal data;
  - this is the open book of production.

## 11. The data model (summary; details in plan/phase_04_catalogue_io_table.md)

- `catalogue.UnitOfMeasure(code, name, dimension)`.
- `catalogue.Item(name, kind[product|service], uom, trade_code, shelf_life_days, status[active|placeholder|retired], created_by_unit)`.
- `catalogue.Offer(unit, item, status[draft|active|paused|retired|value_error], …cycle fields…, advance_share, value_direct, value_indirect, value_total, euro_content, declared_hours_per_unit, measured_hours_per_unit, values_computed_at)`.
- `catalogue.OfferInput(offer, item, quantity_per_batch, source[unicorn|own_free|buy_outside], preferred_supplier_offer, euro_price_estimate, currency, provided_by_member)`.
- `catalogue.OfferTool(offer, tool_item, source[unicorn_owned|own_free|to_buy], uses_per_batch, lifetime_uses, value_uniq, euro_price, currency)`.
- `catalogue.ValueRun(started_at, finished_at, offers, method, converged, max_change)` and `catalogue.OfferValueHistory(run, offer, direct, indirect, total, euro)`, both append-only.
