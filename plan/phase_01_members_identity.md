# Phase 01 — Members, identity and the digital contract

**Goal:** people sign up with an email code or a passkey, sign the one digital contract, are verified (two vouches + an in-person check), keep their personal data encrypted, build a work portfolio, and can leave.
**Read first:** docs/08 sections 2–4, docs/00 ("The legal frame"), docs/01 rules HF-8, HF-13, HF-14.

---

### - [x] P01.T01 — Accounts with django-allauth: email codes and passkeys

**Read:** docs/08 section 3.
**Files:** `unicorn/settings.py`, `unicorn/urls.py`, `templates/account/*.html`, `templates/mfa/*.html`, `apps/members/tests/test_login.py`

**Do:**
1. **Install apps:** `allauth`, `allauth.account`, `allauth.mfa`. Add `allauth.account.middleware.AccountMiddleware`. Include `allauth.urls` under `accounts/`.
2. **Settings.** Check each name against the documentation of the **installed** allauth version, and if a name differs, use the documented one and note it in docs/12:
   - `ACCOUNT_LOGIN_METHODS = {"email"}`, `ACCOUNT_SIGNUP_FIELDS = ["email*"]` (no password field), `ACCOUNT_USER_MODEL_USERNAME_FIELD = None`;
   - `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`, `ACCOUNT_LOGIN_BY_CODE_ENABLED = True`;
   - `ACCOUNT_REAUTHENTICATION_TIMEOUT = 900`;
   - `MFA_SUPPORTED_TYPES = ["webauthn", "recovery_codes"]`, `MFA_PASSKEY_LOGIN_ENABLED = True`, `MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = DEBUG`;
   - `SESSION_COOKIE_AGE = 14 * 24 * 3600`, `SESSION_COOKIE_SECURE = not DEBUG`, `CSRF_COOKIE_SECURE = not DEBUG`.
3. **Templates.** Override the account and mfa templates so that they extend `base.html`, with plain texts in `{% translate %}`. The login page offers "Log in with a passkey" first and "Send me a login code by email" second.
4. **Email.** Login codes are sent by email (the console backend in development).

**Tests:**
- signing up with only an email creates a user with an unusable password;
- login by code works (read the code from `mail.outbox`);
- the login page contains the passkey button.

---

### - [x] P01.T02 — The member

**Read:** docs/10 (Member, Former member), docs/08 section 2.
**Files:** `apps/members/models.py`, `apps/members/services.py`, `apps/members/views.py`, `apps/members/urls.py`, `apps/members/templates/members/*.html`, `apps/members/tests/test_member.py`

**Do:**
1. **`Member` model:**
   - `user` (OneToOne to User, PROTECT);
   - `number` (CharField(12), unique; format `M-XXXX-XXXX` with 8 random characters from the Crockford base-32 alphabet `0123456789ABCDEFGHJKMNPQRSTVWXYZ`);
   - `display_name` (CharField(60), shown to others);
   - `status`: `applicant`, `member`, `suspended`, `former`;
   - `is_founder` (bool), `is_identity_helper` (bool);
   - `joined_at` (contract signed), `verified_at`, `left_at`, `deleted` (bool);
   - `country` (CharField(2), ISO 3166-1), `currency` (CharField(3), ISO 4217, default `EUR`), `timezone` (default `Europe/Berlin`), `postcode` (CharField(12): the area only, never a street address);
   - `public_profile` (bool, default False), `draw_pause_until` (date, null), `receives_benefits` (bool), `last_active_at`.
2. **Services:**
   - `create_applicant(user, display_name, country, currency, postcode) -> Member` makes a unique number (retry on collision);
   - `is_verified(member) -> bool` is true only for status `member` (HF-13);
   - `active_members()` returns members with status `member`.
   - **`CurrentMemberMiddleware`** (`apps/members/middleware.py`, after the authentication middleware) sets `request.member` to the logged-in user's `Member`, or `None`. **Every view and template gets the member from `request.member`, never from `request.user.member`.** Phase 13 (P13.T10) changes only this middleware to let a helper act for someone (CLAUDE.md section 5 states the rule).
3. **Pages:**
   - "My account" (`/me/`): number, display name, status, what is still missing for verification, links;
   - a public profile (`/m/<number>/`): display name and, if `public_profile`, the portfolio (P01.T07).

   A member sees their own private details only on "My account".

