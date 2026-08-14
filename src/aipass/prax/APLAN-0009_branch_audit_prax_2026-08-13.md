# APLAN-0009: Branch audit - prax

Tag: audit, branch-audit, 

> Branch audit @ -- living document tracking health, issues, improvements

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
| **Health** | GREEN — code and tests are sound; every open item is CLI-surface honesty |
| **Last verified** | 2026-08-14 (S72) |
| **Open items** | 6 (2 mine, 2 rulings for @devpulse, 1 fixture sweep, 1 environmental) |
| **Tests** | 1322 pass, 0 fail, 1 skipped (34 files) |
| **Seedgo** | 100% overall — `help_flag_safety` 50 → 100, `architecture` 100 (now a real measurement) |
| **Bypass entries** | 33 (0 under `tests/`) |
| **Test map** | 184 public functions, 179 tested (97%) |

## Current State

### Summary
- Logging backbone for the whole fleet: `from aipass.prax import logger` routes by
  stack introspection, two-tier (central `system_logs/` + branch-local `logs/`).
- Mission Control (4 threads), dashboards, log audit, log health.
- 6 command modules over 11 handler directories; entry point holds zero business
  logic.

### Architecture
`apps/prax.py` auto-discovers `apps/modules/*.py` and routes. Each module is a
thin orchestrator over `apps/handlers/`. Handlers are internal — external
branches import only `aipass.prax` or `aipass.prax.apps.modules.*`.

### What Works Well
- Logging itself. No branch runs its own setup, routing self-heals, and a prax
  import failure degrades to NullLogger instead of crashing the caller.
- Display resilience: everything on screen is another branch's output, escaped at
  the boundary; a line that cannot render costs that line, not the consumer.
- Queue-boundary scoping — out-of-scope traffic cannot evict what you asked for.
- The suite has real canaries: each regression class carries a test proving the
  old expression still fails.

## Issues Found

### Open

Use checkboxes. Mark resolved items `[x]` + note which session resolved them.

- [ ] **`--dry-run` is swallowed, not honoured — highest priority.** `dashboard
  refresh --all --dry-run` accepts and silently ignores the flag and performs the
  real fleet-wide write. Found the hard way in S69: a sub-agent probed with
  `--dry-run` *as a safety measure*, restamped every branch dashboard and
  recreated repo-root `STATUS.md`. Nothing was lost (both are regenerated state),
  but a tool that silently ignores a safety flag converts caution into damage.
  Same family as the item below: the CLI surface lies about what happened.
- [ ] **Error paths exit 0.** `monitor bogus`, `log-audit bogus`, `log-health
  bogus`, `dashboard refresh @nosuchbranch` all print an error and return 0.
  `status` is worse — an unknown subcommand or flag is dropped silently and the
  normal status block prints. Nothing scripted can detect a prax failure from `$?`.
- [ ] **`status sync` still writes — ruling needed from @devpulse.** TDPLAN-0007
  decommissioned the STATUS flow and deleted `STATUS.md` fleet-wide, but only the
  *trigger registration* was unwired. The CLI subcommand still reaches
  `sync_status()` and recreates the repo-root file. Fix is refuse-and-redirect or
  finish the decommission — not a unilateral prax change.
- [ ] **Fixture sweep in `tests/`** (the real fix behind the bypass ruling below).
  Those files carry more unwaived advisories than waived ones — @devpulse counted
  20+4 `hardcoded_path` and `windows_compat` against 3 waived. Restoring waivers
  would have silenced 3 of 7 true findings and bought no clean file.
- [ ] **`monitor run` is not single-instance** (environmental). `instance_lock`
  guards the *Telegram relay* only, so N concurrent Mission Controls start cleanly
  and each adds watches to a system already near `max_user_watches`. Verified S69
  by launching five alongside the systemd service; none complained.

### Resolved

