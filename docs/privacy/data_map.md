# Data map

Where Unicorn keeps personal data, why, on what legal basis, for how long, and who sees it (GDPR Art. 30 and docs/08 section 7). **Every phase that adds personal data adds a row here.** The test `test_hf14_data_map_covers_personal_fields` fails until it does.

Legal bases: **6(1)(b)** the membership contract; **6(1)(c)** a legal duty (books, invoices, taxes); **6(1)(a)** consent; **9(2)(a)** explicit consent for health-related claims. Where the law sets the time, the row says "to be confirmed by lawyers" (docs/12, section 2).

The words in "who sees it": *the member* (about themselves), *confirmers* (random members who look at a ticket), *holders* (members who keep fund euros), *the unit* (workers of a unit), *customers*, *operators* (the people who run the server).

## Members and their accounts

| What | Where | Why | Legal basis | How long | Who sees it |
|---|---|---|---|---|---|
| Email address | `members.User.email` | to log in with an email code and to send notices | 6(1)(b) | until the account is deleted | the member; operators |
| Email address on the waiting list | `members.Waitlist.email` | to invite someone when the founders' trial year ends | 6(1)(a) consent | until the invitation, or 24 months | operators |
| Display name | `members.Member.display_name` | other members see who they work with | 6(1)(b) | until deletion, then "Former member <number>" | all members |
| Postcode (the area only) | `members.Member.postcode` | local councils, cover areas, delivery | 6(1)(b) | until deletion | operators; the number of members per area is public |
| Country, currency, time zone | `members.Member` (no free text) | prices, taxes, times | 6(1)(b) | until deletion | the member; operators |
| "Receives benefits" | `members.Member.receives_benefits` | the pension and benefit rules | 6(1)(b); 9(2)(a) where it is health-related | until deletion | the member; the confirmers of a claim see only the confirmation, never a diagnosis |
| Legal name, street, city, phone, date of birth, bank account (IBAN, BIC, bank name) | `members.MemberPrivate.blob` | contract, identity checks, tax paperwork, payments between members | 6(1)(b), 6(1)(c) | until deletion; the key is destroyed | the member; holders see only what a payment needs |
| The member's own encryption key (wrapped) | `members.DataKey.wrapped` | opens the member's encrypted data | 6(1)(b) | until deletion (destroying it makes the data unreadable) | nobody; operators hold only the wrapped key |
| Uploaded documents (licences, receipts, benefit documents, paper consents) and their file names | `members.PrivateFile.name_enc` and the encrypted file on disk | licences, expense receipts, claims | 6(1)(b); 9(2)(a) for health | until deletion; receipts may need to be kept as books (to be confirmed by lawyers) | the member; seated confirmers for a licence or claim |
| Hashes of email, phone, bank account, name and birth date | `members.MemberHash` | to find a second account of the same person (HF-13) | 6(1)(f) legitimate interest in one person, one account | until deletion | nobody can read them; operators run the comparison |
| Signed contracts, with the text's hash | `members.Signature` | proof of what was agreed | 6(1)(b), 6(1)(c) | kept with the books (to be confirmed by lawyers) | the member; operators |
| Vouches and in-person checks | `members.Vouch`, `members.IdentityCheck` | identity (HF-13) | 6(1)(b) | until deletion | the member; operators |
| Logins, passkeys, recovery codes, sessions | allauth `EmailAddress`, `Authenticator`, Django `Session` | to log in safely | 6(1)(b) | until deletion; sessions expire | the member |
| Skills, availability, licences' status | `members.Skill`, `members.Availability`, `members.Licence` | the work portfolio; licensed trades (HF-17) | 6(1)(b); 6(1)(a) for the public profile | until deletion | the member; others only if the member makes the profile public |
| Consent to be helped, and who helped | `members.AssistConsent`, `members.AssistSummary`, `core.AuditEvent.acted_by` | acting "on behalf of" (P13.T10) | 6(1)(a) consent | until deletion | the member and the helper |

## What members do

