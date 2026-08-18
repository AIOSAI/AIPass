# APLAN-0007: Branch audit - spawn

Tag: audit, branch-audit, spawn

> Branch audit @spawn -- living document tracking health, issues, improvements

---

## What is an APLAN?

Audit Plans (APLANs) are **living documents** -- track ongoing health, issues, improvements for specific branch. Unlike DPLANs (capture moment thinking) or FPLANs (track build), APLANs persist across sessions + grow as branch evolves.

**This IS for:**
- Recording branch health status + key metrics
- Tracking bugs, issues, improvement opportunities as discovered
- Logging what's been dispatched + results
- Maintaining clear picture: open vs resolved
- Serving as working memory next time we touch this branch

**This is NOT for:**
- Building code -- that's FPLAN
- One-off design thinking -- that's DPLAN
- Quick fixes -- just do those directly

**APLANs never trimmed, rarely closed.** They accumulate history. When branch gets major overhaul, start fresh APLAN + archive old one.

**Keep items current.** Check boxes when work done. Add ! issues as found. Update metrics when you verify. Document should always reflect reality.

---

## Quick Status

| Metric | Value |
|--------|-------|
| **Health** | GREEN |
| **Last verified** | 2026-08-17 (S121) |
| **Open items** | 0 mine (1 PARKED BY PATRICK on devpulse's ledger -- cert `id`/`citizen_number`) |
| **Tests** | 483 pass, 1 skipped, 0 fail |
| **Seedgo** | 100% (44 standards) |
| **Bypass entries** | 17 (+1 S119 `atomic_write.py`, +1 S121 `mint_verify.py` -- both `json_structure`, both lift-and-measured in BOTH lanes before adding) |
| **Live command sweep** | unknown-class refusal live-verified S118 (`create wizard` -> exit 1, no branch made) |

**S121 note:** the `project_agent` template was shipping 6 of 18 files short to
every fresh clone (gitignored, never negated) and the mint exited 0 anyway. Both
halves fixed -- see Resolved. Mint now refuses rather than half-registering.

**S118 closed all 4 remaining open items** from the S117 audit: the unknown-class
refusal for `create`, the `.ai_mail.local/` never-update exclusion (devpulse
ruling), and `sync-templates` retired outright (`template_owners.json` confirmed
empty twice running, no live use). The `is_protected()` layer-2 unreachability
item was already covered by unit tests at S117 and needed no further action.

## Current State

### Summary
- Agent factory + branch lifecycle manager: create, update, delete, sync, repair, grant-admin.
- 25 modules/handlers, 21 test files, 484 tests collected.
- Two template classes: `aipass_framework` (46 files, 24 dirs), `project_agent` (18 files, 10 dirs) -- BOTH now ship complete to a fresh clone (S121).
- `admin` permanently refused as class/template at the door, before argparse (DPLAN-0288).

### Architecture
Three layers, enforced by seedgo encapsulation: `apps/spawn.py` (entry, routes only)
-> `apps/modules/` (business logic, argument parsing) -> `apps/handlers/`
(implementation). Entry point never imports handlers directly; `core.py` re-exports
class helpers for that reason.

### What Works Well
- **All 29 live command paths pass**, including every error and refusal path.
- Delete protection is real and layered -- verified live against 6 branches.
- `admin` fence sits in front of the parser, so an unknown class cannot slide into
  the target-path slot and become a directory.
- Update's `.py` skip and `_NEVER_UPDATE_FILES` prevent template pushes from
  clobbering branch code and live state.
- Test isolation is now genuinely hermetic (two sandbox leaks closed, see Resolved).

## Issues Found

### Open

- [ ] **Cert `id` / `metadata.citizen_number` has no authoritative source and is
  corrupt fleet-wide** (S120, escalated to devpulse/Patrick -- a fleet numbering
  ruling, not a spawn implementation choice). No source of truth exists anywhere:
  not `AIPASS_REGISTRY.json` (entry keys are admin, created, description, email,
  last_active, name, owner, path, profile, registry_id, status -- no
  citizen_number), not `.trinity/passport.json`, not `.spawn/.branch_meta.json`.
  `get_next_citizen_number()` returns `len(branches) + 1`, so it is birth-order at
  mint time and unstable forever after. Measured live: `id` mirrors
  `metadata.citizen_number` in every cert, and the values are `"0"` x5,
  `"13"` x2, the registry UUID on ai_mail/seedgo/spawn, and the string
  `"devpulse"` on devpulse. spawn's own cert therefore renders "Citizen
  #7087bb93". I did NOT normalize these (out of scope, and any scheme is a fleet
  ruling) and did NOT fabricate numbers for the 5 fresh mints -- omitted the field
  so honest-absence renders nothing rather than a false record.
  **RULED 2026-08-17 (Patrick, via devpulse 1653d27a): PARKED.** Verbatim -- "we
  can circle back on these, they seem inconsistent tbh". No renumber, no retire;
  the field stays as-is INCLUDING my honest omissions on the 5 new mints. Ruling
  comes at a later sitting and sits on devpulse's ledger, not mine. Nothing for
  @spawn to do -- do not re-escalate this, and do not "helpfully" backfill numbers.
  Same reply also accepted the finding-3 overturn; the phone's Passport No. relabel
  (render the registry ENTRY id, not the project id) is queued on baud's side.

