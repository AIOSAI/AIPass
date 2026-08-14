# APLAN-0002: Branch audit - cli

Tag: audit, branch-audit, cli

> Branch audit @cli -- living document tracking health, issues, improvements

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
| **Last verified** | 2026-08-13 (S40) |
| **Open items** | 4 (0 blocking) |
| **Tests** | 167 pass, 0 fail, 1 skip (159 test defs, 8 files) |
| **Seedgo** | 99% -- one open violation, see Log_Structure below |
| **Bypass entries** | 9 (was 21 -- 13 dead deleted S39, 1 added S40) |
| **Ruff** | clean |
| **Type errors** | 0 |
| **Test map** | 15 public functions, 15 tested |
| **Fleet consumers** | 252 files import `aipass.cli` |

## Current State

### Summary
- Pure library branch. The public display API is the product; commands are introspection + demos only.
- Everything advertised by `drone @cli --help` was run live this audit and works. No broken commands.
- The branch shrank in scope over time: project init moved to @aipass, `drone_adapter.py` and `__main__.py` were archived. Docs had not caught up -- that was the bulk of this audit's findings.

### Architecture
Two-tier. `apps/modules/` is the public API (display.py, templates.py) -- 14 symbols re-exported from `apps/modules/__init__.py`, 6 of them also from the branch root. `apps/handlers/json/json_handler.py` is internal (JSON CRUD, validation, rotation). `apps/cli.py` is the drone entry point: `discover_modules()` scans `modules/*.py` for `handle_command()`, `route_command()` dispatches.

Hard constraint shaping everything: `apps/modules/` cannot import `aipass.prax` -- prax depends on cli, so importing it back is circular. Same for `json_handler.py`. This is why the remaining silent_catch / imports / error_handling bypasses exist and why they are permanent, not debt.

### What Works Well
- All 6 live commands verified this audit: bare introspection, `--version`, `display`, `display demo`, `templates`, `templates demo`. All exit 0, all render correctly.
- Test suite is fast (8.3s) and honest -- 140 green with no xfail padding; the one skip is self-documenting.
- Seedgo 100% across all 44 standards, no type errors, ruff clean.
- Public API has stayed stable while 252 fleet files came to depend on it.

## Issues Found

### Open

Use checkboxes. Mark resolved items `[x]` + note which session resolved them.

- [ ] **`cli_entry()` is orphaned** -- `__init__.py:8`. `pyproject.toml` maps the `aipass` script to `aipass.aipass.apps.aipass:main`, so nothing in-tree calls `cli_entry()` except its own test (`test_integration.py:124`). It is still importable published API. Needs a keep-or-retire call, not a silent deletion: retiring it changes `aipass.cli`'s surface for any external install that imported it. Bypass entry `__init__.py / unused_function` was re-worded this audit to state the real reason. Impact: low, cosmetic -- dead but harmless.
- [ ] **Exit-code API is 4 branches short of a purpose** -- `resolve_exit()` and the failure flag landed 2026-07-09 as a fleet foundation. Live grep: only @ai_mail and @devpulse adopted it. Until branches call `resolve_exit()` in their `main()`, non-zero exit on failure is not real fleet-wide. Not a cli bug -- a rollout that stalled. @devpulse to decide whether it ships or gets dropped.
- [ ] **Log_Structure 50% -- @cli emits zero system logs, and structurally cannot** (opened S40, awaiting @seedgo ruling). The checker reads "3 local logs but 0 system logs -- prax dispatch may be misconfigured". Nothing is misconfigured. `apps/modules/` **cannot import prax at all** (circular: prax depends on cli), so the branch's only four prax call sites are all in `cli.py` and all are failure paths: two module-load `logger.error`, one `logger.warning` on KeyboardInterrupt, one `logger.error` on unhandled exception. A HEALTHY @cli therefore emits nothing, forever -- the zero is the success case, not a symptom. Verified live: no `cli_*.log` exists anywhere in `system_logs/` (330 files). Reported to @seedgo S40; deliberately NOT papered over with a bypass while the checker owner rules. Note the history honestly: S39 deleted a `system_logs / log_structure` bypass after the standard read 100% with it gone; it reads 50% tonight. I cannot explain the flip and am attributing it to no one -- what I can state is the structural fact above, which was true on both days.
- [ ] **`test_scaffold.py` holds one permanently-skipped test** -- the branch conftest replaced the template scaffold fixtures, so the shipped scaffold test can never run here. It skips loudly with a clear reason, so it is honest, but it is 1 of 7 test files earning nothing. Low priority: either delete the file or ask @seedgo whether the template should stop shipping it to branches with real suites.

