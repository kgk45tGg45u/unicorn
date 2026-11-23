# What to do when personal data is lost, stolen or seen by the wrong people

> **DRAFT — to be checked by lawyers.**

GDPR Articles 33 and 34. A **breach** is any event in which personal data is lost, destroyed, changed, or shown to someone who may not see it — by an attack, a mistake, a lost laptop, or a faulty program. Keep this page where the operators can find it without the server.

**The deadline:** the supervisory authority must be told **within 72 hours** of the moment the association became aware of the breach, unless it is unlikely to harm anyone. Do not wait to be sure; write what is known and add the rest later.

## 1. Who does what

| Role | Who | What they do |
|---|---|---|
| **Anyone** (operator, member, helper) | | Tells the breach contact **at once**: `<to fill in: an address and a phone number that always reach a person>`. Does not try to hide it or fix it alone. |
| **Breach lead** | `<to fill in: one named operator, and a named deputy>` | Runs the steps below; keeps the log; decides what to do first. |
| **Decider** | `<to fill in: two members of the board>` | Decides, together with the lead, whether to inform the authority and the members. If they cannot be reached in time, the lead decides and tells them afterwards. |
| **Lawyer** | `<to fill in>` | Is called when the case is not clear. |

Supervisory authority: `<to fill in: the name, address, the online form and the phone number>`.

## 2. The steps

1. **Write down the time** the breach was found, and who found it. The 72 hours count from the moment the association knew.
2. **Stop it.** Examples: take the page offline, block the account, change a password, switch off a job. If a key may be known to someone, go to step 5 at once.
3. **Keep the evidence.** Do not delete logs. Note what was seen and who saw it. Never copy personal data into a chat or email.
4. **Find out what happened.** What data? Whose, and about how many people? Was it encrypted, and was the key also taken? For how long? Is it still happening? The application logs hold request numbers and member numbers, never personal data, so they can be shared with the lawyer.
5. **Change the keys if they may be known.** Follow the steps in docs/08, section 4 ("Key rotation"): `generate_keys`, put the new key in `.env`, restart, `rotate_master_key`, remove the old key, destroy every copy of it. If a hash key may be known, also run `rotate_hmac_key`. Take a new backup, and write the date in the operators' log. Check that sessions of affected members are ended.
6. **Judge the risk.** Unlikely to harm anyone (for example: an encrypted laptop with no key)? Then nothing is sent, but the case still goes in the log. Likely to harm? Then step 7. **Likely to be a high harm** (health data, bank accounts, identity documents, many people)? Then steps 7 and 8.
7. **Tell the authority — within 72 hours.** Say: what happened; the kinds of data and the number of people and records; the contact of the breach lead; the likely results; what has been done and what will be done. Late? Say why. If something is not yet known, say so and send the rest in parts.
8. **Tell the people affected — without delay, in plain words.** Say: what happened; what it could mean for them; what the association has done; what they can do (for example: change a password, watch the bank account); who to ask. Send it by email, and put a notice on the home page if many are affected. Do not tell the people if the data was unreadable to the thief (encrypted and the key safe). Write down why.
9. **Repair and learn.** Fix the cause. Add a test where a program was at fault. Update the data map and the records of processing if they were wrong. Report the case at the next general meeting, without names.

## 3. The log of breaches

**Every** breach is written down, also those that are not reported (Article 33(5)). The log is kept by the breach lead, outside the server, and not in a place that members can read.

| Date found | Found by | What happened | Data and number of people | Effect | Told the authority? (date, or why not) | Told the people? (date, or why not) | What was done | Closed (date) |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

## 4. Practise it

Once a year the breach lead runs a short drill with the operators: a made-up case, the steps above, a stopwatch. Write down what was slow. `<to fill in: date of the last drill>`.
