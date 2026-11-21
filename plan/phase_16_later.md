# Phase 16 — Later: features that wait for a decision

**Goal:** a list of what Unicorn will need after its first years, with what each one needs first and a rough outline of its tasks.
**Rule for the coding agent:** **do not start any item here** until the owner (or a decision of the members) has marked it `Status: ready` in this file, and its open questions in docs/12 are answered. Then turn the outline into tasks in the same form as the other phases (`P16.<item>.T01`, …), and ask the owner to read them before you start.

Each item has:
- **What:** the feature in one or two sentences;
- **Why later:** the reason it is not in phases 00–15;
- **Decide first:** the questions that must be answered;
- **Already prepared:** what earlier phases left ready for it;
- **Outline:** the tasks it will probably need.

---

## L01 — Services paid by planned shifts, or by type of service

**Status:** waiting (owner, 2026-11-21: "only when performed, but possible to change to planned shifts or by type of service later").
- **What:** the other two choices of `economy.services.pay_rule` (docs/06 section 4):
  - `planned_shifts`: the plan gives each service a budget of hours, and shifts are paid when worked, booked or not;
  - `by_type`: always-open services (care homes, shops, kitchens, clinics) are paid by shift, and appointment services when performed.
- **Why later:** paying for idle time needs the yearly plan's budgets (phase 11) and a way to see the cost of idle time.
- **Decide first:** which unit kinds count as always open; how much idle time is acceptable before the light turns red.
- **Already prepared:** the parameter and its choices; `NotImplementedError` in P05.T06; the idle-shifts light in docs/03 section 10.
- **Outline:**
  1. `Shift` and `ShiftBudget` models; councils plan shifts within the budget;
  2. pay worked shifts at the close, with idle time recorded as waste;
  3. the idle-shifts light;
  4. a plan-tier switch through a `parameter_change` ticket.

## L02 — Sharing scarce inputs: the harmony algorithm

**Status:** waiting.
- **What:** when an intermediate input is short (a mill that cannot supply every bakery), the book's harmony algorithm (pp. 118–124) **suggests** how to share it between the units that need it:
  - for each unit, `u = (output − goal) / goal`, and harmony `h = −u²` if `u < 0`, else `√u`;
  - start from the current shares, find the limiting inputs, and move what is left over into a shared pool;
  - cut the units with the highest harmony towards the average (plus a margin `B`), and give the freed inputs to the units with the lowest harmony;
  - repeat until the average changes by less than 1%, with `B` falling at each round.
- **Why later:** until there are real shortages, serving input requests in the order placed is enough (docs/03 section 9).
- **Decide first:** who sets the "goal" of each unit (the plan, or the councils); whether the suggestion goes to the union of the trade or to each council.
- **Already prepared:** `InputRequest` records (P05.T03); the needs board shows shortages; unions (P13).
- **Outline:**
  1. `apps/plan/harmony.py`, a pure function with tests from the book's examples;
  2. a monthly job that runs it for each short input and writes a suggestion to the councils and the union (HF-15: it only suggests);
  3. a page that shows the suggestion and its reasoning.

## L03 — Housing

**Status:** waiting.
- **What:** Unicorn homes, rented to members in UNIQ:
  - `housing.rent_uniq_per_m2` = 0.59 a month and `housing.m2_per_member` = 30;
  - a share of new capital becomes homes (`housing.share_of_investment` = 0.24);
  - a member moves in only if the rent is at most half their income (`housing.max_rent_share`);
  - upkeep is work like any other.
- **Why later:** buying or building homes needs a legal owner, large sums of euros and a lawyer's advice. The simulation counted on homes from about year 6.
- **Decide first:**
  - who legally owns the homes (the association, a separate housing association, or a cooperative);
  - how homes are allocated (a waiting list, by need, or by lot);
  - what happens to a tenant who leaves Unicorn.
- **Already prepared:** the parameters; the plan's investment list (P11) can hold homes; local councils (P13) for local housing matters.
- **Outline:**
  1. `apps/housing/`: `Home`, `Tenancy` (a contract template `tenancy`), `WaitingList`;
  2. monthly rent posted as `rent` (member → Fund 1, P02.T03);
  3. upkeep units of kind `housing`;
  4. the rent light and its place in the tax balance.

## L04 — Paying offline

