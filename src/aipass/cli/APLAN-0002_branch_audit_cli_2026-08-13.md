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
| **Last verified** | 2026-08-16 (S42) |
| **Open items** | 3 (0 blocking) |
| **Tests** | 185 pass, 0 fail, 1 skip (177 test defs, 10 files) -- verified in 5 shells |
| **Seedgo** | 100% |
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
- [ ] ~~**Log_Structure -- @cli emits zero system logs, and structurally cannot**~~ RESOLVED S41 by @seedgo, see Resolved below. Original entry kept for the record: The checker reads "3 local logs but 0 system logs -- prax dispatch may be misconfigured". Nothing is misconfigured. `apps/modules/` **cannot import prax at all** (circular: prax depends on cli), so the branch's only four prax call sites are all in `cli.py` and all are failure paths: two module-load `logger.error`, one `logger.warning` on KeyboardInterrupt, one `logger.error` on unhandled exception. A HEALTHY @cli therefore emits nothing, forever -- the zero is the success case, not a symptom. Verified live: no `cli_*.log` exists anywhere in `system_logs/` (330 files). Reported to @seedgo S40; deliberately NOT papered over with a bypass while the checker owner rules. Note the history honestly: S39 deleted a `system_logs / log_structure` bypass after the standard read 100% with it gone; it reads 50% tonight. I cannot explain the flip and am attributing it to no one -- what I can state is the structural fact above, which was true on both days.
- [ ] **`test_scaffold.py` holds one permanently-skipped test** -- the branch conftest replaced the template scaffold fixtures, so the shipped scaffold test can never run here. It skips loudly with a clear reason, so it is honest, but it is 1 of 7 test files earning nothing. Low priority: either delete the file or ask @seedgo whether the template should stop shipping it to branches with real suites.

### Resolved

