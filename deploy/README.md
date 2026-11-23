# Putting Unicorn on your Virtualmin box: step by step

For the owner. The rule for this guide: **nothing is changed on the server itself.** No program is installed, nothing is added to systemd, no sudo rule, no Apache or Virtualmin setting. Everything happens in two places you said you are happy to use:

1. **Your virtual servers in Virtualmin** (the new domain, and a sub-server for staging), made with your usual defaults, plus the **cron jobs** of the site's user (Virtualmin → *Scheduled Cron Jobs*).
2. **The site's own folder in the user's home**, which Unicorn fills with its own files.

The box was checked with `deploy/check_programs.sh` on 2026-11-23: AlmaLinux 10.3, Python 3.12, MariaDB 10.11 tools, Apache with the proxy, headers and ssl modules, cron, flock, mail, git, Borg; time zone Berlin. Backups are yours (Borg): see "Your backups".

## How it works, in four lines

- **Unicorn runs as an ordinary program of the site's user** (gunicorn, listening only on `127.0.0.1` on a port of its own). A small script, `run_site.sh`, starts it, and a cron job every minute starts it again if it is not running (after a reboot or a crash). That cron job replaces systemd.
- **Apache sends the pages to Unicorn** through a file in the site's own web folder, `.htaccess`. It also leaves the Let's Encrypt checks and the static files to Apache. That file replaces the Apache settings.
- **The site's folder** (`~/unicorn` for production, `~/unicorn-staging` for staging) holds everything of one site: `app/` (the code), `venv/` (its Python libraries), `.env` (its secrets), `run/`, `private_media/`. A sub-server shares the Unix user of its parent, so the two sites sit side by side in separate folders, with the same `~`.
- **A release** is: tag on your Mac, `git push`, and `release.sh` on the box. It asks you for a backup first, and puts the old version back by itself if the new one does not answer `/healthz`.

## What this changes, in total

| Where | What | Step |
|---|---|---|
| Virtualmin | a virtual server for the domain and a sub-server for staging (your defaults), their databases and certificates | 2, 3 |
| The user's home | two site folders, and in each web folder a `.htaccess` and a folder `static/` | 5–10 |
| Virtualmin → Scheduled Cron Jobs | four jobs per site | 11 |
| Everything else | **nothing** | |

The only things fetched from the internet are Unicorn's Python libraries (Django and the like), by `pip`, into the site's own `venv/`.

## How to read the steps

- **[Mac]** your computer. **[site user]** logged in by SSH as the Unix user of the virtual server. **[Virtualmin]** the Virtualmin web screens. **[registrar]** where you register the domain.
- `<domain>` is the new domain, `<box host>` the name you use to log in to the box.
- **Start every SSH session** with these lines for the site you work on, and check what they print:

  ```
  # staging:
  SITE=$HOME/unicorn-staging;  WEB=$HOME/domains/staging.<domain>/public_html
  # production (instead):
  SITE=$HOME/unicorn;          WEB=$HOME/public_html
  echo "$SITE"; ls -d "$WEB"
  ```

  If the last line says "No such file", find the folder with `ls -d ~/domains/*/public_html ~/public_html` (Virtualmin shows it too, under *Virtual Server Details*) and use that.
- Each step ends with **Undo:** one line that puts it back.
- If a step does not give what it says under **You should see**, stop and send me the screen.

---

## Step 1 — [registrar] The domain

Register the domain for Unicorn. Point it at the box the way you do for your other domains: an A record (and AAAA if the box has IPv6) for `<domain>` and for `staging.<domain>`, to the box's address; or give the registrar the box's name servers if you let Virtualmin do the DNS.

**You should see:** after a while, `ping <domain>` answers with the box's address.

**Undo:** delete the DNS records.

## Step 2 — [Virtualmin] The virtual server for the domain (production)

*Create Virtual Server*: name `<domain>`, your usual template, the default features (website, SSL website, MariaDB database, mail). Change no setting. Then *Server Configuration → SSL Certificate → Let's Encrypt*: request a certificate for `<domain>` (and `www.<domain>` if you use it), automatic renewal on.

Write down: the **user name** (Virtualmin shows it under *Virtual Server Details*), the **database name and password** (*Edit Databases*), and the **Home directory**.

