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
