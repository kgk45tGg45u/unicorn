# 12. Open questions

Questions that are not decided. The coding agent adds new ones at the end of section 3 (with the task number) and continues with the simplest option that keeps the hard frame.

## 1. For the owner

1. **Should the simulation be rerun with the app's new rules before the founders adopt the first plan?** Rules not simulated:
   - the equal pension;
   - services paid only when performed instead of planned hours;
   - the cost of governance hours;
   - the retirement account as a suggestion instead of an automatic move.

   A run in `../Unicorn-simulation` with these switches would show whether the default world still meets all four goals.
2. **Pension amount and age:** 60% of the median net UNIQ income, from age 67 (Germany), after 36 active months of at least 10 hours. Are these right?
3. **Should the trade fund pay voluntary German pension contributions** (about €100 a month) for members who left their jobs, so that they do not lose their German pension? It costs euros and delays independence.
4. **Tax balance monthly or yearly?** The simulation balanced monthly. A yearly balance is steadier but lets unspent UNIQ pile up longer (seed review v3, section 8).
5. **The street-price light:** on what should it be based in the real app? Without a basis it stays grey.
6. **When hours run short, who gives way first: Unicorn's tools or members' goods?** The simulation cut tools first for hours but kept tools first for euros (seed review v3, section 8).
7. **The founders' trial year:** should the app stay closed to new members for the first 12 months after launch, as in the simulation?
8. **Where does the Virtualmin box stand?** It must be in the EU/EEA (GDPR). And who besides the owner will be a second operator with the keys?
9. **Which domain name** will the app use?
10. *(Answered 2026-11-21: the code is public on GitHub at `kgk45tGg45u/unicorn`.)*
11. **Should the members' bills paid by the fund** go to the landlord or insurer directly, or to the member? (The tax ruling may decide.)
12. **The second machine for backups and the uptime check:** where will it stand (it must be in the EU), and who runs it? Until it exists, backups stay only on the box (P15.T07).
13. **If the box runs MariaDB 10.5** (AlmaLinux 9's default), should it be upgraded to 10.11 before launch? Unicorn works on 10.5, but 10.11 is supported longer (P15.T01).
14. **The licence:** AGPL-3.0 "or later" (the plan's default) or "version 3 only"? (P14.T08)

## 2. For lawyers and the tax office (from the legal frame)

1. Does the register court accept the e.V.'s purpose as a post box? (Fallback: an eG as post box.)
2. Does the tax office accept the trust agreements, so that held euros are the group's, not the holder's income? (Binding ruling.)
3. How is UNIQ income taxed: at shop value, at the hours it represents, or not at all? (Binding ruling; the biggest risk, docs/02.)
4. Are the fund's payments of members' bills taxable income?
5. Who is the contract partner for bills that need one payer (insurance, server, app stores), when the post box has no account?
6. Can the post box claim stolen fund euros in its own name, through the trust agreement?
7. A written enquiry to BaFin that UNIQ are not e-money and the app is not a payment service.
8. Does the platform-work directive's German law (due 2 December 2026) touch a planning app that only proposes?
9. A group liability insurance for members' services.
10. A data-protection impact assessment before care services start.

## 3. Raised while building

*(The coding agent adds questions here: date, task number, question, the option chosen for now.)*

- 2026-11-22, P00.T01/T03: Python 3.14 (the Mac's default) has no ready-made `cryptography` for this older macOS, so I installed Python 3.12 with Homebrew (`.venv` uses it). Driver: `mysqlclient` built fine, no PyMySQL needed. Local MySQL is 8.3.0.
- 2026-11-22, P01.T01: all allauth setting names in the plan exist in the installed version (65.22). I added `MFA_PASSKEY_SIGNUP_ENABLED = False` and silenced Django check `models.W036` (MySQL ignores allauth's conditional unique constraints; allauth checks them in code). The "12 hours without activity" session end (docs/08 section 3) is not built: no task in the plan covers it, and a 12-hour sliding cookie would clash with the 2-week limit. Needs a decision (P01.T09).
- 2026-11-22, P01.T09: allauth counts only an explicit re-authentication (by code or passkey) as "recent", not the first login, so `sensitive_action` asks a freshly logged-in member to re-authenticate once before the first sensitive action. Chosen for now because it is allauth's behaviour; say if a fresh login should count for 15 minutes.
- 2026-11-22, P02.T05: the local MySQL has binary logging on, so creating the append-only triggers needs `log_bin_trust_function_creators=1`. I set it for the running server with `SET GLOBAL` (lost on restart). To keep it, add `log_bin_trust_function_creators=1` under `[mysqld]` in the local my.cnf, or re-run `make migrate` after resetting (the trigger migration warns, it does not fail). Tests that use `transaction=True` cannot be used on tables with triggers (Django's flush uses DELETE); use plain `django_db`.
- 2026-11-22, P03.T08: a one-person unit has no council, so hours over the weekly limit (48 h) cannot get the "two approvals with reasons" the rule asks for. Chosen for now: such hours stay `submitted` and are not paid until the unit has a council (a second worker joins). Say if a random member should check them instead.
  **ANSWERED by the owner, 2026-11-22:** a person who works alone in a unit gets their hours confirmed by the person who received the service (when that person is in Unicorn). For production, 2 random members audit the worker's profile and confirm. To be built with bookings (P05) and random confirmers (P06); until then the rule above stays. Also in docs/11.
  **Built so far (P05.T06):** for services, the customer's confirmation of the performed session is what creates and approves the provider's hours, also in a one-person unit, so the person who received the service has confirmed them. For production in a one-person unit, the hours are still approved automatically until random confirmers exist (P06): the two random members who audit the worker's profile come with P06.
- 2026-11-22, P05.T08: selling a **service** in person with a QR code is not built (the page says services are booked in the market). A paid-on-the-spot service would need its hours recorded, and the plan does not say how. Chosen for now: in-person payment is for products on the shelf only. Say if services should be sold this way too.
- 2026-11-22, P05.T11/T12: the "same town first" order of the market uses the member's postcode (the same postcode, then the same first two digits) until cover areas and distances come in phase 12. The needs board button "I can make this" opens the unit form with `?item=`, but the form ignores it for now (members who already work in a unit get a button that opens "Add an offer" with the item filled in). Say if the unit form should be prefilled too.
- 2026-11-22, P05.T05/T06: "Not received", "Damaged" and disputed bookings are recorded as audit events, and the UNIQ stay held, until flag tickets exist (P06). A disputed line is not confirmed automatically, so it stays open until the buyer confirms it or P06 decides it.
- 2026-11-22, P05.T04: a line is served from one shelf lot only (not split over several lots), and a lot with a waiting order on it is not written off until that order is settled. Say if lines should be split over lots.

- 2026-11-23, P06.T04/T05: when nobody can be drawn for a ticket (a very young network), the ticket stays `open` with the note "Waiting until members can be drawn", and the ten-minute job tries again. With fewer than 4 eligible members, all of them are seated and the ticket says so; the rule "all must say yes" then applies to the smaller group. Is that right, or should a very small group go straight to a panel or a referendum?
- 2026-11-23, P06.T05: a confirmer whose answer is missing after the second redraw counts as "no", and is not paid. A "no" that comes only from silence is not shown among the reasons.
- 2026-11-23, P06.T07 (owner decision of 2026-11-22 on one-person units): the plan's note says to replace the automatic approval of one-person hours once random confirmers exist. I did **not** switch it off: the market (services confirmed by the customer, production paid when delivered) and the tests of phases 03 to 05 rely on automatic approval. What exists now: the monthly sample of one-person units (`one_person_check`, 1 seat, 15 minutes paid), and the plausibility notices. Do you want hours of a one-person production unit to wait for 2 random members before they are paid?
- 2026-11-23, P06.T07: a dispute ("not received", "damaged", "not performed") opens a `flag` ticket for 4 random confirmers, but the confirmers' answer only goes on record: the held UNIQ are not released or captured by it. Who settles the held UNIQ after the answer (the unit's council, the buyer, or the app)?
- 2026-11-23, P06.T07: `join_forces` suggestions still open one council decision in each unit (each now has its own `council_decision` ticket). One `join_forces` ticket that needs both councils is not built.
- 2026-11-23, P06.T07: an approved `hours_correct` fails, with a plain message and a note to the operators, if the member has already spent the UNIQ that must be taken back. How should such a correction be handled (a debt, a later deduction, or nothing)?
- 2026-11-23, P06.T08: the author of removed content can contest it once: a panel of 12 (never the first deciders) looks again, and a "no" leaves it removed and starts the petition time. The plan says "through the panel and petition steps" without more detail.
- 2026-11-23, P06.T08: hidden things are left out of the market search, the comments, reviews, profiles and ticket pages. Hours and payments can be flagged and recorded as hidden, but no page shows them yet (the payments come in phase 8).
- 2026-11-23, P06.T09: the mediators' time is approved by the system up to 6 hours per mediator and mediation, as the plan says. The panel that decides after "no agreement" votes yes for the side of the member who asked for mediation, no for the other side.
- 2026-11-23, P07.T01/T02: the member who opens a petition also signs it. A ballot's receipt is its primary key, so the order of the stored ballots says nothing about who voted when. Only members verified before a vote opened may vote in it, so the turnout can never pass 100%. A `poll` ticket schedules a vote of all members at once (no confirmers first).
- 2026-11-23, P07.T02/T08: when nobody said "no" before a vote, one random eligible member is asked to write the case against, as a task. I set its pay to 60 minutes of coordination hours and it is paid when the text is handed in (nobody confirms it). How many minutes should it be, and should someone check the text?
- 2026-11-23, P07.T05: a default of the `plan` tier is rejected at once with the words from the plan and two buttons (a request for a vote of all, or a plan proposal); a default of the `hard` tier is rejected with the pointer to the hard-frame procedure. The decision tier recorded for a change is `confirm` when confirmers decided and `referendum` when a vote decided.
- 2026-11-23, P07.T06: a forecast attached to a hard-frame ticket or a vote is a file every member may open. Only an operator (a staff account) can record the release; the app never changes its own code. Changing a hard bound after the release is a data migration written by hand (nothing in the app does it).
- 2026-11-23, P07.T07: the plan's table has one type `delegate`. I use it for the request ("someone must carry this out"; it is approved by four random confirmers like other tickets) and added `delegate_choice` for the second step (who carries it out). A "none of them" answer counts as a "no" and sends the choice to a panel, as the plan says. The panel also ranks. The ticket form has the delegate's powers (euro limit, may sign, may speak for Unicorn) but no trade code yet, so no portfolio notifications go out until a trade can be set.
- 2026-11-23, P07.T07: spending by a delegate is checked by `tasks.services.spend` and stops above the euro limit; the real payment request comes with the trade fund (phase 8) and plugs into `PAYMENT_REQUEST_HOOK`.
- 2026-11-23, P07.T08: a done task is confirmed by the ticket's author with one click, or by one random member (a `task_check` ticket with one seat, paid like other seats). An author who claimed one of their own tasks cannot confirm it.
- 2026-11-23, P07.T09: the first elections start from a ticket whose action is `start_elections` (for example a poll of the founders after launch). There is no page that makes such a ticket yet, so an operator has to create it. The yearly job opens a new election a month before the terms end. Candidates for the trust review group are not checked against the base cap until the fund exists (phase 8). Auditors with a current term receive `audit_failure` tickets; without any, random confirmers do.
