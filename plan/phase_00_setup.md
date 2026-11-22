# Phase 00 — Setup and foundations

**Goal:** a Django 5.2 project on MySQL/MariaDB with tooling, base pages, a background-job runner and the registry of democratic defaults.
**Read first:** CLAUDE.md (all), docs/09_stack_and_hosting.md, docs/01_hard_frame_and_defaults.md sections 2–3.

---

### - [x] P00.T01 — Project skeleton and the custom user model

**Files:** `requirements.txt`, `requirements-dev.txt`, `manage.py`, `unicorn/settings.py`, `unicorn/urls.py`, `apps/__init__.py`, `apps/core/`, `apps/rules/`, `apps/members/`, `.env.example`

**Do:**
1. `python3 -m venv .venv && source .venv/bin/activate`.
2. Create `requirements.txt` with these packages, then `pip install -r requirements.txt` and replace each line with the exact installed version (`==`):
   `Django>=5.2.8,<5.3`, `mysqlclient`, `django-environ`, `django-allauth[mfa]`, `cryptography`, `django-htmx`, `django-csp`, `PyYAML`, `numpy`, `scipy`, `gunicorn`.
   If `mysqlclient` does not build, leave it for P00.T03 and continue.
3. `requirements-dev.txt`: `-r requirements.txt` plus `pytest`, `pytest-django`, `factory-boy`, `hypothesis`, `ruff`, `freezegun` (pinned the same way).
4. `django-admin startproject unicorn .` Create the folder `apps/` with an empty `__init__.py`. Create the apps with `mkdir apps/core && python manage.py startapp core apps/core`, and the same for `rules` and `members`. In each `apps.py`, set `name = "apps.<name>"` and `label = "<name>"`.
5. **Custom user model now**: it cannot be added after the first migration. In `apps/members/models.py`:

   ```python
   class UserManager(BaseUserManager):
       use_in_migrations = True

       def create_user(self, email, password=None, **extra):
           if not email:
               raise ValueError("email required")
           user = self.model(email=self.normalize_email(email), **extra)
           user.set_unusable_password() if password is None else user.set_password(password)
           user.save(using=self._db)
           return user

       def create_superuser(self, email, password=None, **extra):
           extra.update(is_staff=True, is_superuser=True)
           return self.create_user(email, password, **extra)


   class User(AbstractUser):
       username = None
       email = models.EmailField(_("email address"), unique=True)
       USERNAME_FIELD = "email"
       REQUIRED_FIELDS = []
       objects = UserManager()
   ```

   `AUTH_USER_MODEL = "members.User"` in settings.
6. Settings with `django-environ`. Read the file named by the environment variable `UNICORN_ENV_FILE`, defaulting to `BASE_DIR / ".env"` (on the server the file lives outside the code, phase 15):
   - `SECRET_KEY`, `DEBUG` (default False), `ALLOWED_HOSTS`, `DATABASE_URL`;
   - `UNICORN_MASTER_KEY` (Fernet key), `UNICORN_HMAC_KEY` (32+ random bytes, hex), `UNICORN_BACKUP_NOTE` (optional);
   - `EMAIL_URL` (default `consolemail://`), `SITE_URL`.

   Fixed settings: `LANGUAGE_CODE = "en"`, `LANGUAGES = [("en", "English")]`, `LOCALE_PATHS = [BASE_DIR / "locale"]`, `TIME_ZONE = "Europe/Berlin"`, `USE_TZ = True`, `USE_I18N = True`, `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"`.
7. `.env.example` lists every variable, with a comment on how to make each key:
   - `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`;
   - `python -c "import secrets; print(secrets.token_hex(32))"`.

**Tests:** none yet (the test setup comes in T02).
**Done when:** `python manage.py check` prints no errors.

---

### - [x] P00.T02 — Tooling and the Makefile

**Files:** `pyproject.toml`, `Makefile`, `conftest.py`, `apps/core/tests/__init__.py`, `apps/core/tests/test_settings.py`

