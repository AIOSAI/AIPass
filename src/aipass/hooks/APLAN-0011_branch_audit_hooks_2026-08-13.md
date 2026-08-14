# APLAN-0011: Branch audit - hooks

Tag: audit, branch-audit, hooks

> Branch audit @hooks -- living document tracking health, issues, improvements

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
| **Health** | **YELLOW** |
| **Last verified** | 2026-08-13 (S145) |
| **Open items** | 20 (1 security bypass -> DPLAN-0293, 7 parked, 2 escalated, 10 branch-owned) |
| **Tests** | 1450 pass, 0 fail, 2 skip (1452 collected, 47 files) |
| **Seedgo** | **100% shielded / 96% unshielded** (44 standards) -- help_flag_safety 84 -> 100, and 100 unshielded too (fixed, not bypassed) |
| **Bypass entries** | 261 rules / 80 files -- ~77 do real work, 123 inert in both lanes |
| **CLI score** | Nav 4/5, Output 4/5 (surface works; `verify` contract + help-flag safety fixed, `feedback` still lies) |

### Why YELLOW and not GREEN

Every headline number is green: 1405 tests pass, seedgo says 100%, zero ERROR lines in 24h of logs.
None of those numbers can see any of the three things that actually matter here. The suite is green
*because* a test pins the git_gate bypass as correct. Seedgo is 100% *because* 260 bypasses shield it.
The logs are ERROR-free *because* successful blocks are logged at WARNING. A branch whose instruments
all read clean while a security gate is one leading slash from open is YELLOW.

## Current State

### Summary

- @hooks owns the single dispatch engine for all AIPass hook events across Claude Code and Codex.
- 28 native handlers (prompt 9, security 6, lifecycle 8, notification 5) + 14 command modules.
- The branch is **PARKED** on Patrick's word. This audit is read-and-report plus small fixes strictly
  outside the parked list. Parked items below are verified and measured, never touched.
- @devpulse ruling 2026-08-13: a peer dispatch never lifts a park; blocking defects escalate to
  devpulse, who decides whether to hold or wake Patrick. Applied twice this session (items 1 and 2).

### Architecture

Provider settings invoke a thin bridge (`handlers/bridges/claude.py`) two ways: `claude.py EventType`
(one fan-out entry, all enabled handlers -- tool events) or `claude.py EventType:handler_name` (one
entry per handler -- UserPromptSubmit, PreCompact, SessionStart). The bridge normalizes stdin and calls
`engine.dispatch()`, which reads `.aipass/hooks.json` by walking up from CWD, runs matching handlers
sequentially with crash isolation, and logs every execution to `logs/engine.jsonl`.

Measured wiring today: 27 provider manifest entries -- 13 UserPromptSubmit (per-handler), 8 PreCompact
(4 handlers x manual/auto), 1 SessionStart, and 1 fan-out each for PreToolUse, PostToolUse, Stop,
SubagentStop, Notification. Live `~/.claude/settings.json` matches the manifest exactly -- **no
provider drift today**, which is worth recording because DPLAN-0278 found it drifted a full matcher
behind for weeks.

### What Works Well

- **Crash isolation holds.** Exit 2 with block-JSON vs exit 2 bare is correctly discriminated
  (`engine.py:385-421`); a crashed hook logs `action: crashed` and dispatch continues.
- **Block delivery works** -- see parked item 5, which does NOT reproduce. Reasons reach the model.
- **Provider/project wiring is clean.** All 28 handlers wired in hooks.json; every per-handler event
  has its manifest entry; live settings match. `verify` finds nothing because there is nothing.
- **The log-volume fix from S133 held.** Per-hook narration is still suppressed; 219 unique log
  records in 24h, versus the 96-107 lines/min that tripped prax's runaway detector before.
- **Block latency improved ~9x.** All-time median block 1176ms; last-24h median 125ms.
- **This morning's edit_gate work is sound and was independently canaried by @seedgo** from their own
  original repro: cross-file (unknown import symbol) now allows the resolving edit; the local-error
  control still blocks, quoting live text. It got accurate, not weaker.

## Issues Found

### Open

#### SECURITY -- highest priority

