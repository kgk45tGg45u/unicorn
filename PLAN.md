# The build plan

This is the plan for building the Unicorn app. It is written for a coding agent working at low effort: every task is small, says which documents to read, which files to touch, which tests to write, and when it is done. Read [CLAUDE.md](CLAUDE.md) first.

## How the plan works

- The work is split into **17 phases** (00–16). Each phase has its own file in [plan/](plan/) with numbered tasks (`P03.T04` = phase 3, task 4).
- **Do the phases in order, and the tasks in order inside a phase.** A task may use only what earlier tasks built.
- **After each task:** `make check` passes; tick its box in the phase file; commit with `P<phase>.T<task>: <summary>` (CLAUDE.md, section 2).
- **After each phase:** run the phase's **acceptance check** (the last section of its file) and write one line under "Progress" below.
- **Unclear?** Use the simplest option that keeps the hard frame, mark it `# OWNER-CHECK`, and add it to [docs/12_open_questions.md](docs/12_open_questions.md).

## The apps

| App | Holds | Built in |
|---|---|---|
| `core` | base model, money and hashing helpers, audit events, background jobs | P00 |
| `rules` | the democratic defaults (`Parameter`), their history, the hard-frame registry | P00 |
| `members` | user accounts, members, identity checks, the digital contract, encrypted personal data, portfolios | P00 (user model), P01 |
| `ledger` | UNIQ accounts, periods, transactions, holds, the hash chain, audits, open books | P02 |
| `units` | units, working councils, council rules, rotation, hours | P03 |
| `catalogue` | items, offers, recipes, tools, labour values (the input-output table) | P04 |
| `market` | orders, production orders, input requests, bookings, stock, deliveries, reviews, the needs board | P05 |
| `tickets` | tickets, comments, types and actions, random confirmers, panels, flags, mediation | P06 |
| `votes` | petitions, referendums, ballots | P07 |
| `tasks` | mandates for delegates, collective tasks | P07 |
| `tradefund` | holders, the fund's books, payment requests, purchases, donations, trust, exchange rates, benefits | P08 |
| `macro` | the monthly close, tax balance, identities, warning lights, "Are we on track?", transfers, pension | P09 |
| `outside` | outside customers, the outside shop, invoices, set-asides | P10 |
| `plan` | plan periods, proposals, the plan check, planning groups, plan variants, budgets | P11 (plan check stub in P03) |
| `logistics` | cover areas, postcodes, couriers, carriers | P12 |
| `bodies` | unions, local councils, consumers' councils | P13 |
| `reputation` | helpful marks, reputation, recognition | P13 |
| `privacy` | data export, complete deletion, deletion records | P14 |

## The phases

| Phase | File | Goal | Needs |
|---|---|---|---|
| 00 | [plan/phase_00_setup.md](plan/phase_00_setup.md) | Django project on MySQL/MariaDB, tooling, base pages, jobs, the defaults registry | – |
| 01 | [plan/phase_01_members_identity.md](plan/phase_01_members_identity.md) | Sign-up with the digital contract, passkeys and email codes, identity checks, encrypted personal data, portfolios, leaving | 00 |
| 02 | [plan/phase_02_ledger.md](plan/phase_02_ledger.md) | The UNIQ books: Fund 1, Fund 2, member and retirement accounts, holds, hash chain, triggers, audit, open books | 01 |
| 03 | [plan/phase_03_units_councils_hours.md](plan/phase_03_units_councils_hours.md) | Units, working councils and their rules, rotation, recording, approving and paying hours | 02 |
| 04 | [plan/phase_04_catalogue_io_table.md](plan/phase_04_catalogue_io_table.md) | Items, placeholders, offers, recipes, tools, the labour-value engine | 03 |
| 05 | [plan/phase_05_market.md](plan/phase_05_market.md) | Ordering products, booking services, production and input orders, stock, write-offs, deliveries, the needs board | 04 |
| 06 | [plan/phase_06_tickets_confirmers.md](plan/phase_06_tickets_confirmers.md) | Tickets, random confirmers, panels, flags, mediation; earlier flows moved onto tickets | 05 |
| 07 | [plan/phase_07_votes_delegation_tasks.md](plan/phase_07_votes_delegation_tasks.md) | Petitions, referendums, secret ballots, mandates, collective tasks, parameter changes by ticket | 06 |
| 08 | [plan/phase_08_trade_fund.md](plan/phase_08_trade_fund.md) | Holders, the fund's books, payment requests, purchases from capitalism, donations, trust, benefits | 07 |
| 09 | [plan/phase_09_macro_close.md](plan/phase_09_macro_close.md) | The monthly close, tax balance, identities, warning lights, "Are we on track?", pension, retirement suggestions | 08 |
| 10 | [plan/phase_10_outside_sales.md](plan/phase_10_outside_sales.md) | The outside shop, invoices, set-asides, the export cap, yearly statements | 09 |
| 11 | [plan/phase_11_yearly_plan.md](plan/phase_11_yearly_plan.md) | The full plan check, plan proposals, the planning group, 2–3 whole plans, the ranked vote, budgets, focus and closures | 10 |
| 12 | [plan/phase_12_shipping.md](plan/phase_12_shipping.md) | Cover areas, postcodes, couriers, capitalist carriers, delivery choice | 11 |
| 13 | [plan/phase_13_bodies_reputation.md](plan/phase_13_bodies_reputation.md) | Unions, local and consumers' councils, reputation, recognition, acting for a member without a device | 12 |
| 14 | [plan/phase_14_security_privacy.md](plan/phase_14_security_privacy.md) | Data map, rate limits, data export and deletion, key rotation, headers, legal pages, licence, backups, logs, accessibility | 13 (some tasks earlier, see below) |
| 15 | [plan/phase_15_deploy_virtualmin.md](plan/phase_15_deploy_virtualmin.md) | Staging and production on the Virtualmin box, cron, backups, releases, the founders' launch | 14 (or earlier, see below) |
| 16 | [plan/phase_16_later.md](plan/phase_16_later.md) | Later: housing, offline payments, harmony algorithm, in-app forecasts, federation, more languages, three-year plans | 15 |

