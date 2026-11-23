# Phase 13 — Unions, local and consumers' councils, reputation, recognition, acting for others

**Goal:** units of related trades form unions that advise but never command. Members of an area form a local council for local matters. Any members can form a consumers' council. Helpful answers build a reputation that is used only to suggest who might answer a ticket. Recognition replaces extra pay as the reward. A helper can act for a member without a device, and every such action is marked "on behalf of".
**Read first:** docs/05 sections 1 (principle 5), 2 ("The secretariat"), 7, 10 and 11; docs/01 rules HF-2, HF-11, HF-15 and HF-20; book pp. 68, 70 and 139–141.

---

### - [x] P13.T01 — Shared counting and rotation helpers

**Files:** `apps/core/tally.py`, `apps/core/rotation.py`, `apps/units/services.py` (use them), `apps/core/tests/test_tally.py`, `apps/core/tests/test_rotation.py`

**Do:**
1. **`count(votes, rule, quorum, size) -> TallyResult`:**
   - `votes` is a list of `"yes"`, `"no"` or `"abstain"`; `rule` is `majority`, `two_thirds` or `consensus`; `quorum` is a share; `size` is the number of people who may vote;
   - `TallyResult` has `approved`, `quorum_met`, `yes`, `no`, `abstain`, `turnout`;
   - the counting rules are exactly those of P03.T04.
2. **`next_in_rotation(candidates, days_held, declined) -> Member | None`:** the candidate with the fewest days held (ties: the earliest `joined_at`), skipping anyone in `declined`.
3. **P03 uses them:** change `CouncilDecision` tallying (P03.T04) and `units.rotate` (P03.T05) to call these helpers. Their behaviour must not change, and P03's tests must still pass unchanged.

**Tests:** the P03 cases, run directly on `count`; `next_in_rotation` with ties and a decline.

---

### - [x] P13.T02 — Unions: forming, joining, leaving

**Read:** docs/05 section 7 ("Unions").
**Files:** `apps/bodies/` (new app), `apps/bodies/models.py` (Union, UnionMembership, UnionRules), `apps/bodies/services.py`, `apps/tickets/types.py` (add `union_join`, `union_leave`), `apps/bodies/tests/test_unions.py`

**Do:**
1. **Models:**
   - `Union`: `name` (unique), `slug`, `trade_codes` (JSON list of `Unit.trade_code` values), `description`, `status` (`forming`, `active`, `dissolved`), `created_at`, `created_by_unit` (FK Unit).
   - `UnionMembership`: `union`, `unit`, `joined_at`, `left_at` (null), `ticket` (FK Ticket); a unit has at most one active membership per union.
   - `UnionRules`: the same fields as `CouncilRules` (P03.T03) without `hours_approval` and `admission`, with `union` instead of `unit`. Version 1 comes from the `governance.council.*` parameters.
2. **Forming:** a unit's responsible fills in "Form a union" (name, trade codes, description). This creates the union with status `forming` and a `union_join` ticket for the founding unit.
3. **`union_join` ticket:** scope `unit`, decided by that unit's council (a council decision of kind `other`; a one-person unit decides directly). On approval, the action creates the `UnionMembership`. A union becomes `active` once it has `governance.unions.min_councils` member units.
4. **Inviting:** the union page has "Invite a unit", which notifies that unit's responsible and creates a draft `union_join` ticket for it.
5. **`union_leave`:** the same way. A union with fewer than `min_councils` member units returns to `forming`, and after 90 days in `forming` it is `dissolved`.
6. **Replace the placeholder fields** with foreign keys:
   - `Ticket.scope_union_id` (P06.T01) becomes `Ticket.scope_union` (FK Union, null);
   - `ExpertAdviser.nominated_by_union_id` (P11.T04) becomes `nominated_by_union` (FK Union, null).

   All existing values are null, so remove the integer field and add the foreign key in one migration. The migration first checks with `RunPython` that no row has a value, and stops with a clear error if one does.

**Tests:**
- a union becomes active with the second unit;
- a unit's council decides its own joining;
- a union with one unit left returns to `forming`;
- the migration refuses to run if a placeholder field holds a value.

---

