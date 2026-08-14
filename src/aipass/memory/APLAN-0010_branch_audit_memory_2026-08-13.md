# APLAN-0010: Branch audit - memory

Tag: audit, branch-audit, memory

> Branch audit @memory -- living document tracking health, issues, improvements

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
| **Last verified** | 2026-08-14 (S139 — symbolic tier parked, audit re-run 99%) |
| **Open items** | 5 |
| **Tests** | 823 pass, 0 fail, 4 skipped modules (222 tests parked with the symbolic tier; 1022 test functions on disk) |
| **Seedgo** | **99%** with bypasses — one dead_code finding left standing on purpose (see open items) |
| **Bypass entries** | 112 (was 156; 45 removed in S136, **1 added** in S138 for the cross-branch `spawn_background` caller) |
| **CLI score** | Nav 5/5, Output 5/5 (44 command paths + 18 error paths run live) |

**Why GREEN now:** the two structural findings that held it at YELLOW are closed by
fix, not by bypass — `watch` is a module and the entry point imports no handlers;
the three unwired files are archived with the 105 tests that covered them. What
remains open is one decision that belongs to Patrick (`push`), one parked item, one
cosmetic over-cap entry, and one checker defect that is @seedgo's to design.

*(S134's "Why YELLOW": that audit opened on a RED suite and a dead command every previous
report called green. Both are closed above — kept here as the record of how it started.)*

## Current State

### Summary
- Central memory archive: vector search, rollover, `.trinity/` template distribution for all branches.
- 9 modules, 14 handler directories + `central_writer.py`, 997 tests, 9992 vectors stored.
- Rollover watches 17 branch directories / 34 files. **8 files currently over limits** — that is
  pending, not broken: they drain at the next PreCompact anywhere in the fleet (see below).
- Config (`memory_json/custom_config/memory.config.json`) now has a **second front-end**: @baud
  shipped a Memory settings section last night with never-create / zero-refused /
  byte-identical-on-reject guards. It prints `drone @memory rollover push` rather than
  running it. Nothing has written to the live file yet.

### Architecture
Entry point `apps/memory.py` auto-discovers modules via `handle_command()`. Modules are
thin CLI routing; handlers hold domain logic. All ML (fastembed, chromadb) runs via
subprocess — the main process never imports them. Since S136 the entry point imports **no**
handlers: `watch` is a module like every other command, and a contract test keeps it that way.

### What Works Well
- **Search**: 146 results across 31 collections, sub-second after model load. Solid.
- **Rollover is an automatic lane, not a command anybody runs.** `hooks lifecycle/rollover.py`
  fires on **every** PreCompact — auto or manual, any session, any branch — running `rollover
  check` and then `rollover run` if anything is over cap (110s timeout). @devpulse read the
  mechanism and cancelled the manual GO he had promised: no manual `rollover run` from either of
  us, permanently. The `date_guard=False` snapshot drain from DPLAN-0290 gets its first live
  exercise whenever that next natural PreCompact fires — the designed path. If it misbehaves, the
  extractor's own logging (misplaced-entry refusals, newest-first repairs) is where it shows.
- **Error paths**: every unknown-subcommand path names the valid set. 18 error paths run
  live, all clean.
- **Help interception**: verified in both directions — 10 destructive-verb help paths print
  help instead of executing; `search rollover help` still runs as a three-word query.

## Issues Found

### Open

- [ ] **`push` is a fleet-wide reset with no confirmation** — `drone @memory push` (bare alias,
      `memory.py:246`) and `rollover push` both call `push_defaults()`, which overwrites every
      branch's `per_branch` limits with defaults. No prompt, no dry-run, no diff. This mattered
      less when the config was edited by hand; now that BAUD writes it, one word discards
      operator tuning fleet-wide. NOT fixed today on purpose: adding an interactive prompt
      changes the contract with BAUD, which *prints* this command for Patrick to run.
      Needs a decision (prompt? `--yes`? dry-run default?) before it is built.
      **2026-08-13:** routed by @devpulse to Patrick, with his lean — *refuse without an
      explicit `--yes`* (an interactive prompt would hang headless callers), BAUD updates its
      printed string in the same session. Awaiting Patrick's ruling; BAUD m13 also uncommitted.
