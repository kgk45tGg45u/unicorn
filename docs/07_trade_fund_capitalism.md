# 7. The trade fund and the capitalist world

*Owner's design of 21 November 2026 (the trade fund is spread over members' own bank accounts; an e.V. post box with no money and no decision power); `../Unicorn-simulation/docs/real_world/4_legal_frame.md` sections 1–4 and 6–8; book pp. 150–156 (foreign trade). Simulation defaults: docs/02.*

## 1. The design in one paragraph

**The trade fund is not an account.** It is the sum of euro amounts that members hold for the group in their own bank accounts, under a trust agreement they sign when they join.

**How euros move:**
- **In:** euros come in from members' own outside sales, and from donations.
- **Out:** when members approve a purchase or a payment, the app asks one or two holders to transfer the euros. The payer and the receiver confirm.
- **The app never touches money** (HF-12). It only records what members confirm and computes the totals, priorities, caps and ratings.

## 2. Holders

- **Who:** any verified member (HF-13) who signs the **holder agreement**. It is part of the trust agreement and says the held euros belong to the group and are sent on when the members' decision asks.
- **The holder's account:** a separate account at their bank is recommended, and the app asks for its IBAN, which is stored encrypted (HF-14).
- **How euros reach a holder:**
  - from the set-aside of their own outside sales (section 6);
  - from a donation paid into their account (section 8);
  - from another holder, when the fund moves euros to keep within caps.
- **The cap.** A holder may hold at most their **cap** (section 5). Above it, the app asks them to pass the extra to holders with room.
- **Leaving.** A holder who leaves, or deletes their account, first passes their part to other holders (rotation), and the receivers confirm. Only then does the membership end (legal frame, section 1).

## 3. Buying from capitalism

The owner: *"For inputs and tools that are not available on Unicorn … it should be bought from capitalism, in which case the trade fund looks at the plan and, if nothing is against it, gives the money to a member, or gives chunks of money from different members to a trustable member to buy that thing and send it to the user that needs it."*

**A purchase request** (`tradefund.PurchaseRequest`, ticket type `purchase`) comes from:
- a recipe input with source `buy_outside`, through the unit's monthly purchase list (docs/04, section 8);
- a tool with source `to_buy`;
- a member's bill paid as a benefit (section 9);
- an operating cost (servers, insurance, fees).

**Steps:**

1. **The request.** What to buy, how many, the estimated price and currency, a link or seller, why, for which unit, and where it must go.
2. **The plan check.** The plan check (docs/06, section 2) plus the **make-or-buy rule**: if Unicorn makes an equal item at fewer hour-equivalents (docs/03, section 8), the request shows "Unicorn makes this: Linden Woodshop, 4.30 UNIQ". The requester may still ask to buy it, with a reason.
3. **Approval:**

   | Amount and check | Approved by |
   |---|---|
   | green, up to `governance.ticket_limits.purchase_auto_eur` (€50) | automatic |
   | up to `governance.ticket_limits.purchase_confirm_max_eur` (€2,000), or any amber or red | 4 random confirmers (docs/05, section 3) |
   | above €2,000 | an item of the yearly plan's investment list, or a referendum |

4. **How it is paid** (the app proposes; the requester and the confirmers can change it):
   - **The requester buys and is reimbursed:** when the requester's trust allows it (trust ≥ 0.5 and amount ≤ their cap). The simplest way.
   - **One holder pays the seller directly:** a holder with enough held euros pays the seller's invoice. The invoice is addressed to the buying member, or to the association where the law needs a contract partner (legal frame, section 3).
   - **Pooled to a trusted buyer:**
     - when no single holder can pay, at most `tradefund.max_payers_per_request` (2) holders send parts to a **buyer**: a member with high trust, chosen from volunteers near the seller or the receiver;
     - the buyer buys the thing, uploads the receipt, and sends it to the unit that needs it;
     - the buyer returns any change through a payment request, and reports any extra cost the same way.
5. **Closing.** The receiver confirms the delivery, and the ticket closes. A tool bought this way **belongs to the group**: recorded as a group tool and lent to the unit (the "purchase the group owns" reason, legal frame, section 4).

**Each transfer has a written reason** of one of three kinds (legal frame, section 4): `loan` (repaid), `group_purchase` (the group owns the thing) or `gift`. The reference text is always "Unicorn trade fund, ticket T-000214".

**Payers are few and take turns.** Banks watch for many small payments from strangers. So the app chooses payers among holders who:
- hold enough;
- have paid least so far, relative to what they hold;
- are trusted enough.

It never splits a payment over more than 2 payers.

## 4. Payment requests

`tradefund.PaymentRequest`: payer, receiver (a member, or an outside party with name and IBAN), amount, currency, reference, reason kind, due date, ticket.