### - [ ] P13.T03 — Union delegates and union decisions

**Read:** docs/05 section 7 ("Delegates", "No power over councils").
**Files:** `apps/bodies/models.py` (UnionDelegate, UnionDecision, UnionVote), `apps/bodies/services.py`, `apps/bodies/jobs.py`, `apps/bodies/tests/test_union_decisions.py`

**Do:**
1. **`UnionDelegate`:** `union`, `unit`, `member`, `starts_at`, `ends_at` (null while current), `how` (`first`, `rotation`, `handover`), `declined_by` (JSON).
   - The first delegate of a unit is its responsible at the time of joining. A one-person unit's delegate is its member.
   - **Job `bodies.rotate_delegates`** (in `daily`): after `governance.unions.delegate_rotation_months`, the unit's next delegate is chosen by `next_in_rotation` among its council members.
   - Leaving the unit or Unicorn hands the role over at once (a `LEAVE_CHECKS` entry, as in P03.T05).
2. **`UnionDecision` and `UnionVote`:** like `CouncilDecision` and `CouncilVote`. The voters are the current delegates, one vote per member unit; counting uses `count()` with the union's rules. Kinds: `standard`, `recipe_template`, `nominate_expert`, `training`, `rules_change`, `other`.
3. **No power over councils (HF-15, HF-20).** A union decision's action may only:
   - publish union pages and recipe templates (T04);
   - nominate expert advisers (T05);
   - create task lists of union scope;
   - change the union's own rules.

   It may never change a unit, an offer, an hours entry, a council's rules or any parameter. Enforce this with an allow-list of action kinds in `apps/bodies/services.py`.

**Tests:**
- delegates rotate after 6 months;
- one vote per member unit;
- `test_hf20_union_decision_cannot_touch_a_unit` (an action that tries to change a unit raises).

---

### - [ ] P13.T04 — What unions do: advice, standards, recipe templates, mediation, training

**Read:** docs/05 section 7 ("Duties").
**Files:** `apps/bodies/models.py` (UnionPage, RecipeTemplate), `apps/tickets/routing.py`, `apps/catalogue/views.py`, `apps/tickets/draw.py` (mediator pool), `apps/bodies/tests/test_union_duties.py`

**Do:**
1. **Advice on tickets.** In `route(ticket)` (P06.T03), find the ticket's trade: `scope_unit.trade_code`, or the trade code of the offer or item the ticket is about. If an active union covers that trade, notify its current delegates with "Your union is asked to advise".
   - Their comments are marked "Advice from <union> (not binding)" and shown first on the ticket page.
   - The decision method does not change (HF-15).
2. **`UnionPage`** (trade standards, training material): `union`, `title`, `slug`, `body_md`, `version`, `published_at`, `decision` (FK UnionDecision). Publishing or changing a page needs a union decision of kind `standard`.
3. **`RecipeTemplate`:**
   - `union`, `item`, `title`, `notes_md`, `published_at`, `decision` (FK UnionDecision);
   - `inputs` (JSON list: item id, quantity per unit of output, suggested source);
   - `tools` (JSON list: item id, suggested source, uses per output).

   The offer form (P04.T03) gets "Start from a union template". It copies the template into a new draft offer, which the unit then edits and publishes as usual. A template is never a price and never binds a unit.
4. **Mediation inside a trade.** When both parties of a `mediation` ticket (P06.T09) are units of the same union, the draw first uses mediator volunteers who work in that union's other units, and never workers of the parties. If too few are eligible, it falls back to the general pool. Write the choice of pool on the ticket.
5. **Training:** a union decision of kind `training` creates a `task_list` ticket (P07.T08) of scope `union`. Training hours are paid as coordination hours when confirmed.

**Tests:**
- a ticket about a chair offer notifies the woodworkers' union delegates, and its method is unchanged;
- a template creates a draft offer and changes nothing else;
- the mediation draw prefers the union pool and excludes the parties.

---

### - [ ] P13.T05 — Expert advisers named by unions

**Read:** docs/05 section 8 (1 September); P11.T04.
**Files:** `apps/plan/services.py`, `apps/bodies/services.py`, `apps/plan/tests/test_experts_from_unions.py`