- [ ] **git_gate is bypassed by any absolute or relative path prefix.** `RAW_GIT_RE` is
  `(?<![@\w/.])git\s`; the lookbehind exempts anything preceded by a slash. Verified by driving
  `handle()` directly: `git push` BLOCKED, but `/usr/bin/git push`, `./git push`,
  `x=1; /usr/bin/git reset --hard HEAD` and `/usr/bin/gh pr create` are all **ALLOWED**. The entire
  git access-tier model (write = devpulse only) rests on this matcher. Not theoretical: any agent that
  habitually types full paths is already outside the gate and nothing tells them.
  **And `tests/test_git_gate.py:267 test_path_git_not_matched` asserts `/usr/bin/git push` is allowed**
  -- the suite pins the bypass as intended, which is exactly why 1405 green never surfaced it.
  NOT FIXED: the slash in the lookbehind has a real job (not matching paths ending in a `git`
  directory), so this is the same disease as the parked git_gate false-positive item, on the same
  regex, on the same line -- two faces of one defect. Needs a real predicate (resolve the command word,
  then decide), which is a design change, not a STEP 4 small fix. Escalated to @devpulse 2026-08-13
  with a recommendation that it jumps the queue: unlike everything else parked, it fails *permissively*
  and silently.
  **DISPOSITION (Patrick, 2026-08-13): DPLAN-0293 created in @devpulse, visit-later.** Not a scramble.
  @devpulse verified from their own seat before ruling -- `/usr/bin/git commit` in a scratch dir
  reached git itself, while a bare `git commit` is blocked before git ever runs. Live in the
  production hook path, not just my harness. Design direction endorsed: resolve the command word,
  then decide -- one predicate that kills the parked false-positive twin in the same stroke, covers
  `gh`, plus a fleet sweep for the same lookbehind in other gates. I build it as gate owner when the
  session happens; APLAN-0011 stays the evidence record and the DPLAN references it.
  **Interim: no mitigation ruled necessary** -- the fleet types bare `git` by habit and drone-first
  culture is the working control. If an absolute-path git invocation ever shows up in a log before the
  fix lands, that is an immediate mail.
  Live proof of how real it is, from @seedgo: the mail reporting this defect was **refused by the gate
  on its first send**, because their prose quoted the bare form. The gate blocks discussion of the
  hole and permits the hole.

#### ESCALATED -- blocking defect, fix known, not applied