### Resolved

- [x] **help_flag_safety: a question executed a demo** (S40, @seedgo dispatch 24f52754). `display demo --help` and `templates demo --help` reached `run_demo()` with the flag sitting unread at `args[1]` -- both modules gated `args[0]` only. Reproduced live before touching code, all three canaries red. Fixed with the fleet-standard shared predicate: new pure handler `apps/handlers/cli/help_flags.py::wants_help()`, called after the ownership check in both modules. 18 tests added red-first (7 module + 11 predicate), `run_demo` patched out in every case so a question can never reach a doing path. Help_Flag_Safety 100%.
- [x] **A third case @seedgo's checker did not name** (S40) -- `drone @cli demo --help`. The verb arrives in `command`, not `args`, so the old `if command == "demo": run_demo()` branch fired before any gate was consulted -- args were never examined at all. Reported back to @seedgo as a possible checker gap; covered by the same fix and its own test.
- [x] 13 dead bypass rules deleted (S39) -- 21 -> 8. Removed: `tests/test_bootstrap.py` x4 (file does not exist), `setup.py` x5 (no setup.py in branch or repo), `drone_adapter.py` x2 (archived as `drone_adapter(disabled).py`), `tests/test_init_provisioning.py` architecture (seedgo confirmed it suppresses nothing), `system_logs / log_structure` (prax fixed its branch-detection bug; verified by removing the bypass and re-auditing -- Log_Structure held 100%). Audit re-run after every removal: still 100%.
- [x] README claimed `python -m aipass.cli` works -- it does not (S39). Live: `No module named aipass.cli.__main__`. `__main__.py` was archived 2026-05-02. Checked the fleet: **no branch ships a `__main__.py`**, so the archive matched convention and the doc was the wrong half. Fixed docs rather than restoring the file.
- [x] README + branch prompt claimed `aipass` on PATH runs `cli_entry()` (S39) -- false since init ownership moved to @aipass. Both corrected.
- [x] Branch prompt carried a stale critical rule: "handle_command() accepts both `command='init'` and `command='aipass'` -- both paths must stay wired" (S39). No such routing exists in `cli.py` any more, and re-adding it would duplicate @aipass. Replaced with the real rule (handle_command lives in display.py/templates.py) plus an explicit "init is not ours" line.
- [x] README metric drift (S39) -- claimed 127 tests / 5 files / seedgo 99%; reality 141 / 7 / 100%. Public API table listed 10 symbols; reality 14 (the exit-code four were never documented). All corrected.
- [x] Orphaned `init_project` runtime artifacts (S39) -- 3 JSON files in `cli_json/` and `logs/init_project.log`, left behind when init moved out. Moved to `.archive/init_project_leftovers_20260813/` with a README explaining provenance.
- [x] Passport had empty `what_i_do` / `what_i_dont_do` / `traits` (S39) -- filled from verified behaviour, including the "init is not ours" boundary.

## What Needs Doing

### @cli to handle (dispatch)
- [ ] Decide keep-or-retire on `cli_entry()` once @devpulse rules on external-API breakage.
- [ ] Ask @seedgo whether `test_scaffold.py` should still ship to branches whose conftest overrides it.

### devpulse to handle
- [ ] Rule on the exit-code rollout: finish it fleet-wide (15 branches to go) or retire `resolve_exit()` from the public API. It has sat inert since 2026-07-09.