**Do:**
1. `pyproject.toml`:
   - `[tool.ruff]`: `line-length = 120`, `target-version = "py312"`; lint `select = ["E", "F", "I", "B", "UP", "DJ"]`; exclude `migrations`.
   - `[tool.pytest.ini_options]`: `DJANGO_SETTINGS_MODULE = "unicorn.settings"`, `python_files = ["test_*.py"]`, `addopts = "-q"`.
2. `Makefile` with the targets of CLAUDE.md section 3. `check` runs, in order:
   - `ruff check .`
   - `ruff format --check .`
   - `python manage.py check`
   - `python manage.py makemigrations --check --dry-run`
   - `pytest -q`

   Every target uses `.venv/bin/python`.
3. `conftest.py` at the root: a fixture `settings_en` that forces `LANGUAGE_CODE="en"`. More fixtures come later.
4. `test_settings.py`: `test_time_zone_and_user_model` asserts `TIME_ZONE == "Europe/Berlin"`, `USE_TZ`, and `AUTH_USER_MODEL == "members.User"`.

**Done when:** `make check` passes (the database is not needed yet).

---

### - [ ] P00.T03 — The database: MySQL locally, MariaDB on the server

**Read:** docs/09 sections 1–2.
**Files:** `unicorn/settings.py`, `unicorn/__init__.py`, `apps/core/tests/test_database.py`

**Do:**
1. **Start MySQL** (`mysql.server start`) and create the database and user exactly as in docs/09 section 2.
2. **Settings:**

   ```python
   DATABASES = {"default": env.db("DATABASE_URL")}
   DATABASES["default"]["OPTIONS"] = {
       "charset": "utf8mb4",
       "isolation_level": "read committed",
       "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
   }
   DATABASES["default"]["TEST"] = {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"}
   DATABASES["default"]["ATOMIC_REQUESTS"] = False  # services open their own transactions
   ```

3. **The driver.** If `mysqlclient` failed to install on the Mac, first try:

   ```
   export MYSQLCLIENT_CFLAGS="$(mysql_config --cflags)" MYSQLCLIENT_LDFLAGS="$(mysql_config --libs)"
   pip install mysqlclient
   ```

   Only if it still fails, add `PyMySQL` to `requirements.txt` and put this in `unicorn/__init__.py`:

   ```python
   try:
       import MySQLdb  # noqa: F401  mysqlclient, the preferred driver
   except ImportError:  # fallback: docs/09
       import pymysql

       pymysql.version_info = (2, 2, 1, "final", 0)
       pymysql.install_as_MySQLdb()
   ```

   Write which driver you used in docs/12 section 3.
4. **Time zone tables.** With `USE_TZ = True`, Django converts times in the database with `CONVERT_TZ()`, which returns NULL (and date queries silently find nothing) unless the server's time zone tables are loaded. Load them once per database server:

   ```
   mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -u root mysql
   ```

   (Warnings about a few files are normal. On the server, phase 15 does the same for MariaDB.)
5. `python manage.py migrate`.
6. **Tests:**
   - `test_database_is_mysql_family`: the connection vendor is `mysql`, and `SELECT @@character_set_database` (on the test database) is `utf8mb4`;
   - `test_time_zone_tables_loaded`: `SELECT CONVERT_TZ('2026-01-01 00:00:00', 'UTC', 'Europe/Berlin')` is not NULL.

**Done when:** `make migrate` and `make check` pass.

---

### - [ ] P00.T04 — Base page, static files, translations, installable app

**Files:** `templates/base.html`, `templates/partials/nav.html`, `templates/offline.html`, `static/vendor/`, `static/css/unicorn.css`, `static/js/unicorn.js`, `static/manifest.webmanifest`, `static/sw.js`, `static/icons/`, `apps/core/views.py`, `apps/core/urls.py`, `apps/core/tests/test_pages.py`

