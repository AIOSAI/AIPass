# APLAN-0003: Branch audit - drone

Tag: audit, branch-audit, drone

> Branch audit @drone -- living document tracking health, issues, improvements

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
| **Health** | GREEN (was YELLOW at S50 — the functional bug that held it back is fixed) |
| **Last verified** | 2026-08-14 (S54) |
| **Open items** | 5 (2 dead code, 3 housekeeping — the queued rm-guard bug shipped at S54) |
| **Tests** | 1118 pass, 0 fail, 5 skip (1123 collected, 28 files) |
| **Seedgo** | 100% overall — help_flag_safety 100% (was 9% at 16:47, overall 97%), 45 standards, forced full re-scan, no type errors |
| **Bypass entries** | 30 (was 48 at S50 — 19 deleted proven dead, +1 for help_flags; S54 wrote one and withdrew it, fixing the code instead) |
| **CLI score** | cli 100%, cli_flags 100%, cli_ux 100% (no Nav/Output 0-5 scorer exists in seedgo) |
| **Live command sweep** | 29/29 commands executed at S50, 0 broken; +3 new verbs live-proven at S51 |

**Why GREEN now:** `prune-temp` — the one advertised-but-unreachable verb — is wired to owner tier and refuses honestly instead of claiming not to exist, and the *class* of defect is guarded by `test_every_registered_command_holds_a_tier` rather than a test naming the one instance. Nothing reachable is broken. What remains is dead code and housekeeping, not defects.

## Current State

### Summary
- Command router and symbolic addressing for AIPass. Resolves `@branch` -> path via `AIPASS_REGISTRY.json`, routes commands, and owns **all** git operations behind a tier gate.
- The only git interface in the system. Raw `git`/`gh` is blocked at the hook layer, so if drone's git module is wrong, nobody has a fallback.
- v1.1.0, confirmed consistent across `README.md:7`, `__init__.py:44`, `apps/drone.py:46`.
- Last build: the `tag` external-repo lanes (DPLAN-0290 item 1, shipped 2026-08-12, accepted by @devpulse 23:28).

### Architecture
Three routing paths, checked in order: built-in commands (`systems`, `scan`, `activate`, `list`, `remove`, `rm`) handled in `drone.py`; `@target` routing resolved via registry then dispatched by subprocess; module fallback for internal (`git`, via importlib) and external (`seedgo`, `cli`, `spawn`, via `generic_adapter` + `routing_config.json`) modules.

Git access is two tiers checked once at the top of `git_module.handle_command()`. Owner tier is **earned per-repo** from four facts (manager class + registry tenancy + owner flag + passport path-binding), not a hardcoded name list (DPLAN-0281).

### What Works Well
- **Every routing path is live and correct.** All three paths exercised: branch routing, internal module (`@git`), external module fallback (`@seedgo`, `@cli`, `@spawn`). All work.
- **Error paths are clean.** Four failure modes tested (unknown branch, unknown command, unknown shortcut, scan of unknown branch) — all return readable errors, zero Python tracebacks anywhere in the sweep.
- **The owner-tier gate refuses precisely.** `drone @git commit` from this seat returns: `Branch 'drone' is not authorized for 'commit': caller 'drone' is citizen_class 'aipass_framework' — owner-tier requires 'manager'.` It names the caller, its class, and the requirement.
- **The `issue view` rewrite holds.** Both `drone @git issue view 733` and `--comments` render real issues — no trace of the Projects-classic deprecation that killed them before FPLAN-0400.
- **Command-shortcut round trip is non-destructive.** activate -> list -> remove -> restore verified byte-identical (md5 match).
- **Test suite is fast and honest** — 1019 green in ~54s, and the 5 skips all state a real reason.

## Issues Found

### Open

