# 9. The building blocks and the server

*Owner's choice (2026-11-21): the recommended one-language web app (Python/Django, server-built pages, installable on phones), running on his Virtualmin box with AlmaLinux and **MariaDB, no PostgreSQL**.*

## 1. The stack, part by part

| Part | Choice | Why | Watch out for |
|---|---|---|---|
| Language | **Python 3.12** on the server (3.12 or newer locally) | the simulation is in Python, so its maths can be reused; the language agents know best | AlmaLinux's default Python is older: install `python3.12` from AppStream |
| Framework | **Django 5.2 LTS** (latest patch) | accounts, database, forms, translations, security, admin in one; supported until April 2028 | pin the latest 5.2 patch (newer Python versions need newer patches) |
| Database | **MariaDB 10.6 or newer** (10.11 or 11.4 LTS recommended) on the server; **MySQL 8** on the owner's (older) Mac | the owner's server already runs it; Django supports both | write only what both support; check the server's version first (task P15.T01) |
| Database driver | `mysqlclient` | the driver Django recommends | needs build packages (section 3); fallback `PyMySQL` with a version shim (task P00.T03) |
| Pages | Django templates + **HTMX 2** + **Bootstrap 5.3** | pages come ready from the server: simple, fast on old phones, few moving parts; HTMX swaps parts of a page without a JavaScript app | files served from `static/`, never from a CDN (privacy) |
| Install on phones | **PWA**: a web manifest and a small service worker | members add Unicorn to their home screen without an app store | offline use comes later (docs/08, section 9) |
| Accounts | `django-allauth` with its `mfa` part | passkeys and email login codes, tested and maintained | follow the settings of the installed version exactly |
| Encryption | `cryptography` (Fernet) | per-member keys for personal data | the master key lives only in `.env` |
| Background jobs | **own small job table** + cron calling `manage.py run_jobs` every minute (task P00.T06) | no extra server; Virtualmin manages cron; jobs are saved in the same transaction as the data that needs them | one runner at a time (`flock`); jobs must be safe to run twice |
| Scheduled work | cron: `run_jobs` every minute, `daily` at 00:05, `close_period` on the 1st of the month | visible and simple | times in Europe/Berlin |
| Planning maths | `numpy`, `scipy` | sparse matrices for the input-output table; root finding for the tax | floats only inside the engine |
| Web server | **gunicorn** behind **Apache** (Virtualmin's default) as a reverse proxy | standard Django deployment | `SECURE_PROXY_SSL_HEADER` must be set |
| HTTPS | Let's Encrypt through Virtualmin | free, automatic | |
| Email | the box's Postfix through Virtualmin, with SPF and DKIM | login codes and notifications | set up DKIM, or the mail lands in spam |
| Tests | `pytest`, `pytest-django`, `factory-boy`, `hypothesis`, `freezegun` | fast tests of the rules and of the invariants | |
| Code style | `ruff` (lint and format) | one tool | |
| Licence | AGPL-3.0 | the code stays open (HF-19) | |

**Not used, on purpose:**
- PostgreSQL (the owner's choice);
- Docker (the box is managed by Virtualmin);
- Redis/Celery (no extra server);
- React or any JavaScript build step;
- external CDNs or analytics;
- blockchains (legal frame, section 2).

## 2. Local development on the Mac

```
mysql.server start
mysql -u root -e "CREATE DATABASE unicorn_dev CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                  CREATE USER 'unicorn'@'localhost' IDENTIFIED BY '<local password>';
                  GRANT ALL PRIVILEGES ON unicorn_dev.* TO 'unicorn'@'localhost';
                  GRANT ALL PRIVILEGES ON test_unicorn_dev.* TO 'unicorn'@'localhost';"
mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -u root mysql   # once: time zone tables (task P00.T03)
cp .env.example .env        # fill in DATABASE_URL, SECRET_KEY, UNICORN_MASTER_KEY, UNICORN_HMAC_KEY
make setup && make migrate && make defaults && make run
```

Tests create `test_unicorn_dev` themselves. Creating the append-only triggers needs the `TRIGGER` privilege (included in `ALL PRIVILEGES`). If binary logging is on, it also needs `log_bin_trust_function_creators=1`; task P02.T05 explains.

## 3. The server: Virtualmin on AlmaLinux

(Done in phase 15; written here so the owner knows what to expect.)

1. **Look at the box** with `deploy/check_programs.sh` (read only: it lists the needed programs as FOUND or MISSING) and `deploy/check_server.sh`. Nothing is installed from a repository: Unicorn uses what the box already has (Python 3.12, git, MariaDB with its client tools, Apache with the proxy, headers and ssl modules, systemd, cron, flock, mail). The database driver is the pure-Python **PyMySQL** (`requirements-server.txt`), because the database development files that `mysqlclient` needs are not on the box. Unicorn's own Python libraries are installed with `pip` into the site's own folder (`~/venv`), not into the system.
2. **Virtual servers, made in Virtualmin with the owner's usual defaults and no change of settings:** one for the new domain (production) and a sub-server `staging.<domain>` (it shares the Unix user of the domain). Each has its own MariaDB database and Let's Encrypt certificate. Nothing on the server itself is changed: no systemd unit, no sudo rule, no Apache or Virtualmin setting, no package.
3. **Layout under the user's home**, one folder per site (`~/unicorn`, `~/unicorn-staging`):

   ```
   unicorn/
     unicorn.git/      bare repository: the Mac pushes tags here
     app/              the code (git clone, a release tag checked out)
     venv/             python3.12 -m venv venv (requirements-server.txt)
     .env              secrets, chmod 600
     run/              gunicorn.pid, gunicorn.log, lock files
     private_media/    uploaded files, never served directly
     before_release.sh optional: the owner's Borg command, run before each release
   ```

   The site's web folder (Virtualmin's `public_html` for that virtual server) holds `static/` (collectstatic) and the one `.htaccess` file.
4. **The app runs as an ordinary program of the site's user** (gunicorn on `127.0.0.1:<port>`; `deploy/run_site.sh start|stop|restart|status|ensure`). A cron job every minute runs `run_site.sh ensure`, which starts it again after a crash or a reboot. That replaces a systemd service.
5. **Apache sends the pages to the app through the `.htaccess` file in the site's web folder** (`deploy/htaccess_template`): Let's Encrypt checks and the static files stay with Apache, plain http goes to https, everything else is proxied to the app with `X-Forwarded-Proto: https`. That replaces Apache settings. If a box does not honour that file, `deploy/apache_directives.conf` says the same for the virtual server's "Edit Directives" (only with the owner's yes).
6. **Cron**, entered in Virtualmin's *Scheduled Cron Jobs* for the site's user (`deploy/crontab.txt`): the watchdog, `run_jobs` every minute, `daily` at 00:05, `close_period` on the 1st at 00:15. `deploy/manage.sh` finds the site folder from where it lies, sets the settings file and runs `manage.py` (task P15.T04).
7. **Releases** with `<site folder>/app/deploy/release.sh <tag>`, on staging first, then on production. The script asks for a fresh backup (the owner's own), checks out the tag, installs, migrates, collects the static files, restarts the app with `run_site.sh`, and rolls back if `/healthz` fails (task P15.T06).

## 4. Where the data lives

- The box must stand in the EU/EEA (GDPR). If it does not, this is an open question for the owner (docs/12).
- Backups are the owner's (Borg), with a copy on another machine, also in the EU.