**Do:**
1. **Download once and commit:**
   - Bootstrap 5.3.3, from `https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css` and `.../dist/js/bootstrap.bundle.min.js`;
   - htmx 2.0.4, from `https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js`.

   Put them in `static/vendor/`. Pages never load anything from outside the server.
2. **`base.html`:**
   - `{% load i18n static %}`, `<html lang="{{ LANGUAGE_CODE }}">`, `<meta name="viewport" content="width=device-width, initial-scale=1">`;
   - the manifest link, Bootstrap, htmx, `unicorn.js`;
   - `<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>`;
   - the nav, Django messages, `{% block content %}`, and a footer linking to Open books, Rules, Imprint, Privacy.

   Every visible text is inside `{% translate %}` or `{% blocktranslate %}`.
3. **Nav entries** (placeholders until their phase): Market, Needs, Tickets, Plan, My account, Open books, Rules.
4. **Installable app:**
   - `manifest.webmanifest`: name "Unicorn", `start_url "/"`, `display "standalone"`, two plain PNG icons (192 and 512 px, a simple letter U is enough);
   - `sw.js`: caches only `offline.html` and the static files, and serves `offline.html` when the network fails. Register it in `unicorn.js`.
5. **Middleware:** add `django_htmx.middleware.HtmxMiddleware`.

**Tests:** `test_home_page_ok` (GET `/` returns 200 and contains `manifest.webmanifest`); `test_offline_page_ok`.
**Done when:** the home page looks right at 375 px and 1280 px width, and `make check` passes.

---

### - [ ] P00.T05 — Core helpers: money, hashing, audit events

**Read:** CLAUDE.md section 5 (Numbers and money).
**Files:** `apps/core/money.py`, `apps/core/hashing.py`, `apps/core/models.py`, `apps/core/audit.py`, `apps/core/tests/test_money.py`, `apps/core/tests/test_hashing.py`, `apps/core/tests/test_audit.py`

**Do:**
1. **`money.py`:**
   - `UNIQ_Q = Decimal("0.0001")`, `CUR_Q = Decimal("0.01")`;
   - `uniq(x)` and `cur(x)` convert `int | str | Decimal` to `Decimal` and quantize with `ROUND_HALF_EVEN`. They refuse `float` with a `TypeError`;
   - `minutes_to_uniq(minutes: int) -> Decimal` returns `uniq(Decimal(minutes) / 60)`.
2. **`hashing.py`:**
   - `canonical_json(obj)`: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, with `Decimal` written as a string and `datetime` as ISO 8601 UTC;
   - `sha256_hex(text)`;
   - `chain_hash(prev_hash: str, payload: dict) -> str` returns `sha256_hex(prev_hash + canonical_json(payload))`;
   - `hmac_hex(text)` uses `UNICORN_HMAC_KEY`.
3. **Models:**
   - `TimeStamped` (abstract: `created_at` auto_now_add, `updated_at` auto_now);
   - `AuditEvent`: `created_at`; `actor_ref` CharField(32) holding a member number or `"system"`; `verb` CharField(64); `object_type` CharField(64); `object_id` CharField(64); `data` JSONField(default=dict); `request_id` CharField(36, blank).

   `AuditEvent.save()` refuses updates (`if self.pk: raise ValueError`) and `delete()` always raises. The database triggers come in P02.T05.
4. **`audit.record(actor_ref, verb, obj=None, **data)`** creates an `AuditEvent`. It never stores personal data: only member numbers and ids.

**Tests:**
- `uniq("1.23456") == Decimal("1.2346")`;
- `uniq(0.1)` raises `TypeError`;
- `minutes_to_uniq(90) == Decimal("1.5000")`;
- `canonical_json` is the same for dicts with different key order;
- `chain_hash` is deterministic;
- `AuditEvent` cannot be changed or deleted.

---

### - [ ] P00.T06 — Background jobs without an extra server

**Read:** docs/09 section 1 (Background jobs), section 3 item 7 (cron).
**Files:** `apps/core/models.py` (Job), `apps/core/jobs.py`, `apps/core/management/commands/run_jobs.py`, `apps/core/management/commands/daily.py`, `apps/core/tests/test_jobs.py`

