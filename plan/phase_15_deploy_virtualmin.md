# Phase 15 — Running Unicorn on the Virtualmin box

**Goal:** Unicorn runs on the owner's Virtualmin server (AlmaLinux, Apache, MariaDB), with a staging copy and production. Releases are tested on staging first. Cron runs the jobs, the daily work and the monthly close. Email reaches people's inboxes. Backups go off-site and are restore-tested. The founders can launch.
**Read first:** docs/09 sections 3–4; docs/08 section 6; plan/phase_14_security_privacy.md T09 (backups).

**For the founders' pilot,** do T01–T07 right after phase 09 and P14's pilot tasks (T01, T03, T04, T06–T09; see PLAN.md). The steps marked **(root)** need the server's administrator: the owner, or an operator the owner trusts. Write every step you do, its date and anything unexpected in `docs/deploy_log.md`. Never write secrets into that file.

---

### - [ ] P15.T01 — Check the server

*Status 2026-11-23: the files and the written steps are in the repository; the steps on the server itself have not been done yet (they need the box and its administrator). See docs/deploy_log.md.*

**Files:** `deploy/check_server.sh`, `docs/deploy_log.md`

**Do:**
1. **`deploy/check_server.sh`** only reads and changes nothing. It prints:
   - the operating system: `cat /etc/almalinux-release`;
   - the database: `mariadb --version` (or `mysql --version`), and from the database `SELECT @@version, @@log_bin, @@log_bin_trust_function_creators, @@character_set_server, @@innodb_file_per_table;`;
   - whether the time zone tables are loaded: `SELECT CONVERT_TZ('2026-01-01 00:00:00','UTC','Europe/Berlin');` (NULL means no);
   - Apache: `httpd -v`, and whether `httpd -M` lists `proxy_module`, `proxy_http_module`, `headers_module` and `ssl_module`;
   - Python: `python3.12 --version`, if installed;
   - SELinux: `getenforce`;
   - time: `timedatectl` (the clock must be synchronised);
   - space: `df -h /home`, `free -m`, `nproc`.
2. **What the answers mean.** Write them in `docs/deploy_log.md`:

   | Check | Needed | If not |
   |---|---|---|
   | AlmaLinux | 8.10 or 9.x | ask the owner (docs/12) |
   | MariaDB | 10.6 or newer (10.11 or 11.4 recommended) | 10.5 still works: Django 5.2 supports it, and the job runner falls back without "skip locked" (P00.T06). Upgrading to 10.11 is an owner decision, after a full backup (docs/12) |
   | Time zone tables | loaded | T03 step 5 |
   | Apache modules | all four | `dnf install mod_ssl`; the proxy and headers modules come with `httpd` |
   | SELinux | `Disabled` or `Permissive`, or `Enforcing` with T03 step 6 | T03 step 6 |
   | Free space | at least 10 GB in `/home` | ask the owner |
   | Location | the box is in the EU/EEA (the owner answers) | open question in docs/12 |

**Done when:** `docs/deploy_log.md` has the answers and lists what T02–T03 must change.

---

### - [ ] P15.T02 — Install the packages (root)

*Status 2026-11-23: the files and the written steps are in the repository; the steps on the server itself have not been done yet (they need the box and its administrator). See docs/deploy_log.md.*

**Files:** `docs/deploy_log.md`

**Do:**
1. **Install:**

   ```
   dnf install -y epel-release
   dnf install -y python3.12 python3.12-devel gcc git pkgconf-pkg-config mariadb-connector-c-devel age
   ```

   - If MariaDB comes from the official MariaDB repository instead of AlmaLinux, the development package is called `MariaDB-devel`.
   - If `age` is not available, `gnupg2` is used instead (P14.T09).
2. **Check that the database driver builds:**

   ```
   python3.12 -m venv /tmp/check && /tmp/check/bin/pip install mysqlclient && rm -rf /tmp/check
   ```

**Done when:** the driver builds, and the versions are in the deploy log.

---

### - [ ] P15.T03 — Virtual servers, databases, certificates (root)

*Status 2026-11-23: the files and the written steps are in the repository; the steps on the server itself have not been done yet (they need the box and its administrator). See docs/deploy_log.md.*

