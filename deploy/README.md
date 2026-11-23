# Putting Unicorn on the box: step by step

Written for the owner and the people who run the server. Nothing is installed from a repository. Unicorn uses what the box already has (checked with `deploy/check_programs.sh` on 2026-11-23: AlmaLinux 10.3, Python 3.12, MariaDB 10.11 tools, Apache with the proxy, headers and ssl modules, systemd, cron, flock, mail, git, Borg; SELinux off; time zone Berlin).

**Backups are yours** (Borg). Unicorn has no backup program. The section "Your backups" says what a backup must contain and what Unicorn needs from you.

## What changes on the box, in total

| Where | What | Step |
|---|---|---|
| Virtualmin | two virtual servers (staging, production), their databases and certificates | 1, 2 |
| Database | character set, time zone tables (if missing) | 3 |
| The site user's home | `~/unicorn.git`, `~/app`, `~/venv`, `~/.env`, `~/private_media`, `~/run`, `~/public_html/static` | 4–7 |
| `/etc/systemd/system/` | one service file per site | 8 |
| `/etc/sudoers.d/` | one small file per site | 9 |
| Apache (Virtualmin "Edit Directives") | the proxy lines | 10 |
| The site user's crontab | four lines | 11 |

**No program is installed.** The only things fetched from the internet are Unicorn's own Python libraries (Django and the like), by `pip`, into `~/venv`. Nothing outside the site user's home gets Python libraries.

## How to read the steps

- **[Mac]** your computer. **[site user]** logged in by SSH as the virtual server's user (the user Virtualmin made for the site). **[root]** logged in as the administrator. **[Virtualmin]** the Virtualmin web screens.
- `<domain>` is your domain, `<site user>` the Unix user of the site. Do **staging first**, then production (step 14).
- Each step ends with **Undo:** one line that puts it back.
- If a step does not give what it says under **You should see**, stop and send me the screen.

---

## Step 1 — [Virtualmin] The staging site

Create Virtual Server: name `staging.unicorn.<domain>`. Features on: **Apache website**, **SSL website**, **MariaDB database**, **Mail for domain** (only if mail should come from this name; DKIM needs it). Let it make its own Unix user and database. Write down the user name, the database name and the database password (Virtualmin shows them under "Edit Databases" and "Edit Users").

**You should see:** the site in the list of virtual servers, and Virtualmin's placeholder page at `http://staging.unicorn.<domain>/` once DNS works.

**Undo:** Virtualmin → select the server → *Delete Virtual Server*.

## Step 2 — [Virtualmin] DNS and the certificate

An A record (and AAAA if the box has IPv6) for `staging.unicorn.<domain>` pointing to the box. Then *Server Configuration → SSL Certificate → Let's Encrypt*: request it for the name, with automatic renewal. In *Web Configuration → Website Options*, "Redirect HTTP to HTTPS" on.

**You should see:** `https://staging.unicorn.<domain>/` shows the placeholder page, with a valid lock.

**Undo:** delete the DNS record, and *Server Configuration → SSL Certificate → Let's Encrypt* "Remove".

## Step 3 — [site user] The database

Open the database with the name and password from step 1:

```
mariadb -u <database user> -p <database name>
```

Run these three lines and look at the answers:

```
SELECT @@version, @@log_bin, @@log_bin_trust_function_creators, @@character_set_database;
SELECT CONVERT_TZ('2026-01-01 00:00:00','UTC','Europe/Berlin');
SHOW GRANTS;
```

What the answers must be:

1. `@@version`: 10.6 or newer.
2. `@@character_set_database`: `utf8mb4`. If it says something else: `ALTER DATABASE <database name> CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;` (the database is still empty; this only sets its defaults).
3. `CONVERT_TZ` gives `2026-01-01 01:00:00`. If it gives `NULL`, the time zone tables are not loaded. **[root]** once for the whole database server: `mariadb-tzinfo-to-sql /usr/share/zoneinfo | mariadb -u root mysql`.
4. `SHOW GRANTS` must include `TRIGGER` (or `ALL PRIVILEGES`). Virtualmin normally gives it.
5. If `@@log_bin` is `1` and `@@log_bin_trust_function_creators` is `0`: **[root]** add `log_bin_trust_function_creators = 1` under `[mysqld]` in `/etc/my.cnf.d/server.cnf` and run `systemctl restart mariadb`. Without it the append-only triggers cannot be created and the books are only protected by the program and the nightly audit.