- [x] **Mission Control was blind to `projects/*` citizens** (S72, night item 9,
  Patrick-found). `monitor run baud` said "BAUD is not a known branch". prax knew
  two path shapes — `src/aipass/*` and external Vera-class projects — and the
  in-repo `projects/<proj>/src/<mod>/<name>` shape was never learned. Fixed by
  declaration, not path shape: sweep `projects/*/*_REGISTRY.json` after the main
  registry (first registration wins), plus a `.trinity/passport.json` walk-up for
  anything still unresolved. known_branches 17 → 22. 20 tests.
  - Found on the way, worse than the report: BAUD's files were labelled **AIPASS**
    — the old fallback matched path segments against known branch names, and the
    repo directory is called `AIPass`. Misattribution beats UNKNOWN for damage:
    the events appear on the wrong screen *and* are filtered off the right one.
  - Found on the way, third bug: `_register_branch` resolved relative registry
    paths against the **process CWD**. 5 of 17 main-registry entries are relative,
    so launching the monitor from anywhere but the repo root mapped them to
    `<cwd>/src/aipass/<name>`. Masked because the path-segment fallback caught
    them anyway. Paths now resolve against their own registry's directory.
- [x] **A help probe executed the thing it asked about** (S71 — `help_flag_safety`
  50 → 100). All modules gated help at `args[0]` only, and the standalone paths
  screened `--help` but not `-h`, which survives a `--`-prefix filter on its
  single dash. `log_audit.py enforce -h` truncated every oversized log;
  `monitor.py run -h` started a live Mission Control. Whole-sequence check now
  sits inside each `handle_command`, after the ownership check, via a pure
  predicate in `handlers/cli/help_flags.py`. 29 tests. Reported by @seedgo, who
  tightened the rule to "must screen BOTH dashed spellings" *because* prax's own
  `dashboard.py` was already clean — my branch is the case that separates a real
  fix from a half fix.
- [x] **Architecture 100% was not a measurement** (S71 — the secondary item).
  `{"file": "apps/", "standard": "architecture"}` reads as "the apps directory as
  a category", but seedgo's matcher is a substring test, so it covered all 74
  `apps/` files. Measured with the new `--no-bypass` flag: it suppressed 4
  findings, and its stated reason ("template files managed by spawn") describes
  exactly **one** of them. The other three were `apps/plugins/devpulse_dashboard/`
  files flagged as outside the 3-layer structure — unrelated to spawn templates,
  never recorded anywhere. Split into two narrow rules that each say what they
  actually suppress. This is the third-species waiver I described to @seedgo this
  morning — stated reason drifting away from covered findings — found in my own
  registry hours later.
- [x] quick_status clobber, all four writers (S68/S70 — the calculator existed in
  4 copies; `refresh`/`operations` consolidated S68, `template_pusher` S70. All
  delegate to `status.py::calculate_quick_status` and merge. Pinned by a
  parametrised "every calculator agrees" test so a fifth cannot drift in.)
- [x] `push-template` deleted a live @flow key fleet-wide (S70 — `commons_mentions`
  sat in `DEPRECATED_QUICK_STATUS_KEYS`. prax owned it, stopped computing it, and
  marked it deprecated; @flow took it over rather than retiring it, so the list
  outlived the ownership change. A key qualifies only when nobody writes it.)
- [x] `action_required` disagreed with its own summary (S70 — ignored `todo_count`,
  so a block could publish `"1 todos"` and `false` together. Reported by @flow,
  measured against their writer.)
- [x] Silent catch in `rate_tracker.from_dict` (S70 — malformed persisted samples
  were dropped in silence. Now `debug()` per sample plus one summary `warning`, so
  a corrupt file cannot flood the logs this tracker measures.)
- [x] `log-health snapshot` reported a stale all-zero screen (S69 — persisted rate
  history restored and trimmed to the deque horizon; "No recent measurements"
  instead of rendering a quiet fleet as an idle one.)
- [x] README documented a live repo-root writer as dead code (S69 — `status sync`.
  The inverse of the usual drift: scope stayed, the prose buried it.)

## What Needs Doing

### @prax to handle
Items requiring branch itself to fix.

