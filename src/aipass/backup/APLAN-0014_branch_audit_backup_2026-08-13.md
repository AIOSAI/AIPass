# APLAN-0014: Branch audit - backup

Tag: audit, branch-audit, backup

> Branch audit @backup -- living document tracking health, issues, improvements

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
| **Last verified** | 2026-08-13 |
| **Open items** | 7 |
| **Tests** | 313 pass, 0 fail, 1 skipped (was 265 -- +48 today, all red-first) |
| **Seedgo** | 100% WITH bypasses / 99% WITHOUT (45 standards incl. help_flag_safety) |
| **Bypass entries** | 11 (was 27 -- 16 pruned after measuring both lanes) |
| **Ruff / Pyright** | clean / 0 type errors |
| **Test map** | 81 public functions, 50 tested (62%) |

**Why YELLOW, not GREEN:** every headline number above was already green *before*
this audit, and the branch still shipped a help flag that ran real backups, a
typo'd path that got silently scaffolded, an unknown command that exited 0, a
stub that pretended to succeed, and a README that described four working
subsystems as stubs. The numbers could not see any of it. Five live bugs, five
fixes, all red-first and live-proven -- but the gap between "100%" and "correct"
is exactly what this round was for.

## Current State

### Summary
- Standalone backup system for any project on the PC -- not just AIPass projects
- Project-owned stores: `.backup/` + `.backupignore` live in the TARGET project
- 12 commands, 13 auto-discovered modules, all 12 exercised live this audit
- Drive lane is LIVE (creds + Google libs present) -- README had claimed stub

### Architecture
Entry point `apps/backup.py` auto-discovers `apps/modules/*.py` exposing
`handle_command()` and routes by command name. Modules orchestrate; handlers do
the work (scan -> filter -> copy -> state -> report). Snapshot = full mirror,
versioned = per-file baseline + diff store (append-only, never deletes).

### What Works Well
- Versioned engine: baseline/diff/skip/never-delete all correct live and under test
- Restore: list + file, plus honest "no versioned file found" on a bad name
- `.backupignore` pathspec semantics (30 tests) and the seed-template safety model
- Caller-CWD path resolution (`handlers/path/caller.py`) -- relative paths still correct
- Drive lane end-to-end: check PASSED, sync uploaded, share returned a live link
- The one thing other branches may flag is NOT a bug: **`inbox.json` stored as a
  directory in the versioned store is the file-folder layout BY DESIGN**
  (confirmed by @seedgo). Every versioned file becomes `<name>/<name>` plus
  `<name>_diffs/`. Do not "fix" it.

## Issues Found

### Open

- [ ] **`backup_timestamps.json` is ONE GLOBAL FILE, not per project** --
  `handlers/state/backup_timestamps.py:22` pins it to my own branch root, so the
  "Backups now" panel reports the last time ANY project was backed up. A
  brand-new project showed "Versioned: 2 days ago / Drive sync: 27 days ago",
  and backing up project A rewrites what project B reports. Directly contradicts
  the project-owned charter. **Zero test coverage** -- no test references this
  module at all. Needs per-project storage in `.backup/` + a migration for the
  existing global file. Build, not a quick fix.
- [ ] **Refused runs still exit 0** -- `route_command()` returns "handled", not
  "succeeded", so `main()` returns 0 even when the run was refused or errored.
  Scripts cannot detect failure. Fixing means changing the module return
  contract fleet-wide-ish (all 13 modules) -- deliberate, not tonight.
- [ ] **No `unregister` / registry prune command** -- `register` only ever adds.
  Found 5 registrations, 4 pointing at `/tmp` paths that no longer exist (debris
  from earlier audit sessions). Pruned by hand this round; the missing command is
  the actual gap.
- [ ] **No remote-delete surface for Drive** -- `drive_clear` clears only the
  LOCAL dedup tracker. Nothing in my command set can remove a file already
  uploaded. See "cleanup I owe" in Notes.
