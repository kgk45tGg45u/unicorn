# Phase 14 — Security, privacy, backups, licence, accessibility

**Goal:** Unicorn is safe to run with real people's data. Every piece of personal data is mapped, minimal, exportable and deletable. Keys can be rotated. Backups are encrypted, copied off-site and restore-tested. The pages are protected by strict headers, limits and logs without personal data. The licence and the source link keep the code open (HF-19). The legal pages exist as drafts for the lawyers.
**Read first:** docs/08 (all of it); docs/01 rules HF-7, HF-12, HF-13, HF-14 and HF-19; CLAUDE.md section 5 "Security and privacy".

**Before the founders' pilot** (right after phase 09), do T01, T03, T04 and T06–T09 of this phase, then phase 15 T01–T07 (PLAN.md). The pilot holds real people's data, so these cannot wait. The other tasks follow when you reach this phase in order.

---

### - [x] P14.T01 — The data map

**Read:** docs/08 section 7.
**Files:** `docs/privacy/data_map.md`, `apps/core/tests/test_data_map.py`

**Do:**
1. **Write `docs/privacy/data_map.md`.** It has one table row per place where personal data is kept, with these columns:
   - **what:** for example "legal name";
   - **where:** `app.Model.field`, for example `members.MemberPrivate.blob`;
   - **why:** the feature that needs it;
   - **legal basis:** GDPR Art. 6(1)(b) (the membership contract), 6(1)(c) (a legal duty, for example keeping books and invoices), 6(1)(a) (consent), or Art. 9(2)(a) (explicit consent, for health-related claims);
   - **how long:** until deletion, or a fixed time;
   - **who sees it:** the member, seated confirmers, holders, outside customers, operators.
2. **Cover at least:**
   - `members.User.email`, allauth's `EmailAddress` and `Authenticator` rows, sessions;
   - `members.Member` (display name, postcode, country, `receives_benefits`), `MemberPrivate`, `PrivateFile`, `MemberHash`;
   - every field encrypted with `system_encrypt` (holders, external payees, outside customers, invoices, sellers, donors);
   - hours entries, orders, bookings, tickets, comments, votes (only the voter record: the ballot holds no member), trust events, reputation, recognition, assist consents;
   - Apache and application logs, and backups (how long each copy lives).
3. **Retention per row.** Where the law decides it (for example invoices: `# OWNER-CHECK` 8 or 10 years), write "to be confirmed by lawyers".
4. **Later phases** that add personal data must add rows here. The test below fails until they do.

**Tests:** `test_hf14_data_map_covers_personal_fields`:
- collect every model field whose name ends in `_enc`, every `BinaryField`, and the fields `email`, `display_name`, `postcode` and `receives_benefits`;
- check that each `app.Model.field` appears in `docs/privacy/data_map.md`.

---

### - [x] P14.T02 — Limits against spam and overload

**Read:** docs/08 section 1 ("Denial of service, spam"); the `security.*` parameters.
**Files:** `unicorn/settings.py` (CACHES), `Makefile` (`migrate` also runs `createcachetable`), `apps/core/ratelimit.py`, the views that create tickets, comments, flags and outside orders, `apps/core/tests/test_ratelimit.py`

**Do:**
1. **A shared cache:** set `CACHES["default"]` to `django.core.cache.backends.db.DatabaseCache` with the table `unicorn_cache`. All gunicorn workers share it, and django-allauth's own login and sign-up limits use it too (keep allauth's default `ACCOUNT_RATE_LIMITS`).
2. **`hit(key, limit, window_seconds) -> bool`:**
   - counts in the cache under `rl:<key>:<window start>`;
   - returns False once `limit` is passed;
   - is never used for anything but limits.