**Do:**
1. **Nominating:** a union decision of kind `nominate_expert` names a member and a short statement. The member accepts or declines in the app. On acceptance, an `ExpertAdviser` row is created for the current planning group with `nominated_by_union` set.
2. **The planning group** still approves at most `plan.experts_max` advisers by majority (P11.T04), and advisers still cannot vote in the group.
3. **Volunteers:** once any union is active, members without a union nomination can still volunteer, and the group decides on them in the same way. Mark this choice `# OWNER-CHECK: keep volunteers once unions exist?` (docs/11 lists it among the choices waiting for the owner).

**Tests:** a union nomination reaches the group; the limit of `experts_max` holds; an adviser's vote in the group is refused.

---

### - [ ] P13.T06 — Local councils

**Read:** docs/05 section 7 ("Local councils"); P06.T04 (eligibility for `local` scope).
**Files:** `apps/bodies/models.py` (LocalCouncil, LocalResponsibility), `apps/bodies/services.py`, `apps/bodies/jobs.py`, `apps/tickets/types.py` (add `local_council_open` and `local_decision`), `apps/logistics/models.py` (PickupPoint FK), `apps/bodies/tests/test_local.py`

**Do:**
1. **`LocalCouncil`:** `name`, `country` (CharField(2)), `postcode_prefix` (CharField(12)), `level` (`district`, `town`, `region`, `country`), `status` (`active`, `closed`), `created_at`, `ticket` (FK Ticket); unique (`country`, `postcode_prefix`).
2. **Who belongs:** every verified member whose `country` matches and whose `postcode` starts with the prefix. Membership is computed, never stored, so moving house changes it at once. A member can belong to several nested councils (a district and its town).
3. **Opening:** a `local_council_open` ticket of scope `local`, with `scope_area` = the prefix. It needs at least `governance.local.min_members` members in the area, and it is decided by random confirmers from that area. Fix P06.T04's `local` eligibility to check `country` as well as the postcode prefix (add a `scope_country` field to `Ticket`, default `DE`).
4. **The responsible:** `LocalResponsibility` (`council`, `member`, `starts_at`, `ends_at`, `how`, `declined_by`). Members of the area volunteer on the council page, and **job `bodies.rotate_local`** passes the role on after `governance.local.rotation_months` among the volunteers, using `next_in_rotation`. Without volunteers, the role stays empty, and the page says so.
5. **Local matters** are tickets of scope `local`. Most are `local_decision` tickets (decided by random confirmers from the area; action: record the decision, or run a named local action such as opening a pickup point). The council page lists them, and it shows:
   - the area's needs: demand signals and search misses by members of the area (P05.T12);
   - the pickup points of the area;
   - the helpers for assisted access (T09);
   - local task lists, for example local events.
6. **Pickup points:** replace `PickupPoint.managed_by_local_council_id` (P12.T03) with a foreign key (the same safe migration as in T02). A local council opens or closes a pickup point by a `local_decision` ticket, confirmed by random members of the area.

**Tests:**
- a council cannot open with fewer members than the minimum;
- only members of the area are drawn;
- moving to another postcode changes which councils a member belongs to;
- a pickup point is opened by a local ticket.

---

### - [ ] P13.T07 — Consumers' councils

**Read:** docs/05 section 7 ("Consumers' councils").
**Files:** `apps/bodies/models.py` (ConsumerCouncil, ConsumerMembership, Guideline), `apps/bodies/views.py`, `apps/bodies/tests/test_consumers.py`

**Do:**
1. **`ConsumerCouncil`:** `name`, `topic` (for example "food quality", "accessibility"), `description`, `created_by`, `created_at`, `status`. **`ConsumerMembership`:** `council`, `member`, `joined_at`, `left_at`. Any verified member may create one, join or leave.
2. **`Guideline`:** `council`, `title`, `body_md`, `version`, `published_at`. Members of the consumers' council publish a guideline by a majority of the members who vote within 7 days, counted with `count()`.
3. **Units may declare** "We follow the guideline <title>" on an offer, by a council decision or by a one-person unit's member. The declaration is shown on the offer and can be flagged like any content (P06.T08).
4. **No special power:** a consumers' council files tickets and flags like any member, and each flag counts once per member, never per council.

