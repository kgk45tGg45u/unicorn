# 11. Decisions

The owner's decisions that shape the app, with dates. Below them, the choices made while writing these documents that the owner has not decided yet: they are defaults, marked `source: proposal` in config/defaults.yaml.

## The owner's decisions

| Date | Decision | Where it shows |
|---|---|---|
| 2026-10-08 | Unicorn starts as a services network inside capitalism. Members use what they own for free and keep their jobs at first; the trade fund later pays their basic bills so they can leave their jobs. Four goals: attractive, growing, independent, stable. | docs/00, docs/02 |
| 2026-10-09 | 25 founders and a trial year; growth by word of mouth; rent of a Unicorn home in UNIQ per m²; Fund 1 may run a deficit for 20 years, then heals; stability counts from year 6. | defaults `membership.*`, `economy.fund1_deficit_years` |
| 2026-10-14 | The flat tax may also be a democratic fixed rate between 30% and 68%. | `economy.flat_tax.*` |
| 2026-11-21 | Unicorn is fully horizontal: no bank, cooperative or company on top. The trade fund is spread over members' own bank accounts. | docs/07 |
| 2026-11-21 | A registered association (e.V.) as a post box: no money, no decision power, acts only on members' vote; one digital contract makes every account holder a member; deleting the account ends the membership. | docs/00, docs/07, docs/08 |
| 2026-11-21 | Unused output means products made but never bought, and goods made for outside customers that do not sell. | docs/02, docs/04 |
| 2026-11-21 | The mixed rule: planned and ordered work is paid per hour; own-initiative products are paid when sold; failed planned work is written off through the flat tax. | HF-9, docs/06 |
| 2026-11-21 | Prices stay fixed; hidden inflation is shown by warning lights. | HF-3, docs/03 |
| 2026-11-21 | Too many unspent UNIQ: a retirement fund and a higher flat tax for a while. No expiry. | HF-8, docs/03 |
| 2026-11-21 | A leaving member keeps their UNIQ, still spendable. | HF-8 |
| 2026-11-21 | Default share of unsold products for testing: 70%. Outside customers' products mostly made on order. | docs/02 |
| 2026-11-21 | The app's defaults are the conditions of the most successful simulated world while many products go unused, with products ordered before they are made. Every default can be changed democratically, inside the hard frame of the code; expert ideas and prognoses must be confirmed by everyone. | docs/01 |
| 2026-11-21 | The app is built on the e.V. and a horizontal ticketing system that decides everything the book names: opening and closing units, approving each other's actions and requests. | docs/05 |
| 2026-11-21 | The working council of each production unit approves the working hours; every unit with more than one person has a working council that decides its production affairs. | HF-20, docs/05 section 6 |
| 2026-11-21 | The plan decides investment, focus and closures; it has a period (annual first, later e.g. three-yearly); the public creates it through tickets; its default comes from the latest successful simulation. | docs/05 section 8 |
| 2026-11-21 | By default up to 4 random members confirm actions after reading about the topic. **All 4 must say yes**; any "no" goes to a panel of 12; if still contested, signatures force a vote of all. | docs/05 section 3 |
| 2026-11-21 | The yearly plan: a randomly drawn planning group with union experts drafts **2–3 whole plans**; all members rank them. | docs/05 section 8 |
| 2026-11-21 | Services: **paid only when performed**, with a switch to planned shifts or "by type of service" later. Products: ordered first, a tenth made ahead. | docs/06 sections 4–5 |
| 2026-11-21 | When two units make the same item, **each unit's own hours** set its price. Units that need more hours can join forces with units that need fewer. | docs/04 section 2 |
| 2026-11-21 | Pension: **equal for all**, paid from the flat tax, only after a member has been active for "2 or 3 years" (default set to 36 active months). | docs/03 section 6 |
| 2026-11-21 | Languages: **English** only at the start. | CLAUDE.md, phase 0 |
| 2026-11-21 | Stack: Python/Django with server-built pages, installable on phones, on the owner's **Virtualmin box with AlmaLinux and MariaDB, no PostgreSQL**. | docs/09 |
| 2026-11-21 | From the earlier code (Unicorn2), keep: **placeholders for missing inputs** and **prices split into direct and indirect hours**. Do not reuse the code. | docs/04 sections 6 and 9 |
| 2026-11-21 | Missing inputs and tools: the member either provides them free or asks to buy them from capitalism; the trade fund checks the plan and pays one member, or pools parts from several members to a trusted member who buys and sends the thing. | docs/04 section 5, docs/07 section 3 |
| 2026-11-21 | The code is public on GitHub (`kgk45tGg45u/unicorn`), replacing the earlier Node.js/React prototype. The files must not expose the owner's personal details, except his name. | README |
| 2026-11-21 | The market shows what others need and motivates people to make it; opening a unit is easy and immediate when nothing in the plan is against it. | docs/06 sections 2 and 7 |