**Life cycle:**
1. `requested`: the payer is notified: "Please pay €120.00 to Woodshop buyer M-7KQ2, IBAN DE…, reference 'Unicorn trade fund, ticket T-000214', by 28 November."
2. `sent`: the payer confirms "I sent it" and enters the amount sent.
3. `received`: the receiver confirms "I received it" and enters the amount received. For an outside receiver (a seller), the buyer confirms with the invoice.
4. `confirmed`: the amounts match. The fund's books record the movement, and both trust ratings receive their event.
5. `mismatch`: the amounts differ, or one side says it never happened. A flag ticket goes to random confirmers.
6. `overdue`: not sent within `tradefund.payment_deadline_days` (5). A reminder goes out; after 7 more days it counts as a missed payment (section 5) and the request goes to another payer.

**The fund's books** (`tradefund.FundEntry`) are append-only and hash-chained like the UNIQ ledger (HF-7):
- one entry per change in who holds what: set-aside, donation, transfer between holders, payment out, reserve move, correction;
- the currency and the holder are on each entry;
- totals per holder and per currency are computed from the entries.

## 5. The trust rating and the caps

(HF-11; legal frame, section 3. It measures trust, not usefulness. It is computed from the fund's books only. Members cannot rate each other. It is visible and contestable. It never touches work.)

**Score** between 0 and 1:
- it starts at `tradefund.trust.start` (0.2), or 0.5 for founders;
- it grows slowly and falls fast:

| Event | Change |
|---|---|
| a payment made on time | +0.02 |
| each month as an active holder without a problem | +0.01 |
| a payment made late (after the deadline, within 7 days) | −0.05 |
| a missed payment | −0.30 |
| a mismatch decided against the holder | −0.20 |
| leaving without passing on the held part | score 0, and the loss reserve pays |

**Cap:**

```
max_cap = max(base_cap, fund total × tradefund.holder_max_share)     base_cap €300, max share 10%
cap     = base_cap + score × (max_cap − base_cap)
```

**What each member sees:** their score, every event behind it, and their cap. They can contest any event with a `trust_review` ticket. It is decided by the **trust review group**: 3 members elected by referendum for a year, who must not hold more than the base cap themselves. The group can annul an event, with reasons.

**Loss reserve.** `tradefund.loss_reserve_share` (2%) of every set-aside is marked "reserve" and kept by the holders with the highest trust. Thefts and missed payments are paid from it, so that members' bills and materials are not hit.

**If a part is stolen:**
1. The missed payment is flagged, and the holder is asked.
2. After the deadline, the loss reserve covers the payment.
3. The post box files a complaint or civil claim on the members' vote. A lawyer must confirm the legal route (docs/12).

## 6. Selling to outsiders (export)

**Who sells.** A member sells **in their own name** (legal frame, section 3): the sale, the invoice and the VAT are theirs. Most members fall under the small-business rule (§ 19 UStG: under €25,000 turnover last year and €100,000 this year). The app warns when they come near the limit.

**What and at what price.**
- The unit's council chooses which offers are sold to outsiders, and their **euro prices**: ordinary market prices. UNIQ prices never change (HF-3); euro prices for outsiders are a council matter (tier `unit`).
- Outside customers' products are made **on order**, with 10% made ahead (`economy.products.outside_advance_share`).

**The outside shop.**
- A public page lists those offers.
- A customer orders without an account (name, email, delivery address: stored encrypted, deleted after the legal keeping period).
- The app shows the seller's payment details and consumer information:
  - the trader is the member, with their name and address, which members accept when they switch on outside sales;
  - the 14-day right of withdrawal, where it applies;
  - delivery times.

**Payment.** The customer pays the seller directly (transfer or in person). The seller confirms payment received, and the order goes into production.

**The set-aside.** On confirmed payment, the app records:

```
tax reserve = revenue × the seller's tax estimate          (default economy.tax_on_outside_sales_estimate = 15%; the seller may change it with a reason)
set-aside   = (revenue − tax reserve) × tradefund.setaside_share_of_net    (default 100%)
```

The set-aside is held by the seller as holder (up to their cap; the rest is passed on). The tax reserve stays with the seller to pay their taxes. The seller was already paid in UNIQ for the hours (from the tax). This is the simulation's rule: outside sales after German taxes go to the fund.

**The cap on outside sales.** The plan caps outside-sales hours at 53% of all hours (`economy.outside_sales_cap_share`). When a month's outside orders reach it, the shop shows new outside orders for the next month.

**The yearly statement.** Each member gets one for their tax return: what they sold, what they set aside, what they held and what they sent on (legal frame, section 4).

## 7. Licences, insurance, taxes

(Legal frame, sections 4–6. The app enforces HF-17; the details belong to lawyers.)

| Trade | Rule in the app |
|---|---|
| legal advice, tax advice, health care | only members whose licence is verified by two random confirmers who see the document; otherwise the offer cannot be published |
| childcare more than 15 h a week for 3 months | the youth office's permit must be uploaded |
| passenger rides | at cost only: the offer is marked "at cost" and has no euro price for outsiders |
| crafts needing a master craftsman | only under a member with that qualification |
| meals for sale | the kitchen's registration must be uploaded |
| every service | liability insurance: a group policy, or the member's own, confirmed at publishing |

- **Members receiving means-tested benefits** are warned (docs/06, section 11).
- **The tax ruling.** The binding tax ruling on UNIQ income and on the trust agreements comes before the start (docs/12).

## 8. Donations

- **Members and outsiders can donate euros or US dollars** (owner, 2026-11-21) to the trade fund. **A donation earns no UNIQ** (HF-18).
- **How:** the donor pays into the account of a holder the app chooses (one with room under their cap), and both confirm. A member who is a holder may also declare a donation from their own money into their held part.
- **Tax:** donations to the post box are not tax-deductible (it is not charitable). The app says so.
- **Supporters' loans** (Direktkredite) are not taken through the app. They need a housing body and a specialist lawyer (legal frame, section 3).

## 9. Members' bills: benefits by need, and the guarantee

(Simulation recipe: benefits by need, may start at any time, grow only while an hour in Unicorn buys at least 1.15 capitalist hours; guarantee on; docs/02.)

**Benefit claims.** A member who wants to work less in their capitalist job files a `benefit_claim`:
- their monthly basic euro bills: rent, health and care insurance (about €250 for members without a job), basic needs Unicorn does not make yet;
- documents, kept private and seen only by the confirmers of the claim.

**Budget.** The fund's monthly benefit budget follows the simulation's rule:
- it moves toward what the fund can sustain over `economy.benefits.adjust_months` (6);
- it is cut by 5% a month while the reserve is below its minimum;
- it grows only while the attractiveness condition holds.

**By need.** Approved claims are served heaviest burden first, as the budget allows. They are paid monthly by payment requests to the landlord, the insurer, or the member (with the reason `gift` or `bill`, as the lawyers advise).

**The guarantee.** A member who would be worse off on basic needs than without Unicorn (for example, Unicorn delivered less food than they counted on) files a `guarantee_claim`. If confirmed, it is topped up before other benefits grow.

**Taxes.** Whether these payments are taxable income for the member is a question for the tax ruling (docs/12).

## 10. Euro priorities, budgets and the reserve

The plan sets euro budget lines. Each month, the euros held are allocated in this order (the simulation's "tools first" recipe):

1. payments already approved;
2. **the plan's tool purchases** (the accumulation budget; half of them earned by extra outside sales, `economy.tools_from_outside_sales_share` = 0.5);
3. **materials** for members' goods and services (the monthly purchase lists). When euros are short, the offers that need the most euros per hour pause first, but at least 44% of members' usual purchases stay on offer (`economy.min_offer_share_when_euros_short`);
4. **guarantee top-ups, then benefits** by need;
5. **the reserve** up to `tradefund.reserve_target_months` (5.4 months of outgoings);
6. above a full reserve: further tools, land, and later homes.

**The euro reserve light** turns amber below 5.4 months and red below `tradefund.reserve_min_months` (2) (docs/03, section 10).

## 11. Several currencies and members in other countries

**Currency per member.** Every member has a country and a currency, and every holder holds in one currency. Payment requests are in the receiver's currency. A payment across currencies is converted at the European Central Bank's reference rate of the day, and the payer confirms the amount actually sent.

**Exchange rates.** `tradefund.FxRate` is loaded daily from the ECB's public reference rates (no personal data is sent). Totals are shown in euros, and per currency.

**The planning rate** is converted the same way (docs/03, section 8). One hour is one UNIQ in every country (HF-2).

**The law abroad** (legal frame, section 8): Unicorn starts with one German e.V., and members abroad may join. Wherever they work, sell or hold money, their country's laws apply: taxes, VAT, labour law, licences. The app shows a notice to members outside Germany. When a local group abroad forms, it founds a sister association linked by agreement. Federation between such groups comes later (plan/phase_16).

## 12. The book's foreign-trade rules, as the app applies them

| Book (pp. 150–156) | App |
|---|---|
| Import what cannot be made, or costs more hours than the hours needed to earn its price | the make-or-buy rule at the planning rate (docs/03, section 8) |
| Tools and inputs for production before consumer goods | the euro priority order (section 10) |
| Avoid foreign loans; keep trade balanced | no loans are taken through the app; the reserve rule |
| Long-term contracts against price swings | standing purchase requests for a year, approved in the plan |
| No capitalist currency inside; tokens never bought with currency | HF-4: there is no exchange at all |
| Parallel markets will appear; do not build Big Brother | flags and the street-price light; no surveillance of members' private dealings |