- [ ] **`pr_handler.py` is orphaned** — `create_pr()` (line 108) has zero production callers; `_handle_pr()` dispatches to `dev_pr_handler.create_branch_pr()` instead. Its only 7 callers are in `tests/test_git_module.py`. Per S46's ruling (test-only API is what `unused_function` exists to catch, not a false positive), the honest end state is deletion — a whole-module removal, so still logged rather than done. @devpulse agreed the reasoning at S51 and asked that the test cleanup ride with it.
- [ ] **`update_command()` / `command_exists()` in `ops.py`** — tested CRUD API, no production caller. Long-standing known issue, unchanged.
- [ ] **No BrokenPipe handling anywhere in the tree** — piping drone output into a truncating reader gives inconsistent exit codes: `drone @flow --help | head -20` -> 243, `drone systems | head -3` -> 1, `drone @git log | head -2` -> 0. All exit 0 when redirected to a file, and no traceback in any case. `grep -rE 'BrokenPipe|SIGPIPE'` across the branch returns zero hits. Cosmetic, but it means `drone ... | head` cannot be used inside a `set -e` script.
- [ ] **`.archive/` and `logs/.archive/` are accumulating** — 4 archive directories; `logs/.archive` alone holds ~30 rotated logs from 2026-03-24..03-31, including three ~50KB `.log.1` files. Nothing is broken; it is just 4.5 months of sediment nobody has swept.
- [ ] **107 public functions, 101 tested** — 6 untested. Run `drone @seedgo test_map @drone` to name them.

### Resolved

- [x] **`drone rm` sibling-branch guard false-positived on spawn template trees** (reported by @devpulse 2026-08-13, ruled by Patrick 2026-08-14, shipped S54). `_find_branch_root` returned the INNERMOST `.trinity/` ancestor, and @spawn ships a full branch skeleton under `templates/` — so refusals named `aipass_framework`, a template with no mailbox to appeal to. Now walks to the OUTERMOST hit inside the project, matching the mapping @devpulse used on the commit gate (`e934099f`) for the identical mimicry. Fixing it surfaced a second, unreported bug: @spawn could never delete inside its own `templates/`, because a skeleton's name never matches the branch you are standing in. 7 tests, 4 red first. Patrick ruled NO carve-out on the policy half — the guard stays exactly as strict, and build artefacts in another citizen's tree are removed by hand.

