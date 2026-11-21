# 6. Work, production and the market

*Book pp. 59–64 (orders and the central table), pp. 77–79 (unit profile, user profile, cards), pp. 128–132 (supply and demand without profit); owner's decisions of 21 November 2026 (products ordered first, services paid when performed, each unit's own price, units can start immediately). Simulation defaults: docs/02.*

## 1. Units

**A unit** is any group, or single person, that makes products or performs services inside Unicorn.

**Kinds:**
- `production`;
- `service`;
- `social` (free services paid from the tax: care, teaching, culture);
- `courier` (delivery);
- `coordination`: a single system unit whose hours are governance work: council work, reviews, panels, planning, delegates. Its hours are standard times approved automatically when the act is recorded.

**Modes:** `continuous`, `on_order`, `seasonal`, `project` (docs/04, section 4).

**Status:** `trial` (the first 3 months), `open`, `paused`, `dormant` (no activity for 6 months; reopens with one click), `closing`, `closed`, `merged`.

**The unit profile** (book p. 78), kept by the unit's responsible:
- name, kind, mode, trade code, description and photos;
- location (address kept private; town and postcode public) and its **cover area** (section 8);
- workers and council rules;
- offers and recipes (docs/04);
- licences and insurance where needed (HF-17);
- the weekly production plan of a continuous unit.

**Starting services** (the simulation's 14 lighter services, `sectors.seed` without meals, building, transport and machine repair): Unicorn's own coordination; repairs of computers and household goods; personal services (hair, beauty, laundry); teaching and lessons; care and social work; arts and culture; sports and recreation; cleaning, gardening and office help; post and courier; IT services; legal, accounting and advice (licensed members only, docs/07); architecture and engineering; marketing; other professional services (design, photography, translation, veterinary).

**Later trades** open as Unicorn owns tools, in the simulation's order: farming, food workshops, energy, textiles, furniture, car repair, health care, water, waste, and then the rest by members' demand (`sectors.later_order` in the simulation).

## 2. Opening a unit and the plan check

**The owner's rule:** opening a unit is easy and immediate if nothing in the budget plan is against it.

**The form** asks for:
- the name, kind, mode, trade and town;
- the cover area;
- a description;
- licence and insurance, if needed;
- optionally the first offers, and the tools and inputs needed, each with its source (docs/04, section 5).

**The plan check** (`plan.services.check(request)`) returns green, amber or red, with one plain sentence per point. It never rejects on its own (HF-15).

| Point | Green | Amber | Red |
|---|---|---|---|
| The plan's closure list | not on it | | the trade or item is on it |
| Euros needed (tools to buy, monthly outside inputs) | none, or within the trade's free budget this year | within the budget, but the reserve is amber | above the trade's free budget, or the euro reserve is red |
| Scarce Unicorn inputs | none | an input whose supplier is short | |
| Members' demand nearby (for services) | demand or the needs board shows it | no visible demand yet | |
| Plan focus | | | |

A unit for an item on the plan's focus list is marked "plan focus" (no colour). Hard-frame checks come before the plan check and do block: a missing licence or missing insurance (HF-17), or an unverified member (HF-13).

**What happens next:**
- **Green:** the unit opens at once as `trial`.
- **Amber:** it opens at once, and random confirmers review it within 14 days.
- **Red:** random confirmers decide first.

The ticket records everything (docs/05, section 9).

**The same check runs for:** purchase requests, new offers that need euros, and plan proposals.

## 3. Hours: recording, approving, paying

**Recording.** A worker records hours for one unit at a time, with a start and stop timer or by hand:
- **date and minutes;**
- **activity:** `order` (a production order), `booking` (a service performed), `shift`, `project`, `coordination`, `learning`, or `other`;
- **the thing it belongs to:** a production order, booking, shift, task or ticket;
- **a note.**

Hours of performed bookings are created automatically when the customer confirms the service (section 4).

**Approving** (HF-20):

| Unit | Who approves |
|---|---|
| Two or more workers | the council, under its rules (default: any other council member). Never one's own hours. Batch approval for confirmed bookings and completed production orders. |
| One worker | approved automatically, then checked (below) |
| Coordination unit | approved automatically at the standard time when the act is recorded (a vote cast, a task confirmed) |

**Checks** (they produce notices and tickets, never automatic refusals, HF-15):
- **Hours against output, every month.** Approved hours on an offer ÷ units delivered, compared with the declared or measured hours per unit. A gap above 30% for two months opens an `hours_review` ticket for random confirmers. The confirmers can confirm the hours, or correct the recipe; a wrong payment is corrected with a written reason.
- **One-person units.** Each month, 10% of one-person units are drawn, and one random member looks at their hours against their output (a light check, paid 15 minutes).
- **Weekly limit.** At most `membership.max_unicorn_hours_per_week` (48) Unicorn hours a week for a member, over all units: for health, and against invented hours. More needs the council's explicit approval with a reason.

**Paying** (HF-1, HF-2, HF-9). When hours are approved, `units.services.pay_hours()` posts in one transaction:
- Fund 2 → member: the gross hours;
- member → Fund 2: the flat tax at this month's rate.

The member sees gross, tax and net.

**What hours do not pay at once:**
- **Own-initiative products** (made beyond orders and the unit's advance share) are recorded as `pending_sale` and paid only when the products sell, pro rata per unit sold (the owner's mixed rule).
- **Service hours** are paid only when the service is performed and confirmed (section 4).

**The job portfolio** (owner: "user accounts and jobs' portfolios"). Each member keeps a public list of:
- their skills and trades;
- their licences (verified documents stay private: HF-14; the public sees only "licence verified");
- the units they work in;
- the hours they would like to offer each week.

The needs board uses the portfolio to show each member the needs that match their skills. It never assigns work (HF-10).

## 4. Services

**Default (owner, 2026-11-21): paid only when performed.**
1. A member books a slot from a service offer. The price is fixed at booking time, and the customer's UNIQ are **held**.
2. The provider confirms the booking.
3. After the session, the provider marks it **performed**.
4. The customer confirms within 48 hours, or disputes it. Without an answer, it counts as confirmed after 48 hours.
5. On confirmation, the held UNIQ go to Fund 1, and the provider's hours (duration + travel) are created and approved (in a one-person unit at once; otherwise in the council's batch).
6. **No-show:** if the customer does not come, nothing is paid. The provider can report it; repeated no-shows show on the customer's bookings, visible to providers only.