**A pilot for the founders can start earlier.** After phase 09, the founders' trial year can run: members, ledger, units, hours, offers, orders, tickets, votes, trade fund, monthly close. For that, right after phase 09:
1. do phase 14's tasks **T01, T03, T04 and T06–T09** (the data map, data export, complete deletion, security headers and the admin, the legal pages, the licence and source link, backups and the restore test), because the pilot holds real people's data;
2. then phase 15's tasks **T01–T07** (server checks, packages, virtual servers, the app, gunicorn and Apache, releases, cron, email and backups), using the staging server as the pilot.

Tick those tasks when done. Then continue with phase 10, and do the rest of phases 14 and 15 when you reach them.

## Milestones

| Milestone | After | What members can do |
|---|---|---|
| M1 Books | P02 | sign up, be verified, see a UNIQ account (test data only) |
| M2 Work | P05 | open units, publish offers with prices in hours, order products, book services, get paid for approved hours |
| M3 Decide | P07 | decide through tickets, random confirmers, panels, petitions and referendums |
| M4 Euros | P09 | run the trade fund, buy from capitalism, close each month with a balanced tax: **the founders' pilot** |
| M5 Grow | P13 | sell outside, adopt a yearly plan, ship, form unions and local councils |
| M6 Launch | P15 | the public launch on the Virtualmin box |

## Progress

*(One line per finished phase: date, phase, acceptance check passed, notes.)*

- 2026-11-22, P00: acceptance check passed (make check, ping job runs, /rules/ shows 20 rules and all 187 defaults). Python 3.12 via Homebrew; see docs/12 section 3.

- 2026-11-22, P01: all nine tasks done; make check passes; hf_coverage lists tests for HF-8, HF-13 and HF-14. Not walked through in a browser yet (passkey needs a real device); see docs/12 for the open points.

