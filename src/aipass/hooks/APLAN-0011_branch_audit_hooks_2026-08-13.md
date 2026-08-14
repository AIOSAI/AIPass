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
| **Last verified** | 2026-08-13 (S146) |
| **Open items** | 23 (1 security bypass -> DPLAN-0293, 7 parked, 2 escalated, 13 branch-owned) |
| **Tests** | 1451 pass, 0 fail, 2 skip (1453 collected, 47 files) |
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

#### Config-change traps -- discovered by walking into one (S146)

- [ ] **Editing `.aipass/hooks.json` takes EVERY hook in the project dark.** Not a warning, an outage.
  The file is hash-enrolled in the trust registry; any byte change breaks the hash and the trust gate
  refuses the whole config -- edit_gate, git_gate, rm_gate, all 28 handlers, project-wide, for every
  session. I caused it at 21:44:50 adding `"timeout": 90`, discovered it because a timeout proof
  returned the TRUST BREAK banner instead of handler output, confirmed with `drone @hooks status`,
  and reverted to byte-identical HEAD (5427 bytes, sha256 `bb83f2c0e01a1261`) via `git show HEAD:`.
  Dark window ~8 minutes; only my own session was working in it. **Any hooks.json change must land in
  the same operation as `aipass trust /home/patrick/Projects/AIPass`.** Note the compounding failure:
  the banner that fires in this exact state tells you to run `drone @hooks trust enroll`, a command
  that does not exist (parked item 3). The one moment the message matters most is the one moment it is
  wrong. This is a finding about the *system*, not just my mistake -- nothing anywhere warns first.
- [ ] **`aipass init update` silently wipes per-hook timeouts.** `bootstrap.py:168-175` union-merges
  `hooks.json` against `.aipass/project_hooks.json` and preserves only `enabled` -- the whole hook dict
  is replaced for any hook that also exists in the template. The template carries no UserPromptSubmit
  timeouts, so the moment the 90/120 knobs land they are one `init update` from vanishing without a
  log line. Either the template gets stamped too, or this regresses invisibly.
- [ ] **`aipass doctor` is blind to timeout drift.** `doctor.py:420-423` compares `command` and
  `matcher` only. It will report 27 hooks wired and PASS with every timeout missing, and
  `doctor --fix` does nothing. This is why the `auto_process` regression below survived two weeks with
  a healthy doctor.

#### The auto_process timeout regression (root-caused S146, provider-side fix handed to devpulse)

- [ ] **`UserPromptSubmit:auto_process` lost its `"timeout": 120` between 2026-07-31 18:27 and
  2026-08-02 19:57, and that -- not @baud -- is what Patrick has been feeling.** Transcript-observed
  `timeoutMs` for that hook is 120000 through 07-31 and 30000 from 08-02.
  `~/.claude/settings.json.bak.2026-07-18` still carries the 120; current `settings.json` carries
  none. The value never existed in `provider_manifest.json`, so a regeneration reconciled it away --
  it lived only in deployed settings. Rates per 1000 prompts (volume controlled):
  | Window | auto_process | all other hooks |
  |---|---|---|
  | 07-09..08-01 (pre-change) | 0.93 | 27.86 |
  | 08-02..08-08 (post-change, pre-BAUD) | 17.41 | 0.00 |
  | 08-09..08-13 (post-BAUD) | 50.89 | 13.02 |
  Under the old 120s ceiling, 7 of 19 recorded `auto_process` runs already exceeded 30s -- every one
  would be a silent "output discarded" today. Fix is the provider-side pair in the handover below;
  raising the twelve fast handlers to 90 does **not** address this one, restoring 120 does.
  **Separately worth Patrick's attention: a handler that legitimately runs up to two minutes on the
  first prompt of every session is a design problem, not a ceiling problem.** Not in DPLAN-0285's
  items, not touched.

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

- [x] **README wiring claims corrected -- three stale sentences, not the two the DPLAN cited** (S146 --
  @devpulse dispatch 565fbf11, DPLAN-0285 item 1; strikes parked item 4). The plan names README lines
  51 and 127; both had moved, and a third was wrong and uncited. Now at **58, 64, 139**. Line 64 was
  the dangerous one: it told a builder that every new handler needs a provider entry, when for the five
  fan-out events **none** is needed and for PreCompact **two** are -- wrong in both directions, and
  nothing in DPLAN-0285 would have caught it. All three now state the verified shape: 5 fan-out events
  (PreToolUse, PostToolUse, SubagentStop, Stop, Notification), UserPromptSubmit 13 per-handler entries,
  PreCompact 8 (4 handlers x manual/auto), SessionStart 1; and explicitly that there is no bare
  `claude.py UserPromptSubmit` entry. Line 64 replaced with a 3-row table of when a provider change is
  actually needed. No test asserts on README content, so this could not break the suite.