- [x] **Subprocess default timeout 30s -> 60s, stamped in every layer** (S53) — Patrick's ruling: two known runners finish around 31s and were tripping the old default. The default lived in THREE places and only one was a named constant: `DEFAULT_TIMEOUT` in `executor.py:24`, plus `execute_command(timeout: int = 30)` at `executor.py:62` and `execute_branch_command(timeout: int = 30)` at `router_handler.py:282` — two signatures agreeing with the constant by coincidence, not by reference. Raising the constant alone would have left every caller relying on a signature default still at 30, which is precisely the failure DPLAN-0285 had just cost the fleet. Both signatures now reference `DEFAULT_TIMEOUT`, so the layers cannot drift apart again. 7 tests, 4 red first; they assert the NUMBER (the pre-existing tests compare against the constant and stay green at any value) and that all three layers agree. `TIMEOUT_OVERRIDES` untouched, and a test pins that a policy lower than the default still wins — resolution order must not quietly become `max(policy, default)` as the default rises.
- [x] **`--drone-timeout` placement documented from the code, not from assumption** (S53) — the known confusion settled by running it: the flag works ANYWHERE after `@target` (including after the routed command and its arguments) and fails before it with `drone: unknown command '--drone-timeout'`. Both the help table and the README previously showed it in the standalone `drone --drone-timeout <n>` shape, which is the one form that does not work. Fixed in both, with the failing form shown explicitly so nobody has to guess again.
- [x] **help_flag_safety 9% -> 100%: a help flag anywhere now explains, never executes** (S52) — the new standard (DPLAN-0291 rule E) named all 10 of my modules for the same shape: `handle_command()` gated help at `command` or `args[0]` only, so a flag typed later was invisible and the verb ran. **The teeth were in `rm`**, where every token is a PATH: `drone rm notes.md --help` deleted notes.md and then tried to delete a file literally named `--help`. Fixed with one shared predicate, `wants_help()` in `apps/handlers/help_flags.py`, called inside all ten `handle_command()`s — the gate existed as ten copies of the same two lines, which is exactly how ten modules drifted into one bug (S39: define a rule once). 36 tests, 13 red first, every dispatch target mocked and asserted never called — no live verb fired to prove the trap. Live-proven on a throwaway file: `drone rm canary.txt --help` printed usage and the file survived, while an ordinary `drone rm real.txt` still deletes.
- [x] **`discovery help <target>` protected from its own fix** (S52) — discovery owns `help` as a genuine subcommand, so a blanket bare-`help` rule would have made `drone @discovery help @seedgo` print discovery's own help instead of seedgo's. `wants_help(..., bare_help=False)` opts it out; dashed forms still catch. Two tests pin both directions. Worth recording because the fix for one bug was one keyword away from causing another.
- [x] **`prune-temp` wired to owner tier** (S51) — @devpulse ruled owner on the blast-radius argument (deletes merged remote `citizen/*` branches = `delete-branch` class). Now refuses non-owners by naming the tier requirement instead of claiming the command does not exist, and reaches the handler for the owner. Help text moved from the global list to owner. **The instance was the smaller half:** `test_every_registered_command_holds_a_tier` now asserts that every verb in `_COMMANDS` holds a tier, plus a mirror test for tier entries with no registered command. A test naming `prune-temp` would have caught this one verb; the invariant catches the next one.
- [x] **`view N` ate all-digit message IDs** (S51) — reported by @trigger, and reproduced by accident on the very first mail of this session: `drone @ai_mail view 04727185` returned `Message not found: 4727185`, leading zero gone. Root: the `.isdigit()` guard at `drone.py:481` fired on any all-digit token, and ai_mail IDs are `str(uuid4())[:8]`, so (10/16)^8 = 2.3% of them are all digits. `_resolve_mail_token()` now looks the token up as an ID *first* and only falls back to the index, which removes the ambiguity class instead of narrowing it; on failure it returns the ORIGINAL token rather than `str(int(...))`, so the error names what the user typed. 6 tests, all red first. Live-proven on the ID that failed.
- [x] **`git show` added at global read tier** (S51) — requested by @seedgo via @devpulse: auditing a prune means reading what was DELETED, and status/diff/log only show the present, so @seedgo could not verify another branch's committed prune at all. Deliberately NOT branch-scoped — scoping it would refuse the exact use case. Flag-like refs and paths refused before argv is built (S49 lesson). 11 tests red first; live-proven reading `@prax`'s bypass.json at a historical commit from this seat.
- [x] **`register_module()` / `refresh_external_modules()` deleted** (S51) — zero consumers. @devpulse grepped `src/` + `projects/`; I closed the gap they could not see by grepping every other AIPass checkout on disk, since a drone extension point would plausibly be consumed by an *external* project. The only hits were in Dev-Pass, the predecessor system, which defines its own `register_module_commands` and imports nothing from `aipass.drone`. Both functions, their `__all__` entries, the introspection line and their 5 tests are gone.
- [x] **`normalize_branch_arg()` KEPT** (S51) — the third suspected-dead export turned out to have live external production callers: `@seedgo` imports it in `standards_audit.py:51` and `test_map.py:43`. S37's rule (killing an export needs a repo-wide grep) earned its keep — the in-branch view said "dead" and was wrong.
- [x] **19 dead bypass rules deleted** (S50) — seedgo reported 15 suppressing nothing (test-file rules for standards that no longer apply to tests). Found 4 more it did not flag, whose target file no longer exists: three for `hook_sounds_plugin.py` (now `.disabled`) and one for a `CLAUDE.md` this branch does not have. Proven dead the S47 way — deleted them, then forced a full re-scan: still 100%, and the "suppresses nothing" notice is gone. 48 -> 29.
- [x] **A bypass rule was defending orphaned code with a false reason** (S50) — the `pr_handler.py` / `unused_function` rule read "pr command blocked at auth tier". That is not true: `pr` is owner-tier and live, it just dispatches elsewhere. Rewritten to state the real situation and point here. The suppression is still live; only the justification was wrong — which is worse than a dead rule, because it reads as settled.
- [x] **README drift corrected, 10 items** (S50) — see Notes.
- [x] **`routing_config.json` declared `cli` at 2.0.0; `@cli` reports 2.1.0** (S50) — corrected. Latent (drone never renders external-module versions), but it is drone's file and drone's job to keep true.