**Tests:**
- the number format and uniqueness;
- `test_hf13_is_verified_false_for_applicant_and_former`;
- one member cannot see another's "My account".

---

### - [x] P01.T03 — The one digital contract

**Read:** docs/00 ("The legal frame"); `../Unicorn-simulation/docs/real_world/4_legal_frame.md` section 1 items 1–3.
**Files:** `apps/members/models.py` (ContractTemplate, Signature), `apps/members/fixtures/contracts.json`, `apps/members/services.py`, `apps/members/templates/members/contract.html`, `apps/members/tests/test_contract.py`

**Do:**
1. **Models:**
   - `ContractTemplate`: `kind` (`membership`, `holder_agreement`, `council_rules`, `mandate`, `assist_consent`, `outside_seller`), `version` (int), `title`, `body_md` (Markdown), `sha256` (of `body_md`, set on save), `valid_from`, `is_current`. Unique (`kind`, `version`).
   - `Signature`: `template` (FK, PROTECT), `member` (FK, PROTECT), `signed_at`, `text_sha256`, `method` (`passkey`, `code`, `click`), `context` (JSON; for example the unit id for council rules).

     Append-only.
2. **Fixture: one `membership` template, version 1.** Its body has five headed parts: Statute of the association (post box); Trust agreement for the trade fund; Consent to the tax paperwork; Privacy notice; Rules of the trust rating. Each part starts with the line **"DRAFT — to be written with lawyers (docs/12, section 2)"** and then summarises, in plain words, the matching points of docs/00 "The legal frame", docs/07 sections 2 and 5, and docs/08 section 7.
3. **`sign(member, template, method, context=None)`:** creates the `Signature` with the template's hash.
4. **Contract page:** shows each part, with one tick box per part ("I have read and accept …") and the button "Sign". The page shows the hash and the version.

**Tests:**
- the signature stores the template hash;
- signatures cannot be changed or deleted;
- signing requires all tick boxes.

---

### - [x] P01.T04 — Encrypted personal data and private files

**Read:** docs/08 section 4; CLAUDE.md "Security and privacy".
**Files:** `apps/members/crypto.py`, `apps/members/models.py` (DataKey, MemberPrivate, PrivateFile), `apps/members/services.py`, `apps/members/views.py` (file download), `apps/members/tests/test_crypto.py`

**Do:**
1. **`crypto.py`:**
   - `_master()` returns `Fernet(settings.UNICORN_MASTER_KEY)`;
   - `create_data_key(member)` generates `Fernet.generate_key()` and stores it **encrypted with the master key** in `DataKey.wrapped`;
   - `_member_fernet(member)` unwraps the key, and raises `KeyDestroyed` if it was shredded;
   - `encrypt_for(member, data: bytes) -> bytes` and `decrypt_for(member, token: bytes) -> bytes`.
2. **Models:**
   - `DataKey`: `member` OneToOne, `wrapped` (BinaryField), `created_at`, `destroyed_at` (null).
   - `MemberPrivate`: `member` OneToOne, `blob` (BinaryField): an encrypted JSON object with the keys `legal_name`, `street`, `city`, `phone`, `birth_date`, `iban`, `bic`, `bank_name`; `updated_at`.
   - `PrivateFile`: `owner` (Member), `kind` (`licence`, `receipt`, `benefit_document`, `other`), `path` (relative to `PRIVATE_MEDIA_ROOT`), `name_enc` (BinaryField: the encrypted original file name), `size`, `content_type`, `created_at`.
3. **Services:**
   - `set_private(member, **fields)` merges into the blob;
   - `get_private(member) -> dict` returns `{}` with `"deleted": True` if the key is destroyed;
   - `store_private_file(member, uploaded_file, kind) -> PrivateFile`: encrypts the bytes and writes them to `PRIVATE_MEDIA_ROOT/<member number>/<random>.bin`; at most 10 MB; only PDF, JPEG and PNG;
   - `read_private_file(pf) -> (name, bytes)`;
   - `shred(member)` sets `wrapped = b""` and `destroyed_at = now`.
4. **Download view `/files/<id>/`:** allowed only when `can_view_file(viewer, pf)` is true. For now the owner only; later phases add confirmers seated on the ticket that needs the file. Sends `Content-Disposition: attachment`.
5. `PRIVATE_MEDIA_ROOT` comes from the environment (default `BASE_DIR / "private_media"`, which is git-ignored).