**You should see:** `https://<domain>/` shows Virtualmin's placeholder page with a valid lock.

**Undo:** Virtualmin → select the domain → *Delete Virtual Server*.

## Step 3 — [Virtualmin] The sub-server for staging

*Create Sub-Server* under the domain: name `staging.<domain>`, same defaults, with its own **MariaDB database** (write down its name and password), and a Let's Encrypt certificate for it. Staging uses the same Unix user as the domain: that is normal for a sub-server.

**You should see:** `https://staging.<domain>/` shows a placeholder page with a valid lock.

**Undo:** Virtualmin → select `staging.<domain>` → *Delete Virtual Server*.

## Step 4 — [site user] Look at the database (staging first)

Open the database of the site (name and password from steps 2–3). Use `-h 127.0.0.1`, because that is how Unicorn will connect:

```
mariadb -h 127.0.0.1 -u <database user> -p <database name>
```

Run these three lines:

```
SELECT @@version, @@log_bin, @@log_bin_trust_function_creators, @@character_set_database;
SELECT CONVERT_TZ('2026-01-01 00:00:00','UTC','Europe/Berlin');
SHOW GRANTS;
```

What the answers must be:

1. **Connecting works** at all (otherwise MariaDB does not listen on TCP; send me the message).
2. `@@version`: 10.6 or newer.
3. `@@character_set_database`: `utf8mb4`. If not, and the database is still empty: `ALTER DATABASE <database name> CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`
4. `CONVERT_TZ` gives `2026-01-01 01:00:00`. If it gives `NULL`, the database server has no time zone tables.
5. `SHOW GRANTS` includes `TRIGGER` (or `ALL PRIVILEGES`).
6. `@@log_bin` is `0`, or `@@log_bin_trust_function_creators` is `1`.

**If 4 or 6 is not as it should be, do not change anything on the server. Send me the three answers.** Both are settings or data of the database server, not of your virtual server, and you decide what to do:
   - without time zone tables, dates in Berlin time are wrong in some lists. They are loaded with one command by the administrator (a one-time data load, no setting), and I will tell you the line if you want it;
   - with `log_bin` on and no trust setting, the append-only protection of the books cannot be built into the database, and the program's own guards and the nightly audit protect the books instead. That is allowed, but weaker.

**Undo:** nothing was changed (except possibly point 3, which only sets the default of an empty database).

## Step 5 — [Mac] and [site user] The code gets to the box

The code travels by `git`, from your Mac to a bare repository inside the site folder. No hosting service, no key to hand out.

**[site user]** (with the `SITE` and `WEB` lines from above)

```
mkdir -p "$SITE" && git init --bare "$SITE/unicorn.git"
```

**[Mac]**, in the Unicorn folder (the first time, tag the version that goes live):

```
git tag -a v0.0.1 -m "first install"
git remote add staging <site user>@<box host>:unicorn-staging/unicorn.git
git push staging main --tags
```

(For production the remote is `production` and the path `unicorn/unicorn.git`.)

**[site user]**

```
git clone "$SITE/unicorn.git" "$SITE/app"
cd "$SITE/app" && git checkout --detach v0.0.1 && echo v0.0.1 > .version
```

**You should see:** `ls "$SITE/app"` shows `manage.py` and `deploy/`, and `cat "$SITE/app/.version"` says `v0.0.1`.

**Undo:** **[site user]** `rm -rf "$SITE"` (and **[Mac]** `git remote remove staging`).

## Step 6 — [site user] Python libraries, in the site's own folder

```
python3.12 -m venv "$SITE/venv"
"$SITE/venv/bin/pip" install --upgrade pip
"$SITE/venv/bin/pip" install -r "$SITE/app/requirements-server.txt"
mkdir -p "$SITE/run" "$SITE/private_media" "$WEB/static" && chmod 700 "$SITE/private_media"
```

`requirements-server.txt` has the pure-Python database driver PyMySQL instead of `mysqlclient`, because `mysqlclient` needs database development files that are not on the box. It takes a few minutes and about 700 MB: check `df -h ~` first, each site has its own `venv`.

