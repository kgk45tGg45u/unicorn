# Operators' guide: backups, restore tests and disaster recovery

Written for the people who run the server. Plain steps, no surprises. The rules behind it are in `docs/08_security_privacy_persistence.md`, sections 4 and 6.

## What runs by itself

- **Every night** `deploy/backup.sh` runs from cron as the virtual server's user. It dumps the database, packs the private files, encrypts both to the backup **public** key, copies the result to a second machine and keeps 30 daily and 12 monthly copies on both machines. It writes the time of success to `~/run/last_backup`, which the health check reads.
- **Every day** the app checks when a restore test last worked. If there has been none for 35 days, a ticket goes to the elected auditors.

## One-time setup

1. **Make the backup key pair, on an operator's own computer, never on the server:**

   ```
   age-keygen -o unicorn-backup.key
   ```

   It prints a line that starts with `age1...`: that is the public key. Copy only that line to the server, as `~/backup_recipient.txt`.
2. **Keep the private key (`unicorn-backup.key`) in two places, offline,** held by two different operators (for example on two encrypted USB sticks in two homes). Never put it on the server, in the repository, in an email or in a chat. Without it no backup can be read, and anyone who has it can read every backup.
3. **On the server** (as the virtual server's user):
   - `~/.my.cnf` with the database user and password, `chmod 600 ~/.my.cnf`;
   - `~/.backup.env` with `DB_NAME=<database>` and `BACKUP_TARGET=<user>@<second-machine>:<folder>`;
   - an SSH key that may only write to the backup folder on the second machine (restrict it with `command=` or a chrooted `rsync` account);
   - the cron line (P15.T07): `15 3 * * * ~/app/deploy/backup.sh >> ~/logs/backup.log 2>&1`.
4. Run `deploy/backup.sh` once by hand and look at `~/backups/` and the second machine.

## The monthly restore test (staging server)

A backup that was never restored is only a hope. Once a month an operator tests one:

1. Fetch a backup from the second machine to the staging server, for example `unicorn-2027-03-01.tar.age`.
2. Optionally fetch the published fingerprints: `curl -s https://<production>/open-books/fingerprints.json > ~/published.json` and set `PUBLISHED_FINGERPRINTS=~/published.json`.
3. Run the test from your own computer. The private key goes through standard input, so it never touches the disk of the server:

   ```
   ssh staging '~/app/deploy/restore_test.sh /path/unicorn-2027-03-01.tar.age' < ~/keys/unicorn-backup.key
   ```

   The script decrypts the backup, loads it into a separate database, checks the books from the first transaction (`audit_books --full`), compares the chain heads with the published fingerprints, repeats every account deletion (`reapply_deletions`), drops the database again, and prints `RESTORE TEST OK` or `RESTORE TEST FAILED` with the reasons.
4. Write the result down on production, so that the open-books page can show it:

   ```
   ssh production '~/app/deploy/manage.sh record_restore_test --ok --backup-date 2027-03-01 --notes "all fine"'
   ```

   Use `--failed` and write the reasons in `--notes` when it failed. A failed test is urgent: fix the backup before anything else.

Staging never has the production master key, so personal fields in the restored database stay unreadable there. That is on purpose.

## After a disaster

Targets: at most one day of data lost, service back within one day.

1. Get a new box and do phase 15 steps T02 to T05 (packages, virtual servers, the app, gunicorn and Apache). Put the **same `.env` secrets** back from the operators' sealed copy. Without the old master key, personal data cannot be read.
2. Fetch the newest backup from the second machine and check it: `sha256sum -c unicorn-<date>.tar.age.sha256`.
3. Decrypt it with the private key: `age -d -i unicorn-backup.key unicorn-<date>.tar.age | tar -x`. This gives `database.sql.gz` and `private_media.tar.gz`.
4. Load the database: `gunzip -c database.sql.gz | mariadb <database>`. Unpack the private files into `~/private_media`.
5. **Run `reapply_deletions`:** `deploy/manage.sh reapply_deletions`. The backup still holds the plain email address and name of members who were deleted since, and this removes them again.
6. **Run `audit_books --full`** and **compare with the last published fingerprint:** `deploy/manage.sh compare_fingerprints --published published.json`, using the JSON from the open-books page (or a copy you saved earlier). Every published fingerprint up to the last restored transaction must match.
7. Tell the members what happened and how much was lost, on the home page and by email.
