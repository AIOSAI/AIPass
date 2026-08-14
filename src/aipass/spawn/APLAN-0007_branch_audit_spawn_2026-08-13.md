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
| **Health** | YELLOW |
| **Last verified** | 2026-08-13 (S117) |
| **Open items** | 4 |
| **Tests** | 435 pass, 1 skipped, 0 fail |
| **Seedgo** | 100% with bypasses / 98% without (44 standards) |
| **Bypass entries** | 15 (was 56 -- 41 pruned, every one measured in both lanes) |
| **Live command sweep** | 29/29 paths pass, incl. error + refusal paths |

**Why YELLOW, not GREEN:** every headline number is green, but the audit found a
README claim that was false, a live-mailbox write in the update path, and a
protection layer that cannot fire in the live fleet. Numbers alone would have
signed this GREEN; the findings are what the colour is for.

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

- [ ] **`create <unknown-class> <path>` does not refuse** -- an unrecognised leading
  positional is read as the target path, so `create wizard` silently makes a branch
  named WIZARD in `./wizard`. The `admin` fence is a special case in front of the
  parser; there is no general unknown-class refusal. Documented in README Known
  Issues. Impact: low (typo makes a stray branch, not data loss), but it is a
  silent wrong-thing-done rather than an error.
- [ ] **`update` deep-merges into `.ai_mail.local/inbox.json`** -- a live mailbox
  owned by @ai_mail. `deep_merge` keeps existing scalars and non-empty lists, so
  **no message is lost**; verified by reading the merge implementation. The residual
  risk is that `update --apply` rewrites another branch's runtime state at all: a
  message arriving between read and write could be dropped. `DASHBOARD.local.json`
  is already excluded as live state -- same category. Proposal: add
  `.ai_mail.local/` to `_NEVER_UPDATE_PREFIXES`. NOT done unilaterally: it changes
  fleet update semantics and touches another branch's data contract. Raised with
  devpulse + @ai_mail.
- [ ] **`is_protected()` layer 2 (`registry owner`) is unreachable in the live
  fleet** -- devpulse is the only entry carrying `owner: true` and it short-circuits
  on the layer-1 hardcoded floor. The layer is not dead code (an external project
  registry can have a non-floor owner), but it has never executed here. Now covered
  by unit tests against a synthetic registry (added this session).
- [ ] **`sync-templates` is a no-op** -- `template_owners.json` has no entries.
  Re-verified live this session, still true. The template IS the source of truth,
  so there is nothing upstream to pull from; the command is scaffolding for a
  relationship that does not exist. Either wire it or retire it.

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

## What Needs Doing

### @spawn to handle (dispatch)
- [ ] Decide the general unknown-class refusal for `create` (open item 1).
- [ ] Wire or retire `sync-templates` (open item 4).

### devpulse to handle
- [ ] Ruling on excluding `.ai_mail.local/` from template update (open item 2) --
  needs @ai_mail's agreement since it is their data contract.

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
the real repository while it runs. Next attention goes to the unknown class refusal
and to deciding whether the sync templates command should be wired up or retired,
because it currently does nothing at all.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