### Resolved

- [x] **`project_agent` template shipped INCOMPLETE to every fresh clone, and the
  mint hid it by exiting 0** (S121, devpulse dispatch 86cf4a70, CI run
  32094572478). CI showed 2 reds -- both my new `TestBirthCertificateSchema` tests
  from S120, both the `[project_agent]` param, both `FileNotFoundError` on the
  minted `artifacts/birth_certificate.json`; the `[aipass_framework]` params passed
  and everything passed locally.
  ROOT CAUSE: root `.gitignore` blanket-ignores `.ai_mail.local/` (29-30),
  `DASHBOARD.local.json` (32), `logs/` (48) and `artifacts/` (49).
  `aipass_framework` got EIGHT explicit negations; `project_agent` got exactly ONE
  (`.spawn/`). Measured: aipass_framework 0 untracked of 46, **project_agent 6
  untracked of 18** -- `DASHBOARD.local.json`, `logs/README.md`,
  `artifacts/README.md`, `artifacts/birth_certificate.json`,
  `.ai_mail.local/inbox.json`, `.ai_mail.local/README.md`. So a fresh clone minting
  a project_agent citizen produced one with **no birth certificate AND no mailbox**.
  THE WORSE HALF: I reproduced it by stripping those 6 files from a template copy
  and minting -- `create` **exited 0**, printed "Agent created / Files: 11 /
  Registry: updated", and REGISTERED the citizen, with an empty `artifacts/` and an
  empty `.ai_mail.local/`. A citizen with no `inbox.json` cannot receive mail at
  all. Silent-success on missing state, against spawn's own "fail honestly".
  FIX (both halves): `.gitignore` negations added for the 4 categories
  project_agent actually carries, so the template ships complete; and new
  `apps/handlers/mint_verify.py` + guard at `core.py:319-338` verifying every file
  the TEMPLATE'S OWN manifest (`.spawn/.template_registry.json`) declares actually
  landed. Verification sits BEFORE the registry write, so a citizen that cannot be
  born never enters the registry -- no rollback path to fail. Red-first (3 tests
  red first: reported success, got registered, exited 0). The manifest half is the
  load-bearing half: it is tracked, so it survives a truncated clone and keeps
  naming files the clone no longer has -- a disk-only walk sees nothing wrong,
  which is exactly how this stayed silent.
  Re-verified by me against the original repro: same command now exits 1, names all
  6 missing files, diagnoses the gitignore cause in words, and creates no registry
  entry; a COMPLETE template still mints clean with cert + mailbox present.
  483 pass 1 skip, seedgo 100%. Reproduced CI's own invocation
  (`-n auto --dist loadscope` from repo root) -- green, no xdist ordering flakiness.
  The 2 CI tests were KEPT as-is rather than mocked hermetic: they are a genuine
  canary that caught a real shipping defect, proven to pass in a simulated
  fresh-clone tree once the template is complete.