- [ ] **1 unused_function bypass rule is provably dead, cannot tell which** --
  7 rules, 6 violations. The checklist lane does not run `unused_function` at
  all, so the per-file probe that resolved the tests/* rules cannot resolve
  `drive/client.py` vs `report/result.py`. Kept both rather than guess.
- [ ] **`test_entry_point_has_print_help` is `assert True`** -- pins nothing
  (test_cli_routing.py). The new entry-point tests now exercise `main()` for
  real; this placeholder should be retired or given a body.
- [ ] **`json_handler` 66% is a real standing gap** -- backup runs a log-only
  fork (JSONL append) instead of the shared shim, bypassed since 2026-04 with
  "pending migration decision". The decision is still pending. It is the single
  biggest no-bypass score drag.

### Resolved

- [x] **The router fix was only half of it** (S34 -- @seedgo, help_flag_safety
  100 -> 23). Every module also has `if __name__ == "__main__":
  handle_command(PRIMARY_COMMAND, sys.argv[1:])`, which never reaches the
  router's normalisation. `python apps/modules/snapshot.py <project> --help` ran
  a REAL snapshot -- proven live before the fix, store and all. Whole-sequence
  gate now lives INSIDE `handle_command` in all 11 affected modules, screening
  both `--help` and `-h`; bare `help` stays first-position-only because later
  positions are user values. 30 tests (10 modules x 2 spellings + controls).
- [x] **`drive_check` was exposed too, and was NOT in seedgo's list of 10**
  (S34). Their precision cut saw the `args[0] == "run"` comparison and passed
  it, but the default branch runs the check for ANY unrecognised first arg:
  `drive_check foo --help` made a live Drive auth call. Measured before
  touching it, fixed, reported back as evidence for their shape-(a) question.
- [x] **A `--help` probe executed the verb** (S33 -- devpulse rule E, confirmed
  here). `main()` checked only `remaining[0]`, so `snapshot <project> --help`
  resolved the project and ran a real backup -- including `all`
  (snapshot+versioned+drive) and `drive_clear --force`. Now any `--help`/`-h`
  anywhere in the args prints help and runs nothing. 7 tests, live-proven both
  directions (was: 3 files copied + store created; now: help text, no store).
- [x] **Nonexistent project path was scaffolded, not refused** (S33).
  `create_backup_dir()` correctly returned `None` for a non-directory and
  `run_snapshot` ignored the refusal -- the pipeline then created `.backup/`, a
  fresh `.backupignore`, and "backed up" that very `.backupignore`, reporting
  success. Guard added to snapshot/versioned/all via shared
  `display.refuse_missing_root()`. 4 tests.
- [x] **Unknown commands were swallowed** (S33). `display.py` is not a command
  module but its no-args gate had no ownership guard, and discovery put it
  first, so `backup wibble` printed display's introspection and exited 0. Added
  the `command != MODULE_NAME` guard, keeping the gates the introspection
  standard requires. 3 tests.
- [x] **`settings` stub exited 0 in silence** (S33) while help and README sold it
  as working. Now announces "not implemented" out loud. 1 test.
- [x] **README described four working subsystems as stubs** (S33) --
  drive_sync/check/stats/clear and `diff/` are fully implemented and were proven
  live. Entry help also claimed `drive_clear` "clears the remote drive"; it
  clears the local tracker only. Docs corrected in both files.
- [x] **5 hardcoded `/tmp` paths in tests** (S33) -- windows_compat findings the
  audit lane structurally cannot see (it never enters `tests/`). Now
  `tempfile.gettempdir()`.
- [x] **16 dead bypass rules pruned, measured not assumed** (S33) -- 27 -> 11.
- [x] **CLAUDE.md startup read a file that isn't there** (S33) --
  `STATUS.local.md` was archived; only 2 of 18 branches still keep one, so the
  archive matched the fleet and the stale reference was the bug. Now points at
  `DASHBOARD.local.json`.

## What Needs Doing

### @backup to handle (dispatch)
- [ ] Per-project backup timestamps + migration off the global file
- [ ] `unregister` / registry prune command
- [ ] Retire or implement `test_entry_point_has_print_help`
- [ ] Resolve which unused_function bypass is dead (needs an audit-lane probe)

### devpulse to handle
- [ ] Version control for this round -- no git from me, per dispatch
- [ ] Exit-code contract: `handle_command` returning "handled" vs "succeeded"
      affects every branch that copied this router pattern, not just @backup
- [ ] Ruling on the `json_handler` log-only fork: migrate to the shared shim or
      make the bypass permanent with a real reason

### Tracked elsewhere
- [ ] Google Drive sync design -- see DPLAN-003 (note: the doc says deferred,
      the code is live and working; DPLAN-003 needs a truth pass of its own)

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fleet audit round DPLAN-0291 -- full self-audit | YELLOW: 5 live bugs found + fixed red-first, 280 tests, seedgo 100/99, 16 bypasses pruned |
| 2026-08-13 | @seedgo help_flag_safety 23% -- standalone `__main__` entries | Fixed 11 modules (10 reported + drive_check I measured myself), 313 tests, help_flag_safety 100%, devpulse signed off on the morning round |

## Relationships
- **Related DPLANs:** DPLAN-0291 (this round), DPLAN-003 (Drive sync -- stale)
- **Related FPLANs:** None open
- **Owner branch:** @backup
- **Seedgo:** `drone @seedgo audit aipass @backup`

## Notes

**S33 (2026-08-13):** Fleet audit round DPLAN-0291.

Method that actually found things: running every command live, including the
error and refusal paths, instead of trusting the suite. All five bugs were
invisible to a green 265-test suite and a 100% seedgo score. The `--help` probe
(devpulse's rule E) was the sharpest -- it is a safety bug, not a UX one: the
same fall-through would have run `drive_clear --force` from a help probe.

Bypass pruning followed rule C literally. The advisory named 16 dead; rather
than trust it in either direction I emptied the bypass file and re-ran the
CHECKLIST lane per test file. No architecture/encapsulation/trigger findings
appeared on any of them, so those 16 were dead in both lanes -- pruned, re-audit
still 100%. The same probe surfaced 5 windows_compat findings the audit lane
cannot see, which is the real argument for the checklist lane existing.

**Cleanup I owe the user:** exercising the Drive lane live uploaded a throwaway
test project to Patrick's real Drive and `share` created a restricted link for a
test README. No @backup command can delete remote files. Local artifacts
(`/tmp/bkaudit*`, restored file, 5 registry entries) are cleaned; the two Drive
objects need either a manual delete or the remote-delete command listed above.
Flagged rather than hidden.

## Listen (TTS-friendly summary)

Backup is yellow, not green. Every number was already healthy before this audit.
The test suite passed, the standards score was one hundred percent, and the
branch still had five real bugs that only showed up when the commands were run
for real.

The worst one was a help flag. Typing help after a project name did not print
help. It ran a full backup. The same path would have run a forced clear of the
drive tracker. That is fixed now, and a help flag anywhere in the arguments
prints help and runs nothing.

The second was a typo. Pointing backup at a folder that did not exist created
the folder, wrote a fresh ignore file, backed up that ignore file, and reported
success. The code that was supposed to refuse did refuse, but nobody listened to
it. Now the refusal is honoured.

Three smaller ones. An unknown command printed the wrong module's information
and exited as if it worked. The settings command did nothing at all, silently,
while the documentation said it worked. And the readme described four working
drive features as unfinished stubs, when in fact they upload to a live account.

Seven items remain open. The biggest is that backup timestamps are kept in one
shared file instead of one per project, so a brand new project claims it was
backed up two days ago. Nothing tests that file today. There is also no way to
unregister a project, and no way to delete anything already sent to the drive.

One honest note. Testing the drive commands for real uploaded a throwaway test
project to Patrick's actual drive, and no backup command can remove it. That
needs a manual cleanup.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