## Choices made while writing, waiting for the owner

These follow the book, the legal frame or common sense, but nobody has decided them. Each is a default the members can change, and the important ones are in docs/12.

| Choice | Default | Reason |
|---|---|---|
| Hard-frame changes | expert proposal + forecast + completeness check by 4 confirmers + vote of all with two thirds and 25% turnout + new release | "expert ideas and prognosis should be confirmed by everyone" |
| Ordinary referendum | 14 days, 20% quorum, simple majority | common practice |
| Petition threshold | 2% of active members, at least 5 | small enough for 25 founders |
| Confirmers' deadline and pay | 72 hours; 30 minutes paid (panels 45) | deciding is work (book p. 140) |
| Planning group | 15 random members (a third of members if fewer than 45), plus up to 5 union advisers without a vote | the book wants drafters different from approvers |
| Plan calendar | proposals July–August, drafting September to mid-October, vote 1–14 November | a plan ready before the year starts |
| Ranked vote method | instant runoff | simple to explain |
| Council defaults | all workers; majority; rotation of the responsible every 6 months; any other council member approves hours | book p. 139 |
| One-person units | hours approved automatically, then checked against output and by random monthly samples | no council exists; the owner's rule covers units of more than one person |
| Weekly limit | 48 Unicorn hours a week | health; against invented hours |
| Orders | UNIQ held at ordering, charged at delivery; cancelling free until the batch starts | products ordered first |
| Retirement account | the app suggests moving savings above the target while the light is amber; it never moves them by itself | the simulation moved them automatically; moving members' UNIQ without asking seemed too strong |
| Pension amount | 60% of the median net UNIQ income, pension age 67 (Germany), active month = at least 10 approved hours | not simulated; for the first plan to confirm |
| Shortage bonus | off; only a referendum can switch it on, at most +25% for 3 months | book p. 76 and HF-2 |
| Trust rating numbers | start 0.2 (founders 0.5), +0.02 per payment on time, −0.30 per missed payment; base cap €300, at most 10% of the fund | legal frame: "starts small, grows slowly, falls fast" |
| Purchase approval | automatic up to €50 when green; random confirmers up to €2,000; above that, the plan or a referendum | small things fast, big things by many |
| Loss reserve | 2% of every set-aside | the legal frame names one; its size is new |
| Exchange rate | only a planning rate (euros earned per hour of outside sales), never an exchange | HF-4, the legal frame |
| Capitalist carriers | their euros are paid by the fund like materials; the buyer pays nothing in UNIQ for them | prices are only Unicorn hours (HF-3) |
| Courier or carrier | the app proposes by the make-or-buy rule at the planning rate; the selling unit's responsible confirms | book p. 154; HF-15 |
| Courier hours | distance ÷ 15 km/h + 5 minutes a stop, plus the vehicle's wear | a service's labour value like any other |
| Reputation | only for suggesting who might answer a ticket, and for recognition; helpful marks fade by half every 180 days and count for 12 months; members can switch off being suggested | book p. 70; HF-10, HF-15 |
| Recognition | "first maker", "filled a need" and thank-yous from reviews; no ranking list | book p. 76: no extra pay (HF-2) |
| Unions | formed by 2 or more units' councils; one delegate per unit, rotating every 6 months; they advise and nominate experts, and cannot change any unit | book pp. 139–140; HF-15, HF-20 |
| Expert advisers once unions exist | union nominations, and members may still volunteer; the planning group approves at most 5 | the owner named union experts; volunteers keep the door open |
| Local councils | for a postcode area with at least 10 verified members; decided by random members of the area; a volunteer responsible rotating every 6 months | book p. 141 |
| Acting for a member without a device | a helper with signed consent (at most 12 months, at most 5 people per helper) may order, book, record hours and write tickets for them; never vote, confirm, approve hours, hold or pay fund euros, sign contracts, change bank details or delete the account | book p. 68; one person, one vote (HF-13) |
| Limits against spam | 20 tickets a day, 30 comments an hour, 20 flags a day per member; 10 shop orders an hour per internet address | small enough to stop abuse, large enough for normal use |
| Licence | AGPL-3.0 "or later" | the usual choice for open projects; "version 3 only" is the alternative |
| Backups | nightly, encrypted to a key that never lives on the server; 30 daily and 12 monthly copies; a monthly restore test on staging, where the key is sent only through the SSH connection | docs/08 section 6 |
