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

1. **Check versions** with `deploy/check_server.sh` (task P15.T01): `cat /etc/almalinux-release`, `mariadb --version` (10.6+ recommended; 10.5 still works, see P15.T01), `httpd -v`, SELinux, the time zone tables.
2. **Packages** (as root):

   ```
   dnf install -y epel-release
   dnf install -y python3.12 python3.12-devel gcc git pkgconf-pkg-config mariadb-connector-c-devel age
   ```

3. **Virtual servers:** one for `unicorn.<domain>` (production) and one for `staging.unicorn.<domain>`. Each has its own Unix user, MariaDB database and Let's Encrypt certificate. The database server also needs its time zone tables (`mariadb-tzinfo-to-sql /usr/share/zoneinfo | mariadb -u root mysql`), and, with SELinux enforcing, `setsebool -P httpd_can_network_connect 1` (task P15.T03).
4. **Layout under the virtual server's home** (`/home/<user>/`):

   ```
   app/            the repository (git clone, a release tag checked out)
   venv/           python3.12 -m venv venv
   .env            secrets, chmod 600
   public_html/static/   collectstatic target, served by Apache
   private_media/  uploaded files, never served directly
   backups/        local encrypted backups before copying off-site
   run/            lock files
   ```

5. **gunicorn as a systemd service** (`/etc/systemd/system/unicorn.service`, user = the virtual server's user, `--bind 127.0.0.1:8001 --workers 3`; staging uses port 8002). A sudoers line lets the user restart only its own service (task P15.T05).
6. **Apache proxy** in the virtual server's configuration (`deploy/apache_directives.conf`):

   ```
   ProxyPreserveHost On
   ProxyPass /.well-known/acme-challenge/ !
   ProxyPass /static/ !
   ProxyPass / http://127.0.0.1:8001/ timeout=60
   ProxyPassReverse / http://127.0.0.1:8001/
   RequestHeader set X-Forwarded-Proto "https"
   LimitRequestBody 12582912
   ```

7. **Cron** for the virtual server's user (Virtualmin → Scheduled Cron Jobs). `deploy/manage.sh` sets the path of the settings file and runs `manage.py` (task P15.T04):

   ```
   * * * * *  flock -n ~/run/jobs.lock ~/app/deploy/manage.sh run_jobs --max-seconds 55
   5 0 * * *  flock -n ~/run/daily.lock ~/app/deploy/manage.sh daily
   15 0 1 * * flock -n ~/run/close.lock ~/app/deploy/manage.sh close_period
   30 2 * * *  flock -n ~/run/backup.lock ~/app/deploy/backup.sh
   ```

8. **Releases** with `deploy/release.sh <tag>`, on staging first (with the tests against MariaDB), then on production. The script makes a backup, checks out the tag, installs, migrates, collects the static files, restarts the service, and rolls back if `/healthz` fails (task P15.T06).

## 4. Where the data lives

- The box must stand in the EU/EEA (GDPR). If it does not, this is an open question for the owner (docs/12).
- Backups go to a second machine, also in the EU.
