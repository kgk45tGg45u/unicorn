# 8. Security, privacy and keeping the records safe

*Legal frame: `../Unicorn-simulation/docs/real_world/4_legal_frame.md` section 7 (data protection), section 10 (the app's legal duties); book pp. 65–68 (limits of information technology). Hard-frame rules HF-7, HF-12, HF-13, HF-14.*

## 1. What could go wrong, and what stops it

| Threat | Protection |
|---|---|
| **Fake accounts** to vote twice, be drawn as a confirmer, or hold fund euros | identity check: 2 vouches + 1 in-person check (section 2); duplicate detection; unverified accounts cannot vote, confirm, hold or be drawn (HF-13) |
| **Invented hours** (UNIQ without work, the Soviet "manipulated data" problem, book p. 15) | council approval (HF-20); hours against output checks; random checks of one-person units; weekly limit (docs/06, section 3); open books |
| **A council approving each other's fake hours** | hours against output at the level of the whole unit; flags; random `hours_review` |
| **Rigged random draws** | verifiable seed from the public fingerprint; stored eligible-list hash; anyone can ask an auditor to repeat a draw (docs/05, section 3) |
| **A holder running off with fund euros** | caps, trust rating, loss reserve, few payers, written reasons (docs/07, section 5) |
| **Someone changing the books** | append-only tables with database triggers; hash chains; nightly audit; daily public fingerprint (section 5) |
| **The server operator abusing access** | no daily superuser use; read-only admin; every correction is a ticket; operators' shell sessions logged; two operators know the keys, and no one person alone |
| **Account takeover** | passkeys; email login codes; re-authentication for sensitive actions; notifications of new logins |
| **Data breach** | per-member encryption of personal data; member numbers instead of names in all hour and ledger tables; minimal data |
| **Denial of service, spam** | rate limits on login, sign-up, tickets and comments; Apache limits; backups |
| **Black market for UNIQ** | no transfers between members (HF-5); flags; the street-price light (when its basis is decided); no Big-Brother monitoring of private life (book p. 155) |

## 2. Identity: one person, one account

1. **Sign-up.** Email, display name, country, and the one digital contract: the statute, trust agreement, tax consent, privacy notice and rating rules, signed in the app (legal frame, section 1). Minimum age 18.
2. **Two vouches.** Two verified members who know the person confirm: "I know this person, and this is their only account." A voucher can vouch for at most 5 people a month.
3. **One in-person check.** A verified member who volunteered as an **identity helper** meets the person and sees an official ID. The helper records only "seen in person on <date> in <town>", never the ID number or a copy. A helper cannot vouch for the same person.
4. **Founders** verify each other at the founding meeting: each founder is checked in person by two others.
5. **Duplicate detection.** Hashes (HMAC with a server key) of the email, phone, IBAN and "legal name + date of birth" are compared at sign-up and on change. A match opens a flag for random confirmers. The hashes are not reversible, and they are deleted with the account.
6. **Later.** The EU digital identity wallet can replace steps 2–3 once it is available in Germany (plan/phase_16).

## 3. Logging in and permissions

- **Login** by **passkey** (fingerprint, face or phone unlock) or by a **one-time code sent by email**. No passwords are stored (`django-allauth`: login by code and passkeys; the agent checks the exact settings against the installed version).
- **Re-authentication** within the last 15 minutes is required for: approving hours, confirming payments, voting, signing contracts, changing bank details, and holder actions.
- **Sessions** end after 2 weeks, or 12 hours without activity. New logins are notified by email.
- **Permissions come from the data, not from roles handed out by someone:**
  - council member of unit X;
  - the responsible of X;
  - seated confirmer on ticket T;
  - delegate with mandate M;
  - holder;
  - member of the trust review group;
  - elected auditor.

  Each view checks the exact permission it needs. There is no "manager" or "admin" role in the app.
- **The Django admin** is read-only for everyone (CLAUDE.md, definition of done). It is reachable only by operators, with a passkey, from the server's admin path.

## 4. Encryption

- **In transit:** HTTPS only (Let's Encrypt through Virtualmin), HSTS, secure and HTTP-only cookies.
- **Personal data, field by field** (HF-14):
  - each member has a **data key** (a Fernet key from `cryptography`);
  - the data key is stored encrypted with the server's **master key**, which lives only in the `.env` file, outside the web root, readable only by the app's user;
  - `members.MemberPrivate` (legal name, address, phone, date of birth, IBAN) and private files (licences, receipts, benefit documents) are encrypted with the member's data key.
- **Deletion by key** ("crypto-shredding"). Deleting a member's data key makes all their encrypted data unreadable, in backups too.
- **Key rotation** (task P14.T05). It is done yearly, and whenever an operator leaves. The steps:
  1. On the server, run `python manage.py generate_keys`. It prints a new `UNICORN_MASTER_KEY` and a new `UNICORN_HMAC_KEY`. Copy them from the screen; nothing is written to a file or a log.
  2. In `.env`, put the new master key in `UNICORN_MASTER_KEY` and the old one in `UNICORN_OLD_MASTER_KEYS` (several old keys are separated by commas). Restart the app. Everything can still be read.
  3. Run `python manage.py rotate_master_key`. It re-wraps every member's data key and re-encrypts every system-encrypted field (customers, invoices, sellers, donors, payees) with the new key, in batches of 500. It prints only counts. It is safe to run again.
  4. When it says `left to do: 0`, remove the old key from `UNICORN_OLD_MASTER_KEYS` in `.env` and restart. Then destroy every copy of the old key.
  5. Only if the HMAC key changed too: run `python manage.py rotate_hmac_key`. It recomputes every duplicate-detection hash. Do this before step 4 if the HMAC key is also being replaced, so that no duplicate goes unnoticed in between.
  6. Take a new backup, and write the date in the operators' log.
- **Backups** are encrypted with a separate backup key, kept offline by two operators (section 6).
- **Email addresses** are needed in plain text to log in and to send mail. They are kept in the accounts table only, protected by the database's access rules, and never shown to other members.

## 5. The books: persistence and proof

- **Database:** MariaDB with InnoDB and `utf8mb4` (docs/09).
- **Append-only tables:**
  - the UNIQ ledger (`ledger_transaction`, `ledger_entry`);
  - the fund's books (`tradefund_fundentry`);
  - signatures (`members_signature`);
  - parameter changes (`rules_parameterchange`);
  - audit events (`core_auditevent`);
  - ballots and voter records;
  - value history (`catalogue_offervaluehistory`).

  Database triggers refuse UPDATE and DELETE on these tables (task P02.T05). If the database user lacks the right to create triggers, model guards refuse the same in Django, and the nightly audit detects any change.
- **Hash chains:** each ledger transaction stores `hash = SHA-256(previous hash + canonical JSON of the transaction and its entries)`. The fund's books have their own chain.
- **Nightly audit** (`manage.py audit_books`):
  - recomputes both chains;
  - checks that every transaction sums to zero;
  - checks that UNIQ outstanding = −Fund 2;
  - checks that no member balance is below zero;
  - checks that every period close is complete.

  Any failure opens a ticket for the elected auditors and lights a red banner on the open-books page.
- **Daily public fingerprint:** every night the head hash of each chain is published on the open-books page with the date. Members can copy it, and anyone can later prove that the books of that day were not changed. Publishing it outside (for example in a newspaper or a public timestamp service) can come later.
- **Open books:**
  - totals by period, by fund and by use are public;
  - every offer's recipe and values are public;
  - individual accounts are visible only to their owner;
  - pseudonymous member numbers appear only where a member chose to be visible (the job portfolio and unit pages).

## 6. Backups and recovery

- **Nightly:**
  - `mysqldump --single-transaction --routines --triggers`, plus the private files directory;
  - compressed and encrypted with the backup key (`age` or `gpg`);
  - copied by `rsync` over SSH to a second machine in another place.
- **Kept:** 30 daily and 12 monthly copies.
- **Monthly restore test** on the staging server, checked by the nightly audit command. The result is recorded.
- **Targets:** at most one day of data lost; service back within one day.
- **Hash-chain checkpoints** let anyone confirm that a restored database is the true one, up to the last published fingerprint.

## 7. Privacy (GDPR)

- **Data map** (kept up to date in `docs/privacy/data_map.md`, task P14.T01): what personal data, where it is kept, why, on what legal basis, for how long, who sees it.
- **Minimal data.** The app asks only for what a feature needs. Health data appears only where a member asks for something that needs it, and then only as a confirmation ("unable to work: confirmed by 4 confirmers on <date>"), never a diagnosis.
- **Member rights:**
  - see and download all their data (JSON + CSV, task P14.T03);
  - correct it;
  - delete their account.
- **On deletion:**
  - the data key is destroyed;
  - the account is closed, and the member number stays in the books with its history (legal duty to keep the books; HF-7);
  - the member is told first that remaining UNIQ stay in the books but can no longer be spent, and that held fund euros must first be passed on (docs/07, section 2).
- **A data-protection impact assessment** is needed before care services start (Art. 9 health data). A data-protection officer is needed once 20 people regularly handle personal data.
- **The privacy documents of the association** (task P14.T12, all drafts to be checked by lawyers):
  - [records of processing](privacy/records_of_processing.md) (Art. 30), one section per purpose;
  - [a DPIA template](privacy/dpia_template.md) (Art. 35), which the board fills in and signs before care services or benefit claims start;
  - [the breach procedure](privacy/breach_procedure.md) (Art. 33–34): who decides, the 72 hours, informing members, the log, and changing the keys.
- **No tracking:** no third-party analytics, no external fonts, no CDNs in production, no advertising. Logs never contain personal data.

## 8. Logs, monitoring, disclosure

- **Application logs:** errors and warnings, with request IDs and member numbers at most.
- **Error mails** go to the operators' list. An uptime check runs every 5 minutes from outside.
- **Audit events** (`core.AuditEvent`) record who did what to which object, for everything outside the two books.
- **`/.well-known/security.txt`** gives a contact for reporting vulnerabilities.
- **Legal pages:** imprint (the post box), privacy notice, terms of use, the digital contract's current version, consumer information for outside customers.

## 9. When the network is down (later)

The book wants payments to keep working offline (p. 67). The first version needs a connection. Offline payments come in phase 16:
- small amounts, within a per-member offline limit;
- signed on the device, synchronised later;
- double spending checked on synchronisation.