**Tests:**
- set and get private data;
- `test_hf14_blob_contains_no_plaintext`: the raw `blob` does not contain the legal name;
- the file round-trip works;
- after `shred`, `get_private` returns deleted and the file cannot be read;
- another member gets 403 on the download view.

---

### - [x] P01.T05 — Identity: vouches, in-person checks, duplicates, founders

**Read:** docs/08 section 2.
**Files:** `apps/members/models.py` (Vouch, InPersonCheck, MemberHash), `apps/members/services.py`, `apps/members/views.py`, `apps/members/templates/members/vouch.html`, `.../identity_check.html`, `apps/members/management/commands/bootstrap_founders.py`, `apps/members/tests/test_identity.py`

**Do:**
1. **Models:**
   - `Vouch`: `voucher` (Member), `vouchee` (Member), `statement` (Text), `created_at`; unique (voucher, vouchee). Append-only.
   - `InPersonCheck`: `helper` (Member), `member` (Member), `seen_on` (date), `town` (CharField(80)), `created_at`. Append-only. Never store an ID number or a copy of an ID.
   - `MemberHash`: `member`, `kind` (`email`, `phone`, `iban`, `name_birth`), `value` (CharField(64), `hmac_hex` of the normalised value), indexed (not unique).
2. **Services:**
   - **`vouch(voucher, vouchee, statement)`:** the voucher must be verified and not the vouchee; at most `membership.vouches_per_voucher_per_month` vouches a month.
   - **`record_in_person_check(helper, member, seen_on, town)`:** the helper must be verified, an identity helper, and must not have vouched for this member.
   - **`try_verify(member)`:** if the member has at least `membership.vouches_needed` vouches, and an in-person check exists (when `membership.in_person_check` is true), then set status `member` and `verified_at`, and call the hooks in `VERIFIED_HOOKS` (a list other apps add to; P02 opens the accounts).
   - **`update_hashes(member)`:** recompute the member's hashes from the user's email and the private data. If another member has the same hash of the same kind, record `AuditEvent(verb="duplicate_suspected")` and set `Member.status = "applicant"` if they were not yet verified. P06 turns this into a flag ticket.
3. **Pages:**
   - "Vouch for a member" (enter a member number and a statement);
   - "Identity checks" (only for identity helpers): record a check;
   - "My account" shows the vouches and checks received.
4. **`bootstrap_founders --emails a@x b@y …`:** for the founding meeting.
   - It marks the listed members (who must have signed the contract) as `is_founder = True` and `member`.
   - It records one `AuditEvent(verb="founders_verified", data={"numbers": [...]})`.
   - It refuses to run once more than `membership.founders_target` verified members exist.

**Tests:**
- two vouches plus an in-person check verify the member;
- self-vouching fails;
- the monthly vouch limit holds;
- a helper who vouched cannot also check;
- a duplicate email hash is detected;
- bootstrap refuses after the target.

---

### - [x] P01.T06 — Joining: sign-up flow, trial year, notices

**Read:** docs/02 section 3 (25 founders, trial year); `config/defaults.yaml` `membership.*`.
**Files:** `apps/members/models.py` (SiteState, Waitlist), `apps/members/views.py`, `apps/members/forms.py`, `apps/members/templates/members/join_*.html`, `apps/members/tests/test_join.py`

**Do:**
1. **`SiteState`:** a single-row model with `launched_at` (null until the founders launch Unicorn).
2. **Sign-up flow:**
   1. email and code (allauth);
   2. the "About you" form: display name, country, currency, postcode, legal name, date of birth, phone (optional), and "I receive means-tested benefits" (yes or no);
   3. the contract (P01.T03);
   4. "What happens next": who can vouch, where to find an identity helper.

   Store the private fields with `set_private`, then `update_hashes`.
3. **Checks:**
   - Refuse if the person is younger than `membership.min_age` years: "You must be 18 or older to join."
   - If `launched_at` is set and is less than `membership.trial_months` months ago, and the person is not a founder candidate, show "Unicorn is in its founders' trial year until <date>" and offer the `Waitlist` (email only, deleted after the invitation or after 24 months).
   - If `country != "DE"`, show the notice from docs/07 section 11 ("the laws of your country apply …").
   - If they receive benefits, show the warning from docs/06 section 11.
4. **"Unicorn launches" button.** Shown to founders when `founders_target` verified founders exist and `launched_at` is empty. It needs a decision of all founders; until P07, record the click of every founder and set `launched_at` when all have clicked.