**Status:** waiting.
- **What:** small UNIQ purchases without a network connection (docs/08 section 9; book p. 67). The buyer's device signs a payment, the seller's device keeps it, and both synchronise later.
- **Why later:** signing on the device and checking for double spending is hard to get right, and the first version can rely on a connection.
- **Decide first:** the offline limit per member; who carries the loss when a member double-spends.
- **Already prepared:** holds (P02.T04) and the hash chain.
- **Outline:**
  1. a device key per member (WebCrypto, kept in the browser);
  2. signed vouchers within a monthly offline limit, held as a hold in advance;
  3. synchronisation, and a double-spend check that opens a flag;
  4. tests with a simulated clock and two devices.

## L05 — The EU digital identity wallet

**Status:** waiting for the wallet to be available in Germany.
- **What:** verify new members with the EU digital identity wallet instead of two vouches and an in-person check (docs/08 section 2).
- **Why later:** the wallet is not yet generally available.
- **Decide first:** whether the wallet replaces the vouches, or only the in-person check (`membership.vouches_needed` and `membership.in_person_check` are referendum-tier).
- **Already prepared:** `MemberHash` duplicate detection (P01.T05) and the identity steps.
- **Outline:**
  1. an OpenID for Verifiable Presentations flow asking only "is a person over 18" and a unique pseudonym, never the name;
  2. the pseudonym is stored as an HMAC in `MemberHash`;
  3. switches for the referendum.

## L06 — Forecasts inside the app

**Status:** waiting.
- **What:** run the simulation (`../Unicorn-simulation`) from inside the app on the real data, so that every plan variant and hard-frame proposal gets its forecast at once (docs/03 section 11).
- **Why later:** for now the forecasts are made by experts with the simulation outside the app, from the exported `forecast-data.csv` (P09.T09).
- **Decide first:** which simulation version is the official one; who checks that the forecast's assumptions are fair.
- **Already prepared:** the data export and the `Forecast` model (P09.T09).
- **Outline:**
  1. package the simulation's core as a library with a fixed version;
  2. a job that runs a forecast for a plan variant, with a time limit;
  3. a page that shows the four goals, the warning lights and the assumptions;
  4. the result is always shown as a forecast, never as a decision.

## L07 — Members in other countries: sister associations and federation

**Status:** waiting.
- **What:** Unicorn starts as one German association, and members abroad may join (docs/07 section 11). When a local group abroad forms, it becomes a **sister association**: the same rule book, the same app on its own server, and its own trade fund. Sister associations exchange goods and settle differences in euros. UNIQ never cross between them except by agreed rules.
- **Why later:** it needs lawyers in each country and a working first association.
- **Decide first:**
  - the agreement between sister associations;
  - how hours made in one and used in the other are counted;
  - whether a European cooperative society (SCE) should replace the federation later.
- **Already prepared:** country and currency on every member (P01.T02); the ECB rates (P08.T01); one-country carriers (P12.T07).
- **Outline:**
  1. a federation protocol between servers (signed messages for orders and settlements);
  2. per-association settings;
  3. cross-association orders that settle in euros through the trade funds;
  4. shared open books for the federation.

## L08 — More languages

**Status:** waiting (owner, 2026-11-21: English only at the start).
- **What:** German first, then other languages, including Persian, which is written right to left.
- **Why later:** the texts change too often during the first phases.
- **Decide first:** the order of languages; who translates and who checks.
- **Already prepared:** every text is wrapped for translation (CLAUDE.md); `LOCALE_PATHS`.
- **Outline:**
  1. `makemessages` for `de`, translation, `compilemessages` in the release script;
  2. a language switch;
  3. for right-to-left languages: `dir="rtl"`, Bootstrap's RTL stylesheet, and checks of every page;
  4. translated legal pages, checked by lawyers.

## L09 — A phone app wrapper

**Status:** only if the installable web app is not enough.
- **What:** package the web app for app stores.
- **Why later:** the installable web app (PWA) already works on phones without an app store.
- **Decide first:** whether members really need it; the cost of app-store accounts.
- **Outline:** a thin wrapper around the same pages, with no features of its own.

## L10 — The shortage bonus

