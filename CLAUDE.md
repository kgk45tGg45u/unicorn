# Instructions for the coding agent

You are building **Unicorn**, a web app with which members run a planned, horizontal economy inside capitalism. The owner, Bijan Sabbagh, wrote the book it follows and decides what Unicorn is. He is not a programmer: anything you show him (screens, messages, questions) must be in plain words.

## 1. Read before you code

Read these once, in this order, before the first task:

1. [docs/00_intention.md](docs/00_intention.md): what Unicorn is for.
2. [docs/01_hard_frame_and_defaults.md](docs/01_hard_frame_and_defaults.md): the rules HF-1 to HF-20 that the code must enforce. **Never break them.**
3. [docs/10_glossary.md](docs/10_glossary.md): the words. Use them in code and screens exactly as defined.
4. [PLAN.md](PLAN.md): the phases, the order, and the definition of done.

Then, for each task, read only the documents the task lists under **Read**.

## 2. How to work

1. Work on **one task at a time**, in the order of `PLAN.md` and the phase files in `plan/`. Do not start a task whose dependencies are not done.
2. For each task:
   - read the listed documents;
   - write the tests named in the task (you may add more);
   - write the code;
   - run `make check` until it passes;
   - tick the task's box in its phase file (`- [ ]` becomes `- [x]`);
   - commit with the message `P<phase>.T<task>: <short summary>`, for example `P02.T03: ledger post() with hash chain`.
3. Keep each commit to one task. Never commit secrets, `.env` files or personal data.
4. If a task is unclear, or seems to conflict with a hard-frame rule or with another document:
   - choose the **simplest option that keeps every hard-frame rule**;
   - mark the place in the code with a comment `# OWNER-CHECK: <question>`;
   - add the question to [docs/12_open_questions.md](docs/12_open_questions.md) with the task number;
   - continue.
5. Never change a value in [config/defaults.yaml](config/defaults.yaml), or a rule in [docs/01_hard_frame_and_defaults.md](docs/01_hard_frame_and_defaults.md), on your own. Defaults belong to the members and the owner. If you think one is wrong, write it in the open questions.
6. Do not add features that are not in the plan. If something seems missing, add it to the open questions.

## 3. Commands

All commands run from the repository root. `make` targets are created in task P00.T02.

| Command | What it does |
|---|---|
| `make setup` | create `.venv`, install `requirements-dev.txt` |
| `make check` | `ruff check`, `ruff format --check`, `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `pytest -q` |
| `make test` | `pytest -q` only |
| `make run` | development server on http://127.0.0.1:8000 |
| `make migrate` | apply migrations |
| `make defaults` | load `config/defaults.yaml` into the database (`python manage.py load_defaults`) |
| `make jobs` | run due background jobs once (`python manage.py run_jobs`) |

## 4. The machine you work on

- **Local:** the owner's computer is an older Mac, not a recent model and not very fast. Keep tests quick and memory use small. Use a virtual environment in `.venv` with Python 3.12 or newer, and MySQL 8 installed with Homebrew (start it with `mysql.server start`). Pin the latest Django 5.2.x. If something will not install on the local Python, write it in the open questions and try Python 3.12 or 3.13.
- **Server (later, phase 15):** the owner's Virtualmin box, AlmaLinux, **MariaDB** (no PostgreSQL), Apache, Python 3.12. Write code that runs on **both MySQL 8 and MariaDB 10.6+**: only use what Django supports for both (no PostgreSQL-only fields, no `RETURNING` tricks, no database-specific SQL outside the trigger migrations).

## 5. Rules for the code

### Layout

```
manage.py
unicorn/                 Django project: settings.py, urls.py, wsgi.py
apps/<name>/             one Django app per area (see PLAN.md, "Apps")
  models.py  services.py  views.py  urls.py  forms.py  admin.py
  templates/<name>/...   tests/test_*.py