**You should see:** the last `pip` line ends with `Successfully installed ...`, and `"$SITE/venv/bin/python" -c "import django, pymysql; print(django.__version__)"` prints `5.2.19`.

**Undo:** `rm -rf "$SITE/venv"`.

## Step 7 — [site user] The settings file, `.env`

First a free port for this site (each site needs its own; the number only matters on this machine):

```
python3.12 - <<'EOF'
import random, socket
while True:
    port = random.randint(18000, 18999)
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port)); print(port); break
    except OSError:
        pass
    finally:
        s.close()
EOF
```

Then make the secrets (each command prints one value; copy it from the screen, nothing is saved):

```
"$SITE/venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(50))"
"$SITE/venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"$SITE/venv/bin/python" -c "import secrets; print(secrets.token_hex(32))"
"$SITE/venv/bin/python" -c "import secrets; print(secrets.token_hex(8))"
```

They are, in order: `SECRET_KEY`, `UNICORN_MASTER_KEY`, `UNICORN_HMAC_KEY` and `ADMIN_PATH`. Then:

```
cp "$SITE/app/.env.example" "$SITE/.env" && chmod 600 "$SITE/.env"
nano "$SITE/.env"
```

and set (write the real folder names; `echo "$SITE" "$WEB"` shows them):

```
SECRET_KEY=<the first value>
DEBUG=False
ALLOWED_HOSTS=staging.<domain>
SITE_URL=https://staging.<domain>
DATABASE_URL=mysql://<database user>:<database password>@127.0.0.1:3306/<database name>
UNICORN_MASTER_KEY=<the second value>
UNICORN_HMAC_KEY=<the third value>
ADMIN_PATH=<the fourth value>
GUNICORN_PORT=<the free port>
GUNICORN_WORKERS=2
USE_X_FORWARDED_HOST=True
EMAIL_URL=smtp://localhost:25
DEFAULT_FROM_EMAIL=no-reply@staging.<domain>
SERVER_EMAIL=unicorn@staging.<domain>
ADMIN_EMAILS=<your email address>
SECURITY_CONTACT=<your email address>
SOURCE_URL=<the public address of the source code, if there is one yet; else leave it empty>
SECURE_HSTS_SECONDS=3600
STATIC_ROOT=<the folder $WEB>/static
PRIVATE_MEDIA_ROOT=<the folder $SITE>/private_media
BACKUP_RUN_DIR=<the folder $SITE>/run
DISK_CHECK_PATH=<the folder $SITE>
REQUIREMENTS_FILE=requirements-server.txt
```

If the database password has characters like `@`, `/`, `:` or `#`, write them as `%40`, `%2F`, `%3A`, `%23` in `DATABASE_URL`. For production: `ALLOWED_HOSTS=<domain>` (add `www.<domain>` if you use it), `SITE_URL=https://<domain>`, and its **own, different** secrets.