**Social services** (care, teaching paid from the tax): the same steps, without a charge. Hours are paid from the social share.

**Switch for later** (`economy.services.pay_rule`, tier `plan`):
- **`when_performed`** (default).
- **`planned_shifts`:** the plan gives each service a budget of hours. The council approves shifts within it, and shifts are paid when worked, booked or not. Idle time is waste, taken back through the tax, and shows on the idle-shifts light.
- **`by_type`:** always-open services (care homes, shops, kitchens, clinics) work in shifts; appointment services are paid when performed. A unit's kind and mode decide which applies.

## 5. Products

**Default (owner, 2026-11-21): products are ordered before they are made.**

**Orders:**
1. A member orders from an offer. The price is fixed on the order line (HF-3), and the UNIQ are **held**.
2. The order goes into a production order (docs/04, section 8). The marketplace shows the expected date.
3. **Cancelling** is free until the batch starts. After that the order is binding.
4. On delivery (handed over, or confirmed by the buyer within 48 hours), the held UNIQ go to Fund 1.
5. A buyer who refuses a binding order is still charged. The product goes to the unit's shelf for others to buy, and is written off if nobody does.

**Made ahead** (`Offer.advance_share`, default `economy.products.advance_share` = 10%):
- A unit may make up to this share of its expected orders ahead, for its shelf (stock lots).
- These hours are paid like ordered work. If the lots expire or stay unsold for `economy.products.unsold_after_days` (90), they are **written off**. Their hours count as waste, and the next month's flat tax takes them back (HF-9).

**Own initiative:** a member may make more than that, but these hours are paid only when the products sell (section 3).