- [ ] Honour `--dry-run`, or reject unknown flags loudly. Both, ideally.
- [ ] Non-zero exit on every error path, `status` included.
- [ ] Fixture sweep in `tests/` (hardcoded_path, windows_compat advisories).

### devpulse to handle
Items devpulse coordinates or fixes directly.

- [ ] **Ruling on relocating `_ensure_watcher` off the caller's first log line**
  (night item 3, investigation delivered S72 — report only, no fix made).
  `logger.py:95` starts a file watcher (**0.287s**) and fires `trigger.fire("startup")`
  (**0.266s**) on the first `logger.info()` in every process, in front of **0.015s**
  of actual logging setup. Neither output feeds the caller's next action. Measured,
  not estimated: one log call costs 0.60s; every drone command pays it once
  (`drone_router.log` is written on every invocation). Proposed shapes in the
  dispatch reply — both are one-liners guarded by a flag, and both are @devpulse's
  call, not mine.
- [ ] Ruling on `status sync`: refuse-and-redirect to `DASHBOARD.local.json`, or
  finish the TDPLAN-0007 decommission. The engine is intentionally revivable, so
  this is not prax's call alone.

### Tracked elsewhere
Items captured in other DPLANs or FPLANs.

- [ ] Event-queue hardening: FileWatcherManager, diagnostics sink, priority
  eviction — see DPLAN-0280 (needs 2 rulings from @devpulse before build).
- [ ] Shared quick_status calculator: @flow imports prax's
  `calculate_quick_status`/`merge_quick_status`. Both public and stable; @flow
  owns the timing and mails before touching the seam. @devpulse ruled it lands as
  one morning conversation with Patrick, now three parts: the shared calculator,
  the label map, and the section schema below.
- [ ] **Section-level writes still assign wholesale.** The merge invariant agreed
  with @flow covers `quick_status` only. `refresh.py:101` builds `sections.flow`
  as a unit and writes `active_plans` as an **int**; @flow's push writes the same
  field as a **list** of plan objects, in a section whose `managed_by` says flow.
  Both self-consistent, no consumer can type the field. Measured by @flow
  2026-08-13, confirmed here. Either prax stops writing a section it does not own
  or the field gets one declared shape — a schema decision with Patrick in the
  loop, not a unilateral prax edit. Goes into the seam conversation.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Wave-4 branch audit (DPLAN-0291) | Done S69; wave closed by @devpulse 09:56 |
| 2026-08-13 | @flow: action_required flip-flop | Fixed S70, replied — found a 4th writer they could not see |
| 2026-08-13 | @devpulse: 3 false-dead bypass rules | Ruled S70: restore none, change none. Accepted |
| 2026-08-13 | @seedgo: 2 checker observations sent | Both accepted as seedgo bugs, logged in APLAN-0005 with my cases named |
| 2026-08-13 | @devpulse dispatch: help_flag_safety to 100 | Done S71. 3 modules fixed, 29 tests, overall 98 → 100 |
| 2026-08-13 | Secondary: `apps/` bypass width measured | Covered 74 files, reason described 1 of 4 findings. Split into 2 narrow rules |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round), DPLAN-0280 (event queue)
- **Related FPLANs:** None open
- **Owner branch:** @prax
- **Seedgo:** `drone @seedgo audit aipass @prax`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S00 (2026-08-13):** Initial audit created.

**S70 (2026-08-13) — RULING ON THE 3 FALSE-DEAD BYPASS RULES.**

