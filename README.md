# Unicorn: A Model for a Socialist Economic System

Unicorn is an application that runs an economy on **hours of labour**. Every good and service costs the hours of work inside it, and the model extends that idea to macro-economics, micro-adjustment and strategic planning. It builds on the book *Towards a New Socialism* by Paul Cockshott and Allin Cottrell, and on *Unicorn: A Political Economic Model Based on Socialism* by Bijan Sabbagh.

Unicorn brings the economic transactions of a society into one place and decentralises decisions with a **ticketing system** open to all members. The design starts inside today's capitalism, as a network of members who work for each other and sell to outside customers, and grows until its members can live from it.

- Members earn **UNIQ** for every hour they work: 1 hour = 1 UNIQ, the same for everyone.
- A good or service costs the hours inside it, and that price never changes for any other reason.
- Members decide everything through **tickets**: opening and closing units, approving each other's requests, the yearly plan, and the rules themselves. Random members confirm actions after reading about them.
- Each production unit with more than one person has a **working council**, which approves its hours and decides its own production.
- Euros, needed to buy from capitalism, stay in members' own bank accounts as the **trade fund**. The app never moves money; it only shows who should pay whom.

## Where this project stands

This is a **restart**. An earlier prototype (Node.js, React, PostgreSQL) used to live here; it has been replaced. The new version starts from:

- **Simulations** of the whole economy, which found the conditions under which such a network can grow inside capitalism and become independent. The results are in [docs/02_simulation_results.md](docs/02_simulation_results.md).
- **Complete documents** for the app: its intention, its rules, the economics, the input-output table, governance, the trade fund, security and privacy, and the chosen stack (Python and Django, MariaDB).
- A **build plan** of 17 phases (the last one lists later features) and 153 small tasks, written so that a coding agent, or a human newcomer, can build the app one step at a time.

**No code is written yet.** The next step is task `P00.T01` of the plan.

## Where to start

| You are | Read |
|---|---|
| New to the project | [docs/00_intention.md](docs/00_intention.md), then [docs/02_simulation_results.md](docs/02_simulation_results.md) |
| A developer or a coding agent | [CLAUDE.md](CLAUDE.md), then [PLAN.md](PLAN.md) |
| Checking the rules | [docs/01_hard_frame_and_defaults.md](docs/01_hard_frame_and_defaults.md) and [config/defaults.yaml](config/defaults.yaml) |
| A lawyer, tax adviser or economist | [docs/07_trade_fund_capitalism.md](docs/07_trade_fund_capitalism.md), [docs/03_economics.md](docs/03_economics.md) and [docs/12_open_questions.md](docs/12_open_questions.md) |

## Next steps

1. **Build phase 00:** the Django project, the database (MySQL on a laptop, MariaDB on the server), tooling, base pages, background jobs and the registry of democratic defaults.
2. **Phases 01–09:** members and identity, the UNIQ books, units and councils, the input-output table, the market, tickets and random confirmers, votes, the trade fund, and the monthly close.
3. **A pilot** for the founders (about 25 people) on a test server, after phase 09.
4. **Phases 10–15:** outside sales, the yearly plan, shipping, unions and local councils, security and privacy, and the public launch.
5. **Meanwhile,** answer the open questions in [docs/12_open_questions.md](docs/12_open_questions.md), above all the legal ones, and rerun the simulation with the app's newer rules.

The full list is in [PLAN.md](PLAN.md).

## Join in: we need your help

Unicorn is a project for many hands, and it is early enough that your work shapes it. Please get in touch if you can help with any of these:

- **Developers** (Python, Django, MariaDB or MySQL, HTMX): take a task from the plan. Each one says which documents to read, which files to change and which tests to write.
- **Security and privacy reviewers:** read [docs/08_security_privacy_persistence.md](docs/08_security_privacy_persistence.md) and tell us what we missed.
- **Economists and modellers:** check the simulations and the economics, and challenge the default world.
- **Lawyers and tax advisers** (Germany first): the legal questions in [docs/12_open_questions.md](docs/12_open_questions.md) are the biggest risk to the project.
- **Designers and accessibility experts:** the app must work for people on old phones, and for people who cannot use a phone at all.
- **Translators:** English comes first, then German and Persian.
- **Testers and future members:** tell us what you would want from such a network.

**How to reach us:** open an issue or start a discussion in this repository. Say which part interests you and what you can offer; small contributions are welcome. A design from the earlier prototype is still on [Figma](https://www.figma.com/design/VSmk926ar0bdpL1C3Tgy3o/Unicorn?m=auto&t=cyRQBabdPoznvv3E-1).

## The documents

| File | What it holds |
|---|---|
| [docs/00_intention.md](docs/00_intention.md) | What Unicorn is for, in plain words; what the app is and is not |
| [docs/01_hard_frame_and_defaults.md](docs/01_hard_frame_and_defaults.md) | The rules the code enforces (the hard frame), and how members change everything else |
| [docs/02_simulation_results.md](docs/02_simulation_results.md) | What the simulations found, the default world and recipe, the conditions for success |
| [docs/03_economics.md](docs/03_economics.md) | UNIQ, Fund 1 and Fund 2, the flat tax, savings, pension, the planning rate, warning lights, monthly close |
| [docs/04_io_table.md](docs/04_io_table.md) | The input-output table: items, recipes, cycles, products and services, labour values |
| [docs/05_governance.md](docs/05_governance.md) | Tickets, random confirmers, panels, referendums, delegation, councils, unions, the yearly plan, trust and reputation |
| [docs/06_work_production_market.md](docs/06_work_production_market.md) | Units, hours, orders, services, the marketplace, the needs board, shipping |
| [docs/07_trade_fund_capitalism.md](docs/07_trade_fund_capitalism.md) | The trade fund in members' accounts, buying from capitalism, outside sales, donations, other countries |
| [docs/08_security_privacy_persistence.md](docs/08_security_privacy_persistence.md) | Identity, encryption, the books, backups, privacy |
| [docs/09_stack_and_hosting.md](docs/09_stack_and_hosting.md) | The chosen building blocks and the server |
| [docs/10_glossary.md](docs/10_glossary.md) | Words used in the app and the code |
| [docs/11_decisions.md](docs/11_decisions.md) | The owner's decisions, with dates |
| [docs/12_open_questions.md](docs/12_open_questions.md) | Questions still open, for the owner or for lawyers |

The simulations behind the defaults live in a separate project and are summarised in docs/02.

## Rights

The code is licensed under the **GNU Affero General Public License v3.0 or later**: you can fork, clone, study and reproduce Unicorn under any name you see fit, as long as your version stays open too (see rule HF-19 in [docs/01_hard_frame_and_defaults.md](docs/01_hard_frame_and_defaults.md)). If you want to develop a Unicorn, let's do it together.