3. **The decorator `@rate_limited(name, param, window_seconds, per="member")`:** `per="member"` keys by member number; `per="ip"` keys by a SHA-256 of the IP address plus a salt that changes daily, so that no raw IP address is stored. When the limit is passed, the view answers HTTP 429 with a friendly page: "You have done this many times in a short while. Please try again later."
4. **Apply it:**
   - ticket creation (`security.tickets_per_member_per_day`, 86,400 s);
   - comments (`security.comments_per_member_per_hour`, 3,600 s);
   - flags (`security.flags_per_member_per_day`);
   - outside shop orders (`security.shop_orders_per_ip_per_hour`, `per="ip"`).
5. **The client address:** behind Apache, use the last address in `X-Forwarded-For` only when the request comes from `127.0.0.1`; otherwise use `REMOTE_ADDR`.

**Tests:** the 21st ticket in a day gets 429; the window resets the next day (`freezegun`); IP keys are hashed.

---

### - [x] P14.T03 — Download all my data

**Read:** docs/08 section 7 ("Member rights").
**Files:** `apps/privacy/` (new app), `apps/privacy/export.py`, `apps/privacy/views.py`, `apps/privacy/jobs.py`, `apps/privacy/tests/test_export.py`

**Do:**
1. **"Download my data"** on "My account" is a sensitive action (re-authentication, P01.T09). It queues the job `privacy.export` for the member.
2. **A registry of exporters:** `apps/privacy/export.py` keeps `EXPORTERS`, a list of functions `export(member) -> dict[str, list[dict]]` (table name → rows). Each app adds its own in its `AppConfig.ready()`. Apps built later (for example in phases 10–13, if this task is done early for the pilot) add theirs when they are built.
3. **The job** builds a ZIP file:
   - `README.txt` explaining each file in plain words. It also explains that secret ballots cannot be exported, because a ballot holds no member, and that the export shows only that the member voted;
   - `data.json` with everything about the member: member, private data (decrypted), signatures, UNIQ accounts and entries, holds, hours entries and approvals, units and council roles, orders, bookings and reviews, tickets, comments and helpful marks, seats and votes as a confirmer, voter records, fund entries as a holder, payment requests, donations, invoices, trust events, reputation scores, recognitions, assist consents (both sides), notifications, audit events where the member is the actor;
   - one CSV file per table in `data.json`.

   The ZIP is encrypted with the member's data key and stored in private storage. The member gets a notification with a download link that works for 7 days. Then the daily job deletes the file.
4. **The download view** decrypts and streams the file, only to that member.
5. **Other members' data never appears.** In comments and tickets, other people appear only as member numbers.

**Tests:** the export contains the member's ledger entries and private data; it contains no other member's display name or private data; the link expires after 7 days.

---

### - [x] P14.T04 — Deleting an account completely

**Read:** docs/08 section 7 ("On deletion"); P01.T08.
**Files:** `apps/members/services.py` (`delete_account`), `apps/privacy/models.py` (DeletionRecord), `apps/privacy/management/commands/reapply_deletions.py`, `apps/privacy/tests/test_delete.py`

**Do:**
1. **Extend `delete_account` (P01.T08)** so that it also:
   - deletes allauth's `EmailAddress` and `Authenticator` rows of the user, and the member's notifications;
   - sets `display_name` to "Former member <number>", clears `postcode`, and sets `public_profile = False`;
   - shows comments and tickets by the member as written by "a former member", and keeps their text, which belongs to the record of decisions. A member who wants a particular text removed can flag it for privacy (P06.T08) before deleting;
   - deletes private files from the disk;
   - deletes the member's pending data exports;
   - writes a `DeletionRecord` (`member_number`, `deleted_at`), which holds no personal data.