**Do:**
1. **`Job` model:**
   - `kind` CharField(64), `payload` JSONField;
   - `status` (`queued`, `running`, `done`, `failed`);
   - `run_after` (default now), `attempts` (int, 0), `max_attempts` (int, 5), `last_error` (Text);
   - `dedupe_key` (CharField(128), null, unique);
   - `created_at`, `started_at`, `finished_at`.

   Index on (`status`, `run_after`).
2. **`jobs.py`:**
   - a registry `JOBS: dict[str, Callable[[dict], None]]` and a decorator `@job("kind")`;
   - `enqueue(kind, payload, run_after=None, dedupe_key=None)`: if a job with the same `dedupe_key` exists, do nothing;
   - `run_due(max_seconds=55)`, which loops:
     1. In a transaction, select the oldest due queued job with `select_for_update(skip_locked=True)`, set it `running`, and commit. If the database cannot skip locked rows (`connection.features.has_select_for_update_skip_locked` is False, as on MariaDB 10.5), use plain `select_for_update()`: cron's `flock` already lets only one runner work at a time.
     2. Run its function inside `transaction.atomic()`.
     3. Mark it `done`. On an exception: `attempts += 1`, `last_error = traceback`, `run_after = now + 2**attempts minutes`, and status `queued`, or `failed` once `attempts == max_attempts`.
     4. Stop when no job is due or the time is up.
   - **Crash recovery:** at the start of `run_due`, a job that has been `running` for more than 30 minutes (its process was killed) goes back to `queued`, with `attempts += 1`.
   - Every job function must be safe to run twice (write this in the docstring of `@job`).
3. **Commands:**
   - `run_jobs [--max-seconds N]` calls `run_due`;
   - `daily` enqueues the daily jobs (empty list for now, with a comment saying later phases add to it) and runs them.
4. **A demo job** `@job("core.ping")` that writes an `AuditEvent` with verb `ping`.

**Tests:**
- enqueue and run the ping job;
- a failing job is retried with a later `run_after`, and becomes `failed` after `max_attempts`;
- `dedupe_key` prevents doubles;
- a job already `running` is not picked again;
- a job left `running` for 31 minutes is queued again (`freezegun`).

---

### - [ ] P00.T07 — The registry of democratic defaults

**Read:** docs/01 sections 2–3; `config/defaults.yaml` (its header).
**Files:** `apps/rules/models.py`, `apps/rules/services.py`, `apps/rules/management/commands/load_defaults.py`, `apps/rules/tests/test_defaults.py`

**Do:**
1. **Models:**
   - `Parameter`: `key` CharField(120, unique), `value` JSONField, `type` (`decimal`, `int`, `bool`, `choice`, `text`, `list`), `min_value` and `max_value` (CharField(40), null: kept as strings so decimals stay exact), `choices` JSONField(null), `tier` (`unit`, `confirm`, `plan`, `referendum`, `hard`), `source` CharField(200), `help` TextField, `updated_at`.
   - `ParameterChange`: `parameter` FK(PROTECT), `old_value` JSON, `new_value` JSON, `decided_by` CharField(32) (a ticket number such as `T-000123`, or `defaults-file`), `decided_tier`, `reason` TextField, `decided_at`. Append-only (guards as for `AuditEvent`).
2. **`services.py`:**
   - **`TIER_ORDER = ["unit", "confirm", "plan", "referendum", "hard"]`.**
   - **`get_param(key)`** returns the typed value:
     - `decimal` → `Decimal(str(value))`;
     - `int` → `int`;
     - `bool` → `bool`;
     - `choice` and `text` → `str`;
     - `list` → `list`.

     An unknown key raises `KeyError`. No caching.
   - **`set_param(key, value, *, decided_by, decided_tier, reason)`:**
     1. Validate the type, the bounds and the choices (`ValidationError` with a plain message).
     2. Require `TIER_ORDER.index(decided_tier) >= TIER_ORDER.index(param.tier)`; a parameter of tier `hard` requires `decided_tier == "hard"`.
     3. Write a `ParameterChange`, then update `Parameter.value`.

     All inside `transaction.atomic()` with `select_for_update()` on the parameter.