**Write the master key and the HMAC key into your password manager now, and into a second place** (another person's manager, or a printed sheet in a safe). **Losing the master key means losing every member's personal data, and nobody can get it back.** The keys must not be only in the same place as your database backup.

**You should see:** `ls -l "$SITE/.env"` shows `-rw-------`.

**Undo:** `rm "$SITE/.env"`. Only before step 8: afterwards the master key is needed to read the data.

## Step 8 — [site user] First setup (once)

```
"$SITE/app/deploy/first_setup.sh"
```

It makes the tables, the cache table, loads the contracts, collects the static files into `$WEB/static`, loads the democratic defaults and checks the settings. Run it **once**. Later releases never run it again.

**You should see:** a long list of `Applying ... OK`, and at the end `First setup done.` The two warnings `security.W005` and `security.W021` from `check --deploy` are expected and kept on purpose; any line that says `ERROR` is not.

**Undo:** Virtualmin → *Edit Databases* → delete the site's database and create it again, empty (utf8mb4 as in step 4), and `rm -rf "$WEB/static"/*`.

## Step 9 — [site user] Apache sends the pages to Unicorn (test with a dummy first)

This tests the forwarding with a harmless dummy program before Unicorn is involved. In **one** SSH window:

```
PORT=<the free port from step 7>
test -e "$WEB/.htaccess" && echo "A .htaccess ALREADY EXISTS - stop here and send it to me" || sed "s/<PORT>/$PORT/" "$SITE/app/deploy/htaccess_template" > "$WEB/.htaccess"
mkdir -p "$SITE/proxytest" "$WEB/.well-known/acme-challenge"
echo "the forwarding works" > "$SITE/proxytest/index.html"
echo "apache answered" > "$WEB/.well-known/acme-challenge/test"
python3.12 -m http.server "$PORT" --bind 127.0.0.1 --directory "$SITE/proxytest"
```

It keeps running. In your browser (or in a second window with `curl`):

- `https://staging.<domain>/` shows **"the forwarding works"**;
- `http://staging.<domain>/` is sent to `https://`;
- `https://staging.<domain>/.well-known/acme-challenge/test` shows **"apache answered"** (so Let's Encrypt renewals keep working).

Stop the dummy with Ctrl-C. Then `rm -rf "$SITE/proxytest" "$WEB/.well-known/acme-challenge/test"`.

**If you see a plain error page (500), or Virtualmin's placeholder page** instead of "the forwarding works": the box does not honour the `.htaccess` in your web folder. Look at the last lines of the site's Apache error log (Virtualmin → *Logs and Reports → View Logs*, or `tail ~/logs/error_log`) and send them to me. The fallback is to paste `deploy/apache_directives.conf` into *Services → Configure Website → Edit Directives* of **this one virtual server**; that is a setting of your virtual server, not of the system, but I will not suggest it without your yes.

**Undo:** `rm "$WEB/.htaccess"`.

## Step 10 — [site user] Start Unicorn

```
"$SITE/app/deploy/run_site.sh" start
"$SITE/app/deploy/run_site.sh" status
```

**You should see:** `Started on 127.0.0.1:<port>.` and `Running (process ...)`. Open `https://staging.<domain>/` in the browser: the Unicorn home page, with its styles. `https://staging.<domain>/healthz` answers `{"status": "fail", "checks": ["jobs", "daily"]}`, which is right for now: cron does not run yet (step 11).

If it says `Did not start`, the last lines of `$SITE/run/gunicorn.log` are shown; send them to me.

**Undo:** `"$SITE/app/deploy/run_site.sh" stop`.

## Step 11 — [Virtualmin] Cron: the watchdog, the jobs, the daily work, the monthly close

*Services → Scheduled Cron Jobs → Create a new scheduled cron job*, as the site's user, four times. Replace `<site folder>` with the real folder (`echo "$SITE"`), and if the screen has a field for sending the output by email, put your address there.

| Description | Command | When |
|---|---|---|
| Unicorn staging: keep it running | `<site folder>/app/deploy/run_site.sh ensure` | every minute |
| Unicorn staging: jobs | `flock -n <site folder>/run/jobs.lock <site folder>/app/deploy/manage.sh run_jobs --max-seconds 55` | every minute |
| Unicorn staging: daily | `flock -n <site folder>/run/daily.lock <site folder>/app/deploy/manage.sh daily` | every day at 00:05 |
| Unicorn staging: monthly close | `flock -n <site folder>/run/close.lock <site folder>/app/deploy/manage.sh close_period` | day 1 of every month at 00:15 |

The box is on Berlin time, so the times are right as they are. (The same four lines are in `deploy/crontab.txt` for `crontab -e`.) The first job is the watchdog: it says nothing when the app runs, and mails you when it had to start it.

Then once by hand, so that you do not wait for midnight: `"$SITE/app/deploy/manage.sh" daily`.

**You should see:** after two minutes `https://staging.<domain>/healthz` answers `{"status": "ok"}`.

**Undo:** Virtualmin → *Scheduled Cron Jobs* → delete the four jobs.

## Step 12 — Email

In Virtualmin, for the domain: the DKIM, SPF and DMARC records are made by Virtualmin if it also runs your DNS; if the DNS is at the registrar, add the records Virtualmin shows (*Email Settings*) there. Then **[site user]** `"$SITE/app/deploy/manage.sh" sendtestemail <your email address>`.

**You should see:** the message in your inbox, not in spam; in "show original", `dkim=pass`.

**Undo:** delete the DNS records.

## Step 13 — [Mac] and [site user] A release, and the rollback

The way every new version gets onto a site (staging first):

1. **[Mac]** make the change, tag it, push: `git tag -a v0.0.2 -m "test" && git push staging main --tags`
2. **[site user]** `BACKUP_DONE=1 "$SITE/app/deploy/release.sh" v0.0.2`
   (Make your Borg backup first and add `BACKUP_DONE=1`, or let `$SITE/before_release.sh` do it for you: see "Your backups".)

   It remembers the current version, switches the code, installs the libraries, runs `check --deploy`, `migrate`, `createcachetable` and `collectstatic`, restarts the app with `run_site.sh`, waits 5 seconds and asks `/healthz`. If anything goes wrong it puts the old version back and says `Release failed, rolled back to <tag>`. The database stays migrated, which is safe because every migration lets the previous release still run.
3. **Try the rollback once, on staging:** `BACKUP_DONE=1 HEALTH_URL=https://staging.<domain>/no-such-page "$SITE/app/deploy/release.sh" v0.0.2` makes the health check fail on purpose.
4. The founders or testers click through the main pages. Go through `docs/security_checklist.md`.
5. Write the release in `docs/deploy_log.md`.

**You should see:** after 2 `Released v0.0.2.`; after 3 `Release failed, rolled back to ...` and the site still works.

**Undo:** `BACKUP_DONE=1 "$SITE/app/deploy/release.sh" <the earlier tag>`

## Step 14 — Production

Repeat steps 4 to 13 for the domain itself, with the production values:

| | Staging | Production |
|---|---|---|
| Site folder (`SITE`) | `$HOME/unicorn-staging` | `$HOME/unicorn` |
| Web folder (`WEB`) | `$HOME/domains/staging.<domain>/public_html` | `$HOME/public_html` |
| Address | `staging.<domain>` | `<domain>` |
| Git remote on the Mac / path | `staging` / `unicorn-staging/unicorn.git` | `production` / `unicorn/unicorn.git` |
| Database | the sub-server's | the domain's |
| Port, secrets | its own | its own, **different** |
| Cron descriptions | "Unicorn staging: …" | "Unicorn: …" |

A release goes to production only after it has run well on staging.

**Undo:** the same undo lines, step by step, for the production names.

---

## What you can change in Virtualmin afterwards

You can use the Virtualmin screens as before, on your virtual server and in its cron:

- **Free to change:** the certificates, DNS, mail settings and mailboxes, the logs and their rotation, the user's password and SSH settings, the PHP settings (Unicorn does not use PHP).
- **If you change the database password:** put the new one in `$SITE/.env` (`DATABASE_URL`) and run `"$SITE/app/deploy/run_site.sh" restart`.
- **If the domain name changes:** change `ALLOWED_HOSTS` and `SITE_URL` in `$SITE/.env`, then restart.
- **Do not:** delete or rename the site folder, delete the four cron jobs, or add a *Website Redirect* or *Proxy* for the same domain in Virtualmin (it would compete with the `.htaccess`). Virtualmin's own backup of the virtual server is not part of Unicorn's plan; see "Your backups".

## Your backups

Made by you with Borg; Unicorn does not touch them. A backup of one site must contain:

1. **A dump of the database:** `mariadb-dump --single-transaction --routines --triggers --hex-blob --default-character-set=utf8mb4 -h 127.0.0.1 -u <database user> -p <database name> > unicorn.sql`, taken by your backup job.
2. **The private files:** `$SITE/private_media`.
3. **The keys**, kept **apart** from the rest: the master key and the HMAC key from `$SITE/.env`. Without the master key a restored database cannot be read; with it next to the database backup, whoever has the backup can read everything.

And these rules:

- The Borg repository is encrypted, and a copy lies on another machine in the EU.
- Write the retention (how many daily and monthly copies) in `docs/privacy/records_of_processing.md`.
- **Before every release** a fresh backup. Either make it yourself and run `release.sh` with `BACKUP_DONE=1`, or put your Borg command in an executable file `$SITE/before_release.sh`: `release.sh` runs it first, and releases nothing if it fails.
- **Optional:** if your backup job's last line is `date -u +%Y-%m-%dT%H:%M:%SZ > <site folder>/run/last_backup` and `BACKUP_EXPECTED=True` is in `$SITE/.env`, `/healthz` also goes red when no backup was made for 26 hours.

### The monthly restore test

A backup that was never restored is only a hope. Once a month, on staging (never on production), restore the newest backup into a **separate database** and look at it. Then write the result into production, so that the open-books page shows it:

```
"$SITE/app/deploy/manage.sh" record_restore_test --ok --backup-date 2027-03-01 --notes "all fine"
```

Use `--failed` and write the reasons in `--notes` when it failed. A failed test is urgent. If there has been no good test for 35 days, a ticket goes to the elected auditors.

### After a restore (a test or a disaster)

Before anybody uses a restored database (for a test, put `DATABASE_NAME_OVERRIDE=<the restored database>` in the site's `.env` for the time of the test):

1. `manage.sh reapply_deletions` — people who were deleted since the backup stay deleted (the backup still has their email and name).
2. `manage.sh audit_books --full` — the books are in order from the first transaction.
3. `manage.sh compare_fingerprints --published published.json` — with the JSON from the open-books page (or a copy you saved). Every published fingerprint up to the last restored transaction must match.

In a disaster: a new virtual server, steps 5 to 11 with the **same `.env` secrets** from your sealed copy, then restore the database and `private_media` from Borg, then the three lines above. Tell the members what happened and how much was lost, on the home page and by email. Targets: at most one day of data lost, service back within one day.

## Watching the service

- **`/healthz`** answers `{"status": "ok"}`, or HTTP 503 with the names of the checks that failed: `database`, `jobs` (the job runner has not finished a run in 5 minutes), `daily` (not run in 26 hours), `audit` (the last audit of the books found something), `backup` (only if you turned it on). It never says more than the names; for the details look at the logs and the open-books page.
- **The uptime check** emails you on the first failure and when the service is back. Add one more cron job (every 5 minutes): `<site folder>/app/deploy/uptime_check.sh https://<domain> <your email address>`. Run from the same box it tells you when Unicorn is down but not when the whole box is down; for that, run the same command from any other machine that has `curl` and `mail` (copy the file `deploy/uptime_check.sh` there).
- **Logs:** Unicorn's own log is `$SITE/run/gunicorn.log` (warnings and errors only, no personal data; at 10 MB it is moved to `gunicorn.log.1`). Apache's logs are Virtualmin's, with its usual rotation: they hold IP addresses, so keep them no longer than 2 weeks.
- **Disk space:** the `daily` job emails you when the disk of `DISK_CHECK_PATH` is more than 80 % full.
- **`/.well-known/security.txt`** shows `SECURITY_CONTACT` to anyone who finds a security problem. (Unicorn answers it; the `.htaccess` keeps only `/.well-known/acme-challenge/` for Apache.)

## When something does not work

| You see | Probably | Do |
|---|---|---|
| `pip` stops with `error: ... mysql.h` | the list `requirements.txt` was used instead of `requirements-server.txt` | `"$SITE/venv/bin/pip" install -r "$SITE/app/requirements-server.txt"` |
| The page says "Bad Request (400)" | `ALLOWED_HOSTS` does not name this site, or `USE_X_FORWARDED_HOST` is not `True` | fix `$SITE/.env`, then `run_site.sh restart` |
| The browser loops ("too many redirects") | the app does not know the visit was https | the `RequestHeader` line of `.htaccess` is not honoured: send me the Apache error log |
| An error page (500) on every page, also the dummy page of step 9 | the web folder's `.htaccess` is not honoured | step 9, last paragraph |
| `/healthz` says `jobs` or `daily` | cron does not run | step 11; look in the cron screen, and at your mail |
| `/healthz` says `audit` | the audit of the books found something | open the open-books page; do not release anything; send me the text |
| The styles are missing | `static/` is empty | `ls "$WEB/static"`; if empty: `"$SITE/app/deploy/manage.sh" collectstatic --noinput` |
| `run_site.sh` says `Did not start` | the last lines of the log say why | send them to me |
| `release.sh` says "Make your backup first" | it wants a backup | make it, then `BACKUP_DONE=1` |

Write every step you take, with the date, in `docs/deploy_log.md` (never a secret).