- [x] **4 red tests blocked Patrick's fleet commit train -- the suite was a function of the shell** (S42, @devpulse dispatch a94dbb4e, @daemon precedent). `test_templates.py` asserted plain substrings against Rich-rendered output. The gate shell exports `FORCE_COLOR=3`, which makes Rich treat a StringIO as a colour terminal and bold numbers and markup, so `created: 5` renders as `created: \x1b[1m5\x1b[0m` -- the substring is genuinely absent from a string a human reads as correct. `no_color=True` strips COLOUR but not ATTRIBUTES, which is why the old fixture looked safe. Fixed at the capture layer, not in production: one `make_capture_console()` in `tests/conftest.py` pins `force_terminal=False` + `color_system=None`, and `get_output()` runs `strip_ansi()` so every assert is about VISIBLE characters. All three capture sites (display, templates, integration -- including the stderr captures) now route through it; production rendering is untouched and still colours on a real terminal. Swept the whole suite: exactly one Console construction and one buffer read remain, both in conftest. 8 new tests pin the capture layer itself, one of them spawning real subprocesses in four shells because Rich resolves the colour system once at construction. Verified in 5 environments (FORCE_COLOR=3, TERM=dumb, NO_COLOR=1, TERM=xterm-256color, and no colour vars at all): 185 pass, 1 skip in every one. 4 mutations bit.
- [x] **Torn-write json_handler -- silent data loss under concurrency** (S41, @devpulse dispatch 5da09efd, fleet error 90c9e40d). Both write sites opened the target with `"w"`, truncating before the new bytes landed. Proved it on THIS handler before fixing: a 2-writer/2-reader race gave **550 of 949 reads a truncated empty file (58%)**. Worse than a failed read, because `ensure_json_exists()` answers an unreadable file by regenerating a template over it -- the race destroys the live document. Fixed with `_atomic_write_json()` (mkstemp in the SAME directory, then `os.replace`), routed through by BOTH sites including the regenerate path. Same probe after: **0 of 1084 (0%)**, no leftover temp files. 10 tests in a new file, red-first. My handler cannot import prax, so failed writes RAISE instead of logging -- no silent catch added.
- [x] **Log_Structure -- resolved by @seedgo, and the real bug was bigger than I reported** (S41). I reported a false positive; @seedgo found the check was **reading the live `system_logs/` directory**, so the score was a function of runtime state rather than of this branch's code. That is what made it read 100% one morning and violate that same night with my code byte-identical -- logs rotated, the number moved, nobody edited anything. They moved the observation to the non-scored info channel: the information survives, it cannot move the score, and @cli is not asked to log something it has no reason to log. Two corrections to what I wrote in S40: the `50` I quoted was the branch-level violation's own number, not the standard's score (that was 75 blended); and the flip I could not explain has a mechanism now, though neither of us could reconstruct which runtime state existed that morning. @seedgo also confirmed deleting the bypass in S39 was right even though it briefly cost me -- it turned an invisible suppression into a visible question.
- [x] **help_flag_safety: a question executed a demo** (S40, @seedgo dispatch 24f52754). `display demo --help` and `templates demo --help` reached `run_demo()` with the flag sitting unread at `args[1]` -- both modules gated `args[0]` only. Reproduced live before touching code, all three canaries red. Fixed with the fleet-standard shared predicate: new pure handler `apps/handlers/cli/help_flags.py::wants_help()`, called after the ownership check in both modules. 18 tests added red-first (7 module + 11 predicate), `run_demo` patched out in every case so a question can never reach a doing path. Help_Flag_Safety 100%.
- [x] **A third case @seedgo's checker did not name** (S40) -- `drone @cli demo --help`. The verb arrives in `command`, not `args`, so the old `if command == "demo": run_demo()` branch fired before any gate was consulted. Fixed here and covered by its own test. **Status in the STANDARD is half-closed, not closed** (corrected S41, @seedgo's own correction against themselves): they shipped a new arm (e) for the reduced shape I mailed, and it catches that -- but when they reconstructed my ACTUAL pre-fix `display.py` it still scored 100, because further down the function `args` IS read twice (`if not args:` and `if args[0] == "demo"`). "Never examined" was true of the demo PATH, not of the function, and their condition tests the function. Catching mine needs a "never read ABOVE the work call" discriminator, which they will not ship unmeasured. Recorded, per their explicit request, as **reported, reduced, and half-closed** -- do not read this branch's fix as proof the standard covers the shape. They also pinned that the router exemption deliberately does NOT apply to arm (e): a normalising router protects a module by rewriting args to `['--help']`, and a module that never reads args discards the rewrite too.
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
| 2026-08-13 | @seedgo verified + corrected me (24ac112b) | Arm (e) shipped for the reduced shape; my real file still uncaught -- half-closed. Log_Structure de-scored: the check read live runtime state. 100% overall |
| 2026-08-16 | Torn-write json_handler (@devpulse dispatch 5da09efd) | Fixed. Race proved 58% torn before, 0% after. 10 tests, 167 -> 177 pass, seedgo 100% |
| 2026-08-16 | @devpulse + @seedgo accepted both threads | Raise-over-log deviation ruled CORRECT. My FYI led @seedgo to find the same torn write in their OWN handler |
| 2026-08-16 | PRIORITY: 4 reds blocked the commit train (a94dbb4e) | Fixed at the capture layer. 185 pass in 5 shells, 4 mutations bit, seedgo 100%, production rendering untouched |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round)
- **Related FPLANs:** None yet
- **Owner branch:** @cli
- **Seedgo:** `drone @seedgo audit aipass @cli`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S42 (2026-08-16, night):** My suite blocked the fleet commit train, and the humbling part is that it was green when I reported 177 passing this morning -- in a shell without `FORCE_COLOR`. Same code, same tests, different answer twelve hours apart. @daemon's phrase for it is exact: luck is not proof.

Two things worth keeping. First, the fix belongs in the TEST, not the product: the tests were asking "which bytes came out" when they meant "what would a human see". Production highlighting is correct and stayed untouched -- the temptation to make the module quieter so the assert passes is how display code goes grey. Second, @daemon's second-layer lesson earned its keep: their first fix passed under FORCE_COLOR and failed under TERM=dumb, so I verified five shells rather than the one that reported the bug, and pinned the capture console AND stripped ANSI rather than trusting either alone.

A trap worth recording for the next mutation run: my `operation_start` -> `operation_begin` mutation is the SAME BYTE LENGTH, so after restoring the file Python served a stale `.pyc` (mtime granularity + identical size) and a passing test reported red. I nearly filed that as a real failure. Mutation harnesses must run with `-B` / `PYTHONDONTWRITEBYTECODE=1`, or same-length mutations will lie to you in both directions.

**S41 (2026-08-16):** Fleet torn-write defect landed here. The fix is three lines of pattern the fleet already carries; the part worth keeping is that I measured MY OWN handler before touching it instead of trusting the dispatch's numbers. @api reported 23% unparseable reads; mine showed 58% truncated-empty and zero unparseable. Same defect, different signature -- small documents and fast writes mean readers land in the truncation window rather than mid-content. Had I copied their number into my reply it would have been a plausible lie.

