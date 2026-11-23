# Security checklist before a release

Run this before **every** release (task P15.T06 calls it). One person runs it and writes the date, the version and their name at the bottom of the release note. If any line fails, the release waits. Every command runs from the app's folder on the **staging** server unless it says "production".

## 1. The server settings are safe

- [ ] `python manage.py check --deploy` prints no warning, except `security.W005` and `security.W021` (HSTS for subdomains and the preload list). Those two are kept on purpose until the domain is known (docs/12, P14.T06). Any other line is a failure.
- [ ] `DEBUG` is off and `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `SITE_URL` name only the real domain.
- [ ] The page `/` answers with the headers `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy` and `Permissions-Policy`. (`curl -sI https://<domain>/`)
- [ ] Plain `http://` is sent to `https://`.
- [ ] `python -m pytest -q apps/core/tests/test_security_headers.py` passes, with the inline-script test.

## 2. The packages are free of known problems

- [ ] Every package in `requirements.txt` is pinned to an exact version.
- [ ] Read the **Django security announcements** (https://www.djangoproject.com/weblog/ — the "security" tag). If a patch release for the pinned 5.2.x exists, install it first.
- [ ] Read the release notes and security notes of the other packages for the pinned versions: `django-allauth`, `cryptography`, `mysqlclient`, `django-csp`, `django-htmx`, `gunicorn`, `numpy`, `scipy`, `PyYAML`, `django-environ`. Write down the date you looked.
- [ ] Bootstrap and htmx in `static/vendor/` are at the versions named in `THIRD_PARTY.md`, and their own security pages show no open problem.

## 3. No secret is in the repository

Run these in the repository root. Each should show nothing, or only harmless lines (a sample value in a document, a fixed checksum in a fixture). Read every hit.

```
git grep -n -i -E "(SECRET|PASSWORD|TOKEN|_KEY|IBAN)[A-Z_]*\s*[:=]\s*['\"][^'\"\$ ]{8,}" -- . ':!*/tests/*' ':!static/vendor' ':!*/migrations/*'
git grep -n -E "gAAAAA[A-Za-z0-9_=-]{20,}" -- . ':!*/tests/*'
git grep -n -E "\b[0-9a-f]{64}\b" -- . ':!static/vendor' ':!*/tests/*' ':!*/migrations/*' ':!*/fixtures/*'
git ls-files | grep -E "(^|/)\.env($|\.)|\.pem$|\.key$|id_rsa"
```

- [ ] No real key, password, token or IBAN appears. (Names such as `UNICORN_MASTER_KEY` read from `env(...)` are fine.)
- [ ] The last command prints only `.env.example`, and that file has no real values.
- [ ] `.env` on the server is readable only by the app's user (`ls -l .env` shows `-rw-------`), and lies outside the web root.

## 4. The admin is closed

- [ ] `https://<domain>/admin/` answers "not found". The real path (`ADMIN_PATH`) is known only to the operators and is not in the repository.
- [ ] Without a passkey, the real path sends you to the login page and never shows the admin.
- [ ] Every model in the admin is read-only (`python -m pytest -q apps/core/tests/test_security_headers.py -k admin`).

## 5. Who may do what

- [ ] `python -m pytest -q apps/core/tests/test_permissions_matrix.py` passes: every page that accepts a POST is in the table, and an anonymous visitor, an unverified person and an unrelated member are refused.
- [ ] If this release added a page that accepts a POST, its line in the table was written by a person who thought about who may use it. A reviewer looked at that line.
- [ ] `python -m pytest -q -k "hf"` passes: every hard-frame rule still has its test (`python scripts/hf_coverage.py`).

## 6. Backups and the books

- [ ] **Last night's backup exists** on both machines, and `~/run/last_backup` on production shows a time in the last 26 hours.
- [ ] **The last restore test is less than 35 days old.** On production: the open-books page, or `deploy/manage.sh shell -c "from apps.core.models import RestoreTest; print(RestoreTest.objects.order_by('-ran_at').first())"`, shows `ok`.
- [ ] `python manage.py audit_books --full` on staging (with a restored copy) prints that the chains are intact.
- [ ] The release's migrations let the **previous** release still run (CLAUDE.md, "Database"): new columns are empty-able or have a default, and nothing was removed or renamed.

## 7. Logs and privacy

- [ ] `python -m pytest -q apps/core/tests/test_logging.py apps/core/tests/test_data_map.py` passes.
- [ ] If this release added personal data, a row was added to `docs/privacy/data_map.md` and to the records of processing.
- [ ] A new error mail (send one with `deploy/manage.sh shell -c "import logging; logging.getLogger('django').error('test')"`) reaches the operators' list and contains no name, email or address.

## 8. Sign-off

| Release | Date | Done by | All lines ticked? | Notes |
|---|---|---|---|---|
| | | | | |