**Status:** off by default (HF-2), and stays off until a referendum turns it on for one trade.
- **What:** a temporary extra per hour (at most +25%, at most 3 months per decision) for one named trade with a red shortage (book p. 76; docs/05 section 11).
- **Why later:** it is an exception to equal pay, and should be used rarely.
- **Decide first:** whether the bonus is paid from the social share or raises the tax.
- **Already prepared:** `economy.shortage_bonus.*` with hard bounds.
- **Outline:**
  1. a `shortage_bonus` ticket type that only a referendum decides;
  2. the bonus as a separate `transfer` (Fund 2 → member) for the approved hours in that trade, with the ticket as its reason;
  3. it ends by itself;
  4. `test_hf02_bonus_needs_referendum_and_ends`.

## L11 — Three-year plans: the second group

**Status:** waiting until `plan.period_years` is changed to 3 by a referendum (P11.T08 builds only the switch).
- **What:** a second, separately drawn group drafts the long-term part of the plan. The book wants long-term plans approved by different people from those who draft the short-term ones (p. 105).
- **Decide first:** what the long-term part contains (tools, homes, closing trades); how the yearly plans must follow it.
- **Outline:**
  1. `PlanPeriod` with a long-term part;
  2. a second planning group, drawn so that nobody sits in both;
  3. a separate ranked vote;
  4. the yearly plan check also checks the long-term part.

## L12 — Communes

**Status:** waiting.
- **What:** shared living places (each person has their own room) with shared services: a canteen, a kindergarten, classes, workshops, gardens, care for the elderly. Their inside economy links to Unicorn (book, "The Commune"; cohousing; the Marinaleda example).
- **Why later:** it needs housing (L03) first.
- **Decide first:** how a commune's internal work is counted (as Unicorn hours, or partly outside the books, like farmers growing for themselves, book p. 104).
- **Outline:** a unit kind `commune`, built on housing, with local councils as its political body.

## L13 — The street price of a UNIQ

**Status:** waiting (docs/12).
- **What:** the simulation's rough indicator of a black market: what a UNIQ fetches outside the rules. The light exists but measures nothing yet (docs/03 section 10).
- **Decide first:** the basis of the measurement (anonymous surveys, flags, or offers seen outside), without watching members' private lives (book p. 155).
- **Outline:** the measurement, the light's thresholds, and its place in the forecasts.

## L14 — Managed joining

**Status:** off (`membership.joining_rule` = `open`, referendum-tier).
- **What:** admit new members at a planned pace instead of all at once. The simulation's best recipe used open joining.
- **Decide first:** the pace, and who is admitted first (by need, by skills the needs board lacks, or by lot).
- **Already prepared:** `Waitlist` (P01.T06).
- **Outline:** a monthly admissions job that follows the chosen rule, and a waiting list page that shows each person their place.

## L15 — Automatic retirement deposits

**Status:** waiting (docs/11, a choice made while writing: the app only suggests moves into the retirement account).
- **What:** while the unspent-UNIQ light is amber, move a share of savings above the target into each member's retirement account automatically, as the simulation did (`economy.retirement.suggest_share`).
- **Decide first:** whether automatic moves are wanted, and whether each member may opt out.
- **Outline:** a switch, a monthly job using `retirement_in` (P02.T09), and a notice to each member.

## L16 — Contributions to the German pension system

**Status:** waiting (docs/12).
- **What:** whether the trade fund pays voluntary contributions to the German statutory pension (about €100 a month) for members who left their jobs, so that they keep their claims (docs/12, owner question 3).
- **Decide first:** the owner's answer and the legal advice.
- **Outline:** depends on the advice; probably a fund budget line and payment requests (P08).

## L17 — Publishing the daily fingerprint outside Unicorn

**Status:** waiting.
- **What:** publish the daily hash of the books with an outside timestamp service (RFC 3161) or a newspaper, so that anyone can prove later that the books were not changed (docs/08 section 5).
- **Decide first:** which timestamp service, and its cost.
- **Outline:** a daily job that sends only the hash, stores the timestamp token, and shows it on the open-books page.

## L18 — Limits for natural resources

**Status:** waiting.
- **What:** labour values give natural resources no cost (book). The book lets planners give raw resources a "virtual" labour content. Because the owner forbids price changes, Unicorn would instead set **limits** (quotas) on the use of a scarce resource, decided by the plan with scientific advice.
- **Decide first:** quotas, or a virtual labour content; who advises.
- **Outline:** `ResourceLimit` in the plan, a check in the plan check (P11.T02), and a light for use against the limit.