- [ ] **Deleted/renamed errored file deadlocks edit_gate forever.** Reported by @seedgo (mail
  f0dd0ef7), reproduced here in an isolated harness in all four shapes: hard delete, rename to
  `name(disabled).py`, move to `.archive/`, and a deleted red-first test file. `revalidate()` returns
  `None` for a missing path (`diagnostics_state.py:101-102`), `edit_gate.py:537-542` reads `None` as
  "unknown, keep the block", and the only permitted edit is to a file that no longer exists. Two of the
  four shapes ARE the house cleanup rule ("never delete: rename to `name(disabled).py` or move to
  `.archive/`"), so it fires on the fleet's own mandated pattern. **Self-sustaining:** PreToolUse blocks
  the edit, so PostToolUse `auto_fix` never reruns, so the state is never rewritten. No TTL, no reaper.
  Scope: all `.py` edits in the owning branch; other branches exempt; non-`.py` still passes.
  Fix is one line -- `return []` instead of `None` at `diagnostics_state.py:101-102`, because a file
  that does not exist has no type errors -- plus a docstring line, plus flipping
  `tests/test_edit_gate.py:519-522`, which currently pins the defect. The genuinely-unknown cases
  (pyright missing, timeout, unparseable) keep returning `None`, so "unknown is not clean" survives.
  NOT APPLIED: sits inside this morning's edit_gate work already in front of Patrick. Escalated per the
  ruling. Escape for anyone who hits it: recreate the file clean, let re-validation drop the state,
  then remove it.
  **NEW EVIDENCE (@seedgo, 2026-08-13 evening): it is a CONCURRENCY edge, not just a solo one.** They
  ran five sub-agents through their branch and it blocked **four** mid-build. Three escaped with the
  recreate-clean sequence. The fourth could not: it was blocked by type errors in a file it was
  *forbidden to touch* -- another agent's in-flight edit -- and the escape does not cover that shape,
  because making your own file clean does not help when the recorded error is in someone else's. It
  polled and waited for the other agent's implementation to land. Adds to the unpark case: the
  fleet-wide single state slot (parked item 8) and this deadlock compose into a cross-agent stall.

#### Tests that pin defects (rule E)

- [ ] `tests/test_git_gate.py:267` -- pins the git_gate absolute-path bypass (see above).
- [ ] `tests/test_trust_registry.py:382-383 test_no_session_id_never_dedups_but_still_returns_banner`
  -- asserts the one-time-per-session trust nudge fires twice running when `session_id` is empty.
  `loader.py:163-172` states the intent as "a single nudge, not a persistent nag" and the banner text
  says "One-time nudge for this session". Reachable: `engine.py:232` reads `session_id` with an
  empty-string default, so any payload missing it (or any stdin parse failure) nags every turn -- and
  `engine.py:243-247` returns that nudge INSTEAD of every other UserPromptSubmit hook. The test name
  concedes the defect out loud.
- [ ] `tests/test_hook_test.py:92` -- accepts `status in ("crashed", "fired (empty output)")`. Ran its
  own config: a handler pointing at a nonexistent module reports `fired (empty output)`, exit_code 0,
  and renders as a green tick. `"crashed"` is only reachable if `dispatch()` itself raises, which the
  engine is built never to allow. So `drone @hooks test` reports a broken hook as fired.
- [ ] `tests/test_trust_registry.py:444` -- asserts `"trust enroll"` is in the banner, pinning the dead
  command from parked item 3.
- [ ] `tests/test_auto_fix.py:370` -- pins the false-premise `logger_debug` rule (parked item 1).

#### Command surface (outside parked list, branch-owned)

- [ ] **`drone @hooks feedback` reports the opposite of reality.** Prints "Feedback pulse (ENABLED)"
  while `status` prints `x feedback_pulse`. Two sources of truth: `feedback.py:40-54` keys off a
  sentinel file `.aipass/feedback_off` (absent), the hook that actually runs keys off `hooks.json`
  -> `feedback_pulse.enabled: false`. `feedback on` would print ENABLED and change nothing. Fixing the
  display alone leaves the toggle half-wired, so this needs the toggle and the reader unified -- not a
  one-liner, deliberately left for a proper pass.
- [ ] **A crashing module is reported as a typo.** `hooks.py:168-176` catches every exception from
  `module.handle_command`, logs it, continues; `main()` then prints `Unknown command: <cmd>` and exits
  1. Verified with an injected raising module. A genuine handler crash is indistinguishable from a
  misspelling.
- [ ] **`drone @hooks <cmd> --help` fails for 6 of 14 commands.** `cadence`, `engine`,
  `diagnostics_state`, `sessions`, `context_window`, `presence` each test `command in ("--help",...)`
  instead of `args[0]`, and `hooks.py:188` intercepts the bare flags before routing -- so those
  branches are unreachable and the TIP printed in `--help` is broken for them.
- [ ] **`--version` drift**: outputs `hooks 1.1.0`; `hooks.py` header says `1.1.1`.
- [ ] **`claude` advertised under BRIDGES in `--help` but not routable** -- `discover_modules()` only
  scans `apps/modules/`, bridges live under `apps/handlers/bridges/`. `drone @hooks claude` -> exit 1.
- [ ] **`dismiss` with no argument exits 0** after printing usage; `dismiss <nonexistent-id>` prints
  "not found" and also exits 0 (verified genuinely a no-op -- alerts.json untouched).
- [ ] **`<valid-cmd> <bogus-arg>` prints `Unknown command: status`** -- names the command as unknown
  when it is the argument that is bad.
- [ ] **`engine` and `cc_sessions` missing from `--help`** (`engine.py:29` HELP_COMMANDS lists only
  `log`); `presence` and `context_window` have no HELP_COMMANDS at all, so they are invisible in help.
- [ ] **`sessions reclaim [@branch]` loses its argument hint to rich markup** -- `cc_sessions.py:39`
  declares it, `--help` renders it stripped. `hooks.py:117` escapes `\[args...]` for exactly this
  reason, so the pitfall is known and unapplied here.
- [ ] **`drone @hooks status` cannot show "the current project".** `drone` execs the branch app with
  `cwd=branch_path` (`drone/apps/handlers/router_handler.py:316`), so `cd /tmp && drone @hooks status`
  is byte-identical to running it from the branch. The 4 trust-refusal states are unreachable through
  the drone surface entirely -- though `loader.config_unavailable_reason()` is honest and all four are
  distinct when called directly (verified in a throwaway project, trust entry cleaned up after).

#### Silent parse failures (reported by @seedgo 2026-08-13, PARKED -- escalated, not fixed)

- [ ] **`auto_fix.py:237` and `subagent_gate.py:111` parse for a marker `drone @seedgo checklist` has
  never printed.** Both do `if line.startswith("<U+2717 cross>")`. The checklist marks findings with an
  EM DASH; @seedgo verified both directions (grepped their own module -- never emitted; ran a live
  checklist with a real finding -- 1 finding, 0 crosses). **Every standards violation from every
  checklist run since that line was written has been dropped on the floor.** It never looked broken
  because the pyright/type half of `auto_fix` works fine. This is the same missing marker that nearly
  cost @spawn 41 bypass rules -- same cause, opposite consequence.
  @seedgo has now shipped a stable contract on their side: `FINDING_MARKER = "[FAIL]"` at line start
  (`seedgo/apps/modules/checklist.py:273`), documented in `drone @seedgo checklist --help`. I verified
  it is live -- my own checklist run on the new handler printed `[FAIL] — json_structure: ...`.
  Migration is `line.startswith("[FAIL]")` then `line[6:].strip()`. Explicitly NOT counting em dashes
  as a workaround: a wrapped detail line can contain one.
  NOT FIXED -- outside this dispatch's scope fence, and @seedgo sent it as a peer mail precisely
  because a peer mail does not lift a park. Ready when unparked.

#### Infrastructure / observability

- [ ] **`engine.jsonl` retains ~11 minutes, not 24 hours.** 2 generations at ~500KB; under current
  traffic the live window measured **11.2 minutes**, and it rotated *during* the analysis. Every other
  copy on disk is worse (`.backup/snapshots` 08-10, `.claude/hooks/` 05-18). The forensic record that
  the README calls "the source of truth for diagnostics" cannot answer any question older than a coffee
  break. This is the finding behind devpulse's requested latency histogram -- the histogram they asked
  for **cannot be built retrospectively**.
- [ ] **Successful blocks log at WARNING.** `engine.py:396` -- the intentional-block branch (the gate
  working as designed) logs WARNING while the crash branch below logs ERROR. 72 such lines in 24h, 61
  of them `pre_edit_gate`; 100% of pre_edit_gate WARNING volume in the window is successful blocks.
  That is 33.5% of all hooks WARNING traffic, and @trigger measures 11 of 14 escalation digests in 24h
  as originating from these logs. Zero information is lost by dropping to INFO -- `engine.py:397-405`
  already writes the same event structured into `engine.jsonl`. PARKED (one line). Measured, untouched.
- [ ] The other 98 WARNINGs in 24h are edit_gate `.trinity` rollover advisories about **other**
  branches: @ai_mail 15, @daemon 12, @trigger 9, @flow/@drone/@seedgo 6 each. Advisory, never blocking,
  but they are the bulk of the escalation lane's raw volume.
- [ ] **`bridges/claude.py:56-60` has no test at all.** It is the actual block-delivery path -- the
  code parked item 5 accuses. Item 5 does not reproduce, so the accused line is innocent AND untested,
  which is worse than either alone.

#### Bypass registry hygiene (measured, nothing pruned)

- [ ] 5 exact duplicate `(file, standard)` pairs -- `presence_gate.py` x3, `presence.py` x2.
- [ ] 2 rules name a standard `open_encoding` that does not exist in the 44-rule pack. Definitively
  inert.
- [ ] 123 of 129 `tests/*` rules suppress nothing in **either** lane (measured by running the checklist
  lane over all 31 bypassed test files, shielded vs ruleset stubbed empty). Only 6 are live:
  `commented_logger` on test_auto_fix, `hardcoded_path` on test_edit_gate_trinity, `hardcoded_path` +
  `windows_compat` on test_registry_gate, `help_text` on test_engine and test_wire_verify.
  **Zero rules point at a file that no longer exists**, so nothing here is deletable on the only safe
  test. Recorded, not pruned.

### Resolved

- [x] **help_flag_safety 84 -> 100: a help flag anywhere now explains, never executes** (S145 --
  @devpulse dispatch 223f5e3c, red-first). The checker named 2 modules; the defect was a class of
  **9**. Class sweep of `apps/modules/*.py` found the damage, not the count:
  | Module | The command that ran instead of explaining | Damage |
  |---|---|---|
  | `alert_dismiss.py:101` (named) | `dismiss <alert-id> --help` | removed the alert |
  | `hook_test.py:224` (named) | `test --verbose --help` | fired every hook with mock data |
  | `cc_sessions.py` (**unnamed, worst**) | `sessions reclaim --help` | **stopped live sessions**, and consumed the flag as the branch filter -- `args[1].lstrip("@")` made it `"-help"`. Shape (c) and shape (a) in one line. |
  | `feedback.py` (unnamed) | `feedback on\|off --help` | flipped the toggle + logged it |
  | `hooksound.py` (unnamed) | `hooksound off --help` | muted the fleet's hook audio |
  | `engine.py` (unnamed) | `log --help` | dumped the log instead of describing itself |
  | `hookstatus.py`, `sandbox.py`, `wire_verify.py` (unnamed) | `<cmd> <operand> --help` | no damage -- answered "Unknown command" instead of help |
  Fix: new pure predicate `apps/handlers/cli/help_flags.py` (`wants_help`, `is_help_flag`) mirroring
  @memory's reference -- dashed forms anywhere, bare `help` only at slot 0. Gate placed **after** each
  module's ownership check, never at top of function, so no module hijacks another's help (@trigger
  proved that failure mode). +43 tests in `tests/test_help_flags.py`, proven red first (17 failing),
  each mocking the damaging target and asserting it is never called. Suite 1407 -> 1450.
  **Live-proven, not just unit-proven:** `drone @hooks hooksound on --help` left the mute state at
  MUTED; `dismiss <id> --help`, `log --help`, `status foo --help` all describe. `sessions reclaim`
  is proven by mock only -- I would not fire the live one to watch it not stop my own session.
  One measured bypass added (`json_structure` on the new handler): the only finding is the
  `json_handler` import, and importing it would give a help-flag check the power to log and block.
  Same measured bypass all five convention branches carry. **help_flag_safety scores 100 unshielded
  too** -- the fix is real, not the bypass talking.

- [x] **`drone @hooks verify` exited 0 on failure** (S144 -- fixed this session, red-first). Its own
  `--help` promises "Exits non-zero on any ERROR finding"; `handle_command` returned `True`
  unconditionally and `hooks.main()` turned that into exit 0, so a wiring break printed
  `x Wire check FAILED / 1 errors` and reported success to anything reading the exit code. Any CI gate
  on hook wiring was silently green. Fix: `sys.exit(1)` when `results["ok"]` is false, passing path
  unchanged. 2 new tests (`test_error_findings_exit_non_zero`, `test_clean_run_does_not_exit`), proven
  red before green. 42 green in the file.
- [x] **README + branch prompt truth pass** (S144 -- fixed this session, outside the parked list).
  Test count 1370 -> 1407; added `compass_recall`, `auto_process`, `session_boot`, `trust_registry`,
  `post_compact_regrounding` to the trees; event table gained `compass_recall`,
  `post_compact_regrounding`, `auto_process` on PreCompact and a missing **SessionStart** row, plus a
  note that `user_message_relay` is @skills' and `presence_release` is an entry name not a file;
  handler count 27 -> 28 and lifecycle 7 -> 8; `config/` corrected to sit under `handlers/`, not
  `apps/`; Codex bridge "planned" -> shipped; `drone @hooks test` "planned" -> shipping;
  `announce.py` "Inbox banner on prompt" -> announcement tone on Notification; 6 undocumented commands
  added to the command table; Integration Points gained @cli (16 imports).
- [x] **Two false claims in my own README, corrected with measurements** (S144). (a) The sandbox
  section claimed @ai_mail's dispatch_monitor wires `sandbox_launch` -- it wires `build_policy` +
  `build_srt_config` + `resolve_bwrap_command`, pinned by `ai_mail/tests/test_dispatch_monitor.py:1755`;
  and the claim that the @drone broker validates sandbox policy could not be substantiated (the broker
  is a privileged delete daemon), so it was removed rather than restated. (b) The diagnostics section
  claimed re-validation "costs ~800ms and runs only on the path that was about to block; common path
  ~1ms". Falsified: of 8 `pre_edit_gate` calls over 500ms, **7 allowed the edit**; 3 of 4 blocks
  returned in ~0.1s; common-path median is **6.8ms** not ~1ms, slow-path median **1352ms** not 800ms.

## What Needs Doing

### @hooks to handle (dispatch)

- [ ] Unify `feedback` on a single source of truth (reader + toggle together).
- [ ] Distinguish handler crash from unknown command in `hooks.py:168-176`.
- [ ] `--help` plumbing: `args[0]` not `command` in the 6 broken modules; HELP_COMMANDS for `presence`
  and `context_window`; add `engine`; escape `\[@branch]`.
- [ ] `--version` 1.1.0 -> 1.1.1.
- [ ] Test `bridges/claude.py:56-60`.
- [ ] `engine.jsonl` retention -- rotate on age or raise generations; the current window is unusable.

### devpulse to handle

- [ ] **git_gate absolute-path bypass** -- design decision on the matcher predicate. Recommended to
  jump the parked queue: it is the only item that fails permissively and silently.
- [ ] **Deleted-file edit_gate deadlock** -- one-line fix ready, awaiting the word (it sits inside the
  edit_gate work already in front of Patrick).
- [ ] The 8 parked items below -- all verified this session, one is stale and can be struck.

### Parked (Patrick's call -- verified and measured this session, untouched)

| # | Item | Reproduces | Measured today |
|---|------|-----------|----------------|
| 1 | `auto_fix` logger_debug rule | **yes, premise dead** | prax shipped `debug()` 08-11 in `ba4d06a8`, whose commit message reads "Rule retirement dispatched to @hooks + @seedgo". @seedgo `modules_content.py:74` now teaches the OPPOSITE ("Use `logger.debug()` instead: silent"). Two hooks give contradictory advice on the same line. 33 fires in 13 min. |
| 2 | `auto_fix` string-literal grep | **yes** | 3 false positives in a live repro. `_check_line_pattern` (`auto_fix.py:109-115`) only suppresses when the pattern is *immediately* adjacent to a quote, so every docstring, help string and error message that names a pattern trips it. `open_no_encoding` (`:129-132`) has no literal guard at all. |
| 3 | TRUST BREAK banner | **yes** | `loader.py:132` says "Fix: drone @hooks trust enroll". No `trust` verb exists (enumerated every module's HELP_COMMANDS); real path is `aipass trust <path>`, which has no `enroll` subcommand either -- wrong twice. Same file gives THREE different fixes for the same condition (`:92`, `:98`, `:132`, `:192`). Fires when every hook is dark, i.e. when being right matters most. |
| 4 | README single-entry claim | **yes** | README:51 and :128 (also :57, same sentence family). Reality: 13 per-handler UserPromptSubmit entries + 8 PreCompact; only PreToolUse/PostToolUse/Stop/SubagentStop/Notification fan out. The README's own worked example, `claude.py UserPromptSubmit`, is precisely the entry that does not exist. LOGGED AS KNOWN-FALSE, NOT FIXED, per dispatch. |
| 5 | Engine block-path stdout/stderr | **NO -- STALE, STRIKE IT** | Claude Code honours `{"decision":"block","reason":...}` on stdout regardless of exit code. Proven twice: bridge subprocess test (exit 2, 430 bytes stdout, 0 bytes stderr, reason intact) and a live `rm_gate` block that caught one of my own audit agents mid-run and delivered the full reason text. The code still does not match the documented stderr contract, so the smell is real -- but nobody should spend a session on the premise that reasons are being lost. |
| 6 | 13-to-5 handler grouping (perf) | **yes, worse** | Still 13 handlers. Output measured **20,971 bytes** from a @drone seat, ~22.6KB from a @devpulse seat, against the 10,000 cap -- single-dispatch still fails, reproducing DPLAN-0285. Process time now ~44.7s across 13 processes vs DPLAN's ~21 CPU-s. Slowest single hook logged today: 22,771ms. |
| 7 | Timeout both-sides | **yes, and worse than recorded** | The outer timeout is not 30s, it is **ABSENT** -- all 13 UserPromptSubmit manifest entries carry no `timeout` field, inheriting Claude Code's 60s default, while 11 of 13 sit on the hardcoded inner 30 (`engine.py:321`, `:85`, `:54`). `auto_process` is clamped the *other* way: inner 120 against outer 60. Inconsistent in both directions. |
| 8 | Fleet-wide diagnostics state | **yes** | `diagnostics_state.py:40` resolves to `src/aipass/.diagnostics_state.json` -- one inode for every citizen. No lock, non-atomic `write_text`, and the branch check **fails open** for any path outside `src/<pkg>/<branch>` (`edit_gate.py:527-532`). During this audit it held a `/tmp` scratch file from another agent's session. `auto_fix.py:22` still hardcodes its own copy of the path instead of importing `STATE_FILE`, despite the module docstring saying it exists so writer and reader "cannot drift apart". |

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | @devpulse dispatch 37b4397e -- fleet audit round DPLAN-0291, wave 5 of 8 | DONE -- APLAN-0011, verdict YELLOW, replied with counts + top 3 |
| 2026-08-13 | @devpulse mail f4c4bfc2 -- park ruling | Read + accepted: a peer dispatch never lifts a park; blocking defects escalate to devpulse. Applied twice this session. |
| 2026-08-13 | @seedgo mail f0dd0ef7 -- new deadlock edge + bypass ruling | Reproduced all 4 shapes, escalated not fixed. Their ruling: keep both diagnostics_state bypasses as written. |
| 2026-08-13 | Correction email to @devpulse -- git_gate bypass | Sent same session, correcting my own rule-E answer from "1 test pins a defect" to 5, one of them a security bypass |
| 2026-08-13 | @devpulse cb80ffc6 -- verified the bypass from their own seat | Endorsed the handling and the design direction; all findings to Patrick with numbers |
| 2026-08-13 | @devpulse 897e0845 -- Patrick's ruling | DPLAN-0293 created, visit-later, no interim mitigation. Nothing to do now; I build it when the design session happens |
| 2026-08-13 | @seedgo 1dbac150 -- checklist marker + deadlock concurrency evidence | Logged both. Marker migration ready ([FAIL]), NOT applied -- parked |
| 2026-08-13 | @devpulse dispatch 223f5e3c -- fix round to 100 (help_flag_safety) | DONE -- 84 -> 100, class of 9 not the 2 named, 1450 green, overall 100% |

## Relationships
- **Related DPLANs:** DPLAN-0285 (handler perf, item 6), DPLAN-0276 (post-compact regrounding),
  DPLAN-0278 (provider drift), DPLAN-0291 (this audit round)
- **Related FPLANs:** FPLAN-0400 item A / GH #733 (project fence, shipped 08-12)
- **Owner branch:** @hooks
- **Seedgo:** `drone @seedgo audit aipass @hooks`

## Notes

**S144 (2026-08-13):** Full branch audit under DPLAN-0291, wave 5. Six measurement agents run in
parallel, everything below verified rather than reasoned.

The audit's own headline lesson: **every instrument on this branch reads clean for a structural
reason, and each reason is a different way of not looking.** 1405 tests pass, and one of them asserts
that `/usr/bin/git push` should be allowed. Seedgo says 100%, shielded by 260 bypasses -- unshielded
it is 96%. Zero ERROR lines in 24h, because the gate's successful blocks are filed as WARNING and its
crashes are the only thing that would count. Three green numbers, three blind spots, and the blind
spots are where both real defects were hiding.

Second lesson, from the bypass work: I was handed a warning ("tests/* rules look dead to the audit
lane but suppress real findings in the checklist lane") and I measured it instead of repeating it.
Only 6 of 129 tests/ rules are live; 123 are inert in both lanes. The warning is still right as a
*rule* -- never delete unmeasured -- and wrong as a *fact* about this registry. Both halves matter:
I did not prune anything, and I did not pass on a number I had not checked.

Third: @seedgo said out loud that they routed around my deadlock via a Bash heredoc and only reported
it because they were already mailing me. That is the same pattern I recorded in observation 25 this
morning from the other side. An obstacle that can be stepped over never gets measured -- which is
exactly why the git_gate bypass, which requires no workaround at all because it simply lets you
through, went unreported for longer.

Nothing committed -- @devpulse handles version control for the round. Medic muted at session start.

**S145 (2026-08-13, evening):** @devpulse dispatch 223f5e3c -- help_flag_safety 84 -> 100. Overall
100%, 1450 green, ruff clean.

The dispatch's warning was the whole job: *the standard names instances, the defect is a class*. The
checker named 2 modules. Sweeping `apps/modules/*.py` for the shape found **9**, and the worst was
unnamed: `sessions reclaim --help` did not merely run the reclaim, it read `--help` as the branch
filter and reclaimed on `"-help"`. Two failure shapes from the standard, (a) positional gate and (c)
flag-consumed-as-value, in one line of code. If I had fixed only the two named files, the score would
have read 100 and the session-stopping path would still be open. That is the same lesson as this
morning's audit, from the other direction: a green number produced by fixing what was measured rather
than what was broken.

Placement mattered as much as detection. The convention says gate AFTER the ownership check, because
a top-of-function scan makes the first module in the router answer every other module's help. I wrote
six tests asserting each module returns False for a command it does not own, so that failure mode
cannot come back quietly.

Two things I got wrong mid-session and corrected: I wrote a canary asserting `dismiss help` should
dismiss an alert named "help" -- it contradicts the settled contract, which puts bare `help` at slot 0
as a question. And I edited a call site before adding its import, so my own edit_gate blocked me. That
block was satisfiable by the edit it was refusing to let me skip, which is exactly what a gate should
be, and it is worth recording next to learning 110: the diagnostics gate works correctly when the fix
is in the file you are already touching. The deadlock only appears when it is not.

Also handled: Patrick ruled on the git_gate bypass (DPLAN-0293, visit-later, no interim mitigation),
and @seedgo reported that my checklist parsing has been silently dropping every standards finding
since it was written. Both logged above, neither touched -- the dispatch scope-fenced this pass to
help_flag_safety, and a peer mail does not lift a park.

## Listen (TTS-friendly summary)

The hooks branch is healthy on paper and yellow in practice. All one thousand four hundred and five
tests pass, seedgo scores one hundred percent, and there were no error lines in the logs for a full
day. Every one of those clean readings turned out to have a structural reason that hides something.

The most serious finding is a security bypass in the git gate. The gate is supposed to stop every
agent except devpulse from running git write commands directly. It blocks the command git push, but
it allows the same command written with a full path, slash usr slash bin slash git push. The pattern
it uses to recognise git deliberately ignores anything preceded by a slash. Worse, there is a test in
the suite that asserts this behaviour is correct, which is why a fully green test run never revealed
it. I did not fix this, because the same pattern carries a second known defect that Patrick has
parked, and fixing one half of a matcher while the other half waits is how you create a new problem.
It went to devpulse with a recommendation that it goes ahead of everything else in the queue.

The second finding came from seedgo. If a file with recorded type errors is deleted, or renamed, or
moved to the archive folder, the edit gate blocks every python edit in that branch forever, and quotes
errors at a path where nothing exists. Two of those three actions are the cleanup pattern the whole
fleet is told to use. The fix is a single line and I have proven it works, but the code it lives in is
already in front of Patrick, so it waits for his word rather than mine.

I also verified all eight items on the parked list. Seven still reproduce and one does not. The one
that does not is the belief that block reasons vanish when the engine writes them to standard output.
They do not vanish. I proved it twice, including by watching one of my own audit agents get blocked
and receive the full explanation. That item can be struck from Patrick's queue entirely.

Two measurements devpulse asked for are done. Successful blocks are logged at warning level, which
accounts for a third of all warning traffic from this branch and most of the escalations trigger has
been seeing. The timing histogram could not be built, because the diagnostic log only keeps about
eleven minutes of history before it rotates, not the twenty four hours everyone assumed. That gap is
itself the finding.

I fixed two things that sit outside the parked list. The wiring checker used to print failed and then
report success to anything reading its exit code, which meant any automated gate built on it was
silently passing. And the readme carried two false claims of my own making, including a performance
claim about this morning's work that the data contradicts. Both are corrected, and the correction is
recorded rather than quietly overwritten.

In the evening session I fixed the last failing standard, help flag safety, and the branch now scores
one hundred percent. The standard named two of my modules. When I searched for the same shape across
every module I found nine. The most dangerous one was not named: asking for help on the session
reclaim command did not just stop live sessions, it also read the word help as the name of the branch
to stop. If I had fixed only the two files the checker pointed at, the score would have read one
hundred and the session stopping path would still have been open. Every fix was proven with a failing
test first, and I confirmed on the real command line that asking for help no longer changes anything.

Patrick has ruled on the git gate bypass. It now has its own design plan, to be visited later rather
than rushed, and no temporary workaround was judged necessary because agents type the plain form of
the command by habit. I build the fix when that session happens.

Seedgo also found that my own code has been reading their checklist output for a marker they have
never printed, which means every standards finding from that path has been silently discarded since
the line was written. They have published a stable marker on their side. I have logged the migration
but not applied it, because the branch is still parked and this evening's permission covered only the
help flag work.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