- [x] **Birth-certificate paperwork repaired fleet-wide + old schema killed at the
  template** (S120, devpulse dispatch eb8354a2, Patrick-ruled). Before: 12 certs
  populated, 6 carried `metadata.template`, 6 carried old `metadata.citizen_class`,
  4 empty (commons/flow/memory/skills), 1 missing (prax). After: **17/17 populated,
  17/17 `metadata.template`, 0 `citizen_class`**.
  ROOT CAUSE was mine and it was the template: BOTH `templates/*/artifacts/
  birth_certificate.json` minted `metadata.citizen_class`, so every future citizen
  was born old-schema. Fixed to `metadata.template: "{{PROFILE}}"` with the
  description reworded to the current phrasing, red-first via
  `test_citizen_classes.py::TestBirthCertificateSchema` (4 cases through the real
  `_spawn_agent` path; seen red with `KeyError: 'template'`). Template registry
  hashes regenerated after (documented gotcha) -- cert hash `b089aef46e8c` ->
  `1ec401f4e397` in both class registries.
  Also fixed a latent bug found on the way: `placeholders.py` already HAD a
  `PROFILE` placeholder, but defaulted to the hardcoded literal `"AIPass Workshop"`,
  and `update_ops.py:127` passes no profile override -- so a `/business/` branch
  would have rendered the wrong profile. Now derives via `detect_profile(target_dir)`.
  5 certs minted (prax, commons, flow, memory, skills) with `created_at` from the
  registry and `purpose` from each citizen's OWN passport (all 5 -- registry
  fallback never needed). 6 migrated (aipass, backup, cli, hooks, seedgo, spawn):
  retired `citizen_class: "builder"` dropped, `template` added, key order and every
  other field preserved. Normalized `owner` casing on seedgo + spawn (`seedgo` ->
  `SEEDGO`) since the renderer prints `owner` and 14 of 17 were already uppercase.
  **devpulse's cert never touched** -- it carries the signed hmac-sha256 admin grant.
  Verified by git (no diff vs HEAD) and by SHA256 identical before and after:
  `278de0a91d49ab50e05d27981b356345948966f02e662b5fde62eaed15bb7a16`. Its lowercase
  `owner` and `id: "devpulse"` therefore stay as permanent documented exceptions.
  Repair tool: `tools/birth_certificate_repair.py` (sweep/repair, idempotent --
  verified byte-identical on a second run), all writes through `atomic_write_text`.
- [x] **registry_id "duplication" ruled DELIBERATE, not a defect** (S120) -- the
  dispatch reported identical `registry_id` on "at least 8" passports and asked for
  unique ids. Measured: it is **all 17**, and it is correct BY DESIGN.
  `AIPASS_REGISTRY.json` `metadata.id` IS `7087bb93-570f-4b9a-b035-4fd7f570200e` --
  the registry's own id -- and a passport's `citizenship.registry_id` is meant to
  equal it (it answers "which registry do I belong to", the same answer for every
  citizen of one project). My own `check_owner_identity()`
  (`sync_registry_ops.py:375-376`) documents this: flag `passport_mismatch` fires
  when a passport does NOT equal `metadata.id`, and flag `entry_rid_stale` treats a
  registry ENTRY whose id EQUALS `metadata.id` as the error. Per-citizen identity
  already lives in the entries: all 17 unique, none missing, none equal to
  metadata.id. Minting unique ids into passports would have broken my own health
  check on all 17 and been healed straight back by `sync-registry --fix`. Zero
  passports modified. The phone's "Passport No." should render the registry ENTRY
  id, not `citizenship.registry_id` -- a renderer fix on baud's side.