| What | Where | Why | Legal basis | How long | Who sees it |
|---|---|---|---|---|---|
| Hours, approvals, council roles | `units.HoursEntry`, `units.HoursApproval`, `units.UnitMembership`, `units.Responsibility` | pay in UNIQ, the working council | 6(1)(b), 6(1)(c) | kept with the books | the member, the unit's workers |
| UNIQ accounts and entries | `ledger` (member numbers only) | the open books (HF-7) | 6(1)(c) | kept with the books; the member number stays after deletion | public totals; the member's own account |
| Orders, bookings, reviews | `market` (member numbers) | buying and selling | 6(1)(b), 6(1)(c) | kept with the books | the member, the selling unit |
| Tickets, comments, helpful marks, votes as a confirmer | `tickets` | decisions (HF-16) | 6(1)(b) | kept as the record of decisions; shown as "a former member" after deletion | members; the author's display name |
| Voter records (not the ballot) | `votes` | one person, one vote | 6(1)(b) | kept | the member; the ballot holds no member |
| Trust events | `tradefund` | the holding limit (HF-11) | 6(1)(b) | until deletion | the member; holders |
| Reputation scores and recognition | `reputation.ReputationScore`, `reputation.Recognition` | suggestions, recognition | 6(1)(b) | rebuilt daily; recognition until deletion | the member; recognition is shown on unit pages |
| Notifications | `tickets.Notification` | telling members what needs them | 6(1)(b) | until deletion | the member |
| Audit events | `core.AuditEvent` (member numbers only) | who did what | 6(1)(c), 6(1)(f) | kept | operators; the member sees their own "done for me" |

## Money and people outside Unicorn

| What | Where | Why | Legal basis | How long | Who sees it |
|---|---|---|---|---|---|
| Name, address and email of an outside customer | `outside.OutsideCustomer.name_enc`, `outside.OutsideCustomer.address_enc`, `outside.OutsideCustomer.email_enc` | to deliver and to send the invoice | 6(1)(b) | contact details are wiped 90 days after delivery | the seller; operators cannot read them without the system key |
| The customer's data on an invoice | `outside.Invoice.customer_snapshot_enc` | invoices must show who bought | 6(1)(c) | to be confirmed by lawyers (8 or 10 years; `# OWNER-CHECK`) | the seller; tax authorities on request |
| The seller's business address | `outside.SellerProfile.trader_address_enc` | the legal notice on invoices | 6(1)(c) | until the seller stops selling, then as the invoices require | the seller; shown to customers on invoices |
| Name of a donor | `tradefund.Donation.donor_name_enc` | the receipt for a donation | 6(1)(b), 6(1)(c) | to be confirmed by lawyers | holders; operators cannot read it without the system key |
| Bank account of someone paid by the fund | `tradefund.ExternalPayee.iban_enc` | to show a payment request | 6(1)(b) | until the payment is confirmed, then as the books require | holders |
| Holder records | `tradefund.Holder` (member number) | who keeps fund euros | 6(1)(b) | kept with the books | holders and operators |

## Places and public data (no person)

| What | Where | Why | Legal basis | How long | Who sees it |
|---|---|---|---|---|---|
| Location of a unit | `units.Unit.postcode` | cover areas | none needed: a business place, not a person | while the unit exists | everyone |
| A public pickup point | `logistics.PickupPoint.postcode` | collecting orders | none needed: a public place | while it is open | everyone |
| The postcode table | `logistics.PostcodePoint.postcode` | coordinates for distances | none needed: public data | kept | everyone |
| The first two digits of a postcode in a failed search | `market.SearchMiss.area` | what the area misses | none needed: the searcher is not stored | kept | everyone |

## Logs and copies

| What | Where | Why | Legal basis | How long | Who sees it |
|---|---|---|---|---|---|
| Web server logs | Apache, on the server | errors and attacks | 6(1)(f) | 14 days (no personal data in application logs; IP addresses are shortened) | operators |
| Application logs | the app's log files | errors | 6(1)(f) | 30 days; member numbers only, never personal data | operators |
| Backups | encrypted dumps, local and off-site | recovery | 6(1)(f) | daily for 14 days, monthly for 12 months; after a restore, run `reapply_deletions` (P14.T04) | operators; encrypted fields stay unreadable once a key is destroyed. A plain email address in an old backup can be read until the backup is deleted (12 months) |
| Data exports | private storage | the member's right to their data | 6(1)(c) | 7 days | the member |