**Undo:** the time zone tables and the setting do no harm; to take the setting out again, delete the line from `server.cnf` and restart MariaDB.

## Step 4 — [Mac] and [site user] The code gets to the box

The code travels by `git`, from your Mac to a bare repository in the site's home. No hosting service, no key to hand out.

**[site user]**

```
git init --bare ~/unicorn.git
```

**[Mac]**, in the Unicorn folder (the first time, tag the version that goes live):

```
git tag -a v0.0.1 -m "first install"
git remote add staging <site user>@staging.unicorn.<domain>:unicorn.git
git push staging main --tags
```

**[site user]**

```
git clone ~/unicorn.git ~/app
cd ~/app && git checkout --detach v0.0.1 && echo v0.0.1 > .version
```

**You should see:** the folder `~/app` with `manage.py` and `deploy/` in it, and `cat ~/app/.version` says `v0.0.1`.

**Undo:** **[site user]** `rm -rf ~/app ~/unicorn.git` (and **[Mac]** `git remote remove staging`).

## Step 5 — [site user] Python libraries, in the site's own folder

```
python3.12 -m venv ~/venv
~/venv/bin/pip install --upgrade pip
~/venv/bin/pip install -r ~/app/requirements-server.txt
mkdir -p ~/private_media ~/run ~/public_html/static && chmod 700 ~/private_media
```

`requirements-server.txt` has the pure-Python database driver PyMySQL instead of `mysqlclient`, because `mysqlclient` needs database development files that are not on the box. This takes a few minutes and about 700 MB; check `df -h ~` first (each site needs its own `~/venv`).

**You should see:** the last `pip` line ends with `Successfully installed ...`; and `~/venv/bin/python -c "import django, pymysql; print(django.__version__)"` prints `5.2.19`.

**Undo:** `rm -rf ~/venv`.

## Step 6 — [site user] The settings file, `~/.env`

```
cp ~/app/.env.example ~/.env && chmod 600 ~/.env
```

Make four secrets (each command prints one value; copy it on your screen, nothing is saved):

```
~/venv/bin/python -c "import secrets; print(secrets.token_urlsafe(50))"
~/venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
~/venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
~/venv/bin/python -c "import secrets; print(secrets.token_hex(8))"
```

They are, in order: `SECRET_KEY`, `UNICORN_MASTER_KEY`, `UNICORN_HMAC_KEY` and `ADMIN_PATH`. Open `~/.env` (`nano ~/.env`) and set:

```
SECRET_KEY=<the first value>
DEBUG=False
ALLOWED_HOSTS=staging.unicorn.<domain>
SITE_URL=https://staging.unicorn.<domain>
DATABASE_URL=mysql://<database user>:<database password>@127.0.0.1:3306/<database name>
UNICORN_MASTER_KEY=<the second value>
UNICORN_HMAC_KEY=<the third value>
ADMIN_PATH=<the fourth value>
EMAIL_URL=smtp://localhost:25
DEFAULT_FROM_EMAIL=no-reply@staging.unicorn.<domain>
SERVER_EMAIL=unicorn@staging.unicorn.<domain>
ADMIN_EMAILS=<your email address>
SECURITY_CONTACT=<your email address>
SOURCE_URL=<the public address of the source code, if there is one yet; else leave it empty>
SECURE_HSTS_SECONDS=3600
STATIC_ROOT=/home/<site user>/public_html/static
PRIVATE_MEDIA_ROOT=/home/<site user>/private_media
DISK_CHECK_PATH=/home/<site user>
REQUIREMENTS_FILE=requirements-server.txt
```

