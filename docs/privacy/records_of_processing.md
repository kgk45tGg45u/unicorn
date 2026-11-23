# Records of processing activities

> **DRAFT — to be checked by lawyers.**

This is the record the association must keep under GDPR Article 30. It is built from [the data map](data_map.md): the data map says *where* each piece of personal data lives; this record says *what the association does with it, and why*. When a phase adds personal data, it changes the data map first, and this record follows.

**Who is responsible (the "controller"):** the association — `<to fill in: name, address and register number>`.
**Contact for privacy questions:** `<to fill in: an email address read by at least two people>`.
**Data-protection officer:** none yet. One is needed once 20 people regularly handle personal data (docs/08, section 7). `<to fill in: date checked>`.
**People who run the server ("operators"):** `<to fill in: names or roles>`. They are bound to keep personal data secret and may not read encrypted fields (docs/08, section 4).

**Sending data to other countries:** none by design. No third-party analytics, fonts, CDNs or advertising. The server is `<to fill in: the hosting company and its country>`. Backups go off-site to `<to fill in: where>`; they are encrypted before they leave the server.

**Security measures in every purpose below:** encrypted connections only; personal data encrypted member by member (HF-14); a member's key is destroyed when they delete their account; roles and permissions checked on every page; logs without personal data; encrypted backups, and a restore test every month; the steps in the [breach procedure](breach_procedure.md). Details: docs/08.

---

## 1. Membership

| | |
|---|---|
| **What we do** | Create and keep accounts; check that each person has one account (HF-13); let members sign the digital contract; show a member's name to other members; send notices; let members see, download and correct their data, and delete their account. |
| **Whose data** | Members, and people who applied or joined the waiting list. |
| **What data** | Email address; display name; postcode (area only); country, currency, time zone; legal name, street, city, phone, date of birth, bank account (encrypted, in `MemberPrivate`); hashes of email, phone, bank account, name and birth date; signed contracts with the text's hash; vouches and in-person checks; passkeys and sessions; skills and availability; consent to be helped, and who helped. |
| **Legal basis** | 6(1)(b) the membership contract; 6(1)(c) legal duties (the signed contracts are kept with the books); 6(1)(a) consent for the waiting list, the public profile and being helped; 6(1)(f) for the duplicate-detection hashes. |
| **Who gets it** | The member; other members see the display name and the number; operators see the email address and the area. Nobody reads the hashes. |
| **How long** | Until the account is deleted. Then the key is destroyed; the member number stays in the books as "Former member <number>". Waiting list: until the invitation, or 24 months. |
| **Where it comes from** | The member. |

## 2. The UNIQ books

| | |
|---|---|
| **What we do** | Record hours, pay in UNIQ, and keep the open books that every member can check (HF-7). Show a member's own account to the member. |
| **Whose data** | Members who work, buy or sell; units. |
| **What data** | Member numbers (no names) with hours, orders, bookings, reviews, units' reports and the hash chain of the ledger. |
| **Legal basis** | 6(1)(c) the duty to keep books; 6(1)(b). |
| **Who gets it** | Public totals for everyone; the member's own account for the member; a unit's hours for its workers. |
| **How long** | Kept with the books: `<to fill in: the legal period, 8 or 10 years; to be confirmed by lawyers>`. The books never hold a name, so deleting an account does not break them. |
| **Where it comes from** | The members' actions in the app. |

## 3. The trade fund

| | |
|---|---|
| **What we do** | Show payment requests for euros, record that a holder confirmed a payment, keep the fund's books, issue receipts for donations. The app never moves money and never reads a bank account (HF-12). |
| **Whose data** | Holders, members who pay or are paid, donors, outside payees. |
| **What data** | Holder records (member number); trust events; donor name (encrypted); the bank account of an outside payee (encrypted). |
| **Legal basis** | 6(1)(b); 6(1)(c) for receipts and the fund's books. |
| **Who gets it** | Holders see what a payment needs; operators cannot read encrypted fields without the system key. |
| **How long** | Payee bank accounts: until the payment is confirmed, then as the books require. Donor names and receipts: `<to fill in: to be confirmed by lawyers>`. |
| **Where it comes from** | The member who asks for the payment; the donor. |

## 4. Outside sales

| | |
|---|---|
| **What we do** | Let a unit sell to people outside Unicorn: take the order, show the consumer information, deliver, send the invoice, handle withdrawal and returns. |
| **Whose data** | Outside customers; the seller. |
| **What data** | The customer's name, address and email (encrypted); the customer's data as printed on the invoice (encrypted); the seller's business address (encrypted). |
| **Legal basis** | 6(1)(b) the sale; 6(1)(c) invoices and taxes. |
| **Who gets it** | The seller; tax authorities on request. Operators cannot read the fields without the system key. |
| **How long** | Contact details are wiped 90 days after delivery. Invoices: `<to fill in: 8 or 10 years; to be confirmed by lawyers>`. |
| **Where it comes from** | The customer. |

## 5. Tickets and votes

| | |
|---|---|
| **What we do** | Run decisions: tickets, comments, random confirmers, working-council votes, general votes, mediation, reputation suggestions and recognition. |
| **Whose data** | Members. |
| **What data** | Member numbers with tickets, comments, helpful marks, confirmers' answers, voter records (that someone voted, never what they voted), notifications, reputation scores and recognition. |
| **Legal basis** | 6(1)(b); 6(1)(f) for the audit events. |
| **Who gets it** | Members see a ticket's author by display name; confirmers see the ticket. A ballot holds no member. |
| **How long** | Tickets are kept as the record of decisions; after a deletion the author is shown as "a former member". Notifications: until deletion. |
| **Where it comes from** | The members' actions in the app. |

## 6. Care and benefit claims

> **Special category data (Article 9).** This purpose may not start until the board has signed a DPIA ([dpia_template.md](dpia_template.md)).

| | |
|---|---|
| **What we do** | Let a member say they cannot work, or that they receive benefits, so the equal pension, care or a benefit rule can apply; let random confirmers confirm the claim. |
| **Whose data** | Members who ask. |
| **What data** | The yes/no "receives benefits"; uploaded documents (encrypted, in private storage); the confirmation ("unable to work: confirmed by 4 confirmers on <date>"). Never a diagnosis. |
| **Legal basis** | 6(1)(b), and 9(2)(a) explicit consent to every claim, withdrawable at any time. |
| **Who gets it** | The member; the seated confirmers see the documents of the claim; everybody else sees only the confirmation. |
| **How long** | Documents: until the claim is closed, and no longer than the member's account. `<to fill in: to be confirmed by lawyers>`. |
| **Where it comes from** | The member. |

---

## Also recorded (not a purpose of its own)

- **Logs:** web server logs 14 days, application logs 30 days, with member numbers only (6(1)(f)).
- **Backups:** daily for 30 days, monthly for 12 months, encrypted (6(1)(f)). After a restore, `reapply_deletions` is run so deleted people stay deleted.
- **Data exports** made for a member: kept 7 days.

## Review

Read again every year, and whenever a phase adds personal data. `<to fill in: date and the initials of the person who checked>`.