- [ ] **`introspection` 85% on `pool.py` + `lint.py` is a checker blind spot, not a code defect**
      — @seedgo's `_is_help_check` only accepts an `if` whose *test expression* contains a literal
      `"--help"`/`"-h"`. The shared `wants_help()` predicate is a Call node, so it is invisible.
      Worth flagging to @seedgo: the 5 sibling modules that *pass* do so via a vestigial
      `if command in ("--help","-h","help")` — a **command-name** check, not argument interception.
      The checker currently rewards the weaker pattern. Mailed @seedgo. Not bypassed.
      **2026-08-13 (S136): RESOLVED for these two modules** — @seedgo shipped it the same day;
      `_is_help_check` now accepts a delegated predicate call. Both are 100% with no code change
      here. The item stays open only for its **sharper half**, which @seedgo has *not* fixed and
      logged in APLAN-0005 with this branch's case named: `encapsulation` scored `apps/memory.py`
      100% while `watch` was structurally dead and 66% once it worked. A checker that rewards the
      dead form teaches branches not to fix. Behaviour-sensitive checking needs its own design.
- [ ] **1 observation over the 300-char cap** — `observations.json` index 13 (entry #20, 383/300).
      Was 3; the other two archived out naturally at rollover, as predicted. Left in place
      deliberately: self-pruning historical entries is the exact behaviour observation #18 warns
      against. It will archive out the same way.
- [ ] **4 digests remain quarantined** — PARKED by Patrick. Not touched, not re-diagnosed.
      Noted here only so the next audit knows they are known.
- [ ] **`handlers/vector/embedder.py` is orphaned by the symbolic park (S139)** — its only two
      importers were `symbolic/storage.py` and `symbolic/retriever.py`, both now in
      `.archive/parked_symbolic_20260814/`. Measured, not assumed: `embed_subprocess.py` (the
      one the live lane actually runs, by path, from `query_executor`, `plans_processor` and
      `orchestrator`) is self-contained and imports nothing from the package. So dead_code's
      1/36 finding is TRUE, and it is the frontier moving again (learning #50).
      **Deliberately left standing at 99%**: no bypass, because a bypass would assert a caller
      that does not exist. Disposition is a real decision, not cleanup — park it with the tier
      (and its 15-test `test_vector.py` suite goes dark with it), or keep it as the generic
      vector utility for the next consumer. Devpulse/Patrick's call; reported 2026-08-14.
- [ ] **`seedgo.local` is in a permanent rollover skip loop** — 18/15 `key_learnings`, and all
      three excess entries are dated *today*, so the DPLAN-0278 `_is_misplaced_entry` guard
      refuses every candidate: `execute_rollover` reports 1 trigger / 0 processed, forever.
      **Pre-existing, not caused by S138** — the 23:38 PreCompact run, minutes before the
      relocation was touched, logged the identical `"Extraction skipped for seedgo.local
      (18/15 key_learnings): No entries exceed v2 limits"`. Same class as learning #46 and as
      DPLAN-0290 item 3, which turned `date_guard` off for the *snapshot* lane only; the audit
      round pushed @seedgo to 18 learnings in one day, which is the write rate that breaks the
      heuristic on the ordinary lane too. NOT fixed inside dispatch 331f3f62 — it touches the
      safety valve and wants its own item and Patrick's word. Reported to @devpulse.
      Second-order: `auto_process()` sets `success: false` on this *correct* refusal, so the
      lane's success flag is permanently false and cannot report a real failure.
      **2026-08-14 update: it self-healed at midnight, exactly as predicted.** The excess
      entries aged from "today" to "yesterday", the guard stopped refusing them, and this
      morning's live run reported 3 triggers / 3 processed with `seedgo.local` back to OK.
      The wedge is gone; the *class* is not — any branch writing more than its cap in a single
      day is wedged until the next date rolls. Still Patrick's ruling to make.

### Resolved

- [x] **`watch` handler imports sat in the entry point** (S136) — `encapsulation` 66% on
      `apps/memory.py`, the branch's only violation of that standard. `watch` is now
      `modules/watch.py` (CLI routing + display) over `handlers/monitor/watch_runner.py`
      (lifecycle: start / sample / block / stop). The entry point imports **no** handlers at all,
      and a contract test fails the suite if one reappears. Live-proven end to end: 17 branch
      directories, 34 files, graceful Ctrl+C, help intercepted, unknown-arg rejected.
      No-args still starts the watcher — the live contract — with Level 2 introspection printed
      as the watcher's banner. 19 tests, red-first.
- [x] **3 unwired handler files archived** (S136) — `dead_code` 95% → 100%, **no bypass added**.
      `learnings/manager.py` (superseded by the rollover extractor), `search/vector_search.py` and
      `storage/chroma.py` (in-process ChromaDB, superseded by `chroma_subprocess.py`), each with
      the tests that covered it — 105 in total. All in `.archive/unwired_handlers_20260813/`
      with the measurement written down. `chroma.py` was **not** in the finding: it surfaced only
      after `vector_search.py`, its sole referencer, was archived — a checker reports the frontier,
      not the closure.
- [x] **6 relative imports in `modules/rollover.py` + `pool.py`** (S136, found by the class sweep)
      — every `apps/modules/*.py` ships a `__main__` block, and `python3 apps/modules/rollover.py
      --help` died with *"attempted relative import with no known parent package"*: the same defect
      class that left `watch` dead, hidden because entry-point routing imports them as a package.
      All six absolute; a contract test now scans the whole directory. Live-proven both ways.

- [x] **`drone @memory watch` was dead** (S134) — `apps/memory.py:273,277` used relative imports
      (`from ..handlers...`) inside a file drone executes as a *script*, so it raised
      "attempted relative import with no known parent package" at call time. Live-proven broken,
      fixed to absolute imports, live-proven working: 17 branch directories, 34 files monitored.
      The 3 contract tests that catch this were already in the tree, already red.
- [x] **`rollover push --help` executed the reset it was asked to describe** (S134, work started by
      an earlier session of mine) — modules read help flags at `args[0]` only. Now routed through
      `handlers/cli/help_flags.wants_help()`, evaluated before any subcommand dispatch.
      Verified live on 10 paths including `templates push-templates --help` and `pool process --help`.
- [x] **`lint @<unknown>` reported a clean bill of health** (S134, same earlier session) — an
      unrecognised branch name silently matched nothing and printed no violations. Now errors
      with a suggestion. Verified live.
- [x] **45 stale bypass rules removed** (S134) — see Bypass Registry below.
- [x] **README drift** (S134) — claimed 7 modules (8), 1063 tests (1081), seedgo 100% (99%),
      and listed 2 known issues that no longer reproduce.

## Bypass Registry — measured, not assumed

156 → 111 rules. Method matters here, because the advisory list is unreliable in both directions:

- **4 rules pointed at files that do not exist** (`CLAUDE.md`, and three `handlers/...` paths
  missing the `apps/` prefix). 3 of the 4 had an exact correctly-prefixed twin already in the
  registry, so removal is a no-op under either exact or suffix matching. Only class safe to
  delete unmeasured.
- **42 `tests/*` rules measured individually, in the checklist lane.** The audit lane never
  enters `tests/`, so these *look* dead there while still able to suppress findings in the
  PostToolUse checklist lane. For each of the 13 files: captured `drone @seedgo checklist <file>`
  output with the rules present, pulled that file's rules, re-ran, diffed **raw output**.
  All 13 byte-identical → all 42 genuinely suppress nothing in either lane.
- **Control test run first**, because "identical output" would also be the result if the
  checklist lane ignored `bypass.json` entirely. Pulling `embed_subprocess.py`'s rules changed
  32-standards-pass into a visible `silent_catch` finding — lane confirmed live, measurement valid.
- **The em-dash trap was real**: that control finding rendered as `— silent_catch: ...`, not a
  cross. A glyph grep would have returned zero findings and "proved" every rule dead. Raw diff
  only.
- **+1 rule added**: `apps/handlers/cli/help_flags.py` / `json_structure` — pure argument-inspection
  predicate, no I/O, runs on every CLI call; `log_operation()` there would flood the operation log.
- Post-prune audit still 99% — the removed rules were shielding nothing, which is the point.

## What Needs Doing

### @memory to handle (dispatch)
- [ ] Guard `push` once Patrick rules on the shape (prompt vs `--yes` vs dry-run default).
- [ ] Offer @daemon a single public health-check surface if they want one, rather than importing
      three handlers (`entry_limits.load_entry_limits`, `detector.check_single_file`,
      `lint_handler.run_lint`). Offered 2026-08-13; their call.

### devpulse to handle
- [ ] Commit this round — no version control from me per dispatch, and Patrick is holding the
      round commit. Working tree carries: the `help_flags` handler, 7 module edits, the `watch`
      fix, bypass prune, README (S134) **plus** `modules/watch.py`, `handlers/monitor/watch_runner.py`,
      the 6 absolute-import fixes, `.archive/unwired_handlers_20260813/` (3 files + 105 tests),
      and this APLAN (S136).

### Tracked elsewhere
- [x] @seedgo: delegated help predicate — **shipped 2026-08-13**, `pool.py` + `lint.py` at 100%,
      no change needed here. Their no-regression sweep moved exactly those 2 files across 916.
- [ ] @seedgo (APLAN-0005): `encapsulation` scores the dead form higher than the working one —
      this branch's `watch` is the named case. Open by their design decision, not deferred.
- [ ] @daemon (APLAN-0015): `memory_health` requires a `limits` field that schema 3.0.0 removed,
      so all 17 branches report WARNING forever. Schema call sent 2026-08-13 — check the three
      config-aware APIs, never a per-file copy of the caps.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fleet audit round DPLAN-0291 (wave 5, dispatch deb9ad79) | YELLOW — 1081 green, 99%/96%, 5 open items, 2 live bugs fixed |
| 2026-08-13 | Dispatch 40e33e8b (@devpulse) — fix round to 100 | **100%** overall, 997 green, ruff clean. dead_code: 3 files archived with 105 tests, no bypass. encapsulation: `watch` → module + handler. Riders: 6 relative imports fixed (same class as the dead `watch`), todo count reported as 1 not 11. |
| 2026-08-13 | Mails 86a30278 + c0b4988c (@devpulse) | Signed off at the final numbers (1081 / 99-96 / 111 bypasses). The 3 fixes he approved had already landed pre-mail — all re-verified live (help guard, `watch` 17 dirs/34 files, `lint @<unknown>`), suite re-run 1081 green. `push` → Patrick; @seedgo item consolidated with @api's; trigger's 5 `captured_memory` ERRORs (11:08–11:21) closed stale — they were this audit probing the then-dead `watch`. Control-first bypass measurement adopted as the round's reference method. Duplicate APLAN-0012 closed; 0010 stays open. |
| 2026-08-13 | Dispatch 331f3f62 (@devpulse) — DPLAN-0295 item 1, night shift: `auto_process` off the prompt lane | Shipped, **not committed** (dispatch constraint). Mechanism: fire-and-forget detached child, hook stays the trigger — chosen over a @daemon schedule (a down daemon stops vectorizing *silently*) and over PreCompact-only (a session that never compacts never drains the pool). New `spawn_background()` + `run_once()` + tempdir single-flight lock in `apps/handlers/intake/auto_process.py`; `auto_process()` untouched and still the sync API. 14 tests red-first, **1011 green**, ruff clean, audit re-run **100%** (1 measured bypass added for the cross-branch caller). Live proof, not mocks: parent returned in **738ms** (was 78–120s), the detached child vectorized a real pool drop (1 file / 1 chunk, vectors 10045→10046, pool drained), and a deliberate double-kick proved single-flight — one child worked 2.78s, the other declined with `another run holds the lock`. Hook-shell spec (one line: `module.auto_process()` → `module.spawn_background()`, session guard kept) sent to @hooks via the reply — **their file, not edited here**. Two surprises reported: the `seedgo.local` skip loop above, and the edit gate deadlocking red-first work. |

| 2026-08-14 | Dispatch 69b843f0 (@devpulse) — Patrick's ruling: park the symbolic fragments tier | Shipped, **not committed**. Verified dormant BEFORE disabling: no `.aipass/hooks.json` entry, no caller in rollover/extractor/auto_process/search/verify, and no cross-branch caller. One live thread found and cut — `apps/handlers/__init__.py` imported the package on *every* live call, so an unwired tier was still being loaded. Implementation preserved byte-identical in `.archive/parked_symbolic_20260814/` (7 handler files + the 1602-line module + a README with revival steps). Fail-honest surfaces: `handlers/symbolic/__init__.py` raises `SymbolicTierParked`, `modules/symbolic.py` refuses every subcommand with exit 1 and answers for the whole old API via module `__getattr__`. 34 new tests red-first (31 red → all green); the 4 legacy symbolic test files are **skipped, not deleted**, with the ruling as the skip reason. Suite 823 green + 4 skipped modules; audit 99% (the one finding is the orphaned `embedder.py` above, left standing on purpose). Answer to the report-only question: `should_surface` is **LIVE** — @hooks' `compass_recall` calls it on every `UserPromptSubmit`. |

## Relationships
- **Related DPLANs:** DPLAN-0295 (prompt-lane relocation), DPLAN-0291 (fleet audit round), DPLAN-0290 (date_guard, night before), DPLAN-0278 (safety valve)
- **Related FPLANs:** None open
- **Owner branch:** @memory
- **Seedgo:** `drone @seedgo audit aipass @memory`

## Notes

**S134 (2026-08-13):** Full branch audit. Opened by finding an unfilled APLAN-0010 in the tree
stamped 10:08 — two minutes after the dispatch landed — plus ~250 lines of uncommitted work I had
no memory of. Per the round's rule B I treated it as mine and re-measured rather than inheriting
or discarding it: a `help_flags` handler, 7 modules rewired to it, 18 new tests. The work was
sound and is now live-verified. What that session had *not* finished was the other half of its own
red-first cycle — it wrote 3 contract tests proving `drone @memory watch` was dead and never
applied the fix. The suite was RED (3 failed / 1078 passed) at the start of this audit while my
memories, my README and last night's commit message all said 1063 green. A suite is only green
where someone ran it.

Second lesson, sharper: the encapsulation checker scored `apps/memory.py` at **100% while the
command was dead** and at **66% once it worked** — the relative-import form was invisible to it,
the absolute form is not. The broken code scored better than the working code. Same shape as the
`introspection` finding: both checkers reward a pattern rather than a behaviour. I published both
seedgo numbers and left both violations unshielded rather than bypass my way back to 100%.

**S136 (2026-08-13):** Fix round to 100%. Both remaining gaps closed by fix, none by bypass.

The `dead_code` finding named two files; the honest answer needed three checks the checker cannot
do. Repo-wide grep, because it only sees one branch. A dynamic-invocation check, because this
branch really does invoke a handler by `importlib` string. And a path-invocation check, which is
what saved `chroma_subprocess.py` and `embed_subprocess.py` — both look exactly as unreferenced as
the files I archived, and both are load-bearing, executed as scripts in memory's `.venv`. A
transitive reachability walk also flagged `intake/plans_processor.py`, which is called by @flow
across the branch boundary. Archiving on the tool's word alone would have broken the branch.

Two things the round's own lesson earned. Archiving `vector_search.py` orphaned `chroma.py` — the
checker reports the frontier, not the closure, so a removal must be followed by a re-audit. And
sweeping for the *class* rather than the instance found six relative imports in `rollover.py` and
`pool.py`: every module ships a `__main__` block, and `python3 apps/modules/rollover.py --help`
died exactly the way `watch` did. Not a live outage — entry-point routing hides it — but the same
defect, one direct invocation away.

The hygiene rider did not match reality: my todos were **1**, not 11 over cap. The files sitting at
11 are @hooks and @trigger. Reported rather than silently ignored.

## Listen (TTS-friendly summary)

Memory branch audit, thirteenth of August. Verdict is yellow. Eleven hundred and eighty one tests
pass with no failures, and seedgo scores ninety nine percent with bypasses or ninety six percent
with the bypass registry emptied. Both numbers are published on purpose.

Two real bugs were fixed. The watch command was completely dead. It used relative imports inside a
file that drone runs as a script, so it failed the moment anyone called it, and it had been
reported as healthy for weeks. It now runs and monitors seventeen branch directories. The second
bug was worse in character. Asking a command for help could execute the command instead. Rollover
push, which resets every branch's limits across the whole fleet, would perform that reset when
asked to describe itself. Help is now checked before anything runs, and that was verified live on
ten different dangerous commands.

The bypass registry went from one hundred and fifty six rules to one hundred and eleven. Every
removal was measured by pulling the rule and re running the check, never assumed from the advisory
list, and a control test confirmed the measurement lane was actually reading the registry before
any conclusion was drawn.

Five items stay open. The most important one is that push resets every branch's settings with no
confirmation prompt at all, and that matters more now that the settings panel writes to the same
file. That needs a decision from Patrick before it is built, because adding a prompt would change
what the settings panel is telling him to run.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13 (S136 — fix round to 100%, dispatch 40e33e8b)*