If the database password has characters like `@`, `/`, `:` or `#`, write them as `%40`, `%2F`, `%3A`, `%23` in `DATABASE_URL`.

**Write the master key and the HMAC key into your password manager now, and into a second place** (another person's manager, or a printed sheet in a safe). **Losing the master key means losing every member's personal data, and nobody can get it back.** The keys must not be only in the same place as your database backup.

**You should see:** `ls -l ~/.env` shows `-rw-------`.

**Undo:** `rm ~/.env`. Only do this before step 7: afterwards the master key is needed to read the data.

## Step 7 — [site user] First setup (once)

```
~/app/deploy/first_setup.sh
```

It makes the tables, the cache table, loads the contracts, collects the static files, loads the democratic defaults and checks the settings. It is run **once**. Later releases never run it again.

**You should see:** a long list of `Applying ... OK`, and at the end `First setup done.` Warnings from `check --deploy` named `security.W005` and `security.W021` are expected and kept on purpose; any line that says `ERROR` is not.

**Undo:** Virtualmin → *Edit Databases* → delete the database and create it again empty (set the character set as in step 3), and `rm -rf ~/public_html/static/*`.

## Step 8 — [root] The service that runs Unicorn

```
SITE_USER=<site user>
sed -e "s/<user>/$SITE_USER/g" -e "s/8001/8002/" /home/$SITE_USER/app/deploy/unicorn.service > /etc/systemd/system/unicorn-staging.service
systemctl daemon-reload && systemctl enable --now unicorn-staging
systemctl status unicorn-staging --no-pager
```

(Staging uses port 8002; production uses 8001 and the file name `unicorn.service`, see step 14.)

**You should see:** `Active: active (running)`. And, as a check from the box:

```
curl -s -H "X-Forwarded-Proto: https" -H "Host: staging.unicorn.<domain>" http://127.0.0.1:8002/healthz
```

answers `{"status": "fail", "checks": ["jobs", "daily"]}`. That is right for now: cron does not run yet (step 11).

**Undo:** `systemctl disable --now unicorn-staging && rm /etc/systemd/system/unicorn-staging.service && systemctl daemon-reload`

## Step 9 — [root] Let the site user restart its own service

```
SITE_USER=<site user>
sed -e "s/<user>/$SITE_USER/g" -e "s/unicorn.service/unicorn-staging.service/g" /home/$SITE_USER/app/deploy/sudoers_unicorn > /etc/sudoers.d/unicorn-staging
chmod 440 /etc/sudoers.d/unicorn-staging && visudo -c
```

**You should see:** `visudo -c` ends with `parsed OK`, and as the site user `sudo /usr/bin/systemctl status unicorn-staging.service` works without a password. The line lets the user only restart and look at this one service, nothing else.

**Undo:** `rm /etc/sudoers.d/unicorn-staging`

## Step 10 — [Virtualmin] Apache sends the pages to Unicorn

*Services → Configure Website → Edit Directives*, for the **SSL** website (the one on port 443). Paste the lines of `deploy/apache_directives.conf`, with `8001` changed to `8002` (staging), and save. Then **[root]**: `apachectl configtest && systemctl reload httpd`.

**You should see:** `Syntax OK`, and `curl -s https://staging.unicorn.<domain>/healthz` answers `{"status": "fail", "checks": ["jobs", "daily"]}`; the home page opens in the browser with its styles.

**Undo:** remove the pasted lines in *Edit Directives* and save; `systemctl reload httpd`.

## Step 11 — [site user] Cron: the jobs, the daily work, the monthly close

```
crontab -l                       # look at what is there; keep it
sed 's/operators@example.org/<your email address>/' ~/app/deploy/crontab.txt > /tmp/unicorn.cron
(crontab -l 2>/dev/null; cat /tmp/unicorn.cron) | crontab - && rm /tmp/unicorn.cron
crontab -l
```

Then once by hand, so that you do not wait for midnight: `~/app/deploy/manage.sh daily`.

The box is on Berlin time, so the lines (daily at 00:05, close on the 1st at 00:15) are right as they are.

**You should see:** after two minutes, `curl -s https://staging.unicorn.<domain>/healthz` answers `{"status": "ok"}`.

**Undo:** `crontab -e` and delete the lines that start with `MAILTO`, `* * * * *`, `5 0`, `15 0`.

## Step 12 — Email

1. **[Virtualmin]** *Email Settings → DomainKeys Identified Mail* on; publish the DKIM record it shows in DNS.
2. In DNS, a TXT record with the SPF text `v=spf1 a mx -all`, and a TXT record `_dmarc` with `v=DMARC1; p=quarantine; rua=mailto:<your email address>`.
3. **[site user]** `~/app/deploy/manage.sh sendtestemail <your email address>`

**You should see:** the message in your inbox (not spam); in "show original" `dkim=pass`.

**Undo:** remove the DNS records.

## Step 13 — [Mac] and [site user] A release, and the rollback

The way every new version gets onto a site (staging first):

1. **[Mac]** make the change, tag it, and push: `git tag -a v0.0.2 -m "test" && git push staging main --tags`
2. **[site user]** `BACKUP_DONE=1 ~/app/deploy/release.sh v0.0.2 unicorn-staging.service`
   (Make your Borg backup first and add `BACKUP_DONE=1`, or let `~/before_release.sh` do it for you; see "Your backups".)

   It remembers the current version, switches the code, installs the libraries, runs `check --deploy`, `migrate`, `createcachetable` and `collectstatic`, restarts the service, waits 5 seconds and asks `/healthz`. If anything goes wrong it puts the old version back and says `Release failed, rolled back to <tag>`; the database stays migrated, which is safe because every migration lets the previous release still run.
3. **Try the rollback once, on staging:**
   `BACKUP_DONE=1 HEALTH_URL=https://staging.unicorn.<domain>/no-such-page ~/app/deploy/release.sh v0.0.2 unicorn-staging.service`
   makes the health check fail on purpose.
4. The founders or testers click through the main pages. Go through `docs/security_checklist.md`.
5. Write the release in `docs/deploy_log.md`.

**You should see:** after step 2 `Released v0.0.2.`; after step 3 `Release failed, rolled back to ...` and the site still works.

**Undo:** `BACKUP_DONE=1 ~/app/deploy/release.sh <the earlier tag> unicorn-staging.service`

## Step 14 — Production

Repeat steps 1 to 13 for `unicorn.<domain>`. What is different:

| | Staging | Production |
|---|---|---|
| Name | `staging.unicorn.<domain>` | `unicorn.<domain>` |
| Git remote on the Mac | `staging` | `production` (`git remote add production <site user>@unicorn.<domain>:unicorn.git`) |
| Port | 8002 | 8001 |
| Service file | `unicorn-staging.service` | `unicorn.service` (no `sed` for the port) |
| Sudoers | `unicorn-staging.service`, file `unicorn-staging` | `unicorn.service`, file `unicorn` (no second `sed`) |
| `~/.env` | its own keys | its own, **different** keys |
| `release.sh` | `release.sh <tag> unicorn-staging.service` | `release.sh <tag>` |

A release goes to production only after it has run well on staging.

**Undo:** the same undo lines, one step at a time, for the production names.

---

## Your backups

Made by you with Borg; Unicorn does not touch them. A backup of one site must contain:

1. **A dump of the database:** `mariadb-dump --single-transaction --routines --triggers --hex-blob --default-character-set=utf8mb4 -u <database user> -p <database name> > ~/unicorn.sql` (or with your own login file), taken by your backup job.
2. **The private files:** `~/private_media`.
3. **The keys**, kept **apart** from the rest: the master key and the HMAC key from `~/.env`. Without the master key a restored database cannot be read; with it next to the database backup, whoever has the backup can read everything.

And these rules:

- The Borg repository is encrypted, and a copy lies on another machine in the EU.
- Write the retention (how many daily and monthly copies) in `docs/privacy/records_of_processing.md`.
- **Before every release** a fresh backup. Either make it yourself and run `release.sh` with `BACKUP_DONE=1`, or put your Borg command in an executable file `~/before_release.sh`: `release.sh` runs it first, and releases nothing if it fails.
- **Optional:** if your backup job's last line is `date -u +%Y-%m-%dT%H:%M:%SZ > ~/run/last_backup` and `BACKUP_EXPECTED=True` is in `~/.env`, `/healthz` also goes red when no backup was made for 26 hours.

### The monthly restore test

A backup that was never restored is only a hope. Once a month, on staging (never on production), restore the newest backup into a **separate database** and look at it. Then write the result into production, so that the open-books page shows it:

```
~/app/deploy/manage.sh record_restore_test --ok --backup-date 2027-03-01 --notes "all fine"
```

Use `--failed` and write the reasons in `--notes` when it failed. A failed test is urgent. If there has been no good test for 35 days, a ticket goes to the elected auditors.

### After a restore (a test or a disaster)

Before anybody uses a restored database (for a test, put `DATABASE_NAME_OVERRIDE=<the restored database>` in the site's `.env` for the time of the test):

1. `deploy/manage.sh reapply_deletions` — people who were deleted since the backup stay deleted (the backup still has their email and name).
2. `deploy/manage.sh audit_books --full` — the books are in order from the first transaction.
3. `deploy/manage.sh compare_fingerprints --published published.json` — with the JSON from the open-books page (or a copy you saved). Every published fingerprint up to the last restored transaction must match.

In a disaster: a new box, steps 1 to 11 with the **same `~/.env` secrets** from your sealed copy, then restore the database and `~/private_media` from Borg, then the three lines above. Tell the members what happened and how much was lost, on the home page and by email. Targets: at most one day of data lost, service back within one day.

## Watching the service

- **`/healthz`** answers `{"status": "ok"}`, or HTTP 503 with the names of the checks that failed: `database`, `jobs` (the job runner has not finished a run in 5 minutes), `daily` (not run in 26 hours), `audit` (the last audit of the books found something), `backup` (only if you turned it on). It never says more than the names; for the details look at the logs and the open-books page.
- **The uptime check** emails you on the first failure and when the service is back: add to the site user's crontab
  `*/5 * * * * ~/app/deploy/uptime_check.sh https://unicorn.<domain> <your email address>`.
  Run from the same box it tells you when Unicorn is down but not when the whole box is down. For that, run the same line from any other machine that has `curl` and `mail` (copy the file `deploy/uptime_check.sh` there).
- **Logs:** **[root]** in `/etc/systemd/journald.conf` set `SystemMaxUse=500M` and `MaxRetentionSec=30day`, then `systemctl restart systemd-journald`; in Virtualmin set the Apache log rotation to weekly, keeping 2 weeks (they hold IP addresses).
- **Disk space:** the `daily` job emails you when the disk of `DISK_CHECK_PATH` is more than 80 % full.
- **`/.well-known/security.txt`** shows `SECURITY_CONTACT` to anyone who finds a security problem.

## When something does not work

| You see | Probably | Do |
|---|---|---|
| `pip` stops with `error: ... mysql.h` | the list `requirements.txt` was used instead of `requirements-server.txt` | `~/venv/bin/pip install -r ~/app/requirements-server.txt` |
| The page says "Bad Request (400)" | `ALLOWED_HOSTS` does not name this site | fix it in `~/.env`, restart the service |
| `/healthz` says `jobs` or `daily` | cron does not run | step 11; look at `crontab -l` and your mail |
| `/healthz` says `audit` | the audit of the books found something | open the open-books page; do not release anything; send me the text |
| The styles are missing | Apache does not serve `/static/` | step 10 (the `ProxyPass /static/ !` line), and check `ls ~/public_html/static` is filled |
| `release.sh` says "Make your backup first" | it wants a backup | make it, then `BACKUP_DONE=1` |

Write every step you take, with the date, in `docs/deploy_log.md` (never a secret).