## What Needs Doing

### @drone to handle (dispatch)
- [ ] Decide `pr_handler.py`: delete the module and its 7 tests, or wire it back. It cannot stay orphaned indefinitely.
- [ ] Add BrokenPipe handling at the CLI boundary so piped output exits consistently.
- [ ] Sweep `logs/.archive` and the `recovery_*` directories in `.archive/` (2026-03 vintage).
- [ ] The line-scoped `cli` bypasses keep drifting (`apps/drone.py` at S51, `apps/modules/router.py` at S52 — a one-line import moved the write site). **Function-scoping was tried at S52 and does NOT work**: converting both rules to `"functions": [...]` re-reported every violation, so the `cli` checker honours `lines` but not `functions` (`unused_function` does honour it — `pr_handler.py` uses it today). Reverted to lines. Reported to @seedgo; blocked on their checker until then, so the cost is a refresh on every edit above a write site.

### devpulse to handle
- [x] ~~Rule on `prune-temp`'s tier~~ — ruled OWNER at S51, implemented same session.

### Tracked elsewhere
- [ ] `merge_plugin.py:104` — `pull --rebase` against a stale `origin/dev` mints duplicate commits. Fix is fetch + FF-only. Carried in drone's `.trinity` todos since S32, confirmed by devpulse. Not urgent, still open.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | @devpulse dispatch 34cbab6a — help_flag_safety 9/100, 10 modules | 100%, 36 tests red-first, `rm` deletion bug live-proven fixed |
| 2026-08-13 | @trigger dispatch b7c79832 — `view N` eats all-digit IDs | Fixed, 6 tests red-first, live-proven |
| 2026-08-13 | @devpulse ruling — `prune-temp` tier | OWNER, wired + class-level invariant test |
| 2026-08-13 | @devpulse/@seedgo request — `git show` at global tier | Built, 11 tests red-first, live-proven on the requested use case |
| 2026-08-13 | @devpulse — export removal call | 2 deleted (evidence gap closed on external checkouts), 1 KEPT (live seedgo consumer) |
| 2026-08-13 | Fleet audit round DPLAN-0291, wave 1 (dispatch 8f928ddf) | Complete — YELLOW, 1 functional bug found (`prune-temp`), 19 dead bypasses deleted, 10 README drifts fixed |
| 2026-08-12 | DPLAN-0290 item 1 — translate `tag` for external seats | Accepted by @devpulse; ls-remote exit-code guard called "the catch of the night" |
| 2026-08-12 | FPLAN-0400 E — `issue view` deprecation fix | Shipped; re-verified live in this audit |

## Relationships
- **Related DPLANs:** DPLAN-0291 (this fleet audit round), DPLAN-0281 (owner tier earned per-repo), DPLAN-0290 (tag lanes)
- **Related FPLANs:** FPLAN-0403 (tag translation), FPLAN-0400 (issue view rewrite)
- **Owner branch:** @drone
- **Seedgo:** `drone @seedgo audit aipass @drone`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S54 (2026-08-14):** Two Patrick rulings — the deletion record, and the guard fix it arrived beside.