**Tests:** anyone can join; a guideline needs the members' majority; a declaration can be flagged.

---

### - [ ] P13.T08 — Reputation: helpful answers, used only for suggestions

**Read:** docs/05 section 10 (the table); docs/01 HF-11 and HF-15.
**Files:** `apps/reputation/` (new app), `apps/reputation/models.py` (ReputationScore), `apps/reputation/services.py`, `apps/reputation/jobs.py`, `apps/tickets/routing.py`, `apps/members/views.py` (profile), `apps/reputation/tests/test_reputation.py`

**Do:**
1. **The topic of a comment** is the type of its ticket plus the ticket's trade code, if any (for example `question:wood`).
2. **The score** for a member and topic is the sum, over the `HelpfulMark`s on the member's comments (P06.T02) from the last `reputation.window_months` months, of `0.5 ** (age_days / reputation.half_life_days)`.
   - Marks from one marker to the same author count at most `reputation.max_marks_per_pair_per_month` times a month.
   - Marks from unverified members never count.
3. **Job `reputation.recompute`** (in `daily`) rebuilds `ReputationScore` (`member`, `topic`, `score`, `computed_at`), a cache table that can always be rebuilt.
4. **`suggest_answerers(ticket)`** (replacing the stub of P06.T03): the top `reputation.suggest_count` members for the ticket's topic, then for its trade alone. It excludes:
   - the author;
   - members with a declared conflict;
   - members who switched off "Suggest me for questions" (a setting on their account, on by default).

   Suggested members get one notification, "You might know the answer to T-…". Nothing else happens.
5. **The profile** shows "Helpful answers in the last 12 months: N" (the plain count of marks, not the weighted score). The member can see their own topics and scores.
6. **Never used elsewhere.** Reputation must never touch work, pay, votes, prices, draws or trust. Write `test_hf15_reputation_only_suggests`, which uses `ast` to check that no module in `apps/ledger`, `apps/units`, `apps/catalogue`, `apps/market`, `apps/votes`, `apps/tradefund` or `apps/tickets/draw.py` imports `apps.reputation`.

**Tests:**
- decay halves a mark's weight after 180 days;
- a mark older than 12 months counts nothing;
- the pair limit holds;
- a member who switched suggestions off is never suggested;
- `test_hf15_reputation_only_suggests`.

---

### - [ ] P13.T09 — Recognition instead of extra pay

**Read:** docs/05 section 11 ("Incentives"); docs/01 HF-2.
**Files:** `apps/reputation/models.py` (Recognition), `apps/reputation/services.py`, `apps/reputation/apps.py` (register the handler), `apps/catalogue/services.py` (`publish_offer` calls the hook for `first_maker`), `apps/reputation/tests/test_recognition.py`

**Do:**
1. **`Recognition`:** `member` (null), `unit` (null), `kind` (`first_maker`, `filled_need`, `thanks`), `item` (null), `review` (FK Review, null), `text` (at most 280 characters), `from_member` (null), `created_at`, `hidden_by_owner` (bool).
2. **Fill the hook of P05.T12:** in `ReputationConfig.ready()`, append `apps.reputation.services.on_recognition` to `apps.core.hooks.RECOGNITION_HANDLERS`. Other apps keep calling `RECOGNITION_HOOK` and never import `apps.reputation`. The handler records:
   - `filled_need`: an offer for an item from the needs board was published;
   - `first_maker`: the first published offer of an item ever (`publish_offer` calls the hook with this kind);
   - `thanks`: a review marked `as_thanks` (P05.T10), shown with its first 280 characters;
   - the recognition goes to the unit and to its workers at that time.
3. **Thanks** appear on the unit page and can be flagged like any content (P06.T08).
4. **Shown** on the unit page and, unless the member hides it, on the member's job portfolio. There is no ranking list and no "top members" page.
5. **No UNIQ:** write `test_hf02_recognition_pays_nothing`, which checks that creating each kind of recognition posts no ledger transaction.

**Tests:** publishing the first offer for an item creates `first_maker`; a wanted item creates `filled_need`; thanks appear and can be hidden; `test_hf02_recognition_pays_nothing`.