**Standing orders:** a member can subscribe to an offer, for example a vegetable box every week (the simulation's "ordering ahead"). Each delivery is a new order line at the price of that day. The subscription can be paused or ended at any time before a batch starts.

**Continuous units:** their council sets a weekly production plan (quantity per offer), and members order into it. A plan larger than the week's orders plus the advance share needs a council decision with a reason. It shows on the unsold light if the extra goes unsold.

## 6. The marketplace

- **Search and browse** offers by item, trade, place and kind. Only offers whose cover area reaches the member's address (or pickup point) are shown as orderable.
- **Each offer shows:**
  - the price in UNIQ, split into **direct hours** and **indirect hours** (kept from Unicorn2);
  - its euro content ("€0.13 bought from outside");
  - the expected date and the unit;
  - whether the price comes from declared or measured hours;
  - reviews.
- **Reviews** (1–5 stars and a text) go to the unit's council as feedback. They never change prices, pay or the order in which offers are listed (HF-3, HF-10).
- **Listing order** is by distance, then alphabetical. There is no ranking by price or by score.
- **Buying in person** (book pp. 67, 77: card readers):
  - the seller creates a sale in the app (offer and quantity), which shows a QR code;
  - the buyer scans it and confirms, and UNIQ go to Fund 1 at once;
  - offline payments come later (plan/phase_16).
- **Shortages** (prices never move, HF-3):
  - orders are served first come, first served;
  - a sold-out item takes a **waiting list**;
  - while the shelves light is red for an item, each member may order at most `market.shortage_cap_per_member` (default 2) units a month (constitution draft rule 2: shortages are shared out).

## 7. The needs board

The owner: *"The market shows the services and products currently needed by others and motivates people to create them."*

**Four sections:**

| Section | Shows | From |
|---|---|---|
| **Wanted now** | items with waiting lists or with demand above supply for 2 months (docs/03, section 9) | orders, waiting lists |
| **Bought from outside** | placeholder items and outside inputs Unicorn buys with euros | purchase lists of the trade fund |
| **Plan focus** | the yearly plan's focus list | the plan |
| **Missing near you** | services members searched for, or asked for in tickets, with no provider in their area | search log (counted per area, without names), `idea` tickets |

**Each card shows:**
- the item and how many people want it;
- the hours of work a month it would give;
- the euros a month Unicorn would save by making it (for things bought outside);
- the nearest units that make it;
- **"I can make this"**. The button opens the unit form, or adds an offer to one of the member's units, prefilled with the item.

**The board also uses each member's portfolio:** "Needs that match your skills". When an offer removes an item from the board, its maker gets a recognition entry, "filled a need" (docs/05, section 11).

## 8. Shipping and fulfilment

**Cover area of a unit:**
- a radius in km around its location (default `logistics.default_cover_radius_km` = 10), plus optional extra postcodes;
- distance by the haversine formula between postcode centres;
- postcode coordinates come from an open dataset loaded once (plan/phase_12).

**Delivery modes of an order:**

| Mode | When | Cost to the buyer |
|---|---|---|
| `pickup` | at the unit or a pickup point of the local council | nothing |
| `unicorn_courier` | a courier unit within its own cover area | the courier service's labour value, as its own order line (hours = distance ÷ speed + 5 minutes a stop, docs/04 service values) |
| `capitalist_carrier` | the buyer is outside every courier's cover area, or the make-or-buy rule at the planning rate says the carrier is cheaper (docs/03, section 8) | **nothing in UNIQ**: the carrier's euros are paid by the trade fund like bought materials (they appear in the offer's euro content statistics, not in its price, HF-3) |

- **Who chooses the carrier:** the app proposes the mode by these rules, and the selling unit's responsible confirms it. Buyers choose only between pickup and delivery.
- **Delivery records:** each delivery is confirmed by the receiver ("received") or flagged ("damaged", "missing"). A damaged delivery is replaced or refunded: the held UNIQ are released, or a correction is posted with a reason.
- **Packaging** is an input of the courier offer like any other.

## 9. Import, export and other countries

Buying from capitalism (import), selling to outsiders (export), donations and members abroad are in docs/07.

## 10. Housing (later)

- The simulation's homes come late, once Unicorn has euros for land (`housing.share_of_investment` 24%, rent 0.59 UNIQ per m² a month, paid to Fund 1). In the real world, land and homes need a legal owner, such as a housing body on the Mietshäuser Syndikat model (`../Unicorn-simulation/docs/real_world/4_legal_frame.md`).
- The app will add a housing module later (plan/phase_16): homes, rents in UNIQ, upkeep work, and the waiting list.
- The book's land rules (p. 96) apply: no profit from selling homes, and resale only at labour cost minus depreciation.

## 11. Rules about work that the app keeps

- **Members choose what, when and how much they work** (HF-10). Suggestions and the needs board are information only.
- **No algorithm ranks workers.** Reviews belong to offers, not people, and never reach pay.
- **Licensed trades** only by members with a verified licence; services need liability insurance (HF-17; docs/07, section 7).
- **Weekly limit** of Unicorn hours (section 3).
- **Members who receive benefits** are warned at sign-up and when they pass 15 hours a week: Unicorn income can count against means-tested benefits (legal frame, section 4).