*Correction, same session:* I first wrote this entry saying "the wave-4 audit has
not run." It had. S69 ran it — 44 command paths, 17 error paths, the `status
sync` and `--dry-run` findings, `test_log_health.py`, and this file — and then
ended without saving a memory, so S70 opened with a template it read as untouched
and no session entry to correct it. @devpulse's close mail is what surfaced it.
An unsaved session is indistinguishable from a session that never happened.

Context: my 2026-08-13 prune (385d5943, 76 -> 31 rules) measured deadness with
`audit_branch(bypass_rules=[])`. @seedgo found that instrument has a lane — the
AUDIT lane walks `apps/` and never enters `tests/`, so a `tests/*` rule reads as
dead there while still suppressing findings in the CHECKLIST lane (the
PostToolUse hook). @devpulse read my deleted rules out of git history and
measured both lanes: 42 of 45 were `apps/` files, safe. Three were `tests/*`
rules that now surface advisories.

Decision: **restore none, change none.** Re-measured all three myself:

| Rule | Advisory now visible | Why it stands |
|------|---------------------|---------------|
| `tests/test_log_watcher.py` / naming | `_RealFSHandler` non-PascalCase | `check_class_naming` matches `^[A-Z][a-zA-Z0-9]*$`, which no leading-underscore class can satisfy. `tests/test_branch_scope.py` carries the identical advisory (`_Event`, `_Bare`) and never had a waiver — waiving one and not its twin is the inconsistency. |
| `tests/test_filesystem_handler.py` / log_structure | `/home/` line 1676 | Rule is `re.search(r"/home/\w+", line) and "log" in line.lower()`. Line 1676 is `_build_display_name(Path("/home/user/modules/logger.py"))` — path-parser *fixture data*, not log configuration, matched because the fixture filename contains "log". The same file holds 21 more `/home/user/` literals the rule does not see. |
| `tests/test_logging.py` / log_structure | `/home/` lines 29, 35 | Same rule, same shape: `_is_prax_internal("/home/user/.../logger.py")` fixtures. |

Rejected alternatives, and why: restoring the waivers blankets a whole
file+standard pair (proven live — `apps/handlers/logging/setup.py`'s naming
waiver is worded about mutable flags and is silently also covering a
`_WindowsSafeRotatingHandler` class finding nobody recorded). Renaming the
`/home/user/` prefixes would satisfy the regex without making anything less
hardcoded, and would be incoherent applied to 3 of 24 identical literals.
Registry stays at 31. Both checker observations sent to @seedgo.

Correction worth keeping: I first read `setup.py`'s clean `naming` line as
evidence that the checker treats `class _Foo(Base)` differently from
`class _Foo:`, and nearly mailed @seedgo that claim. It passed because a waiver
hid it. The regex has no such distinction — checked the source before sending.

## Listen (TTS-friendly summary)

Prax is healthy. All 1273 tests pass, the standards audit is at 100 percent across 44 standards, and the logging system itself, which is the part the whole fleet depends on, has no open issues. Every problem worth naming is on the command line surface rather than in the code.

The one that matters most is the dry run flag. Asking prax to refresh all dashboards with dry run does not preview anything. Prax accepts the flag, ignores it, and performs the real fleet wide write. A sub agent used dry run as a safety measure during yesterday's audit and rewrote every branch dashboard because of it. Nothing was lost, because those files are regenerated anyway, but a tool that quietly ignores a safety flag turns caution into damage. Closely related, almost every error path returns success. An unknown command prints an error and exits zero, so no script can tell whether prax failed.

Two fixes landed today, both from other branches noticing things I could not see from inside. Flow reported that the action required flag ignored todos, so a dashboard could say one todo and no action needed in the same breath. Chasing that turned up something worse. The code that calculates a branch's status existed in four separate copies, and the fourth one, behind push template, writes every branch in the fleet. It had no todo counter, it replaced the status block instead of merging it, and it listed a key that flow actively owns as deprecated, which means one run of that command would have deleted flow's data from every branch on purpose. All four copies now share one implementation, and a test proves they agree.

Devpulse asked for a decision on three waiver rules I deleted last week that turned out to still be doing work. I measured them and restored none. Two of them flag test fixture data as if it were logging configuration, and the third flags a private class name that is perfectly ordinary Python. Restoring them would have hidden more true findings than false ones.

What needs attention next is the dry run flag, then the exit codes, then a ruling from devpulse on the status sync command, which was supposedly decommissioned months ago but still rewrites a file at the top of the repository every time someone runs it.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
