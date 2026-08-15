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
| **Last verified** | 2026-08-15 (S118) |
| **Open items** | 0 |
| **Tests** | 434 pass, 1 skipped, 0 fail |
| **Seedgo** | 100% (44 standards) |
| **Bypass entries** | 15 (unchanged since S117 prune) |
| **Live command sweep** | unknown-class refusal live-verified this session (`create wizard` -> exit 1, no branch made) |

**S118 closed all 4 remaining open items** from the S117 audit: the unknown-class
refusal for `create`, the `.ai_mail.local/` never-update exclusion (devpulse
ruling), and `sync-templates` retired outright (`template_owners.json` confirmed
empty twice running, no live use). The `is_protected()` layer-2 unreachability
item was already covered by unit tests at S117 and needed no further action.

## Current State

### Summary
- Agent factory + branch lifecycle manager: create, update, delete, sync, repair, grant-admin.
- 23 modules/handlers, 19 test files, 436 tests collected.
- Two template classes: `aipass_framework` (45 files, 23 dirs), `project_agent` (17 files, 9 dirs).
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

None -- all 4 items opened at S117 closed at S118 (see Resolved).

### Resolved

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

Last verified 2026-08-15.

---
*Created: 2026-08-13*
*Updated: 2026-08-15*