*The record had to cover the lane nobody named.* The ruling said "if something deletes, there should be a record of it", and the ticket pointed at `drone rm`. But drone has TWO delete lanes — `rm_handler` and the broker daemon, which performs its own `rmtree`/`unlink` for sandboxed callers. Wiring the record only where the ticket pointed would have left a hole exactly the size of the sandboxed lane. Both feed `handlers/deletion_log.py` now. The broker passes its HMAC-authenticated requester in explicitly, because resolving identity from cwd there would record the daemon's own location instead of whoever asked.

*The remaining `unlink` sites are drone's own runtime, not anyone's data* — the broker's socket file (bind and teardown), the git lock release, and json_handler's atomic-write temp cleanup. Listed rather than wired: a record of drone deleting its own socket on startup is noise that makes the real records harder to find.

*Green on the first run is an unproven canary.* All 26 deletion tests passed immediately, which is the same shape as S52's canary that never bit. Two deliberate mutations settled it: dropping the pre-delete measurement failed 5, dropping refusal records failed 6, and each failed for its own stated reason. One identity test survived both — it put a passport inside a directory named after the branch, so path-shape matching answered identically. Rewritten with the names deliberately different.

*Two seedgo findings were right and one was a shape mismatch.* A rotation-check failure passing silently is how a bounded log stops being bounded — real bug, fixed. The third wanted a logger call inside a tree-walk `except`, which on a large directory means one line per file, burying the signal. I wrote the bypass, then found the honest answer instead: DEBUG for which entry, one INFO for the total, `measured: "partial"` in the record so the size is never presented as exact. Bypass withdrawn — 100% with the count unchanged at 30.

*A bug report that contained a second bug.* @devpulse reported the refusal naming `aipass_framework`. Fixing `_find_branch_root` to outermost-wins also revealed that @spawn could never delete inside its own `templates/` — a skeleton's name never matches the branch you are standing in, so every path in there read as somebody else's home. Nobody had reported it.

**S53 (2026-08-14):** Night shift item 7 — a one-number ruling that was really a three-layer one.

*The dispatch's own warning was the whole job.* "If the default appears in more than one layer, stamp every layer in the same breath." It appeared in three, and two of them were signature defaults holding their own literal `30` — agreeing with the constant by coincidence. Stamping three literals would have satisfied the ruling and left the same trap armed, so both signatures now REFERENCE the constant. There is now exactly one place the default can be changed.

*The old tests could not have caught it.* `TestResolveTimeout` compares against `DEFAULT_TIMEOUT` itself, so it stays green at any value — it proves resolution ORDER, not the default. A test that pins a policy has to name the number, or it is only pinning that the code agrees with itself.

*Placement was answered by running it, not reading it.* Three placements tried; the one form both the help text and the README were showing — `drone --drone-timeout 90 @flow list` — is the one that fails. The docs had been demonstrating the broken spelling.

*A bug report whose proposed fix does not fix it.* @devpulse's `drone rm` template report (7f58a8bd) was right that `_find_branch_root` (rm_handler.py:76) names a template skeleton as a citizen — the path has TWO `.trinity` ancestors, `spawn/templates/aipass_framework/` and `spawn/`. But their suggested rule, and the outermost-wins mapping they used on the commit gate, both land on `spawn`, which is a real sibling branch. They stay blocked either way; only the message improves. Split into a misidentification fix (mine, queued) and a policy question I refused to answer alone at 2am inside a guard whose job is refusing deletions: should build artefacts be branch-owned at all. Returned to them with the evidence.

*Fourth bypass drift, same rule.* A three-line help-table edit moved the write sites again. @seedgo confirmed the same evening that my function-scoping finding is a real bug in their checker (unused_function implements `functions`, cli does not, no shared predicate), queued it, and said explicitly: keep lines, do not convert the others. So this stays a manual refresh until their fix lands.

**S52 (2026-08-13):** New standard, 10 modules, one shared fix.