2. **Backups still hold the old rows** for up to 12 months, but their encrypted fields are unreadable because the data key is gone. The plain email address and display name stay readable in old backups. So after any restore, run **`reapply_deletions`**, which repeats step 1 for every `DeletionRecord`. The restore procedure (T09) calls it, and the data map states the 12 months.
3. **Wipe jobs that already exist** (outside customers' contacts after 90 days, P10.T02) are listed in the data map with their times.

**Tests:**
- `test_hf14_deleted_member_leaves_no_plaintext`: after deletion, search every text and char field of every model for the member's email address and display name, and find none;
- `reapply_deletions` on a database restored from before the deletion removes them again.

---

### - [ ] P14.T05 — Changing the keys

**Read:** docs/08 section 4 ("Key rotation").
**Files:** `apps/members/crypto.py`, `apps/members/management/commands/rotate_master_key.py`, `apps/members/management/commands/rotate_hmac_key.py`, `apps/members/management/commands/generate_keys.py`, `apps/members/tests/test_rotation.py`

**Do:**
1. **An old key during the change.** The new setting `UNICORN_OLD_MASTER_KEYS` is optional and comma-separated. `_master()` becomes a `MultiFernet([new] + old)`, so data encrypted with an old key can still be read during rotation. The system key (HKDF, P08.T02) is derived from each key in the same way.
2. **A registry of encrypted fields:** `SYSTEM_ENCRYPTED_FIELDS` lists every `(model, field)` encrypted with `system_encrypt`. A test checks that every field ending in `_enc` is in the list.
3. **`rotate_master_key`:** run it after the operator has put the new key in `UNICORN_MASTER_KEY` and the old one in `UNICORN_OLD_MASTER_KEYS`. It then:
   - re-wraps every `DataKey` with the new key;
   - re-encrypts every registered system-encrypted field;
   - works in batches of 500, each in its own transaction;
   - can safely be run twice;
   - prints only counts, never keys or data.

   When it reports 0 left, the operator removes the old key from `.env` and restarts.
4. **`rotate_hmac_key`:** recomputes every `MemberHash` (P01.T05) from the decrypted private data and the email with the new `UNICORN_HMAC_KEY`. Members whose key was destroyed have no hashes left anyway.
5. **`generate_keys`:** prints a new Fernet key and a new HMAC key, for the operator to copy into `.env`. It never writes them to a file or a log.
6. **docs/08 section 4:** add the exact steps, and that it is done yearly and whenever an operator leaves.

**Tests:** after rotation, all private data and system-encrypted fields decrypt with the new key alone; running it twice changes nothing more; the HMAC rotation still detects a duplicate email.

---

### - [ ] P14.T06 — Headers, cookies, content rules, the admin

**Read:** docs/08 sections 3–4.
**Files:** `unicorn/settings.py`, `apps/core/middleware.py`, `templates/base.html`, `static/css/unicorn.css`, `unicorn/urls.py`, `apps/core/tests/test_security_headers.py`

**Do:**
1. **Settings when `DEBUG` is False:**
   - `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`, `SECURE_SSL_REDIRECT = True`;
   - `SECURE_HSTS_SECONDS`, read from the environment: 3600 at first, and 31536000 once the site has run for a week without problems;
   - `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE = "Lax"`;
   - `SESSION_COOKIE_AGE = 1209600` (2 weeks) and an idle limit of 12 hours, checked by a small middleware that stores the last activity in the session;
   - `X_FRAME_OPTIONS = "DENY"`, `SECURE_REFERRER_POLICY = "same-origin"`, `SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"`;
   - `CSRF_TRUSTED_ORIGINS` from `SITE_URL`.
2. **Content Security Policy** with `django-csp`. Version 4 uses `CONTENT_SECURITY_POLICY = {"DIRECTIVES": {...}}` with `csp.constants.SELF`; check the installed version's documentation. The directives:
   - `default-src 'self'`, `script-src 'self'`, `style-src 'self'`;
   - `img-src 'self' data:`, `font-src 'self'`, `connect-src 'self'`;
   - `frame-ancestors 'none'`, `form-action 'self'`, `base-uri 'self'`, `object-src 'none'`.

   htmx adds a `<style>` element for its loading indicator unless told not to. So add `<meta name="htmx-config" content='{"includeIndicatorStyles": false}'>` to `base.html`, and put the `.htmx-indicator` rules in `unicorn.css`.
3. **No inline scripts or styles:** write `test_templates_have_no_inline_script_or_style`. It fails on any `<script>` without `src`, any `style="` attribute and any `on…=` event attribute in `templates/` and `apps/*/templates/`.
4. **The admin:**
   - its path comes from the environment (`ADMIN_PATH`, never `admin/`);
   - it is read-only for everyone (CLAUDE.md section 7);
   - a middleware lets only `is_staff` users through, and only those with a passkey (an allauth `Authenticator` of type `webauthn`);
   - Django admin's own login page redirects to the allauth login.
5. **`manage.py check --deploy`** with production-like settings shows no warnings. Write any warning you cannot fix, with the reason, in docs/12 section 3.

**Tests:** the headers are present on a page; the inline check passes; a staff user without a passkey cannot open the admin; an idle session ends after 12 hours.

---

### - [ ] P14.T07 — Legal pages and third-party notices

**Read:** docs/08 section 8 ("Legal pages"); legal frame (`../Unicorn-simulation/docs/real_world/4_legal_frame.md`) sections 1, 7 and 10.
**Files:** `content/legal/imprint.md`, `content/legal/privacy.md`, `content/legal/terms.md`, `THIRD_PARTY.md`, `apps/core/views.py`, `apps/core/urls.py`, `templates/core/legal.html`, `apps/core/tests/test_legal_pages.py`

**Do:**
1. **The pages** `/imprint/`, `/privacy/`, `/terms/`, `/contract/` (the current membership contract, P01.T03) and `/third-party/` render Markdown files from `content/legal/`. They are public, linked from the footer, and changed only by a release.
2. **Every legal text starts with** "DRAFT — to be written with lawyers". The drafts contain:
   - **imprint:** the association's name, its address (the post box), the board, the register court and number, a contact email (all as `<to fill in>`);
   - **privacy:** the controller, the purposes and legal bases (from the data map, T01), the retention times, the recipients (none outside the EU), the member's rights, the right to complain to a supervisory authority, the contact;
   - **terms:** the rules of use, the notice-and-action procedure for flags (P06.T08), and that Unicorn is not a bank and never moves money (HF-12).
3. **`THIRD_PARTY.md`** and `/third-party/` list each library shipped in `static/vendor/` with its licence (copy the licence headers from the downloaded files). P12.T01 adds the postcode data's attribution to the same file.
4. **The launch check** (P15.T09) warns while any legal page still contains "DRAFT" or `<to fill in>`.

**Tests:** each page loads without login; the footer links to each page; the third-party page names Bootstrap and htmx.

---

### - [ ] P14.T08 — The licence and the source link (HF-19)

**Read:** docs/01 rule HF-19.
**Files:** `LICENSE`, `pyproject.toml` (`license`), `templates/base.html` (footer), `unicorn/settings.py` (`SOURCE_URL`, `UNICORN_VERSION`), `apps/core/tests/test_hf19.py`

**Do:**
1. **`LICENSE`:** the full, unchanged text of the GNU Affero General Public License version 3. It is already in the repository (downloaded from `https://www.gnu.org/licenses/agpl-3.0.txt`); check that it is still unchanged. In `pyproject.toml`, set `license = "AGPL-3.0-or-later"` (the owner may choose "version 3 only" instead: docs/12, owner question 14).
2. **The source link.** The AGPL asks that people who use the app over the network can get its source. The footer of every page shows "Source code" (linking to `SOURCE_URL` from the environment) and the running version (`UNICORN_VERSION`, set by the release script, P15.T06).
3. **Nothing can be sold:** there is no paid-access feature. Write `test_hf19_licence_and_source_link`, which checks that:
   - `LICENSE` contains "GNU AFFERO GENERAL PUBLIC LICENSE" and "Version 3";
   - the rendered home page contains a link to `SOURCE_URL`;
   - no Python file in `apps/` contains the words `paywall`, `subscription` or `premium`.

**Tests:** `test_hf19_licence_and_source_link`.

---

### - [ ] P14.T09 — Backups and the restore test

**Read:** docs/08 section 6.
**Files:** `deploy/backup.sh`, `deploy/restore_test.sh`, `deploy/README.md`, `apps/core/models.py` (RestoreTest), `apps/core/management/commands/record_restore_test.py`, `apps/core/tests/test_restore_record.py`

**Do:**
1. **`deploy/backup.sh`** runs nightly as the virtual server's user (cron, P15.T07). It uses `set -euo pipefail` and:
   1. `mariadb-dump --single-transaction --routines --triggers --hex-blob --default-character-set=utf8mb4 <db>`, with the database password read from `~/.my.cnf` (chmod 600), never from the command line;
   2. `tar` of `~/private_media`;
   3. compresses both with `gzip`, and encrypts them with **`age`** to the backup public key in `~/backup_recipient.txt`. The private key is never on the server: two operators keep it offline. If `age` is not installed, use `gpg --encrypt --recipient` with a public key in the same way;
   4. writes `~/backups/unicorn-<YYYY-MM-DD>.tar.age` and a SHA-256 checksum file;
   5. copies them with `rsync -e ssh` to the second machine (`BACKUP_TARGET` in `~/.backup.env`), using an SSH key that may only write to the backup folder there;
   6. keeps 30 daily and 12 monthly copies (the copy of the 1st of each month), both locally and on the second machine, and deletes older ones;
   7. writes the time of success to `~/run/last_backup`, which `/healthz` reads (P15.T08).

   Locally on the Mac, `mysqldump` takes the place of `mariadb-dump`: the script uses whichever exists.
2. **`deploy/restore_test.sh <backup file>`** runs monthly on the **staging** server, started by an operator over SSH, who sends the private key through standard input. The key never touches the disk:

   ```
   ssh staging '~/app/deploy/restore_test.sh /path/unicorn-2027-03-01.tar.age' < ~/keys/unicorn-backup.key
   ```

   The script:
   1. decrypts with `age -d -i -`;
   2. loads the dump into the database `<staging user>_restore`;
   3. runs `audit_books --full` against it;
   4. compares the chain heads with the fingerprints published on that day;
   5. runs `reapply_deletions` (T04);
   6. drops the restore database;
   7. prints `RESTORE TEST OK` or `RESTORE TEST FAILED` with the reasons.

   The operator then records the result on production: `ssh production '~/app/deploy/manage.sh record_restore_test --ok --backup-date 2027-03-01 --notes "..."'` (or `--failed`). `deploy/manage.sh` comes in P15.T04.

   Staging never holds the production master key, so personal fields stay unreadable there.
3. **`RestoreTest`:** `ran_at`, `backup_date`, `ok`, `notes`, `operator_number`. The open-books page shows the date of the last successful restore test. If there has been none for 35 days, a warning ticket goes to the elected auditors.
4. **`deploy/README.md`** explains to the operators, in plain steps:
   - making the `age` key pair (`age-keygen -o unicorn-backup.key`, then copy the public line to the server);
   - where the two copies of the private key are kept;
   - how to restore after a disaster: a new box, then phase 15 T02–T05, then decrypt the last backup, load it, run `reapply_deletions`, run `audit_books --full`, and compare with the last published fingerprint.

**Tests:** `record_restore_test` stores a row; the 35-day warning ticket is created (`freezegun`); `bash -n` passes on both scripts (a test runs `bash -n deploy/*.sh`).

---

### - [ ] P14.T10 — Logs without personal data

**Read:** docs/08 section 8.
**Files:** `unicorn/settings.py` (LOGGING, ADMINS), `apps/core/logging.py`, `apps/core/middleware.py` (request id), `apps/core/tests/test_logging.py`

**Do:**
1. **A request id:** a middleware sets `request.id` (from `X-Request-ID`, or a new random hex string), adds it to the response header, and puts it into every log record.
2. **`RedactFilter`** on every handler replaces email addresses, IBANs (`[A-Z]{2}\d{2}[A-Z0-9]{10,30}`), Fernet tokens (`gAAAAA…`) and long hex strings with `[removed]`.
3. **LOGGING:**
   - application logs go to standard error (gunicorn and journald keep them; retention in P15.T08), with the level, the time, the request id, the member number (if any) and the message;
   - errors are mailed to `ADMINS` (from the environment);
   - `django.security` is logged at WARNING;
   - SQL queries are never logged in production.
4. **Error pages** show the request id, so that a member can report it without sending any personal data.

**Tests:** a log message with an email and an IBAN comes out redacted; the response carries `X-Request-ID`.

---

### - [ ] P14.T11 — Accessibility and the installable app

**Read:** docs/09 ("Install on phones"); docs/05 principle 5 (anyone can take part).
**Files:** `templates/base.html`, `templates/partials/*.html`, `static/css/unicorn.css`, `static/sw.js`, `apps/core/tests/test_accessibility.py`

**Do:**
1. **The basics of WCAG 2.1 AA:**
   - a "Skip to content" link;
   - visible focus;
   - every form field has a `<label>`, and errors are named in words, not only by colour;
   - colour contrast of at least 4.5:1 (check Bootstrap's defaults and the own CSS);
   - `aria-live="polite"` on the regions htmx replaces;
   - buttons are `<button>`, links are `<a>`;
   - pages work with the keyboard alone and at 200% zoom.
2. **Plain language:** short sentences; the glossary words (CLAUDE.md); no technical errors shown.
3. **The installable app:**
   - the service worker's cache name includes `UNICORN_VERSION`, so each release replaces old files;
   - the offline page explains that Unicorn needs a connection for now;
   - the manifest has `lang`, `description` and maskable icons.
4. **Test page by page:** render the main pages (home, market, an offer, a ticket, "My account", the hours page) in tests and check with `html.parser` that every `input`, `select` and `textarea` has a label, every `img` has `alt`, and the page has one `h1`.

**Tests:** `test_main_pages_have_labels_alt_and_one_h1`; the service worker contains the version.

---

### - [ ] P14.T12 — Privacy documents for the association

**Read:** docs/08 section 7 ("A data-protection impact assessment"); docs/12 (lawyer questions).
**Files:** `docs/privacy/records_of_processing.md`, `docs/privacy/dpia_template.md`, `docs/privacy/breach_procedure.md`

**Do:**
1. **Records of processing** (GDPR Art. 30): one section per purpose (membership, the UNIQ books, the trade fund, outside sales, tickets and votes, care and benefit claims), built from the data map.
2. **A DPIA template** (Art. 35) for care services and benefit claims: the description, necessity, risks, measures, and the sign-off by the board. The board fills it in before care services start.
3. **A breach procedure** (Art. 33–34): who decides, notifying the supervisory authority within 72 hours, informing members, a log of breaches, and rotating the keys (T05).
4. All three start "DRAFT — to be checked by lawyers" and are linked from docs/08 section 7.

**Done when:** the three files exist and docs/08 links to them.

---

### - [ ] P14.T13 — A security check before going live

**Files:** `docs/security_checklist.md`, `apps/core/tests/test_permissions_matrix.py`

**Do:**
1. **The checklist** (run before each release, P15.T06):
   - `check --deploy` is clean;
   - the pinned packages have no published security advisories (read the Django security announcements and the release notes of the other packages);
   - no secret is in the repository (search for `SECRET`, `KEY=`, `password`);
   - the admin path is secret, and the admin works only with a passkey;
   - the backup of last night exists, and the last restore test is less than 35 days old.
2. **The permission matrix test:** for each URL that changes data, a test that an anonymous user, an unverified member and an unrelated member are refused. List the URLs from `unicorn/urls.py` automatically, and fail if a new URL that accepts POST has no entry in the test's table.

**Tests:** `test_every_post_url_is_in_the_permission_matrix`.

---

## Acceptance check for phase 14

1. A member downloads their data, deletes their account, and a search of the database finds neither their email nor their display name.
2. The master key is rotated on a copy of the data, and everything still decrypts.
3. A backup is made, encrypted and restore-tested on staging, and the result appears on the open-books page.
4. `check --deploy` is clean, the CSP header is present, and the inline-script test passes.
5. The footer shows the source link and the version; `test_hf19_licence_and_source_link` passes.
6. Add a line to PLAN.md "Progress".
