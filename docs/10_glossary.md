# 10. Glossary

Words used in the app, the documents and the code. Code names are in `code font`.

| Word | Meaning | In the code |
|---|---|---|
| **UNIQ** | Unicorn's unit of account: one approved hour of work = 1 UNIQ before tax. Not money: it cannot be exchanged, transferred or sold. | `ledger`, amounts in UNIQ |
| **Fund 2** | The fund that pays members for hours worked and pays transfers. | `Account.kind = fund2` |
| **Fund 1** | The fund that receives every UNIQ spent. Its balance is cancelled at each period close. | `Account.kind = fund1` |
| **UNIQ outstanding / Fund 1's deficit** | UNIQ paid out but not yet spent: members' and former members' savings. | `−balance(fund2)` |
| **Period** | A calendar month (Europe/Berlin). | `ledger.Period` |
| **Flat tax** | One share of every paid hour, the same for everyone, that pays for everything except members' own purchases. | `Period.tax_rate` |
| **Tax balance** | The monthly rule that sets the next month's flat tax so that what members can buy equals what is made (book p. 88). | `macro.services.next_tax_rate` |
| **Transfer** | UNIQ paid without work, by the plan's decision: the equal pension, care. Covered by the tax. | `Transaction.kind = transfer` |
| **Retirement account** | A member's own locked savings in UNIQ. | `Account.kind = retirement` |
| **Former member** | Someone who left. They keep their UNIQ and can spend them, but earn none. | `Member.status = former` |
| **Unit** | A group or one person that makes products or performs services. | `units.Unit` |
| **Working council** | All workers of a unit with two or more workers (unless its rules choose a smaller council). It approves the unit's hours and decides its production. | `units` council tables |
| **Responsible** | The council member who, for a period, keeps the unit's profile and speaks for it. Rotates. | `units.Responsibility` |
| **Council rules / internal contract** | The unit's own rules, signed by its workers. | `units.CouncilRules` |
| **Union** | A group of related working councils. Advises; never commands. | `bodies.Union` |
| **Local council** | Members living in one area, for local matters. | `bodies.LocalCouncil` |
| **Item** | A kind of product or service, with a unit of measure. | `catalogue.Item` |
| **Placeholder** | An item nobody in Unicorn makes yet. | `Item.status = placeholder` |
| **Offer** | One unit's way of making an item: recipe, cycle, price. One row of the input-output table. | `catalogue.Offer` |
| **Recipe** | An offer's inputs, tools and working time. | `OfferInput`, `OfferTool` |
| **Input source** | Where an input comes from: `unicorn`, `own_free` ("I provide it free"), `buy_outside` ("buy it from capitalism"). | `OfferInput.source` |
| **Labour value / price** | The hours inside one unit of an item, direct and indirect. The only price in UNIQ. | `Offer.value_total` |
| **Direct / indirect hours** | Hours worked on the item itself / hours inside its inputs and tools. | `value_direct`, `value_indirect` |
| **Euro content** | The euros of bought inputs and tools inside one unit of an item. Shown, never charged in UNIQ. | `Offer.euro_content` |
| **Advance share** | The share of expected orders a unit may make ahead of orders (default 10%). | `Offer.advance_share` |
| **Own-initiative products** | Products made beyond orders and the advance share. Paid only when sold. | `HoursEntry.status = pending_sale` |
| **Written off** | Products that expired or stayed unsold. Their hours are waste, taken back by the tax. | `StockLot.status = written_off` |
| **Hold** | UNIQ reserved for an order or booking until delivery. | `ledger.Hold` |
| **Needs board** | The page that shows what members need and Unicorn lacks. | `market` needs views |
| **Ticket** | Any request, proposal, complaint, flag or decision, with its history. | `tickets.Ticket` |
| **Brief** | The short text deciders read before deciding. | `Ticket.brief` |
| **Check question** | One question about the brief that confirmers must answer correctly before voting. | `Ticket.check_question` |
| **Random confirmers** | Four members drawn at random who must all say yes for a ticket to pass. | `tickets.Confirmation` |
| **Panel** | Twelve members drawn at random after a "no"; 7 yes approve. | `Confirmation.round = panel` |
| **Petition** | Signatures that force a referendum. | `votes.Petition` |
| **Referendum** | A vote of all members. | `votes.Referendum` |
| **Mandate** | Power given to one delegate for one decision only. | `tasks.Mandate` |
| **Task** | A piece of work from a ticket that anyone can take. | `tasks.Task` |
| **Plan check** | The automatic check of a request against the plan: green, amber, red. Never a refusal. | `plan.services.check` |
| **Yearly plan** | Shares, budgets, investments, focus and closures for a plan period. | `plan.PlanPeriod`, `PlanVariant` |
| **Planning group** | Randomly drawn members (with union advisers) who draft 2–3 whole plans. | `plan.PlanningGroup` |
| **Trade fund** | The euros members hold for the group in their own bank accounts. | `tradefund` |
| **Holder** | A member who holds part of the trade fund. | `tradefund.Holder` |
| **Cap** | The most a holder may hold. | `Holder.cap` |
| **Trust rating** | A score from the fund's records that sets a holder's cap. Nothing else. | `tradefund.trust` |
| **Payment request** | "Please pay €X to Y with reference Z", confirmed by payer and receiver. | `tradefund.PaymentRequest` |
| **Purchase request** | A request to buy something from capitalism with fund euros. | `tradefund.PurchaseRequest` |
| **Set-aside** | The part of an outside sale held for the group. | `FundEntry.kind = setaside` |
| **Loss reserve** | A slice of every set-aside that covers thefts and missed payments. | `FundEntry.kind = reserve` |
| **Planning rate** | Euros earned per hour of outside sales. Used only to compare making with buying. Never an exchange rate for UNIQ. | `macro` planning rate |
| **Warning lights** | Signals of hidden inflation and euro trouble: unspent UNIQ, shelves, unsold, street price, euro reserve, idle shifts. | `macro.MacroSnapshot.lights` |
| **Are we on track?** | The page that compares the real world with the simulation's conditions for success. | `macro` world tracker |
| **Hard frame** | The rules HF-1 to HF-20 that the code enforces. | `rules.hard_frame` |
| **Default** | Any rule outside the hard frame, changeable at its tier. | `rules.Parameter` |
| **Tier** | Who may change a default: `unit`, `confirm`, `plan`, `referendum`, `hard`. | `Parameter.tier` |
| **Post box** | The registered association (e.V.): no money, no decision power, signs where the law needs a name. | (legal) |
| **Coordination unit** | The system unit whose hours are governance work. | `Unit.kind = coordination` |
| **Identity helper** | A verified member who checks new members in person. | `members.InPersonCheck` |