- [x] **Torn-write defect across spawn's own JSON/text write sites** (S119, fleet
  error 90c9e40d, devpulse dispatch) -- `Path.write_text()` truncates in place, so
  a concurrent reader lands on an empty or partial file. Spawn was NOT in the
  original 7-branch sweep. Measured before fixing: 2 writers vs 2 readers in
  separate processes against the real passport-write shape gave **38.2% and 55.3%
  unusable reads** across two 8s runs (98,578 empty + 6,638 unparseable of 275,669
  reads; fleet spread was 23-92.5%). After: **0.00%** unusable over 2,463,548 reads
  in a 45s run -- at the pre-fix rate that run should have produced ~18,000 bad
  reads.
  Worst site was `sync_registry_ops.py:633,658` rewriting **another citizen's
  `.trinity/passport.json`** during `sync-registry --fix` -- a torn write there
  corrupts a branch's identity file. Also `file_ops.py:76,226`,
  `update_ops.py:192,405,446`, plus two near-miss sites: `meta_ops.py:161` used
  `Path.rename` (not atomic-overwrite on Windows) and both it and
  `regenerate_registry_ops.py:90` used a FIXED `.tmp` name, so two concurrent
  writers collided on one staging path.
  Fix: new `apps/handlers/atomic_write.py` -> `atomic_write_text()` --
  `mkstemp(dir=path.parent)` (same filesystem, so `os.replace` stays a real rename)
  -> `os.write` -> `fsync` -> `close` -> `os.replace`, unlink staged file on every
  failure path, **raises, never swallows**. Every site routed through it. Caller
  contracts preserved exactly (passport loops still warn+continue, `_merge_json`
  still returns `"error"`, `save_branch_meta` still returns `False`, the
  `UnicodeEncodeError` -> `shutil.copy2` fallbacks still fire).
  37 new tests in `tests/test_json_durability.py`, **21 red-first**. Includes an
  AST source guard (`TestNoRawTruncatingWritesInSource`) that fails if a raw
  truncating write reappears in `apps/`, exempting the two legitimate flock targets
  (`repair_ops.py:61`, `registry.py:258`) by opened-path, not by variable name.
  Guard mutation-checked red for both `open(...,'w')` and `.write_text(` shapes --
  re-verified independently by me with my own probe after the build.
  `registry.py:save_registry` needed no change: already routed through the shared
  atomic `json_handler.write_json`.
- [x] **`update --help` / `delete --help` fell through argparse** (S117) -- a past
  audit recorded both as broken. Re-tested live: both print proper subcommand help
  and exit 0. Stale finding, closed. This is exactly the item devpulse warned sits
  unfixed for months -- it was already fixed, and the memory was the stale part.
- [x] **41 bypass rules suppressed nothing** (S117) -- pruned 56 -> 15. Every
  deletion measured in BOTH lanes first (audit + `drone @seedgo checklist <file>`
  with the rule lifted). Audit stayed 100% after.
- [x] **`TestHandleRegenerateRegistry` restamped the shipped template registry**
  (S117) -- fixed earlier today by an `_isolate_templates` fixture redirecting every
  class lookup into `tmp_path`. Verified: hash AND mtime of the shipped registry
  unchanged across a run of that class.
- [x] **conftest wrote `AIPASS_REGISTRY.json.test_backup` into the repo root**
  (S117) -- flagged by @backup. The file existed in the repo root for the duration
  of every run, so a crashed or killed suite orphaned it. Backup moved to
  `tmp_path_factory`. Verified: repo root clean mid-run, 435 tests still pass,
  registry hash unchanged (protection still works).
- [x] **`tests/test_scaffold.py` refreshed into branches with real suites** (S117,
  @seedgo ruling) -- already implemented: it is in `_NEVER_UPDATE_FILES`, covered by
  `test_update.py::test_scaffold_test_never_re_added`. Create-only, never re-added.
- [x] **`repair_ops.py` duplicate `fcntl` import** (S117) -- gone; single guarded
  import at L59. Its stale windows_compat bypass rule was pruned above.