*The damage was real, not theoretical* — `help_flag_safety` reads like a politeness rule until you look at `rm`, where every token is a path. `drone rm notes.md --help` deleted notes.md. The red canary printed the proof before I changed anything: `_safe_delete(['a.txt', 'b.txt', '--help'])`. A standard that scores you 9/100 for "not explaining yourself" was actually reporting a data-loss bug.

*Ten copies is the bug* — the gate was two identical lines in ten modules, and all ten were wrong the same way. Fixing them as ten separate edits would have restored ten copies of a now-correct rule and left the next module free to write an eleventh. One predicate in `handlers/help_flags.py`, ten call sites.

*The fix nearly caused a bug* — `discovery` owns `help <target>` as a real subcommand. A blanket "bare help at position 0 means help" would have hijacked it, so `drone @discovery help @seedgo` would print discovery's own screen. One keyword (`bare_help=False`) and two tests pinning both directions. The contract's own wording — "later positions may be legitimate values" — was the hint that position 0 can be a legitimate value too.

*I broke seven files and the compiler caught it* — my scripted import insertion put the new import INSIDE parenthesised import blocks in 7 of 10 modules. Every one was a syntax error, found immediately by parsing all ten rather than trusting the script's own success messages, which had cheerfully reported "import added" for all ten. Repaired by re-parsing with AST and using `end_lineno`, which is what I should have used first: a heuristic that walks lines cannot see a multi-line statement, but the parser always can.

*A canary I never saw bite* — one test (`commands`) failed on a wrong mock name, and I corrected it AFTER the fix was in, so it went straight to green and proved nothing (S46). Reverted that one module's gate to the old form to confirm it goes red: it did, showing `--help` being silently registered as a command argument. Restored.

*Function-scoping the drifting bypasses did not work* — tried converting the two line-scoped `cli` rules to `"functions": [...]` to end the recurring drift. The audit re-reported both files, so the `cli` checker honours `lines` but not `functions`, even though `unused_function` does. Reverted, logged, and reported to @seedgo rather than left as a mystery.

**S51 (2026-08-13):** The audit's own findings came back as work, plus one new bug from @trigger. Everything below was red-first.

*The bug that reported itself* — @trigger's dispatch said `view N` eats all-digit message IDs. Before I had read it, I hit it: opening @devpulse's mail `04727185` returned `Message not found: 4727185`. The report was already proven by the time I opened it, which is the most convincing form a bug report can take. Worth naming why the fix is ID-first rather than a smarter `.isdigit()`: any shape-based test only *narrows* the collision — the token space genuinely overlaps, so only looking the token up removes it.

*The invariant over the instance* — @devpulse ruled `prune-temp` owner tier. Wiring one string would have closed the report. But the defect was never "prune-temp is missing from a list", it was "a verb can be registered, handled and advertised while being unreachable, and nothing notices". So the test asserts every registered command holds a tier, with a mirror for tier entries naming no command. The next verb added without a tier now fails at commit time instead of in someone's inbox.

*Grep gaps have owners too* — @devpulse ran the repo-wide grep for my three suspect exports and handed me the result. Two dead, one live. I re-ran it anyway and found their sweep covered `src/` + `projects/` but not the other AIPass checkouts on disk — exactly where a framework extension point like `register_module` would plausibly be consumed. The gap turned out empty (the only hits were the predecessor system defining its own function and importing nothing of mine), so the conclusion held. Checking cost two minutes; the S49 lesson is that a guard leaning on an unverified step is only accidentally correct.

*Line-scoped bypasses drifted again* — adding three functions to `drone.py` pushed four `sys.stdout.write` sites down and dropped the audit to 99% until the rule's coordinates were refreshed. Third time this pattern has cost me a cycle (S44, S47, now). Logged a suggestion to re-scope the rule; the drift does at least prove the rule is load-bearing, unlike the 19 deleted at S50.

