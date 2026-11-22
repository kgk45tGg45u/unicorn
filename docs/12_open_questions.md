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
