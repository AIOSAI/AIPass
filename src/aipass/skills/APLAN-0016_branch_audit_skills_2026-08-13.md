# APLAN-0016: Branch audit - skills

Tag: audit, branch-audit, skills

> Branch audit @skills -- living document tracking health, issues, improvements

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
| **Open items** | 6 |
| **Tests** | 1351 pass, 0 fail, 1 skipped |
| **Seedgo** | 100% with bypasses / **99% without** (37 standards) |
| **Bypass entries** | 44 (was 45; one measured dead and pruned) |
| **CLI score** | Nav 5/5, Output 5/5 (after this session's two fixes) |

YELLOW, not GREEN: two real defects were shipped and live in the CLI until this
session, one test pinned nothing, and the audit lane's green headline covers 14
files out of 101.

## Current State

### Summary
- 101 Python files / 31k lines: `apps/` 20 files / 2.3k, `lib/` 63 files / 26k, `tests/` 18 files / 2.7k.
- The branch is small; the **telegram skill is 84% of the code** and carries the only live external surface.
- 6 skills discovered: branch_health, drone_commands, github, inbox_check, system_status, telegram.
- Every documented command was run live this session, including error and refusal paths.

### Architecture
Thin-module pattern holds: `apps/modules/` orchestrate, `apps/handlers/` implement.
`apps/skills.py` exposes `handle_command()` for drone routing; drone executes a
branch command as a **subprocess** and propagates its return code — which is why
the swallowed exit code below was a real, scriptable defect and not cosmetic.

### What Works Well
- Discovery/loader/runner/creator/validator: all five verbs work, all refusal paths give clear messages.
- All 3 scaffold tiers produce valid skills; invalid name, duplicate target and unknown template each refuse correctly.
- The telegram handler refuses unknown actions instead of falling through — the safe pattern.
- `/suspend` is grounded and stays grounded: `_suspend_enabled()` (base_bot.py:2473) gates it, and a disabled bot answers with a refusal instead of suspending the machine. Verified present this session. **Never live-test `/suspend` without Patrick** — the config flag is the brake, not a convention.
- Suite is large and fast (1351 tests, ~2m40s) and has caught real regressions three sessions running.

## Issues Found

### Open

- [ ] **Audit lane covers 14 of 101 files** — `files_checked: 14`, all in `apps/`. `lib/` (26k lines, 84% of the branch) is not walked by the audit headline. Worse, checkers disagree: `unused_function` *does* report on `lib/telegram/*` while the headline count stays 14. So "100%" is a green number over a slice. Walk scope is seedgo's, not mine.
- [ ] **38 of 44 bypass rules are unmeasurable in either lane** — their standards (architecture, encapsulation, documentation, trigger, handlers, meta, unused_function) are not evaluated by the checklist lane at all, and the audit lane never reaches the `lib/`/`tests/` files they point at. Cannot prove live or dead. Left in place.
- [ ] **The advisory dead-list is wrong here** — seedgo reports "27 bypass rules now suppress nothing". Of the 7 rules I could actually measure, **6 are LIVE**. Do not act on that advisory for this branch without measuring.
- [ ] **`tests/` findings are invisible to the audit headline** — e.g. `test_mirror_session.py` has 5 unguarded POSIX patterns (L92 hardcoded `/tmp`). Real checklist findings, zero effect on the score.
- [ ] **README is 4 months stale** (Last Updated 2026-04-07). Every command it documents does run — no lies — but it predates the telegram skill's growth and documents no exit-code contract.
- [ ] **Bare `drone @skills` prints help, not the introspection self-map** the kernel describes. `print_introspection()` is only reachable via `handle_command(None)`, which the CLI never passes. Not changed unilaterally: it is a user-facing convention call.

- [ ] **`user_message_relay` blocks the prompt path for nothing** (raised by @hooks 2026-08-14, measured: 0 stdout on 18/18 runs). Verified independently in my own file: no `print(`/`sys.stdout` anywhere, so it cannot inject — yet it is registered as a UserPromptSubmit *injector* and does `urlopen(..., timeout=10)` at line 119. If Telegram is slow, every prompt in a TG branch waits before the model sees anything, and a hook that dies just injects nothing, so nobody would notice. Fix shape agreed: keep the dedupe decision in the parent, move the send to a detached child (@memory's `auto_process.py:140` is the reference; no lock needed since the parent decides before sending). **Mapped in full at S103 as DPLAN-0299** (dispatch 74a136dd, MAP ONLY — no code touched). That map adds two things the brief lacked: line 209 returns `"sound": "user message relay"`, a real foreground contribution that is success-gated, and the dedupe hash is success-gated too — so a detached child converts both semantics. Build blocked on Patrick's ruling on the sound. Not built yet — needs its own FPLAN.

### Resolved

- [x] **Bare `/start` spawned an interactive ghost in @aipass's home** (S103 — root-caused by @aipass's APLAN-0018, fixed here). `branch_arg or "aipass"` meant the `/start` every Telegram client sends on opening a chat defaulted to @aipass, then spawned `claude -c || claude` detached and interactive in that branch's directory. The ghost tripped wake.py's occupancy gate, so @aipass's real headless wake was REFUSED — 6 measured occurrences 07-29 to 08-11, which Patrick had been killing by hand. Bare `/start` now spawns nothing and answers with usage; `/start <branch>` unchanged.
- [x] **Bare `/kill` would have killed @aipass's session** (S103) — same `or "aipass"` default one line below, not in the brief. A destructive verb must never pick its own target. Bare `/kill` now refuses. Found by reading the neighbouring line, confirmed by a test whose captured log showed a real `kill-session -t aipass-aipass`.
- [x] **Three more tests pinning broken behaviour** (S103, rule D — brings this branch's tally to 4). `test_start_default_branch_is_aipass` and `test_kill_default_branch_is_aipass` asserted the bug as the contract. `test_start_wakes_on_aipass_branch_name` was about *routing* but asserted it on a bare `("start", "")`, so it only passed because of the default — renamed intent preserved, explicit branch supplied, plus a new test that bare /start still routes but spawns nothing.

- [x] **Every failure exited 0** (S102 — `main()` discarded `handle_command()`'s bool; now `sys.exit(0 if ok else 1)`). Verified live through drone: `info nosuchskill`/`validate nosuchskill`/`bogusverb` → 1, `list` → 0. 6 subprocess tests pin it. Attribution checked first: drone's `executor.py` propagates `returncode`, so the swallowed code was mine, not the router's.
- [x] **Rule E: `run <skill> --help` dispatched `--help` as an ACTION** (S102). `branch_health`/`inbox_check` treat an unknown action as a *branch name*, so it answered "Branch '--help' not found". Read-only, no external effect. Now routes to skill info; 3 tests, one asserting real actions still dispatch.
- [x] **Rule D: a test that could not fail** (S102) — `test_output_capture_unknown_command` ended in `or len(captured.out) > 0`. Now pins the real contract.
- [x] **A flaky test I wrote in S101, fixed properly this session** (S102) — `test_retry_count_is_unchanged` asserted on a module-level `time.sleep` that live bot threads elsewhere in the suite also call. My first attempt (assert a consecutive `[1.0, 2.0]` pair) still failed on the next full run, because another thread can interleave *between* the pair. Now records only calls made on the test's own thread. Confirmed by two consecutive full telegram runs, 1090 passed each.
- [x] **One measured-dead bypass pruned** (S102) — `permission_flags` on `lib/telegram/tests/test_mirror_session.py`. Control-first method: pulled a rule known to be live, confirmed the lane reacted, then measured. Audit re-run 100% after the prune.

## What Needs Doing

### @skills to handle (dispatch)
- [ ] README truth-and-freshness pass: document the exit-code contract, refresh the telegram section.
- [ ] Decide bare-invocation behaviour once Patrick/devpulse rule on help-vs-introspection.
- [ ] Guard the `/tmp` paths in `test_mirror_session.py` for Windows.

### devpulse to handle
- [ ] Rule the bare `drone @skills` convention: help (today) or introspection self-map (kernel).
- [ ] Carry to @seedgo: audit walk scope (`files_checked: 14` vs 101), the checker-scope disagreement, and that the "suppresses nothing" advisory misreports 6 of 7 measurable rules here.
- [ ] Commit the tree — as of S103 wrap the skills scope shows 3 modified: `APLAN-0016` (this doc), `lib/telegram/apps/handlers/base_bot.py` (v1.6.1 — S101 backoff classification + S103 `/start`+`/kill` default removal) and `lib/telegram/tests/test_control_verbs.py` (S103), plus one untracked new file, `DPLAN-0299_*.md`. S102's `apps/skills.py` / `test_cli_routing.py` / `.seedgo/bypass.json` and S100's `log_streamer.py` / `test_log_streamer.py` / `test_network_backoff.py` are already committed — verified, no longer pending.

### Tracked elsewhere
- [x] Prior-session WIP reconciled at S103 wrap: everything from S100/S102 is committed. Only base_bot.py + test_control_verbs.py remain uncommitted, both from S103. Nothing unexplained in the tree.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fleet audit round (DPLAN-0291), dispatch 74dd63d7 | YELLOW — 2 defects found and fixed, 4 open items raised |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round)
- **Related FPLANs:** FPLAN-0395 (streamer 400s), FPLAN-0402 (send-path classification)
- **Owner branch:** @skills
- **Seedgo:** `drone @seedgo audit aipass @skills`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S102 (2026-08-13):** Full self-audit. The two defects fixed here were both
*shipped* behaviour, not theory: the exit code made `drone @skills validate x &&
next` run `next` on failure, and `run <skill> --help` was answered with "Branch
'--help' not found". Both were invisible to a green suite, which is the honest
lesson — 1342 tests passed while both defects were live.

Bypass work followed rule C exactly and it mattered: my first control FAILED. I
had patched `load_bypass_rules`, but `run_checklist` calls a private
`_load_bypass_for_file`, so pulling a rule changed nothing and every rule would
have looked dead. Re-ran the control against the right symbol on a rule whose
standard the lane actually evaluates — it passed, and 6 of 7 measurable rules
turned out LIVE. Had I trusted the first run, or the advisory, I would have
deleted live suppressions.

No outbound telegram probes. External surface verified by code path and mocked
transport only; `create` exercised through the module API with an explicit /tmp
target so no scaffold residue landed in the repo.

## Listen (TTS-friendly summary)

The skills branch is healthy but signed yellow, not green. All thirteen hundred
and fifty one tests pass, and the standards audit scores one hundred percent with
bypasses and ninety nine percent without, so the bypasses are hiding almost
nothing. The yellow comes from two real defects that were live in shipped code
until today. The first is that every failure exited with a success code, which
means a caller chaining commands together would carry on after a failure. That is
fixed and verified through drone. The second is that asking for help on a skill
was treated as a command to run, so one skill replied that it could not find a
branch called dash dash help. That is also fixed. A third problem was a test that
could never fail, which has been tightened.

The main open concern is coverage. The audit only walks fourteen files out of a
hundred and one, and the telegram skill, which is most of the code and the only
part with a live external surface, sits outside that count. So the green headline
describes a slice, not the branch. Related to that, thirty eight of the forty
four bypass rules cannot be measured in either lane, so they were left alone
rather than guessed at. One rule was measured as dead and removed. Notably, the
tooling advisory claiming twenty seven rules suppress nothing is wrong here: of
the seven I could measure, six are live.

What needs attention next is a readme refresh, a ruling on whether a bare skills
command should print help or an introspection map, and a conversation with seedgo
about how much of a branch its audit actually walks.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