- 2026-11-22, P02: all nine tasks done; make check passes; HF-1, 4, 5, 6, 7, 8 each have tests; audit_books --full is clean and the triggers exist on the local MySQL (needs log_bin_trust_function_creators=1, see docs/12).
- 2026-11-22, P01: all tasks done and `make check` passes; test-covered by the `test_hf13_`/`test_hf14_` tests.
- 2026-11-22, P02: acceptance check passed (make check, `audit_books --full` says the books are in order, append-only triggers exist, open-books page built).
- 2026-11-22, P03: acceptance check passed (make check; all test_hf02_, hf09_, hf15_, hf17_, hf20_ tests pass; own hours cannot be self-approved; 2 h 30 min pays 2.5000 UNIQ gross with the period's tax). One open question in docs/12 (hours over the weekly limit in a one-person unit).
- 2026-11-22, P04: acceptance check passed (make check; the docs/04 examples built through the services show 0.1425 [0.14 on screen], 1.00 and 4.30 UNIQ with the right direct, indirect and euro split; the three open-data CSVs download; test_hf03_price_only_from_engine passes). Owner decision on one-person unit hours recorded (docs/11) for P05/P06.
- 2026-11-22, P05: acceptance check passed (make check; the acceptance test places the 2-loaf order and finds the bakery batch, the mill's input request and the salt need; Fund 1 receives 0.2850 UNIQ; a haircut is booked, performed, confirmed and its 1-hour entry paid; an advance lot expires into a waste record; the needs board lists salt under "Bought from outside"). Open points for the owner are in docs/12 section 3 (services sold in person, the unit form prefilled from the needs board, disputes until tickets exist, splitting a line over shelf lots).
- 2026-11-23, P06: acceptance check passed (make check; the acceptance test opens a red-listed unit through a ticket: four yes votes open it and each seat gets 30 paid minutes; one "no" draws a panel of 12 and 7 yes votes open it; `reproduce` repeats the draws from the eligible lists; the `test_hf13_` and `test_hf15_` tests pass). Open points for the owner are in docs/12 section 3 (one-person hours still approved automatically, held UNIQ after a dispute, contesting a removal).
- 2026-11-23, P07: acceptance check passed (make check; the acceptance test walks a rejected ticket through a petition, a vote and its receipt check, changes `logistics.default_cover_radius_km` by a `parameter_change` after four yes votes with the history linking the ticket, and chooses, reports and pays a delegate; all `test_hf16_` tests pass). Open points for the owner are in docs/12 section 3 (the pay for writing the case against, the first elections, the delegate's trade).
- 2026-11-23, P08: acceptance check passed (make check; the acceptance test makes two founders holders, records a 100 euro donation with 2% reserve, closes the bakery's salt purchase by reimbursement and a receipt, pools a 300 euro tool purchase from two holders to a volunteer buyer after four confirmers said yes and unblocks the woodshop's chair offer, and covers a missed payment from the reserve; the `test_hf11_`, `test_hf12_` and `test_hf18_` tests pass). Open points for the owner are in docs/12 section 3 (payments in one currency only, mismatch rules, who may buy, the vanished holder).
- 2026-11-23, P09: acceptance check passed (make check; the acceptance test closes a month of the phase 05 example plus one pension: Fund 1 is zero, every identity is zero, the next flat tax comes with H, C, S and T on `/open-books/`, the street light is grey and `/on-track/` shows the default world's month 1). Open points are in docs/12 section 3.
- 2026-11-23, P10: acceptance check passed (make check; the acceptance test sells an oak chair for 180 euros: the invoice carries the § 19 note, 153 euros are set aside after a 15% tax reserve, handing it over raises `trade` by 4.30 hours, and no UNIQ moved; `test_hf04_outside_orders_never_touch_uniq` passes). Open points are in docs/12 section 3 (products only, no bot protection yet, refunds of spent set-asides).
- 2026-11-23, P11: acceptance check passed (make check; the acceptance test adopts the first plan, files three proposals, draws a group of 9 from 25 members, drafts two plans that pass the engine check, picks one by ranked vote and applies it on 1 January with history rows citing the referendum's ticket; a closed trade gives a red plan check; `test_hf15_check_never_rejects` and `test_hf16_` pass). Open points are in docs/12 section 3 (euro budgets at launch, the implied flat tax, investments without a unit).
- 2026-11-23, P12: acceptance check passed (make check; with the fixture postcodes a member 3 km from the bakery sees "deliverable to you"; a courier delivery is quoted from its hours plus depreciation, held, sent, delivered, confirmed and paid as an hours entry; a member 255 km away gets a carrier proposal with 0 UNIQ shipping and a purchase request for the carrier's euros; `test_hf03_carrier_euros_never_enter_an_offers_uniq_price` passes). Open points are in docs/12 section 3 (outside customers and couriers, parcel weight, refunds after payment).
- 2026-11-23, P12 addition (owner decision): outside customers pay Unicorn couriers in euros, directly to the courier; the set-aside goes to the trade fund books; no UNIQ move (HF-4). It is written in docs/06 section 8, docs/07 section 6 and docs/11, and tested in `apps/logistics/tests/test_outside_courier.py`. Later phases must not change it.
- 2026-11-23, P13: acceptance check passed (make check; the acceptance test forms the woodworkers' union from two councils with a delegate each, notifies the delegates about a chair question and shows their answer as advice that changes nothing, opens a local council for postcode prefix 10 with random confirmers from that area and a pickup point through a local ticket, suggests a member with three helpful marks for a new wood question, and lets a helper with consent place an order "on behalf of" a member who then cannot be voted for; `scripts/hf_coverage.py` lists the `test_hf02_`, `test_hf13_`, `test_hf15_` and `test_hf20_` tests of the phase). Open points are in docs/12 section 3 (volunteer advisers, paper summaries, union decision forms).
- 2026-11-23, P14: acceptance check passed (full `pytest` run is green; a member's data export and deletion leave no email or display name behind, `test_hf14_deleted_member_leaves_no_plaintext`; the master key is rotated on test data and everything still decrypts; the backup scripts, the restore test and its result on the open-books page are built, but they have not run against a real server or a real `age` key yet; the security headers, the content security policy and the inline-code test pass; the footer shows the source link and the version, `test_hf19_licence_and_source_link`). The permission matrix test and the security checklist are in. Open points for the owner are in docs/12 section 3 (the legal texts and privacy documents are drafts for the lawyers, `SOURCE_URL`, the two HSTS warnings kept on purpose, the placeholder icons).