- [x] **`create <unknown-class> <path>` did not refuse** (S118) -- fixed in
  `apps/spawn.py`: a lone `create` positional is now refused unless it is a
  registered citizen class OR path-shaped (`/`, `\`, or leading `~`/`.`/`@`),
  mirroring the `admin`-fence pattern (DPLAN-0288). Red-first
  (`test_cli_routing.py::TestCreateUnknownClassRefusal`, 4 tests): the repro test
  failed against unfixed code with `WIZARD` actually created on disk before the
  fix. Live-verified post-fix: `create wizard` -> exit 1, refusal message naming
  both registered classes, no directory created. `create <path>` and
  `create <class> <path>` unaffected -- 86 tests across
  `test_cli_routing.py`/`test_admin_fence.py`/`test_contracts.py`/
  `test_citizen_classes.py` green.
- [x] **`update` deep-merged into `.ai_mail.local/inbox.json`** (S118) --
  devpulse ruling: YES, add to never-update prefixes (their read: mailbox is
  live runtime state, same category as `DASHBOARD.local.json`, and the
  exclusion only reduces what update writes so the blast radius of being wrong
  is zero). `_NEVER_UPDATE_PREFIXES` in `apps/handlers/update_ops.py` now reads
  `(".trinity/", ".ai_mail.local/")`. Red-first: new test
  `test_update.py::TestNeverUpdateGuard::test_ai_mail_local_inbox_never_touched`
  failed against unfixed code (template's `schema_version` key leaked into the
  branch's live inbox via `_merge_json`), passes after the fix. Full
  `test_update.py` -- 23 passed.
- [x] **`is_protected()` layer 2 (`registry owner`) unreachable in the live
  fleet** (S117) -- not dead code, just never executed here (devpulse is the
  only owner-flagged entry and is caught by the layer-1 floor first); already
  covered by mutation-proven unit tests against a synthetic registry added at
  S117. No further action needed -- carried in Open by mistake at S117, moved
  here at S118.
- [x] **`sync-templates` retired** (S118) -- devpulse's lean: RETIRE unless a
  live use exists. `template_owners.json` re-confirmed empty (`managed_files:
  {}`) a third time running across two audits, no consumer anywhere in the
  codebase depends on the command executing. Removed entirely:
  `apps/modules/sync_templates.py`, `apps/handlers/sync_templates_ops.py`,
  routing/help/introspection in `apps/spawn.py`, the `TestSyncTemplates` class
  (5 tests) from `test_lifecycle.py`, references in `test_output_streams.py`,
  README (Quick Start, architecture tree x2, Known Issues, stale metrics), and
  `.aipass/aipass_local_prompt.md`. `template_owners.json` itself left in place
  (nothing else reads it, no reason to delete a harmless empty config).
  Full suite: 434 passed, 1 skipped, 0 failed (net -1 from 435: -6 removed,
  +5 added across the three items above). Seedgo re-run: 100% across all 44
  standards.

## What Needs Doing

Nothing open. All S117 items closed at S118.

### Tracked elsewhere
- [ ] Nothing currently tracked in another plan.

## Findings for @seedgo

**The dead-rule detector has false negatives, not just false positives.** Devpulse
warned wave 3 about rules reported dead that are still live in the checklist lane.
I hit the opposite: `apps/handlers/repair_ops.py [windows_compat]` was NOT in the
audit's "suppresses nothing" list, but measured dead in **both** lanes. Of 41 rules
I proved dead, the detector named only 21. Reporting so the detector's miss rate is
measured in both directions.

**Measurement note for whoever automates this:** checklist findings are marked with
`—` (em dash), not `✗`. My first sweep grepped for `✗`, got zero findings on all 18
files, and would have "proved" every rule dead. The false-green was caught only by
dumping one raw checklist output and seeing a `deep_nesting` finding my parser had
silently dropped.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fleet audit round (DPLAN-0291), wave 3 | YELLOW -- 4 open, 6 resolved |
| 2026-08-15 | Closed all 4 open items per devpulse's mail ruling (bfba4f0a) | GREEN -- 0 open, 11 resolved |
| 2026-08-16 | Torn-write template+live fix (devpulse dispatch bc4e48f9, error 90c9e40d) | GREEN -- templates already clean, 6 live sites fixed, 38%->0% unusable |
| 2026-08-17 | Birth cert + passport repair round (devpulse dispatch eb8354a2) | GREEN -- 12->17 certs, 6->17 template key, registry_id ruled deliberate, 1 escalated |
| 2026-08-17 | CI red on my S120 tests (devpulse dispatch 86cf4a70) | GREEN -- project_agent template was shipping 6/18 files short; silent mint now refuses |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round), DPLAN-0288 (admin ceremony)
- **Related FPLANs:** None open
- **Owner branch:** @spawn
- **Seedgo:** `drone @seedgo audit aipass @spawn`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S117 (2026-08-13):** Full branch audit. 29 live command paths, 435 tests, seedgo
100%/98%. Pruned 41 measured-dead bypass rules (56 -> 15). Fixed the conftest repo-root
backup leak and added 4 `is_protected()` layer tests (mutation-proven: layer 2 fails
red when the owner check is disabled). Corrected a false README claim that the
`registry owner` refusal was verified live -- it cannot fire in this fleet.

Found in the tree at session start and NOT authored by me in this session: the
APLAN stub, README edits, the `_isolate_templates` fixture, the `test_scaffold.py`
exclusion, and a bypass prune of retired-passport rules -- all timestamped 08:15-08:53
today. Attributing to no one; recording that they were verified, not inherited on
trust. Every claim above was re-measured this session.

**S118 (2026-08-15):** Closed all 4 S117 open items, triggered by devpulse's reply
(mail bfba4f0a) verifying APLAN-0007 and ruling/delegating the three live decisions.
Unknown-class refusal for `create` and the `.ai_mail.local/` never-update exclusion
both built red-first (failing repro test against unfixed code, confirmed green after).
`sync-templates` retired outright rather than wired -- `template_owners.json` empty
a third time running, no consumer anywhere. `is_protected()` layer-2 item turned out
to already be closed at S117 (it was carried in Open by mistake -- the mutation-proven
tests already existed); moved to Resolved, no code change needed. Full suite 434
passed / 1 skipped / 0 failed (net -1: -6 removed with sync-templates, +5 added
across the other two items). Seedgo re-run 100% across all 44 standards. Live-verified
the refusal by hand: `create wizard` exits 1 with a message naming both registered
classes, no directory created.

**S119 (2026-08-16):** Fleet torn-write round (error 90c9e40d). The dispatch's
premise was that spawn's TEMPLATE stamps a defective `json_handler.py` into every
new citizen -- **it does not**. Neither template tree carries a `json_handler.py`
at all (`apps/handlers/` holds only `__init__.py` + README in each), nothing in the
create flow writes one, both template registries are clean with zero
tree-vs-registry discrepancies, and a sweep of every file in both trees found no
raw truncating write shape anywhere. Future citizens were never born with this bug.
Verified twice -- by me at the start, independently again during the build.

The real defect was in spawn's own live handlers, which bypassed the atomic path
(see Resolved). Spawn's `json_handler.py` is a thin shim over
`aipass.aipass.shared.json_handler`, whose `write_json` was ALREADY atomic -- so
"fix your json_handler" was a no-op, while six handlers writing JSON *around* it
were the actual hole. Chased the shim to the shared implementation before
concluding anything; the file named in the dispatch was the one file that was fine.

Not changed, and flagged to devpulse: the shared `write_json` returns `False` on
`OSError` rather than raising. That is @aipass's contract on another branch's file,
not mine to alter.

**S120 (2026-08-17):** Birth cert repair round. Third session running where a
fleet dispatch's premise needed correcting before building -- but this time the
template WAS the root cause (S119 it wasn't), so the lesson is to measure, not to
assume either way. Two of four findings landed as reported (5 certs, 6 old-schema);
one was a misread of which field means what (registry_id -- ruled deliberate with
the design docstring as evidence); one was already satisfied (template passports
carry `identity.traits`). Found two things the sweep missed: the `PROFILE`
placeholder's hardcoded default (latent wrong-profile bug for `/business/` paths)
and the fleet-wide corrupt `id`/`citizen_number`, escalated rather than guessed.

Declined to fabricate: the 5 fresh mints carry NO `citizen_number`, because no
authoritative source for it exists anywhere in the system. Honest-absence renders
nothing; an invented number would render as provenance. Also refused to normalize
the existing corrupt ids -- any numbering scheme is a fleet ruling, not mine.

**S121 (2026-08-17):** CI red on my own S120 tests, and they were right. The
`project_agent` template had been shipping 6 of 18 files short to every fresh
clone since whenever the negations were written -- `aipass_framework` got eight
`.gitignore` negations, `project_agent` got one. My tests did not break CI; they
were the first thing to ever LOOK at project_agent's minted output on a clean
machine, and they found a citizen born with no birth certificate and no mailbox.
Kept them as-is rather than mocking them hermetic: a test that only passes where
the state happens to exist is the thing that let this hide.

The deeper bug was mine to own: the mint exited 0 on an incomplete template,
printed "Agent created", and REGISTERED the citizen. Verified by stripping a
template copy and running the real path. Now it verifies against the template's
own manifest before the registry write and refuses loudly. The manifest is the
load-bearing half -- it is tracked, so it survives a truncated clone and still
names what is missing, where a disk-walk sees nothing wrong because the files are
absent from the source too.

Also corrected my OWN branch prompt, which is injected every turn and had gone
stale: it advertised `drone @spawn passport` (retired, archived) and named the
citizen classes as "builder, birthright" when they are `aipass_framework` and
`project_agent`. A sub-agent caught it correcting a premise I had stated as fact.

## Listen (TTS-friendly summary)

Spawn's audit is signed yellow. Every number is green: four hundred thirty five tests
pass, seedgo scores one hundred percent with bypasses and ninety eight without, and
all twenty nine live command paths work including the error paths. Two commands an
older audit recorded as broken turned out to be fixed already, so the memory was the
stale part, not the code.

The yellow is for three things the numbers do not show. A claim in the readme said a
delete protection layer had been verified live, but that layer cannot fire in this
fleet at all, because the only branch carrying the owner flag is caught by an earlier
check first. That claim is now corrected and covered by tests instead. The update
command writes into another branch's live mailbox file. No message can be lost, but
rewriting another agent's runtime state is not something the template updater should
do, so it is raised with devpulse and ai mail rather than changed alone. And creating
a branch with an unknown class does not refuse. It quietly treats the class name as a
folder name and makes a branch with the wrong name.

Forty one bypass rules were deleted after proving each one suppresses nothing in both
audit lanes. Two test isolation leaks are closed, so the suite no longer writes into
the real repository while it runs.

Update at session one eighteen: the audit is signed green. All four open items closed
the same day devpulse replied with a ruling and two decisions. Creating a branch with
an unknown class now refuses in front of the parser instead of quietly making a branch
with the wrong name, built red first against a live repro. The update command no longer
touches another branch's mailbox file at all, following devpulse's ruling that a
template updater should never write into another agent's live runtime state, also built
red first. The sync templates command did nothing since it had no configured entries,
so it was retired outright rather than wired up. The fourth item was already fixed at
the prior session and only needed moving from open to resolved. Full suite still green,
seedgo still one hundred percent, and the refusal was hand-verified live.

Update at session one nineteen: the fleet's torn write defect reached spawn, but not
where anyone expected. The task assumed spawn's template stamps a broken json handler
into every new branch. It does not stamp one at all, so no future citizen ever carried
this bug. Spawn's own json handler was also already safe, because it delegates to a
shared one that was fixed correctly. The real hole was six other handlers that wrote
files directly, going around the safe path. The worst of them rewrote another
citizen's passport, their identity file, in a way a reader could catch half finished.
Measured before fixing: thirty eight to fifty five percent of concurrent reads came
back empty or unreadable. After fixing: zero, across two and a half million reads.
Every write now stages to a temp file beside the target and swaps atomically, and a
source guard fails the suite if anyone reintroduces the unsafe shape.

Update at session one twenty: the fleet's birth certificates are repaired. Five
branches had no certificate to draw and now have real ones, built only from facts
that could be verified: the date from the registry, the purpose in each citizen's own
words from their passport. Six more carried an old schema field holding a class name
that was retired months ago, now corrected. The important fix was upstream: both of
my templates minted that old field, so every future citizen would have been born with
it. That is fixed and the template hashes regenerated.

Two things in the request were wrong and I checked before building rather than after.
The identical passport numbers across every branch are not a defect. That field names
the registry a citizen belongs to, so every citizen of one project shares it by
design, and my own health check treats a passport that does not match as the error.
The per citizen numbers already exist and are all unique. And the traits field the
request asked me to add to the template was already there.

One thing I refused to do. The certificates hold a citizen number that has no
authoritative source anywhere in the system, and the existing values are already
corrupt, holding registry identifiers and even a branch name instead of numbers. I
did not invent numbers for the new certificates. A missing field draws nothing, but a
made up number would read as a record. That needs a ruling, and it is escalated.

Devpulse's certificate was never touched. It carries a signed grant that one changed
byte would break, and its checksum is identical before and after.

Update at session one twenty one: continuous integration went red on two tests I
wrote this morning, and the tests were right. One of my two branch templates had
been shipping incomplete to every fresh copy of the repository. Six of its eighteen
files were being ignored by version control, because the other template was given
eight exemptions and this one was given a single exemption years apart. Nobody had
noticed, because on this machine the files exist. My new tests were the first thing
to ever look at that template's output on a clean machine.

The worse half was mine. When the template was incomplete, creating a branch
reported success, exited cleanly, and registered the new citizen anyway, while
producing a citizen with no birth certificate and no mailbox. A citizen without a
mailbox cannot receive mail at all. I reproduced it deliberately before fixing it.
Creating a branch now checks what the template itself claims to contain, refuses
out loud when anything is missing, and registers nothing.

I kept the two failing tests exactly as they were rather than making them pass
artificially. A test that only passes where the state happens to exist is precisely
what let this hide for so long.

Last verified 2026-08-17.

---
*Created: 2026-08-13*
*Updated: 2026-08-17 (S121)*