**Files:** `docs/deploy_log.md`

**Do:**
1. **Two virtual servers** in Virtualmin ("Create Virtual Server"):
   - `unicorn.<domain>` (production) and `staging.unicorn.<domain>` (staging; the founders' pilot runs here first);
   - features: Apache website, SSL website, MariaDB database, and mail for the domain (needed for DKIM, T07);
   - each has its own Unix user, home folder and database.
2. **DNS:** A (and AAAA, if the box has IPv6) records for both names.
3. **Certificates:** "Server Configuration → SSL Certificate → Let's Encrypt" for each, with automatic renewal. Also tick "Redirect HTTP to HTTPS".
4. **Databases:**
   - set the character set of each: `ALTER DATABASE <db> CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`;
   - on staging, also create `<staging user>_test` (for the tests, T06) and `<staging user>_restore` (for the restore test, P14.T09);
   - the virtual server's database user needs all rights on its own databases, including `TRIGGER`. Virtualmin normally grants them; check with `SHOW GRANTS`.
   - If `@@log_bin` is ON, add `log_bin_trust_function_creators = 1` under `[mysqld]` in `/etc/my.cnf.d/server.cnf` and restart MariaDB. Without it, the append-only triggers cannot be created, and P02.T05's fallback (model guards plus the nightly audit) is all that protects the books.
5. **Time zone tables** (once for the database server):

   ```
   mariadb-tzinfo-to-sql /usr/share/zoneinfo | mariadb -u root mysql
   ```

   (`mysql_tzinfo_to_sql` and `mysql` are the older names of the same tools.)
6. **SELinux:** if `getenforce` says `Enforcing`, allow Apache to connect to gunicorn: `setsebool -P httpd_can_network_connect 1`.

**Done when:** both sites show Virtualmin's placeholder page over HTTPS, the time zone check is not NULL, and `SHOW GRANTS` includes `TRIGGER`.

---

### - [ ] P15.T04 — The app, its settings and its files

*Status 2026-11-23: the files and the written steps are in the repository; the steps on the server itself have not been done yet (they need the box and its administrator). See docs/deploy_log.md.*

**Read:** docs/09 section 3, items 4–5.
**Files:** `deploy/manage.sh`, `deploy/first_setup.sh`, `.env.example` (the production variables), `unicorn/settings.py` (`STATIC_ROOT`, `PRIVATE_MEDIA_ROOT`, `UNICORN_VERSION` and `TEST_DATABASE_NAME` from the environment)

**Do:**
1. **Get the code**, as the virtual server's user (not root). Use a read-only deploy key for the repository; where the repository lives is an open question in docs/12.

   ```
   cd ~ && git clone <repository URL> app && cd app && git checkout <tag>
   python3.12 -m venv ~/venv
   ~/venv/bin/pip install --upgrade pip && ~/venv/bin/pip install -r requirements.txt
   mkdir -p ~/private_media ~/backups ~/run && chmod 700 ~/private_media ~/backups
   ```

2. **`~/.env`** (chmod 600, outside the code and the web root) has every variable of `.env.example`:
   - `DEBUG=False`, `ALLOWED_HOSTS`, `SITE_URL`, `DATABASE_URL`;
   - `SECRET_KEY`, `UNICORN_MASTER_KEY`, `UNICORN_HMAC_KEY`, made with the commands in `.env.example` (or `generate_keys` once P14.T05 exists);
   - `EMAIL_URL=smtp://localhost:25`, `DEFAULT_FROM_EMAIL=no-reply@<site host>`, `ADMINS`, `SECURITY_CONTACT`;
   - `ADMIN_PATH` (a random path), `SOURCE_URL`, `SECURE_HSTS_SECONDS=3600`;
   - `STATIC_ROOT=/home/<user>/public_html/static`, `PRIVATE_MEDIA_ROOT=/home/<user>/private_media`;
   - on staging also `TEST_DATABASE_NAME=<staging user>_test`.
3. **The keys are written down twice.** Two operators keep the master key and the HMAC key in their password managers. Losing the master key means losing every member's personal data, and no one can recover it.
4. **`deploy/manage.sh`**, used by cron and by operators:

   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   export UNICORN_ENV_FILE="$HOME/.env"
   cd "$HOME/app"
   exec "$HOME/venv/bin/python" manage.py "$@"
   ```

5. **`deploy/first_setup.sh`**, run once per virtual server: `migrate`, `createcachetable`, `collectstatic --noinput`, `load_defaults`, and `check --deploy`. On later releases, `load_defaults` is never run again, because parameters then change only through tickets (P07.T05).
6. **Settings:** `UNICORN_VERSION` comes from the file `.version` in the code folder (written by the release script, git-ignored), or `"dev"`. `DATABASES["default"]["TEST"]["NAME"]` comes from `TEST_DATABASE_NAME` when it is set.

**Done when:** `deploy/manage.sh check --deploy` prints no errors on staging.

---

### - [ ] P15.T05 — gunicorn and the Apache proxy (root)

*Status 2026-11-23: the files and the written steps are in the repository; the steps on the server itself have not been done yet (they need the box and its administrator). See docs/deploy_log.md.*

**Files:** `deploy/unicorn.service`, `deploy/apache_directives.conf`, `deploy/sudoers_unicorn`, `deploy/README.md`

**Do:**
1. **`deploy/unicorn.service`**, a template. Copy it to `/etc/systemd/system/unicorn.service` for production, and as `unicorn-staging.service` with port 8002 for staging:

   ```
   [Unit]
   Description=Unicorn web app (gunicorn)
   After=network.target mariadb.service

   [Service]
   User=<user>
   Group=<user>
   WorkingDirectory=/home/<user>/app
   Environment=UNICORN_ENV_FILE=/home/<user>/.env
   ExecStart=/home/<user>/venv/bin/gunicorn unicorn.wsgi:application --bind 127.0.0.1:8001 --workers 3 --timeout 60 --max-requests 1000 --max-requests-jitter 100
   Restart=on-failure
   RestartSec=5
   NoNewPrivileges=true
   PrivateTmp=true

   [Install]
   WantedBy=multi-user.target
   ```

   Then `systemctl daemon-reload && systemctl enable --now unicorn`.
2. **Restarting without root:** `deploy/sudoers_unicorn`, copied to `/etc/sudoers.d/unicorn` and checked with `visudo -c`, lets the user only restart and query its own service:

   ```
   <user> ALL=(root) NOPASSWD: /usr/bin/systemctl restart unicorn.service, /usr/bin/systemctl status unicorn.service
   ```

   Staging gets the same line for its own user and `unicorn-staging.service`.

3. **Apache:** in Virtualmin, "Web Configuration → Edit Directives" of the SSL site, add `deploy/apache_directives.conf`:

   ```
   ProxyPreserveHost On
   ProxyPass /.well-known/acme-challenge/ !
   ProxyPass /static/ !
   ProxyPass / http://127.0.0.1:8001/ timeout=60
   ProxyPassReverse / http://127.0.0.1:8001/
   RequestHeader set X-Forwarded-Proto "https"
   LimitRequestBody 12582912
   ```

   - The `acme-challenge` line keeps the Let's Encrypt renewals working.
   - `/static/` is served by Apache from `public_html/static`.
   - `private_media` is outside `public_html`, so Apache never serves it.
   - Then `apachectl configtest && systemctl reload httpd`.
4. **Check:** `curl -fsS https://staging.unicorn.<domain>/healthz` returns `{"status": "ok"}`.

**Done when:** the staging site works over HTTPS with its static files, and the user can restart the service.

---

### - [ ] P15.T06 — Releases: staging first, then production

*Status 2026-11-23: the files and the written steps are in the repository; the steps on the server itself have not been done yet (they need the box and its administrator). See docs/deploy_log.md.*

**Read:** P07.T06 (hard-frame releases).
**Files:** `deploy/release.sh`, `CHANGELOG.md`, `deploy/README.md`

**Do:**
1. **Version tags** look like `v0.9.0`. Each release adds a section to `CHANGELOG.md` in plain words. A release that carries an approved hard-frame change names its ticket (`T-…`) in the changelog, and the operator records it with the action `record_release` (P07.T06).
2. **`deploy/release.sh <tag> [service]`**, run as the virtual server's user (`set -euo pipefail`; the service defaults to `unicorn.service`, and staging passes `unicorn-staging.service`):
   1. remember the current tag;
   2. `git fetch --tags` and `git checkout --detach <tag>`, then write the tag to `.version`;
   3. `pip install -r requirements.txt`;
   4. run `deploy/backup.sh` (a fresh backup before any migration);
   5. `deploy/manage.sh check --deploy`, `migrate --noinput`, `createcachetable`, `collectstatic --noinput`;
   6. `sudo /usr/bin/systemctl restart <service>`;
   7. wait 5 seconds and fetch `/healthz`. If it fails, check out the previous tag, reinstall, restart, and print "Release failed, rolled back to <tag>". The database stays migrated, which is safe because of the migration rule below.
3. **The migration rule** (CLAUDE.md, "Database"): every migration must let the previous release still run. New columns are nullable or have a default; a column is removed or renamed only one release later.
4. **On staging, before production:**
   - `release.sh <tag>`;
   - install `requirements-dev.txt` and run `~/venv/bin/pytest -q --reuse-db` against the staging test database (MariaDB). If the test runner cannot use that database, write it in docs/12 for the owner;
   - the founders or testers click through the main pages;
   - the security checklist (P14.T13), once that phase exists.
5. **Then on production:** `release.sh <tag>`.

**Done when:** a test release `v0.0.1` goes through staging and production, and the rollback works when `/healthz` is made to fail on purpose (on staging).

---

### - [ ] P15.T07 — Cron, email and backups

*Status 2026-11-23: the files and the written steps are in the repository; the steps on the server itself have not been done yet (they need the box and its administrator). See docs/deploy_log.md.*

**Read:** docs/09 section 3, item 7; P14.T09.
**Files:** `deploy/crontab.txt`, `deploy/README.md`, `docs/deploy_log.md`

**Do:**
1. **Cron** for each virtual server's user ("Scheduled Cron Jobs" in Virtualmin, or `crontab -e`), from `deploy/crontab.txt`:

   ```
   MAILTO=<operators' address>
   * * * * *  flock -n ~/run/jobs.lock ~/app/deploy/manage.sh run_jobs --max-seconds 55
   5 0 * * *  flock -n ~/run/daily.lock ~/app/deploy/manage.sh daily
   15 0 1 * * flock -n ~/run/close.lock ~/app/deploy/manage.sh close_period
   30 2 * * *  flock -n ~/run/backup.lock ~/app/deploy/backup.sh
   ```

   The times are the server's local time: set the box to `Europe/Berlin`, or shift the lines to match. Staging gets the same lines without the backup line, until the owner decides otherwise.
2. **Email** through the box's Postfix:
   - DKIM on in Virtualmin ("Email Settings → DomainKeys Identified Mail"), and the DKIM record published in DNS;
   - SPF: `v=spf1 a mx -all` (or with the box's IP address);
   - DMARC: `v=DMARC1; p=quarantine; rua=mailto:<operators' address>`;
   - test with `deploy/manage.sh sendtestemail <operator's address>`, and check that the message arrives in the inbox with DKIM passed.
3. **Backups:**
   - put the `age` public key in `~/backup_recipient.txt`, and set `BACKUP_TARGET` and the restricted SSH key for the second machine (P14.T09);
   - run `deploy/backup.sh` once by hand, and then the first restore test on staging (P14.T09);
   - until the second machine exists, the backups stay only on the box, and the deploy log says so in capitals. Choosing the second machine (in the EU) is an open question for the owner.

**Done when:** jobs run every minute, `daily` ran at 00:05, a login code arrives by email, and a backup exists and has been restore-tested.

---

### - [x] P15.T08 — Watching the service

**Files:** `apps/core/views.py` (`/healthz`), `apps/members/models.py` (SiteState: `last_jobs_run_at`, `last_daily_at`), `deploy/uptime_check.sh`, `deploy/README.md`, `apps/core/tests/test_healthz.py`

**Do:**
1. **`/healthz`** also checks:
   - the job runner finished a run in the last 5 minutes (`run_jobs` writes `SiteState.last_jobs_run_at`);
   - `daily` ran in the last 26 hours (`SiteState.last_daily_at`);
   - the last book audit is OK (P02.T07);
   - `~/run/last_backup` is less than 26 hours old (production only, `BACKUP_EXPECTED=True` in `.env`).

   It answers `{"status": "ok"}`, or HTTP 503 with `{"status": "fail", "checks": [<names of the failed checks>]}`. It never gives details beyond the names.
2. **The uptime check** runs from the second machine every 5 minutes (`deploy/uptime_check.sh`: `curl -fsS --max-time 20 <site>/healthz`, and an email to the operators on the first failure and on recovery). No outside monitoring company is needed.
3. **Logs:**
   - journald keeps gunicorn's logs for 30 days (`SystemMaxUse` and `MaxRetentionSec=30day` in `/etc/systemd/journald.conf`, root);
   - Apache's access logs are rotated weekly and kept for 2 weeks (Virtualmin "Log file rotation"), because they contain IP addresses. Write both times in the data map (P14.T01).
4. **Disk space:** `daily` warns the operators by email when `/home` is more than 80% full.

**Tests:** `/healthz` fails with `jobs` when no runner has run for 6 minutes (`freezegun`).

---

### - [x] P15.T09 — The founders' launch

**Read:** docs/00 ("How Unicorn starts: inside capitalism"); docs/02 section 5; P01.T05–T06; P03.T01; P08.T02; P11.T01.
**Files:** `apps/core/management/commands/launch_check.py`, `docs/launch_checklist.md`, `apps/core/tests/test_launch_check.py`

**Do:**
1. **`launch_check`** prints a table of OK, WARN and FAIL lines:
   - the defaults are loaded, and no parameter differs from `config/defaults.yaml` without a `ParameterChange`;
   - the contracts (membership, holder agreement, council rules, mandate, assist consent, outside seller) have current versions, with a WARN while any still says "DRAFT";
   - the legal pages are filled in (WARN while "DRAFT" or `<to fill in>` remains, P14.T07);
   - `bootstrap_founders` has run, and every founder has been checked in person by two others (P01.T05);
   - the coordination unit exists (P03.T01), and the starter services of `sectors.starter_services` are shown on the needs board;
   - the first plan referendum has been started (P11.T01; before phase 11, the founders' meeting adopts the defaults and records it in the deploy log);
   - the trial year is on in `SiteState` (P01.T06);
   - at least two founders are active holders with signed holder agreements (P08.T02);
   - the ECB rates were fetched today (P08.T01);
   - last night's backup exists, and a restore test is less than 35 days old;
   - `scripts/hf_coverage.py` shows no MISSING;
   - `check --deploy` is clean.
2. **`docs/launch_checklist.md`** gives the founders' meeting its order of business, in plain words:
   1. sign the statute, and register the association;
   2. sign the digital contract in the app;
   3. verify each other in person;
   4. choose two holders and two operators;
   5. adopt the default plan;
   6. open the coordination unit and the first services;
   7. agree when the trial year ends.

**Tests:** `launch_check` reports FAIL on an empty database and OK on a fully set-up test database.

---

### - [ ] P15.T10 — Every hard-frame rule is tested

**Files:** `scripts/hf_coverage.py`, any test files that are missing

**Do:**
1. Run `scripts/hf_coverage.py`. For every rule shown as MISSING, write the missing test, named `test_hf<NN>_…`, in the app where the rule is enforced (docs/01 section 1, column "where").
2. Make the script exit with code 1 when anything is MISSING, and add it to `make check`.

**Done when:** `make check` passes, and `scripts/hf_coverage.py` lists at least one test for each of HF-1 to HF-20.

---

## Acceptance check for phase 15

1. Staging and production run over HTTPS on the Virtualmin box, with static files, cron, email and backups.
2. A release goes to staging, passes the tests on MariaDB, and then goes to production. A failed release rolls back by itself.
3. The uptime check emails the operators when `/healthz` fails.
4. `launch_check` shows no FAIL.
5. `scripts/hf_coverage.py` shows no MISSING, and `make check` runs it.
6. Add a line to PLAN.md "Progress".