The other half of today was a correction TO me, and it is the more valuable one. @seedgo took my "cannot explain the flip" paragraph -- the thing I nearly left out as noise -- and found the actual bug behind it: their check was reading the live logs directory, so the score moved on its own with no edit anywhere. An audit number that changes by itself is worse than a wrong one, because nobody can act on it. Two lessons stack here: reporting confusion honestly is what surfaced it, and my S39 instinct to delete a bypass rather than keep an invisible suppression is what made it visible at all. They also corrected me AGAINST themselves on the help-flag arm -- my real file is still uncaught -- which is now recorded as half-closed rather than the win I would otherwise have banked.

**S40 (2026-08-13, evening):** @seedgo widened help_flag_safety and this branch was the only one in the fleet it newly named. Both findings real, both fixed. The lesson is not the bug -- it is that severity and priority are different questions. `run_demo()` only prints, so nothing was lost; on the same night the same shape stopped live sessions at @hooks and wrote a registry at @flow. The rule does not bend for cheap cases, because the gate that is wrong here is the gate that is wrong there.

Two things this audit produced that the dispatch did not ask for. First, a third broken case the checker did not name (`demo --help` -- verb in `command`, gate never consulted), sent back to @seedgo since they said they would rather re-audit than defend the checker. Second, a Log_Structure violation I chose to leave RED at 99% rather than bypass: @cli cannot import prax in `modules/` and its only four prax calls are error paths, so a healthy branch emits zero system logs by construction. That is worth a checker conversation, not a quiet suppression -- and it lands the morning after S39 removed a bypass in that exact standard, which I have recorded without inventing a cause.

**S39 (2026-08-13):** First full audit. Verdict GREEN -- nothing is broken, and the failure mode here is not rot but *lag*: code moved out of this branch (init to @aipass, drone_adapter and `__main__.py` to `.archive`) and the documentation, bypass file and runtime artifacts kept describing the old shape. 13 of 21 bypass rules were protecting files that no longer exist. The one live-tested breakage (`python -m aipass.cli`) turned out to be a doc claim, not a regression -- checking the fleet first is what prevented "fixing" it by restoring a file no other branch ships. Seedgo cannot catch this class: every metric was already 100% while the README was three facts wrong.

## Listen (TTS-friendly summary)

August sixteenth, night. Four of my tests were failing and blocking the commit train for the whole fleet. The cause is worth understanding, because the code was never broken. My tests checked the exact letters coming out of the display functions. But the display library decides whether to add invisible colour codes based on the shell it is running in, and the shell running the commit gate turns colour on always. So the words created colon five came out with invisible bold markers wrapped around the five. A person reading the screen sees it perfectly. A test looking for the plain letters does not find them. That is why my suite passed this morning and failed tonight on identical code. Green in one shell is luck, not proof.

The fix is in the tests, not in the product. The display still colours things on a real terminal, exactly as it should. What changed is that every test now strips the invisible codes before checking, so it asks what a human would see, which is what those tests always meant to ask. There is one shared helper for this now instead of three copies, and eight new tests guard the helper itself, including one that runs the same code in four different shells and demands an identical answer. The whole suite was then run in five different environments and gives one hundred and eighty five passes in all five. Four deliberate sabotages were introduced to confirm the tests still catch real breakage, and all four were caught.

One trap for next time, recorded because it nearly fooled me: one of my sabotages replaced a word with another word of exactly the same length, and after undoing it Python served a stale cached copy and reported a passing test as failing. Mutation runs must disable the bytecode cache.

August sixteenth. A defect found across the whole fleet reached this branch. Every time this branch saved one of its own data files, it emptied the file first and then wrote the new contents. Anything reading during that gap got an empty file, and this handler responds to an unreadable file by writing a blank template over it. So a moment of bad timing did not just fail a read, it destroyed the document. Before fixing anything I measured it here: with two writers and two readers running at once, five hundred and fifty out of nine hundred and forty nine reads came back empty. That is fifty eight percent. After the fix, the same test gave zero out of one thousand and eighty four. The file is now written to a temporary name first and then swapped into place in a single step, so a reader always sees either the whole old version or the whole new one.

Also today, seedgo corrected two things I recorded on Thursday, and both corrections go against them rather than against me, which is worth noting. The logging complaint I left open was not just a false alarm. Their check was reading the live log folder, so the score changed by itself as logs rotated, with no code changing anywhere. That is fixed at the source and the branch is back at one hundred percent. And the help flag gap I reported is only half closed, not closed. They caught the simplified version I described but not my actual file, and they asked me to record it that way rather than claim the win.

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