3. **`load_defaults [--reset]`:**
   1. Read `config/defaults.yaml` and walk the tree: a leaf is a dict containing both `value` and `tier`. Build dotted keys.
   2. Validate each leaf (value within bounds, choice in choices, required keys present), and stop with a clear error on the first bad leaf.
   3. Create missing parameters, each with a `ParameterChange(decided_by="defaults-file")`.
   4. For existing parameters, update `type`, bounds, `choices`, `tier`, `source` and `help`, **but never `value`**. With `--reset` (allowed only when `DEBUG`), the values are reset too.
   5. Print how many were created, updated and unchanged.

**Tests:**
- loading creates exactly as many parameters as the file has leaves (count them in the test by walking the YAML);
- `get_param("governance.confirmers.size") == 4`;
- `get_param("economy.flat_tax.max") == Decimal("0.68")`;
- `set_param` with a value above `max` raises;
- `set_param` with too low a tier raises;
- a changed value survives `load_defaults` (without `--reset`);
- a deliberately broken YAML leaf is reported.

---

### - [ ] P00.T08 — The hard-frame registry and the rules page

**Read:** docs/01 section 1.
**Files:** `apps/rules/hard_frame.py`, `apps/rules/views.py`, `apps/rules/urls.py`, `apps/rules/templates/rules/index.html`, `apps/rules/tests/test_hard_frame.py`, `scripts/hf_coverage.py`

**Do:**
1. **`hard_frame.py`:** a tuple `RULES` of 20 dataclass entries `(id="HF-1", title=..., text=...)`, with the texts copied from docs/01 section 1 (plain English).
2. **Public page `/rules/`:**
   - the 20 rules;
   - then every parameter grouped by its first key part, with its value, bounds, tier (explained in words: "the unit's council", "4 random members", "the yearly plan", "a vote of all members", "the hard frame"), source and help;
   - each parameter links to its history (its `ParameterChange` rows).
3. **`scripts/hf_coverage.py`:** scans `apps/**/tests/test_*.py` for function names `test_hf<NN>_` and prints, for HF-1 to HF-20, the tests that cover it, or "MISSING". It exits 0 always; phase 15's acceptance requires no MISSING.

**Tests:**
- `test_hf_registry_has_20_rules` (ids HF-1 … HF-20, in order);
- `test_rules_page_lists_parameters` (after `load_defaults`, the page contains `governance.confirmers.size`).

---

### - [ ] P00.T09 — Home, health check, error pages

**Files:** `apps/core/views.py`, `apps/core/urls.py`, `templates/core/home.html`, `templates/404.html`, `templates/500.html`, `apps/core/tests/test_pages.py`

**Do:**
1. **Home:**
   - logged out: what Unicorn is, in five sentences taken from docs/00 ("The answer: Unicorn", points 1–5, shortened), and a "Join" button (it leads to sign-up in P01);
   - logged in: a dashboard placeholder with the sections "My work", "My orders", "Tickets for me", "Warning lights" (filled in later phases).
2. **`/healthz`:** returns `{"status": "ok"}` after a `SELECT 1`, or HTTP 503.
3. **Friendly 404 and 500 pages** in plain words.

**Tests:** `/healthz` returns 200 with `ok`; an unknown URL returns the 404 page.

---

## Acceptance check for phase 00

1. In a fresh clone, these all succeed:
   - `make setup`, `make migrate`, `make defaults`, `make check`;
   - `python manage.py run_jobs` runs a queued `core.ping`.
2. `/rules/` shows 20 rules and every parameter of `config/defaults.yaml`.
3. Add one line to PLAN.md "Progress".