- [x] **Timeout knobs proven non-decorative on both sides** (S146 -- DPLAN-0285 item 2; the *change*
  is handed to @devpulse, the *proof* is done and lives here). Controlled proof with real threads and
  a real `worker.join`: a 35s handler under inner=30 is **killed at 32.73s with stdout EMPTY** -- that
  is Patrick's failure reproduced exactly, output silently discarded -- while inner=90 waits 35.00s and
  keeps its output. Fast handlers are byte-identical under 30 vs 90 (temporal 44B, identity 1151B,
  tier0_kernel 0B, sha256 equal), so raising the ceiling changes nothing about normal output. +1 test
  in the suite (`test_inner_timeout_above_30_reaches_the_join`) pinning that a `hooks.json` value >30
  reaches `worker.join` uncapped -- there is no clamp anywhere in the dispatch path (`engine.py:322`
  reads `timeout`, `:123` joins on it, defaults at `:55` and `:86`, exactly one join).
  **NOT APPLIED HERE** -- see the trust trap above. Handover artifacts: `/tmp/hooks_timeout_90.patch`
  (inner knobs), the provider spec in the reply to 565fbf11, and `/tmp/live_config_timeout_tests.py`
  (3 config-pinning tests, deliberately kept out of the suite because the config is deliberately not
  shipped -- they would be red on purpose).
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
- [ ] **Apply the timeout pair as ONE operation** (S146 handover): `git apply
  /tmp/hooks_timeout_90.patch`, add `"timeout": 90` to twelve `UserPromptSubmit:<name>` entries and
  `"timeout": 120` to `auto_process` in `~/.claude/settings.json` (lines
  209/217/225/233/241/249/257/265/273/281/289/297/305, none currently carry the field), stamp the same
  into `.claude/provider_manifest.json` lines 7-19 so the next wire run does not strip it
  (`provider_wire.py:72-73` honours a manifest timeout), then **`aipass trust
  /home/patrick/Projects/AIPass`** or the project goes dark. Then add
  `/tmp/live_config_timeout_tests.py`. Devpulse edits both provider files -- I am outside
  `TRUSTED_HOOK_EDITORS` and the manifest is the only one of the two I own at all.
- [ ] The 8 parked items below -- items 4 and 5 are now struck; 6 remain live.

### Parked (Patrick's call -- verified and measured this session, untouched)