### Tracked elsewhere
- None.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fleet audit round wave 1 (DPLAN-0291, dispatch fa52a464) | GREEN -- 140 tests, seedgo 100%, 13 dead bypasses removed, 6 doc-drift fixes, 3 open items |
| 2026-08-13 | @devpulse verified wave 1 (3e14161b) | Re-ran the audit himself, 100% held. Both rulings escalated to Patrick via DPLAN-0291 |
| 2026-08-13 | help_flag_safety fix (@seedgo dispatch 24f52754) | Fixed, 3 canaries green, 18 tests, 167 pass. Found a 3rd case the checker missed; opened Log_Structure finding |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round)
- **Related FPLANs:** None yet
- **Owner branch:** @cli
- **Seedgo:** `drone @seedgo audit aipass @cli`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S40 (2026-08-13, evening):** @seedgo widened help_flag_safety and this branch was the only one in the fleet it newly named. Both findings real, both fixed. The lesson is not the bug -- it is that severity and priority are different questions. `run_demo()` only prints, so nothing was lost; on the same night the same shape stopped live sessions at @hooks and wrote a registry at @flow. The rule does not bend for cheap cases, because the gate that is wrong here is the gate that is wrong there.

Two things this audit produced that the dispatch did not ask for. First, a third broken case the checker did not name (`demo --help` -- verb in `command`, gate never consulted), sent back to @seedgo since they said they would rather re-audit than defend the checker. Second, a Log_Structure violation I chose to leave RED at 99% rather than bypass: @cli cannot import prax in `modules/` and its only four prax calls are error paths, so a healthy branch emits zero system logs by construction. That is worth a checker conversation, not a quiet suppression -- and it lands the morning after S39 removed a bypass in that exact standard, which I have recorded without inventing a cause.

**S39 (2026-08-13):** First full audit. Verdict GREEN -- nothing is broken, and the failure mode here is not rot but *lag*: code moved out of this branch (init to @aipass, drone_adapter and `__main__.py` to `.archive`) and the documentation, bypass file and runtime artifacts kept describing the old shape. 13 of 21 bypass rules were protecting files that no longer exist. The one live-tested breakage (`python -m aipass.cli`) turned out to be a doc claim, not a regression -- checking the fleet first is what prevented "fixing" it by restoring a file no other branch ships. Seedgo cannot catch this class: every metric was already 100% while the README was three facts wrong.

## Listen (TTS-friendly summary)

Evening update, August thirteenth. Seedgo widened one of its checkers and found that asking this branch for help could run a demo instead. Typing display demo dash dash help gave you the demo, not the explanation, because the help gate only ever looked at the first argument and the flag was sitting in the second. Three of those cases were broken, including one seedgo did not know about, where the word demo arrives in a different slot and the gate is never consulted at all. All three are fixed and verified by running them, not just by testing them. Eighteen new tests, and the demo function is blocked in every one of them, so a question can never reach a doing path. Nothing was ever lost by this bug, because the demo only prints, but the same shape stopped live sessions on another branch the same night.

One violation is deliberately left open rather than hidden. The standards checker says this branch is missing its system logs and suspects a misconfiguration. It is not misconfigured. This branch cannot import the logging system at all, because the logging system depends on this branch, and the only four places it does log are error paths. So a healthy cli branch produces no logs by design, and the zero is the success case. That question goes back to seedgo, who owns the checker, instead of being silenced with a bypass. The branch sits at ninety nine percent and the reason is written down.

The cli branch is healthy. Everything it advertises was run live and works, all one hundred forty tests pass, the standards audit is at one hundred percent, and there are no type errors. Nothing is broken.

The real finding is that the documentation had fallen behind the code. Over the last few months this branch got smaller. Project init moved to the aipass branch, and two entry point files were archived. The readme and the branch prompt never caught up, so they promised three things that are no longer true, including a python module command that fails immediately when you run it. Those are all fixed now, and the branch prompt has a new rule saying plainly that init does not belong here, so nobody rebuilds it by accident.

The bypass file was the worst of it. Twenty one rules, and thirteen of them were guarding files that no longer exist. All thirteen are gone and the audit still scores one hundred percent. One of those removals doubles as proof that the prax logging bug from March is genuinely fixed.

Three things are left open, none of them urgent. A leftover entry point function called cli entry is no longer wired to anything and needs a decision on whether to keep it. The exit code feature built in July is still only used by two branches out of seventeen, so devpulse needs to decide whether to finish that rollout or drop it. And one test file holds a test that can never run here.

Health is green. Last verified August thirteenth.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