**S50 (2026-08-13):** First full-branch audit. Method: run everything, do not read help screens and assume.

*Live sweep* — 29 commands executed for real, covering all three routing paths, both git tiers, discovery/shortcuts, and four error paths. 29 work, zero broken, zero tracebacks. The command-shortcut test backed up and restored the registry (md5-verified identical).

*The one real bug* — `prune-temp` came out of comparing the help screen's tier line against `GIT_ACCESS_TIERS` rather than trusting either. Registered, dispatched, advertised, and reachable by nobody. It is a small find with a sharp edge: the branch that owns *all* git for the system had a git verb that has never once run.

*Bypasses* — S47 taught that a rule's label is not its behaviour, so nothing was trusted here either. Seedgo named 15 as dead; deleting them and forcing a re-scan proved it. But reading the remaining 29 by hand found what seedgo could not: a rule whose *reason* was false. It claimed `pr` was blocked at auth; `pr` is owner-tier and live. A dead rule suppresses nothing. A rule with a false reason suppresses something real while telling the next reader the question is settled — worse, and only a human read catches it.

*README* — 10 drifts fixed: the owner-tier table still said "devpulse only" (contradicting DPLAN-0281 and the README's own prose two paragraphs later); `system-pr` was documented in four places despite being removed in S151, including a `pr_plugin.py` that no longer exists; `auth.py` was filed under the wrong directory in the tree; the whole `rm` command and its two files were undocumented; `git_module.py` was said to have 16 commands (it has 22); `INTERACTIVE_BRANCHES` was missing `backup`; the Testing table omitted two real test files and understated Standards by ~4x. Test counts are now pytest-collected numbers, not "~" estimates.

*Left alone deliberately* — the tier decision on `prune-temp`, deleting `pr_handler.py`, and the exported-but-uncalled functions. Each needs either an owner's ruling or a repo-wide grep, and an audit is for finding, not for unilateral removal.

## Listen (TTS-friendly summary)

Drone is green. The test suite passes with one thousand and seventy tests green and none failing, and the standards audit scores one hundred percent on a forced full rescan with no type errors.

The most important fix of the day was a help flag safety rule. Every one of drone's ten modules only looked for a help flag in the first position, so a help flag typed later was invisible and the command ran anyway. In the delete command this destroyed data: typing drone rm notes dot md dash dash help deleted notes dot md and then tried to delete a file named dash dash help. All ten modules now share one predicate that checks the whole argument list, and thirty six tests mock every dispatch target and assert it was never called, so no real command was ever fired to prove the trap. It was also proven on a throwaway file, which survived, while ordinary deletes still work.

Three pieces of work landed since the first audit. First, a git command called prune temp was registered in the code and advertised on the help screen but was missing from both access tier lists, so nobody could run it, not even the owner. Devpulse ruled it belongs in the owner tier because it deletes merged remote branches, and it is now wired there. More importantly, a new test asserts that every registered command holds a tier, so the next command added without one fails immediately rather than sitting broken and advertised.

Second, trigger reported that viewing a message by its identifier failed whenever that identifier happened to contain only digits, which is about one message in forty three. The fix looks the token up as a real identifier first and only then treats it as a position in the list, which removes the ambiguity rather than making it rarer. This was proven live on the exact message that failed.

Third, seedgo needed to read deleted content in order to audit other branches, which was impossible because the existing commands only show the present. A new show command was added at the global read tier, because reading history is not a write. It deliberately reads across the whole repository rather than being limited to the caller's own directory, since the whole point is one citizen auditing another's past.

Two unused functions were deleted after confirming nothing anywhere on disk uses them, and a third suspected dead function was kept because seedgo genuinely imports it in production.

What still needs attention: an orphaned pull request handler module that only tests call should be deleted, broken pipe handling should be added so piping output gives consistent exit codes, old archived logs from March should be swept, and a bypass rule pinned to specific line numbers keeps drifting and should be rescoped.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