| # | Item | Reproduces | Measured today |
|---|------|-----------|----------------|
| 1 | `auto_fix` logger_debug rule | **yes, premise dead** | prax shipped `debug()` 08-11 in `ba4d06a8`, whose commit message reads "Rule retirement dispatched to @hooks + @seedgo". @seedgo `modules_content.py:74` now teaches the OPPOSITE ("Use `logger.debug()` instead: silent"). Two hooks give contradictory advice on the same line. 33 fires in 13 min. |
| 2 | `auto_fix` string-literal grep | **yes** | 3 false positives in a live repro. `_check_line_pattern` (`auto_fix.py:109-115`) only suppresses when the pattern is *immediately* adjacent to a quote, so every docstring, help string and error message that names a pattern trips it. `open_no_encoding` (`:129-132`) has no literal guard at all. |
| 3 | TRUST BREAK banner | **yes** | `loader.py:132` says "Fix: drone @hooks trust enroll". No `trust` verb exists (enumerated every module's HELP_COMMANDS); real path is `aipass trust <path>`, which has no `enroll` subcommand either -- wrong twice. Same file gives THREE different fixes for the same condition (`:92`, `:98`, `:132`, `:192`). Fires when every hook is dark, i.e. when being right matters most. |
| 4 | README single-entry claim | **FIXED S146 -- STRIKE IT** | Was README:51/:57/:128; unparked by @devpulse dispatch 565fbf11 as DPLAN-0285 item 1 and fixed at lines 58/64/139. Three sentences, not two -- see Resolved. The README's own worked example, `claude.py UserPromptSubmit`, was precisely the entry that does not exist; it now says so out loud. |
| 5 | Engine block-path stdout/stderr | **NO -- STALE, STRIKE IT** | Claude Code honours `{"decision":"block","reason":...}` on stdout regardless of exit code. Proven twice: bridge subprocess test (exit 2, 430 bytes stdout, 0 bytes stderr, reason intact) and a live `rm_gate` block that caught one of my own audit agents mid-run and delivered the full reason text. The code still does not match the documented stderr contract, so the smell is real -- but nobody should spend a session on the premise that reasons are being lost. |
| 6 | 13-to-5 handler grouping (perf) | **yes, worse** | Still 13 handlers. Output measured **20,971 bytes** from a @drone seat, ~22.6KB from a @devpulse seat, against the 10,000 cap -- single-dispatch still fails, reproducing DPLAN-0285. Process time now ~44.7s across 13 processes vs DPLAN's ~21 CPU-s. Slowest single hook logged today: 22,771ms. |
| 7 | Timeout both-sides | **yes -- ROOT-CAUSED S146, fix handed to @devpulse** | Outer is not 30s, it is **ABSENT**: all 13 UserPromptSubmit manifest entries carry no `timeout`, inheriting Claude Code's 60s default, while 11 of 13 sit on the hardcoded inner 30 (`engine.py:322`, `:86`, `:55`). `auto_process` is clamped the other way, inner 120 against outer 60 -- and it is the one that actually times out (measured 78.5, 78.7, 83.1, 86.9, 87.3, 120.4, 120.5s). Both knobs proven live. Target: 90/90 for the twelve fast handlers, **120 outer for auto_process** to restore what was lost 08-01. Not applied here -- editing hooks.json breaks the trust hash. |
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
| 2026-08-13 | @devpulse dispatch 565fbf11 -- DPLAN-0285 items 1+2 + Patrick's BAUD question | Item 1 DONE (3 README sentences). Item 2 PROVEN but handed over as a patch -- applying it broke the trust hash and took all hooks dark for ~8 min; reverted. BAUD answered NO, root cause is an 08-01 config regression. Items 3+4 untouched per ruling. |

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

**S146 (2026-08-13, late evening):** @devpulse dispatch 565fbf11 -- DPLAN-0285 items 1 and 2, plus
Patrick's question about whether @baud caused the timeouts. 1451 green, ruff clean, seedgo 100%.

**I took every hook in this project dark for about eight minutes.** Adding `"timeout": 90` to
`.aipass/hooks.json` broke the file's enrolled trust hash, and the trust gate then refused the entire
config -- not my change, the whole thing: edit_gate, git_gate, rm_gate, all 28 handlers, every session
in the project. I found out because my own timeout proof came back with the TRUST BREAK banner instead
of handler output. The instinct is to file this as carelessness, and it partly is, but the honest
finding is structural: **the config file is the thing that authorises the config file, so editing it
is indistinguishable from tampering with it.** Nothing warns first. And the banner that fires in
exactly this state tells you to run `drone @hooks trust enroll` -- a command that has never existed
(parked item 3). The one moment that message matters most is the one moment it is wrong. I had that
item written down as a wording defect. It is not; it is a defect that fires only during an outage, and
I only learned that by causing the outage.

The dispatch said to leave working-tree changes in place. It also said Patrick cannot afford hooks
breaking. Those two collided the moment my edit disabled hooks rather than sitting inert, and I took
the consequence instruction as the senior one: saved the change as a patch, reverted to byte-identical
HEAD, verified `hooks_enabled: ON`. My own git_gate correctly refused the `git checkout` I reached for
first, which is the gate working -- I restored via `git show HEAD:` instead. Reported to devpulse
before anything else in the reply.

On the BAUD question the answer is no, and the interesting part is how nearly I got it wrong.
`engine.log` begins 2026-08-04; BAUD arrived 08-09. **Anyone reading my own logs would have concluded
"August, so probably BAUD", because that is where the tape starts.** The real record was 598 Claude
Code transcripts, 205,467 lines back to 07-09: earliest true timeout 07-15, worst day 07-28 with 37 --
three weeks before BAUD existed -- and zero of the 125 real timeouts in a BAUD directory. The cause is
a config regression: `UserPromptSubmit:auto_process` lost its `"timeout": 120` between 07-31 18:27 and
08-02 19:57, because the value lived only in deployed settings and never in the manifest, so a
regeneration reconciled it away. It is one handler, and it steps up before BAUD landed. Also worth
recording: 302 `hook_cancelled` events, but only 125 carry `timedOut: true`. The other 177 are user
aborts. Counting the wrong 302 would have produced a confident, wrong, 2.4x-inflated answer.

That is the same lesson as S144's, arriving a third way: my instruments were clean because they could
not see far enough back to be dirty. Retention *is* the finding, again.

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

In the late evening session I was asked to fix two things and answer one question, and I managed to
break the whole hook system doing the second one. Adding a timeout setting to the hooks config file
changed the file, and changing the file broke the fingerprint that proves the file is trusted, so the
system refused all of it. Every hook in the project stopped running, for about eight minutes, until I
put the file back exactly as it was. The lesson is not simply that I was careless. The config file is
the thing that authorises itself, so editing it looks identical to tampering with it, and nothing
warns you first. Worse, the message that appears in exactly that situation tells you to run a command
that has never existed. I had already written that down as a wording problem. It is not a wording
problem. It is a message that is only ever read during an outage, and it is wrong.

So the timeout change went to devpulse as a patch with exact instructions, rather than being applied
here. The proof that it works is done and it is solid. A handler that takes thirty five seconds is
killed at thirty two with its output thrown away, which is exactly the failure Patrick has been
seeing, and with the larger ceiling it finishes and its output survives.

Patrick asked whether the new baud branch caused the timeouts. The answer is no, and I almost got it
wrong in a way worth remembering. My own engine log only goes back to the fourth of August, and baud
arrived on the ninth. Anyone reading my logs would have concluded August, therefore baud. The real
record was in six hundred Claude Code transcripts going back to the ninth of July. The first real
timeout was the fifteenth of July, and the worst day in the entire record was the twenty eighth of
July, three weeks before baud existed. The actual cause is that one handler, the memory processor,
lost its two minute allowance somewhere around the first of August, and has been dying at thirty
seconds ever since. That allowance only ever existed in the deployed settings file, never in the
template, so the first time something regenerated the settings it was quietly reconciled away.

Also worth saying: of three hundred and two cancelled hook events, only a hundred and twenty five had
actually timed out. The rest were Patrick pressing escape. Counting the wrong number would have given
a confident answer that was more than twice too large.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