templates/               base.html and shared partials
static/                  css, js (htmx, bootstrap), icons
config/defaults.yaml     the democratic defaults (read-only for you)
```

- Business logic goes in `services.py` functions, never in views, templates or `save()` methods. Views only check permissions, call a service and render.
- Views and templates get the current member from `request.member` (set by `CurrentMemberMiddleware`, task P01.T02), never from `request.user.member`.
- Every service that changes data runs inside `transaction.atomic()`.
- Every action a member takes is recorded: ledger entries for UNIQ, fund entries for euros, `AuditEvent` for everything else.

### Numbers and money

- UNIQ: `Decimal`, stored as `DecimalField(max_digits=18, decimal_places=4)`. Round with `apps.core.money.uniq()`.
- Euros and other currencies: `DecimalField(max_digits=14, decimal_places=2)` plus a 3-letter `currency` field. Round with `apps.core.money.cur()`.
- **Never use `float` for UNIQ or money.** Floats are allowed only inside the planning engine (`numpy`), and results are converted to `Decimal` at the boundary.
- Hours are stored as whole **minutes** (`PositiveIntegerField`) and converted to UNIQ with `uniq(minutes / 60)`.

### The ledger

- **All UNIQ movements go through `apps.ledger.services.post()`.** No other code may create `Transaction` or `Entry` rows.
- Ledger rows are never updated or deleted. Mistakes are fixed with a new correcting transaction that has a written reason.
- Every transaction needs a non-empty `reason` (legal rule: every transfer has a written reason).

### Time

- Store all times in UTC (`USE_TZ = True`). Show them in the member's time zone (default `Europe/Berlin`).
- A period is a calendar month in `Europe/Berlin`.

### Words on screen

- Every text a member sees is plain English and wrapped for translation: `{% translate %}` in templates, `gettext_lazy` / `gettext` in Python. Only English exists for now; other languages come later.
- Use the words of the glossary: UNIQ, unit, working council, ticket, random confirmers, trade fund, holder, needs board.
- Never show technical errors to members. Show what happened and what they can do.

### Database

- MySQL 8 locally, MariaDB 10.6+ on the server. `utf8mb4`, InnoDB, isolation level READ COMMITTED (set in `DATABASES['default']['OPTIONS']`).
- Lock rows you are about to change with `select_for_update()`. Use `skip_locked=True` only in the job runner.
- Raw SQL is allowed only in the migrations that create the append-only triggers (task P02.T05).
- Every migration must let the previous release still run (task P15.T06): new columns are nullable or have a default, and a column is removed or renamed only one release later.

### Tests

- `pytest` with `pytest-django`, `factory-boy` and `hypothesis`. Tests live in `apps/<name>/tests/`.
- Every hard-frame rule has at least one test whose name starts with `test_hf<number>_`, for example `test_hf05_no_transfer_between_members`.
- Random draws in tests use a fixed seed. Tests never call the internet.

### Security and privacy

- No secrets in code. Settings read secrets from environment variables (`.env` locally, loaded by `django-environ`).
- Personal data (legal name, address, phone, date of birth, bank account numbers, licence documents) lives **only** in `members.MemberPrivate` and private files, encrypted per member (task P01.T04). Everything else refers to members by their member number.
- Never write personal data, passwords, tokens or keys to logs.
- Uploaded files go to private storage outside the web root and are served only through a view that checks permission.
- The app never moves money and never reads bank accounts (HF-12). It only shows payment requests and records confirmations.

## 6. Allowed dependencies

Use only these unless a task says otherwise. If you truly need another, write why in [docs/09_stack_and_hosting.md](docs/09_stack_and_hosting.md) and in the open questions.

| Purpose | Package |
|---|---|
| Framework | `Django` 5.2.x (latest patch) |
| Database driver | `mysqlclient` (fallback `PyMySQL`, see task P00.T03) |
| Settings | `django-environ` |
| Accounts, passkeys, email login codes | `django-allauth` (with its `mfa` part) |
| Encryption | `cryptography` |
| Pages | `django-htmx`; HTMX 2 and Bootstrap 5.3 as static files (no build step, no CDN in production) |
| Security headers | `django-csp` |
| YAML | `PyYAML` |
| Planning maths | `numpy`, `scipy` |
| Web server | `gunicorn` |
| Tests and tools | `pytest`, `pytest-django`, `factory-boy`, `hypothesis`, `ruff`, `freezegun` |

## 7. Definition of done for a task

- The tests named in the task exist and pass; `make check` passes.
- No hard-frame rule is weakened; the `test_hf*` tests still pass.
- New screens: every text is wrapped for translation, the page works at phone width, and only permitted members can reach it.
- New models: they have `__str__`, they are registered in the admin as **read-only** (members change data through the app and its tickets, not through the admin), and their migrations are committed.
- The task's box is ticked in its phase file, and the commit message names the task.