**Tests:**
- a full sign-up creates an applicant with encrypted data and a signature;
- an under-18 person is refused;
- the waitlist is used during the trial year;
- the non-German notice is shown.

---

### - [ ] P01.T07 — Work portfolio and licences

**Read:** docs/06 section 3 ("The job portfolio"); docs/07 section 7.
**Files:** `apps/members/models.py` (Skill, Licence, Availability), `apps/members/views.py`, `apps/members/templates/members/portfolio*.html`, `apps/members/tests/test_portfolio.py`

**Do:**
1. **Models:**
   - `Skill`: `member`, `trade_name` (CharField(80)), `trade_code` (CharField(16), blank: a CPA code such as `CPA_Q87_88`), `description`, `level` (`learning`, `able`, `expert`).
   - `Licence`: `member`, `kind` (`legal_advice`, `tax_advice`, `health_care`, `childcare_permit`, `master_craftsman`, `food_registration`, `passenger_transport`, `other`), `document` (FK PrivateFile), `status` (`submitted`, `verified`, `rejected`, `expired`), `expires_on` (null), `verified_at`, `decided_by` (CharField(32): a ticket number later).
   - `Availability`: `member` OneToOne, `hours_per_week` (Decimal), `note`.
2. **Pages:**
   - edit my portfolio (skills, availability);
   - upload a licence (stored with `store_private_file`; status `submitted`; verification by confirmers comes in P06);
   - the public portfolio on the profile page, if `public_profile`: skills, units (later), "licence verified" badges without documents.
3. **`has_verified_licence(member, kind) -> bool`:** a verified licence that is not expired.

**Tests:**
- the licence document is private (another member gets 403);
- `has_verified_licence` respects `expires_on`.

---

### - [ ] P01.T08 — Leaving and deleting the account

**Read:** docs/08 section 7 ("On deletion"); docs/01 HF-8; docs/07 section 2 ("Leaving").
**Files:** `apps/members/services.py`, `apps/members/views.py`, `apps/members/templates/members/leave.html`, `apps/members/tests/test_leave.py`

**Do:**
1. **`LEAVE_CHECKS`:** a list of functions `check(member) -> list[str]` that return blocking reasons in plain words. Other apps add to it (P03: council responsibility; P07: active mandates; P08: held fund euros).
2. **`leave(member)`:** runs the checks; if any reason is returned, refuse and show the reasons. Otherwise set status `former` and `left_at`, and record an `AuditEvent`. The UNIQ account stays (HF-8): former members can still log in and spend.
3. **`delete_account(member)`:**
   1. calls `leave` if needed;
   2. shows (in the view, before confirming) the warning from docs/08 section 7: remaining UNIQ stay in the books but can no longer be spent;
   3. then calls `shred(member)`, deletes the `MemberHash` rows, sets the user's email to `deleted-<number>@invalid`, `is_active = False`, and `Member.deleted = True`.

   The `Member` row and its number stay (the books need them).
4. **Pages:** "Leave Unicorn" and "Delete my account", each with a clear explanation and a confirmation.

**Tests:**
- a blocking check stops leaving;
- after leaving the member is `former` and can still log in;
- after deletion the private data is gone and the hashes are deleted.

---

### - [ ] P01.T09 — Sensitive actions and login notices

**Read:** docs/08 section 3.
**Files:** `apps/core/decorators.py`, `apps/members/signals.py`, `apps/members/tests/test_sensitive.py`

**Do:**
1. **`sensitive_action`:** a view decorator that wraps allauth's `reauthentication_required` (use the name exported by the installed version). Later phases use it for approving hours, confirming payments, voting, signing, changing bank details and holder actions.
2. **On every successful login,** email the member: "New login to your Unicorn account on <date, time>. If this was not you, …" (plain text; no IP address stored).
3. **Update `Member.last_active_at`** at most once an hour, in a middleware.

**Tests:**
- a view with `sensitive_action` redirects to re-authentication when the last authentication is older than 15 minutes (use `freezegun`);
- a login sends the notice mail.

---

## Acceptance check for phase 01

1. A new person signs up with an email code, adds a passkey, fills "About you", and signs the contract.
2. Two founders vouch, an identity helper records a check, and the person becomes `member`.
3. Their private data is encrypted in the database; deleting the account makes it unreadable.
4. `make check` passes, and `scripts/hf_coverage.py` lists tests for HF-13 and HF-14.
5. Add a line to PLAN.md "Progress".
