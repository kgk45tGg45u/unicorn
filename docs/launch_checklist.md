# The founders' meeting: the order of business

For the founders (about 25 people) and the two operators. Read it aloud, item by item. Nobody needs to know how the program works: every step says who does it and what to look for.

Before the meeting, an operator runs `deploy/manage.sh launch_check` on the staging server and reads out what it says. Lines that say **FAIL** must be fixed before the meeting can finish; **WARN** lines are things to look at (for example a text that the lawyers have not finished). The same command is run again at the end, on production.

## 1. Sign the statute and register the association

- Read the statute (it is part 1 of the membership contract in the app) and the lawyers' remarks on it.
- Every founder signs the paper statute. The board of unpaid signers is chosen. The association is registered by the people the law names.
- Write the date and the register number down. The operators put them in the imprint and the privacy notice (`content/legal/`).
- *Look for:* the legal pages no longer say "to fill in" (launch_check, line "The legal pages and contact addresses").

## 2. Sign the digital contract in the app

- Each founder opens Unicorn, logs in with a passkey or an email code, and signs the membership contract.
- Each founder reads it first. Nobody signs for someone else.
- *Look for:* every founder has a signature; the contracts line of launch_check shows no "DRAFT" once the lawyers have written them.

## 3. Verify each other in person

- Every founder meets two other founders, face to face, in the meeting. Each of them says: "I saw this person, and this is their only account."
- An identity helper enters each check in the app (date and town; never an ID number or a copy of an ID).
- Afterwards an operator runs `deploy/manage.sh bootstrap_founders --emails <the founders' email addresses>`. It makes the founders verified members.
- *Look for:* launch_check, line "The founders": every founder was seen by two others.

## 4. Choose two holders and two operators

- **Two holders** keep the group's euros in their own bank accounts. Each reads the holder agreement, signs it in the app, and enters the account number (it is stored encrypted). Pick people the group trusts and who will not be away for months.
- **Two operators** look after the server. They each keep the master key and the HMAC key in their own password managers (docs/09; losing the master key means losing every member's personal data). They also keep the private backup key offline, one each.
- Write the names in the minutes, not in the app's files.
- *Look for:* launch_check, line "The holders" shows two.

## 5. Adopt the default plan

- The first yearly plan is the default plan of the simulation (docs/02). An operator runs `deploy/manage.sh start_first_plan`. It opens a yes/no vote for the founders.
- Every founder votes in the app. Say aloud what a "no" would mean: there is no plan, and the founders talk again.
- *Look for:* launch_check, line "The first plan vote" says started; after the vote, the plan shows as adopted.

## 6. Open the coordination unit and the first services

- The coordination unit (Unicorn's own work) is already there. Its workers are chosen.
- Each founder who offers a first service (repairs, lessons, care, IT, hair and beauty, and so on) opens their own unit. The list of starter services is in the defaults (`sectors.starter_services`).
- *Look for:* launch_check, line "The coordination unit"; the starter services line is a WARN until a page shows the list.

## 7. Agree when the trial year ends

- Every founder clicks "Unicorn launches" on the launch page. When all have clicked, the trial year starts (12 months, set in the defaults).
- Write down the date on which the trial year ends, and what the group wants to decide by then: who may join, and how fast.
- *Look for:* launch_check, line "The trial year" shows the end date.

## At the end

- An operator runs `deploy/manage.sh launch_check` on **production**. Every line OK or WARN, no FAIL.
- Read the WARN lines aloud and write who will fix each, and by when.
- Write the date and the version (the footer shows it) in `docs/deploy_log.md`.
