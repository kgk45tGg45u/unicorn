# Operators' guide: the server, releases, backups and disaster recovery

Written for the people who run the server. Plain steps, no surprises. The rules behind it are in `docs/08_security_privacy_persistence.md`, sections 4 and 6, and in `docs/09_stack_and_hosting.md`, section 3. Write every step you take, with the date, in `docs/deploy_log.md` (never a secret).

**Contents:** [Setting up a box](#setting-up-a-box-phase-15-t01-t05) · [Releases](#releases) · [Cron, email and backups](#cron-email-and-backups) · [Watching the service](#watching-the-service) · [What runs by itself](#what-runs-by-itself) · [Backups: one-time setup](#one-time-setup) · [Restore tests](#the-monthly-restore-test-staging-server) · [After a disaster](#after-a-disaster)

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
   - the cron line: it is in `deploy/crontab.txt` (see "Cron, email and backups").
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


## Setting up a box (phase 15, T01–T05)

Steps marked **(root)** need the server's administrator. Do staging first, then production. The `<user>` is the virtual server's Unix user.

### T01 — Look at the server (read only)

```
bash deploy/check_server.sh
```

It only reads. Copy its answers into `docs/deploy_log.md` and fill in the table "What it means". What is needed: AlmaLinux 8.10 or 9; MariaDB 10.6 or newer (10.5 still works); the time zone tables loaded; Apache with the proxy, proxy_http, headers and ssl modules; Python 3.12; SELinux off, permissive, or on with the `httpd_can_network_connect` switch; a synchronised clock; at least 10 GB free in `/home`; and a box in the EU/EEA.

### T02 — Packages **(root)**

```
dnf install -y epel-release
dnf install -y python3.12 python3.12-devel gcc git pkgconf-pkg-config mariadb-connector-c-devel age
python3.12 -m venv /tmp/check && /tmp/check/bin/pip install mysqlclient && rm -rf /tmp/check
```

If MariaDB comes from the official MariaDB repository, the development package is called `MariaDB-devel`. If `age` is not available, install `gnupg2` (backup.sh uses either). The last line must end without an error: it proves the database driver builds.

### T03 — Virtual servers, databases, certificates **(root)**

1. In Virtualmin, "Create Virtual Server" twice: `unicorn.<domain>` (production) and `staging.unicorn.<domain>` (staging; the founders' pilot runs here first). Features: Apache website, SSL website, MariaDB database, mail for the domain. Each gets its own Unix user, home folder and database.
2. DNS: A (and AAAA, if the box has IPv6) records for both names.
3. Certificates: "Server Configuration → SSL Certificate → Let's Encrypt" for each, with automatic renewal, and "Redirect HTTP to HTTPS".
4. Databases:
   - `ALTER DATABASE <db> CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;` for each;
   - on staging also create `<staging user>_test` (for the tests) and `<staging user>_restore` (for the restore test);
   - the database user needs all rights on its own databases, including `TRIGGER` (`SHOW GRANTS`);
   - if `@@log_bin` is ON, add `log_bin_trust_function_creators = 1` under `[mysqld]` in `/etc/my.cnf.d/server.cnf` and restart MariaDB. Without it the append-only triggers cannot be created, and then only the model guards and the nightly audit protect the books.
5. Time zone tables, once for the database server: `mariadb-tzinfo-to-sql /usr/share/zoneinfo | mariadb -u root mysql`.
6. SELinux: if `getenforce` says `Enforcing`: `setsebool -P httpd_can_network_connect 1`.
7. Set the box to Berlin time: `timedatectl set-timezone Europe/Berlin` (the cron lines assume it).

Done when both sites show Virtualmin's placeholder page over HTTPS, `SELECT CONVERT_TZ('2026-01-01 00:00:00','UTC','Europe/Berlin');` is not NULL, and `SHOW GRANTS` includes `TRIGGER`.

### T04 — The app, its settings and its files

As the virtual server's user (not root):

```
cd ~ && git clone <repository URL> app && cd app && git checkout <tag>
python3.12 -m venv ~/venv
~/venv/bin/pip install --upgrade pip && ~/venv/bin/pip install -r requirements.txt
mkdir -p ~/private_media ~/backups ~/run && chmod 700 ~/private_media ~/backups
cp .env.example ~/.env && chmod 600 ~/.env
```

Use a **read-only deploy key** for the repository. Fill in `~/.env` (outside the code and the web root):

- `DEBUG=False`, `ALLOWED_HOSTS`, `SITE_URL`, `DATABASE_URL`;
- `SECRET_KEY`, `UNICORN_MASTER_KEY`, `UNICORN_HMAC_KEY`: make them with `deploy/manage.sh generate_keys` (it prints them on the screen and writes nothing). **Two operators write the master key and the HMAC key into their password managers.** Losing the master key means losing every member's personal data, and nobody can recover it;
- `EMAIL_URL=smtp://localhost:25`, `DEFAULT_FROM_EMAIL=no-reply@<site host>`, `ADMIN_EMAILS` (the operators), `SERVER_EMAIL`, `SECURITY_CONTACT`;
- `ADMIN_PATH` (a long random path), `SOURCE_URL` (the repository's public address, HF-19), `SECURE_HSTS_SECONDS=3600`;
- `STATIC_ROOT=/home/<user>/public_html/static`, `PRIVATE_MEDIA_ROOT=/home/<user>/private_media`;
- on production `BACKUP_EXPECTED=True`; on staging `TEST_DATABASE_NAME=<staging user>_test`.

Then, once: `deploy/first_setup.sh` (migrate, cache table, contracts, static files, defaults, `check --deploy`). It is never run again: on later releases the defaults change only through tickets.

Done when `deploy/manage.sh check --deploy` prints no errors on staging. (Two warnings, `security.W005` and `security.W021`, stay on purpose; see docs/12.)

### T05 — gunicorn and Apache **(root)**

1. Copy `deploy/unicorn.service` to `/etc/systemd/system/unicorn.service` (production, port 8001), and as `unicorn-staging.service` with port 8002 for staging. Replace `<user>`. Then `systemctl daemon-reload && systemctl enable --now unicorn`.
2. Copy `deploy/sudoers_unicorn` to `/etc/sudoers.d/unicorn` (replace `<user>`; staging gets the same line with `unicorn-staging.service`), and check it with `visudo -c`. This lets the user restart and look at its own service, and nothing else.
3. In Virtualmin, "Web Configuration → Edit Directives" of the **SSL** site: paste `deploy/apache_directives.conf` (port 8002 on staging). Then `apachectl configtest && systemctl reload httpd`.
4. Check: `curl -fsS https://staging.unicorn.<domain>/healthz`. It answers `{"status": "ok"}` once cron runs (see "Cron, email and backups"); until then it names `jobs` and `daily`.

Done when the staging site works over HTTPS with its static files, and the user can run `sudo systemctl restart unicorn-staging.service`.

## Releases

Version tags look like `v0.9.0`. Each release adds a section to `CHANGELOG.md` in plain words. A release that carries an approved change to the hard frame names its ticket there, and an operator records it with `record_release` (P07.T06).

**The migration rule:** every migration must let the **previous** release still run. New columns are empty-able or have a default; a column is removed or renamed only one release later. That is what makes the automatic rollback safe.

**On staging first:**

1. `deploy/release.sh v0.9.0 unicorn-staging.service`. It remembers the current version, switches the code, installs the packages, makes a fresh backup, runs `check --deploy`, `migrate`, `createcachetable` and `collectstatic`, restarts the service, waits 5 seconds and asks `/healthz`. If anything fails it puts the old version back and says "Release failed, rolled back to <tag>". The database stays migrated.
2. Install `requirements-dev.txt` and run the tests against the staging test database: `~/venv/bin/pytest -q --reuse-db` (with `TEST_DATABASE_NAME` set in `~/.env`). If the test runner cannot use that database, write it in docs/12.
3. The founders or testers click through the main pages.
4. Go through `docs/security_checklist.md`.

**Then production:** `deploy/release.sh v0.9.0`, and write both releases in `docs/deploy_log.md`.

**To try the rollback** (on staging, once): `HEALTH_URL=https://staging.unicorn.<domain>/no-such-page deploy/release.sh v0.0.1 unicorn-staging.service` makes the health check fail on purpose; the old version must come back.

## Cron, email and backups

1. **Cron** for each virtual server's user: install `deploy/crontab.txt` (`crontab -e`, or "Scheduled Cron Jobs" in Virtualmin) after putting the operators' address in `MAILTO`. Staging gets the same lines without the backup line, until the owner decides otherwise. The box must be on Berlin time (T03 step 7).
2. **Email** through the box's Postfix:
   - DKIM on in Virtualmin ("Email Settings → DomainKeys Identified Mail"), and the DKIM record published in DNS;
   - SPF: `v=spf1 a mx -all` (or with the box's IP address);
   - DMARC: `v=DMARC1; p=quarantine; rua=mailto:<operators' address>`;
   - test with `deploy/manage.sh sendtestemail <an operator's address>`, and check that the message arrives in the inbox with DKIM passed.
3. **Backups:** follow "One-time setup" below; run `deploy/backup.sh` once by hand; then run the first restore test on staging. Until the second machine exists the backups stay only on the box, and `docs/deploy_log.md` says so **in capitals**. Choosing the second machine (in the EU) is an open question for the owner (docs/12).

Done when jobs run every minute, `daily` ran at 00:05, a login code arrives by email, and a backup exists and has been restore-tested.

## Watching the service

- **`/healthz`** answers `{"status": "ok"}`, or HTTP 503 with the names of the failed checks: `database`, `jobs` (the job runner has not finished a run in 5 minutes), `daily` (not run in 26 hours), `audit` (the last audit of the books found something), `backup` (production only: no backup in 26 hours). It never says more than the names. For the details, look at the logs and at the open-books page.
- **The uptime check** runs from the **second machine**, every 5 minutes, so it still works when the box is down: copy `deploy/uptime_check.sh` there and add
  `*/5 * * * * ~/uptime_check.sh https://unicorn.<domain> <operators' address>`. It emails the operators on the first failure and when the service recovers. No outside monitoring company is needed. It needs a command called `mail` on that machine.
- **Logs:** journald keeps gunicorn's logs for 30 days: in `/etc/systemd/journald.conf` set `SystemMaxUse=500M` and `MaxRetentionSec=30day`, then `systemctl restart systemd-journald` **(root)**. Apache's access logs are rotated weekly and kept for 2 weeks (Virtualmin "Log file rotation"), because they contain IP addresses.
- **Disk space:** `daily` emails the operators when the disk of `DISK_CHECK_PATH` (default `/home`) is more than 80 % full.
- **`/.well-known/security.txt`** shows `SECURITY_CONTACT` to people who find a security problem.