---

### - [ ] P13.T10 — Acting for a member ("on behalf of")

**Read:** docs/05 section 1 (principle 5); docs/08 section 3; book p. 68.
**Files:** `apps/members/models.py` (AssistConsent), `apps/members/assist.py` (middleware, decorator), `apps/members/fixtures/contracts.json` (`assist_consent` v1), `apps/core/models.py` (AuditEvent: `acted_by`), `apps/members/templates/members/assist*.html`, `apps/members/tests/test_assist.py`

**Do:**
1. **`AssistConsent`:**
   - `member` (the person helped), `helper` (a verified member), `scopes` (JSON list from `orders`, `bookings`, `hours_entry`, `tickets`, `comments`);
   - `signature` (FK Signature of the `assist_consent` contract, signed by the person helped);
   - `paper_copy` (FK PrivateFile, null), `witnessed_by` (FK Member, null);
   - `valid_until` (at most `governance.assist.max_months` ahead), `revoked_at`.
2. **Signing:**
   - **in the app:** the person helped logs in with their own email code on the helper's device and signs;
   - **on paper:** the helper uploads a scan as a private file, and an identity helper (P01.T05) who met the person confirms it, filling in `witnessed_by`.
   - A helper may act for at most `governance.assist.max_assisted_per_helper` members at a time.
3. **"Acting for" mode:**
   - The helper chooses "Act for M-…" in the nav. The session stores the consent's id, and a bright banner shows "You are acting for <name>" on every page.
   - The middleware sets `request.member` to the person helped and `request.acting_helper` to the helper.
   - Views allow an action only if it is decorated `@assist_allowed("<scope>")` with a scope in the consent. Everything else is refused with a plain message.
4. **Never on behalf of anyone:** voting, sitting as a confirmer, approving hours, holder actions and payments, signing contracts, changing bank details, deleting the account. These views carry no `@assist_allowed`. Write `test_hf13_votes_cannot_be_cast_on_behalf`.
5. **The record:**
   - every action in "acting for" mode writes an `AuditEvent` with `acted_by` = the helper;
   - orders, tickets and comments store `acted_by` (FK Member, null) and show "placed by <helper> on behalf of <member>";
   - the person helped sees all of these on "My account → Done for me", and gets a monthly summary by email, or on paper through the local council if they have no email.
6. **Revoking:** the person helped or the helper can end the consent at any time, and it ends by itself at `valid_until`.

**Tests:**
- an order placed in "acting for" mode belongs to the person helped and shows the helper;
- an action outside the consent's scopes is refused;
- `test_hf13_votes_cannot_be_cast_on_behalf`;
- the helper limit holds;
- a revoked consent stops "acting for" mode at once.

---

### - [ ] P13.T11 — Pages for the bodies

**Files:** `apps/bodies/views.py`, `apps/bodies/urls.py`, `apps/bodies/templates/bodies/*.html`, `apps/bodies/tests/test_pages.py`

**Do:**
1. **`/bodies/`** lists the unions, local councils and consumers' councils, with a search field.
2. **A union page** shows its member units and delegates, its rules, pages and recipe templates, its open decisions, the tickets it advises on, and its expert nominations.
3. **A local council page** shows what T06 lists, plus the responsible and how to volunteer.
4. **A consumers' council page** shows its members (display names), guidelines and tickets.
5. **"My bodies"** on the member's dashboard lists the bodies they belong to, with anything waiting for them.

**Tests:** each page loads for a member and shows the right open items.

---

## Acceptance check for phase 13

1. Two woodshops form the woodworkers' union through their councils' tickets, and each sends a delegate.
2. A question about a chair offer notifies the union's delegates. Their answer is marked as advice, and the decision method is unchanged.
3. A local council for the postcode prefix `10` opens with random confirmers from that area, and it opens a pickup point.
4. Three helpful marks give a member a reputation, and a new question about wood suggests them.
5. A helper with consent places an order for a member without a device. The order shows "on behalf of", and the helper cannot vote for them.
6. `scripts/hf_coverage.py` shows the new HF-2, HF-13, HF-15 and HF-20 tests.
7. Add a line to PLAN.md "Progress".
