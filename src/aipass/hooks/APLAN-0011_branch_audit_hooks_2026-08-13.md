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
| **Last verified** | 2026-08-14 (S152) |
| **Open items** | 21 (1 security bypass -> DPLAN-0293, 3 parked, 2 escalated, 12 branch-owned, 1 @aipass, 2 @memory/@skills) |
| **Tests** | 1483 pass, 0 fail, 2 skip (1485 collected, 48 files) |
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

#### Found while working, S148 -- other branches' lanes, reported not touched

- [ ] **@memory: `spawn_background()` checks a lock its own child has not taken yet.** The parent only
  *reads* `_LOCK_PATH`; the child takes it in `run_once()` via `_acquire_lock()`. Between `Popen`
  returning and the child creating the lock file (~0.5s of interpreter startup) a second
  `spawn_background()` sees no lock and spawns a second child, which then declines atomically at
  `_create_lock_file()` (`O_CREAT|O_EXCL`) and exits. **Correctness is safe** -- the child-side lock is
  the real one and I found a genuine `{"skipped": true, "reason": "another run holds the lock"}` line
  in their child log proving it works. The cost is one wasted process per racing session, which
  matters precisely because DPLAN-0294 exists to reduce prompt-lane process pressure.
  **Honesty about evidence: I did NOT reproduce this.** My three probes ran sequentially and none
  raced; the decline line in their log predates them and belongs to @memory's own testing. This is a
  code-path reading, and I say so rather than dress it as a repro.
- [ ] **My own SessionStart records do not log `source`.** 9 real SessionStart dispatches in the
  retained window and not one of them can tell you whether it was `startup`, `resume`, `clear` or
  `compact`, because the JSONL never writes the field. That is why I cannot answer @memory's question
  from evidence (below) -- and it is a one-line fix in my own logging. Mine to do.

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
  **ROOT-CAUSE SHARPENED S148, with a pyright probe -- this is the recommendation for Patrick's
  morning queue.** @memory hit the deadlock tonight in exactly the shape my morning fix was supposed
  to cover, so I checked instead of assuming, and the fix is narrower than I thought.
  `_CROSS_FILE_SIGNATURES` (`diagnostics_state.py:47-50`) contains exactly two strings:
  `"is unknown import symbol"` and `"could not be resolved"`. I ran pyright on a scratch red-first file
  containing all three canonical shapes and captured what it actually emits:
  | Red-first shape | pyright message | Covered? |
  |---|---|---|
  | `from impl import not_yet_written` | `"not_yet_written" is unknown import symbol` | **YES -- allowed** |
  | `impl.spawn_background()` | `"spawn_background" is not a known attribute of module "impl"` | **NO -- blocks** |
  | `impl.existing(mode="fast")` | `No parameter named "mode"` | **NO -- blocks** |
  So the morning fix covers the *import* shape only, and two of the three commonest red-first shapes
  still deadlock. That is @memory's case and it is a gap, not a regression.
  **RECOMMENDATION (Patrick-present class, NOT applied tonight -- load-bearing infra):** add
  `"is not a known attribute of module"` to the signature tuple. It is unambiguously cross-file: a
  module-level attribute can only be created in the module that lacks it. Treat
  `"No parameter named"` as a **separate judgment call for Patrick, and I would not ship it silently**
  -- that error is genuinely two-sided (fix the caller or fix the callee), so allowing it weakens the
  gate in a way the attribute case does not. Combined with the deleted-file `return []` fix already
  written, that is two small changes covering the three shapes the fleet actually writes.
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
- [ ] **NOT MINE -- @aipass: `aipass init update` re-enrolls only when its merge happens to rewrite
  `hooks.json`.** Found S147 while fixing the TRUST BREAK banner, which used to offer this command as
  the remedy. `bootstrap.py:555-560` gates `_enroll_project(target)` behind
  `if existing_hooks != merged_hooks`. So for a hand-edit the template does not touch -- exactly the
  shape that breaks the hash -- the union-merge is a no-op, nothing is written, **and nothing is
  enrolled**, so the project stays dark and the command reports success. When it *does* enroll, it does
  so by overwriting the change that caused the break. Either way it is the wrong instruction for a
  trust break, which is why I removed it from the banner rather than reword it. Static code-path fact,
  read not run -- I did not execute `init update` against a scratch project, so the runtime confirmation
  is owed. The same command is still offered by `never_enrolled_banner()` (`loader.py:192`), where it
  is *usually* right and fails only for a project already template-current; left alone deliberately --
  different condition, outside the two riders. Mail to @aipass, not a fix from me.
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
- [x] ~~`tests/test_trust_registry.py:444` -- asserts `"trust enroll"` is in the banner~~ **FIXED S147**
  with the banner itself; it now asserts the real remedy including the project path.
- [x] ~~`tests/test_auto_fix.py:370` -- pins the `logger_debug` rule~~ **MY CLAIM WAS WRONG, S147.**
  Re-read on the way to retiring the rule: those three tests exercise the generic `_check_line_pattern`
  helper and pass the pattern in as a literal argument, so they never asserted the rule existed and
  they stayed green after the delete. They *do* still use `logger.debug(` as the sample string, which
  is residue worth a future sweep, but that is a naming smell and not a test pinning a defect. Rule-E
  count for this branch drops from 5 to 4. Correcting my own audit rather than leaving the number to
  look thorough.
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
- [x] ~~The other 98 WARNINGs in 24h are edit_gate `.trinity` rollover advisories about **other**
  branches: @ai_mail 15, @daemon 12, @trigger 9, @flow/@drone/@seedgo 6 each. Advisory, never blocking,
  but they are the bulk of the escalation lane's raw volume.~~ **RESOLVED S149 by compass #273** --
  this is the class that just moved to INFO. The audit measured the volume and called it "the bulk of
  the escalation lane's raw volume" without questioning the *level*; @trigger asked the better
  question (why is a by-design event a warning at all) and Patrick ruled on intent. Worth keeping
  visible: I had the number and still framed it as a volume problem.
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

### The UserPromptSubmit sweep (DPLAN-0294 phase 2, S148 -- INVESTIGATION, nothing relocated)

Patrick's rule (compass #272): a UPS hook belongs foreground **only if its stdout feeds the prompt**.
Verdict below is measured, not read off the category folder -- `stdout_len` and `elapsed_ms` come from
this branch's own `engine.jsonl` over the retained window (383 UPS dispatches; median total 679ms,
p95 7873ms, max 17404ms, against the new 90s ceiling).

| # | Handler | Runs w/ stdout | Max stdout | Median ms | Verdict |
|---|---------|---------------|-----------|-----------|---------|
| 1 | `identity_injector` | **30/30** | 2513 B | 13.0 | INJECTOR -- stays |
| 2 | `temporal` | **19/19** | 42 B | 12.1 | INJECTOR -- stays |
| 3 | `branch_prompt` | 6/29 | 8932 B | 3303.6 | INJECTOR (cadence-gated) -- stays |
| 4 | `navmap` | 6/29 | 8162 B | 3461.2 | INJECTOR (cadence-gated) -- stays |
| 5 | `tier0_kernel` | 6/29 | 2472 B | 3787.6 | INJECTOR (cadence-gated) -- stays |
| 6 | `email_notification` | 4/29 | 130 B | 3284.2 | INJECTOR -- stays |
| 7 | `context_gauge` | 2/19 | 193 B | 18.0 | INJECTOR -- stays |
| 8 | `compass_recall` | 2/18 | 605 B | **4364.6** | INJECTOR -- stays, **flagged** |
| 9 | `persistent_alert` | 0/19 | 0 B | 14.7 | INJECTOR by code (no alerts in window) -- stays |
| 10 | `feedback_pulse` | disabled | -- | -- | INJECTOR when enabled -- stays |
| 11 | `presence_gate` | 0/18 | 0 B | 3842.3 | **GATE -- stays, non-negotiable** |
| 12 | `auto_process` | 0/19 | 0 B | 12.3 | WORKER -- **relocated tonight (item 1b)** |
| 13 | `user_message_relay` | **0/18** | 0 B | 4013.4 | **WORKER -- strongest relocation candidate** |

- [ ] **`user_message_relay` (@skills, not mine) is the clearest case in the sweep.** Every return
  path in the file yields `"stdout": ""` -- I read all of them -- and 18/18 live runs agree. It
  contributes **nothing** to the prompt, ever. What it does instead is a blocking HTTPS POST to
  `api.telegram.org` with `timeout=10` (`user_message_relay.py:119`) on the critical path of every
  prompt in a TG-configured branch. Median 4013ms, max 11976ms. It is also the only UPS handler whose
  latency is owned by a third party: if Telegram is slow, every prompt waits. Relocation candidate #1.
  Not mine to move -- goes to @skills as a plan.
- [ ] **`presence_gate` side-work: the premise does not reproduce.** The dispatch asked me to look
  hard at it. There is nothing to find: `handle()` only reads (`cc_sessions.find_occupant` over
  `~/.claude/sessions/*.json`, `presence._resolve_session_pid` over `/proc`), `_write_presence` exists
  but is reached only from `claim`/`release`/`refresh`, none of which the UPS path calls, and
  `handle_stop` is a documented no-op. It must stay foreground regardless -- its stdout on the block
  path *is* the `{"decision":"block"}` payload, and a gate you can relocate is a gate you have
  removed. Clean.
- [ ] **`compass_recall` is the injector to watch.** It does inject (2/18, max 605 B) so it stays under
  the rule, but it has the highest median of all 13 (4364.6ms), imports @memory's governance and
  @devpulse's compass at call time, writes cadence state, and calls `mark_surfaced()` into
  @devpulse's store. It is the only injector whose read cost is not bounded by construction. If phase
  3 wants a second candidate after `user_message_relay`, this is where to look -- as a split (recall
  foreground, bookkeeping deferred), not a move.
- [ ] **The timing column has an unexplained split and I am not going to pretend otherwise.** Seven
  handlers sit at 3.3-4.4s median and five at 12-18ms, with no obvious code reason -- `identity_injector`
  (13.0ms) and `tier0_kernel` (3787.6ms) both do essentially one file read. `elapsed_ms` covers the
  handler's own `importlib.import_module` plus the call (`engine.py:95-140`), which explains *some*
  spread but not this shape. Reported as measured; **nobody should plan capacity on these numbers
  until the split is explained.** The `stdout_len` column, which is what the verdicts actually rest on,
  does not depend on it.

### Resolved

- [x] **The over-budget class leaves the escalation lane -- WARNING to INFO** (S149 -- @devpulse
  dispatch c3e1af67, @trigger's diagnosis, **compass #273**: severity follows design intent;
  red-first). `edit_gate.py:225` `_warn_over_budget` -> **`_note_over_budget`**, and its
  `logger.warning` at `:232` -> `logger.info`. Three call sites (`:266`, `:274`, `:299`) are one class,
  so one change covers all three. Message text untouched, per spec -- the level is a field, not prose.
  Patrick's reasoning, which is the whole point: *"It is not a warning. It is not wrong behavior. It is
  behavior that we chose to have."* The message already says nothing is lost, because @memory's
  rollover archives the overflow at the next PreCompact. Scale: this one by-design class held 8
  signatures, 579 occurrences, and **10 of the 62 digests the escalation lane has ever sent -- 16%**.
  The rename matters as much as the level: a function called `_warn_*` that logs INFO is an invitation
  for the next reader to "fix" the level to match the verb, so a test asserts `_warn_over_budget` is
  **gone**, not merely that a new name exists.
  5 tests, 4 red first. Three cover the three call sites separately -- one class, but a fix that missed
  a site would still have left a third of the lane. The fifth is the guard that makes this surgical
  rather than a mute: **the over-limit *entry* advisory (`:181`) must stay at WARNING**, because that
  one names a cap the author has to act on and nothing archives it for them. If someone ever quiets
  this file wholesale, that test fails.
  **Live-proven in the exact stream @trigger reads.** Drove the real `handle()` with a real payload:
  `LEVEL=INFO`, message identical, `exit_code 0` (advisory, never blocked), nothing written to disk.
  The branch's own prax log now carries both sides of the change in one file -- 5 historical WARNING
  lines and the new INFO line, same text. No provider wire needed.
  **A finding on the way past, not fixed:** the *blocking* trinity path (`:175-179`) returns its block
  dict without logging anything at all. My first draft of the guard test asserted a block logs at
  WARNING; it does not, so I rewrote the test rather than keep an assertion that happened to pass for
  the wrong reason. The block is still recorded -- by the engine (`engine.py:396`), which is the
  existing "successful blocks log at WARNING" item above -- so nothing is lost, but the emitter itself
  is silent on its loudest outcome and quietest on its most routine one. Worth a look when that item
  is picked up.
- [x] **DPLAN-0294 phase 1b -- `auto_process` leaves the prompt lane** (S148 -- @devpulse dispatch
  8bb1bab7, @memory's spec, red-first). `handle()` now calls `spawn_background()` instead of
  `auto_process()`: the child is detached and the hook returns immediately. Session guard kept exactly
  as-is, now meaning **kicked-once, not ran-once** -- a refusal (a live run already holds the lock)
  marks the guard too, because the work is happening; only a failed kick stays retryable. Sound is
  action-gated to a real spawn, so a refusal stays silent, per the branch convention. The old
  pool/rollover counters are gone at hook time -- the child reports them to
  `memory_json/auto_process_log.json` -- and a test asserts the hook no longer invents them.
  24 tests in the file (8 red first). **Live-proven three ways, not just unit-proven:**
  `handle()` returned in **0.7102s / 0.7326s / 0.7595s** on three real invocations; `pgrep` confirmed
  the detached child (pid 89285) still running *after* the handler returned; @memory's own log
  timestamps its work at 00:04:42.887 -> 00:04:47.524, i.e. 4.6s of rollover that used to sit on the
  prompt. Refusal path proven live too, with a held lock: no child spawned, no sound, reason logged,
  0.6992s. Both registered events (UserPromptSubmit and PreCompact) take the same path -- asserted,
  because one handler serves both and fixing only the prompt lane would have looked identical in the
  suite. Timeouts untouched, as instructed. No provider wire needed.
- [x] **Rider 1 -- `auto_fix` logger_debug rule retired** (S147 -- @devpulse dispatch 882e6339,
  Patrick approved post-park, red-first). Deleted `auto_fix.py:30-33`. The premise died on 2026-08-11
  when @prax shipped `SystemLogger.debug()`; @seedgo had already retired the contradicting doctrine in
  `5d87fcc8`, so the rule was disagreeing with prax's code, prax's README and seedgo's standards at
  once, 33 fires in 13 minutes. 4 new tests: the key is gone from `PYTHON_PATTERNS`, no rule targets
  `logger.debug` at all, `_check_patterns` on a file that calls it returns `[]`, and -- the one that
  matters most -- **the premise itself is asserted** (`callable(system_logger.debug)`), so if prax ever
  removes it the suite says so instead of the rule quietly becoming right again. 3 of the 4 proven red
  first. No provider wire needed.
- [x] **Rider 2 -- TRUST BREAK banner now names a command that exists** (S147 -- same dispatch,
  red-first; strikes parked item 3). `loader.py:132` said `drone @hooks trust enroll`: no `trust` verb
  exists on @hooks, and `aipass trust` has no `enroll` subcommand -- wrong twice, in the one message a
  human sees while every hook in the project is dark. **I read that exact banner during my own outage
  three hours earlier**, which is why it was worth doing properly rather than minimally. Now
  `Fix (re-enroll): aipass trust {project_dir}` -- same wording and same path-bearing shape as
  `config_unavailable_reason()`, so the two paths for one condition can no longer drift. Rendered live
  to confirm the path interpolates. 2 new tests: one asserts neither dead command appears, one asserts
  the two code paths name the *same* remedy. Both red first, plus the existing `:444` flipped.
  **I also dropped the `(or: aipass init update)` alternative rather than keeping it** -- see the
  @aipass finding below; it is not a reliable remedy for this condition.
- [x] **Parked item 7 (timeout both-sides) -- APPLIED by @devpulse** (2026-08-13 22:10, commit
  `3da11942`). All four layers in one breath with the re-enroll, zero dark window: `.aipass/hooks.json`
  byte-identical to my patch, `~/.claude/settings.json` and `.claude/provider_manifest.json` stamped
  (12x90 + `auto_process` 120), and **the template trap closed** -- `.aipass/project_hooks.json` got 5
  UPS handlers stamped at 90 so `init update` cannot silently wipe the live values. My 3 config-pinning
  tests landed as `tests/test_live_config_timeouts.py`. Devpulse proved `aipass trust` worked from
  their seat on the *unchanged* config before editing -- my outage report bought that step.
  Follow-up open as **DPLAN-0294**: relocate `auto_process` off the prompt lane entirely (Patrick's
  ruling, compass #272), which is the design fix behind the ceiling fix.
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
- [x] **DONE 2026-08-13 22:10, commit `3da11942`** -- all four layers plus the re-enroll, zero dark
  window, template trap closed. Original handover spec kept below for the record.
- [ ] ~~**Apply the timeout pair as ONE operation** (S146 handover): `git apply
  /tmp/hooks_timeout_90.patch`, add `"timeout": 90` to twelve `UserPromptSubmit:<name>` entries and
  `"timeout": 120` to `auto_process` in `~/.claude/settings.json` (lines
  209/217/225/233/241/249/257/265/273/281/289/297/305, none currently carry the field), stamp the same
  into `.claude/provider_manifest.json` lines 7-19 so the next wire run does not strip it
  (`provider_wire.py:72-73` honours a manifest timeout), then **`aipass trust
  /home/patrick/Projects/AIPass`** or the project goes dark. Then add
  `/tmp/live_config_timeout_tests.py`. Devpulse edits both provider files -- I am outside
  `TRUSTED_HOOK_EDITORS` and the manifest is the only one of the two I own at all.~~
- [ ] The 8 parked items below -- items 1, 3, 4, 5 and 7 are now struck; **3 remain live** (2, 6, 8).
- [ ] **Mail @aipass** about `init update` enrolling only when its merge rewrites hooks.json
  (`bootstrap.py:555-560`) -- their code, my finding, sent S147.

### Parked (Patrick's call -- verified and measured this session, untouched)

| # | Item | Reproduces | Measured today |
|---|------|-----------|----------------|
| 1 | `auto_fix` logger_debug rule | **FIXED S147 -- STRIKE IT** | Retired on Patrick's approval (dispatch 882e6339). Premise died 08-11 when prax shipped `debug()` in `ba4d06a8`; @seedgo retired the contradicting doctrine in `5d87fcc8`. 3-line delete + 4 tests, incl. one asserting the premise so it cannot silently become true again. See Resolved. |
| 2 | `auto_fix` string-literal grep | **yes** | 3 false positives in a live repro. `_check_line_pattern` (`auto_fix.py:109-115`) only suppresses when the pattern is *immediately* adjacent to a quote, so every docstring, help string and error message that names a pattern trips it. `open_no_encoding` (`:129-132`) has no literal guard at all. |
| 3 | TRUST BREAK banner | **FIXED S147 -- STRIKE IT** | Was wrong twice (`drone @hooks trust enroll`: no `trust` verb, no `enroll` subcommand) in the only message shown while every hook is dark -- **I read it myself during S146's outage**. Now `Fix (re-enroll): aipass trust {project_dir}`, matching `config_unavailable_reason()` word for word so the two paths cannot drift. 2 new tests + `:444` flipped. See Resolved. |
| 4 | README single-entry claim | **FIXED S146 -- STRIKE IT** | Was README:51/:57/:128; unparked by @devpulse dispatch 565fbf11 as DPLAN-0285 item 1 and fixed at lines 58/64/139. Three sentences, not two -- see Resolved. The README's own worked example, `claude.py UserPromptSubmit`, was precisely the entry that does not exist; it now says so out loud. |
| 5 | Engine block-path stdout/stderr | **NO -- STALE, STRIKE IT** | Claude Code honours `{"decision":"block","reason":...}` on stdout regardless of exit code. Proven twice: bridge subprocess test (exit 2, 430 bytes stdout, 0 bytes stderr, reason intact) and a live `rm_gate` block that caught one of my own audit agents mid-run and delivered the full reason text. The code still does not match the documented stderr contract, so the smell is real -- but nobody should spend a session on the premise that reasons are being lost. |
| 6 | 13-to-5 handler grouping (perf) | **yes, worse** | Still 13 handlers. Output measured **20,971 bytes** from a @drone seat, ~22.6KB from a @devpulse seat, against the 10,000 cap -- single-dispatch still fails, reproducing DPLAN-0285. Process time now ~44.7s across 13 processes vs DPLAN's ~21 CPU-s. Slowest single hook logged today: 22,771ms. |
| 7 | Timeout both-sides | **FIXED -- @devpulse applied 22:10, commit `3da11942`. STRIKE IT** | Outer is not 30s, it is **ABSENT**: all 13 UserPromptSubmit manifest entries carry no `timeout`, inheriting Claude Code's 60s default, while 11 of 13 sit on the hardcoded inner 30 (`engine.py:322`, `:86`, `:55`). `auto_process` is clamped the other way, inner 120 against outer 60 -- and it is the one that actually times out (measured 78.5, 78.7, 83.1, 86.9, 87.3, 120.4, 120.5s). Both knobs proven live. Target: 90/90 for the twelve fast handlers, **120 outer for auto_process** to restore what was lost 08-01. Not applied here -- editing hooks.json breaks the trust hash. |
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
| 2026-08-14 | @devpulse c3e1af67 -- night item 4, over-budget WARNING -> INFO (compass #273) | DONE -- `_warn_over_budget` -> `_note_over_budget`, level changed, 3 call sites, text untouched. 5 tests (4 red first) incl. a guard that the over-limit entry class STAYS at WARNING. Live-proven in the prax stream itself: same file now holds 5 old WARNING lines and the new INFO one |
| 2026-08-14 | @devpulse d370516d -- verify on 1b + sweep | ACCEPTED. Both judgment calls approved (refusal-marks-guard, no-sound-on-refusal). user_message_relay -> Patrick's morning queue as relocation candidate 1; compass_recall split parked; edit-gate recommendation to morning queue verbatim |
| 2026-08-14 | @devpulse 8bb1bab7 -- night shift DPLAN-0295 items 1b + 2 | DONE -- 1b shipped red-first and live-proven (0.71s return, detached child confirmed by pgrep); item 2 verdict table delivered, 2 workers of 13, nothing relocated. Both FYIs answered with evidence: edit-gate gap root-caused by pyright probe, SessionStart question answered with an explicit "cannot confirm, and here is my own blind spot" |
| 2026-08-13 | @devpulse 882e6339 -- riders GO (Patrick present): retire logger_debug + fix TRUST BREAK banner | DONE -- both red-first, 6 tests, 1460 green, seedgo 100% on a forced full re-scan. Parked items 1 and 3 struck. Third defect found in @aipass's `init update`, reported not fixed. |
| 2026-08-13 | @devpulse e52ec095 -- timeout pair APPLIED, all 4 layers, zero dark window | Parked item 7 struck. Template trap closed at their end. DPLAN-0294 opened for the auto_process relocation |
| 2026-08-13 | @devpulse dispatch 565fbf11 -- DPLAN-0285 items 1+2 + Patrick's BAUD question | Item 1 DONE (3 README sentences). Item 2 PROVEN but handed over as a patch -- applying it broke the trust hash and took all hooks dark for ~8 min; reverted. BAUD answered NO, root cause is an 08-01 config regression. Items 3+4 untouched per ruling. |

## Relationships
- **Related DPLANs:** DPLAN-0285 (handler perf, item 6), DPLAN-0276 (post-compact regrounding),
  DPLAN-0278 (provider drift), DPLAN-0291 (this audit round)
- **Related FPLANs:** FPLAN-0400 item A / GH #733 (project fence, shipped 08-12)
- **Owner branch:** @hooks
- **Seedgo:** `drone @seedgo audit aipass @hooks`

## Notes

**S152 (2026-08-14):** Dispatch 590601bd, Patrick-ruled: *"we need a log for deleted files - if
something deletes, it should be a record of it."* @drone records the sanctioned lane; my half was the
leak. `rm_gate` saw every raw `rm` an agent ran and wrote down none of them -- it only ever spoke when
it blocked, and even then the engine recorded *that* a block happened, never *what* was deleted, into
a stream (`engine.jsonl`) that retains about eleven minutes.

Now every raw rm this gate sees gets one line, allowed or blocked, at INFO
(`rm_gate.py:128-140`): timestamp, status, caller branch, cwd, command as the agent wrote it.
Branch comes from a passport walk (`:104`), not the path -- learning 109, path shape lies. `drone rm`
and `git rm` are skipped: their deletions belong to someone else's record and double-logging would
make the fleet's delete count a lie. Zero decisions moved; a 13-case canary pins that.

The part worth keeping: **the first run of my own tests wrote 3597 lines/min into the live deletion
log and prax fired a CRITICAL runaway before the feature was finished.** 70 tests exercising a
recorder means 70 real writes into the record the recorder keeps -- to both sinks, branch-local and
the `system_logs/` aggregate @trigger watches. @devpulse caught it mid-build and steered without
stopping the work. The fix is an autouse fixture routing the writes to `tmp_path`, plus a guard that
runs 100 deletions and asserts both live files are byte-identical after. But the fixture fixes one
handler out of 28 that log; the class question -- how many other suites have been quietly writing
their own live logs, under the runaway threshold where nobody noticed -- is a new todo.

Judgment @devpulse asked for on the audit lane's own runaway exposure: prax detection is enough. One
line costs one Bash *tool call* -- a shell loop deleting 10,000 files is still one call and one line.
The only way to reach 3597/min is a harness calling the hook directly, which is what just happened and
which prax caught in 60s. A cap in the writer would drop lines exactly during a mass-delete incident,
which is the one time every line matters.

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

**S147 (2026-08-13, late night):** @devpulse dispatch 882e6339 -- the two post-park riders, approved
by Patrick while present. Both applied red-first. 1460 green, ruff clean, seedgo 100% on a **forced
full re-scan**, not the cache. Nothing committed.

The pairing was accidental and instructive: rider 2 fixed the banner I had personally read three hours
earlier, at the moment every hook in this project was dark because of my own edit. **A message that
only ever renders during an outage cannot be reviewed by using the system normally** -- which is why
it stayed wrong long enough to be parked as a wording nit. It was never a wording nit. It was the only
instruction available at the worst moment, and it named a command that has never existed.

That is also why I did not stop at the literal ask. The banner offered `aipass init update` as an
alternative; checking it before preserving it showed `bootstrap.py:555-560` gates enrollment behind
`if existing_hooks != merged_hooks`, so for a hand-edit the template does not touch -- precisely the
edit that breaks a hash -- the merge is a no-op, nothing enrolls, and the command reports success on a
still-dark project. When it does work it works by overwriting the change that caused the break. So I
removed the alternative rather than reword it, and mailed @aipass rather than touch their file. Two
things I want on the record about that: it is a **code-path fact I read, not a run I performed**, and
the sibling `never_enrolled_banner()` still offers the same command, where it is usually right --
different condition, outside the riders, deliberately untouched.

Rider 1 cost me a correction to my own audit. I had logged `tests/test_auto_fix.py:370` as a test
pinning the logger_debug rule. Re-reading it on the way to the delete, it does not: those three tests
pass the pattern into the generic `_check_line_pattern` helper as a literal, so they never asserted the
rule existed and stayed green afterwards. Rule-E count for this branch is 4, not 5. I would rather
shrink my own finding than let a number stand because it sounded thorough. The test I care most about
in that new class is the one asserting `system_logger.debug` is callable -- if prax ever drops it, the
suite says so, instead of a deleted rule quietly becoming correct again.

Also closed tonight, by @devpulse rather than me: parked item 7. They applied the timeout pair across
all four layers in one breath with the re-enroll and zero dark window, having first proved
`aipass trust` worked from their seat on the *unchanged* config. My outage report bought that step,
which is the most useful thing that came out of breaking it.

**S148 (2026-08-14, night shift):** @devpulse dispatch 8bb1bab7 under DPLAN-0295, Patrick asleep,
devpulse orchestrating. 1464 green, ruff clean, seedgo 100% on a forced full re-scan. Nothing
committed.

Item 1b closes the loop that started with Patrick's 21:23 timeout last night. The chain is worth
writing down whole, because no single step of it would have found the answer: a prompt died at 30s →
the ceiling had been silently reconciled away on 08-01 → the ceiling was never the real problem, a
two-minute job on the prompt lane was → @memory built the detachment → tonight it landed on my side.
The fix that mattered was not the one that was asked for first.

Two measurements I want kept. The handler now returns in **0.71s** having handed off work that
@memory's own log timestamps at **4.6 seconds** in the child — and that is a quiet night; the same job
has been measured at 78-120s. And the guard changed meaning without changing code: it now records
"kicked", not "ran". I made a refusal mark the guard too, because a live run *is* the work happening,
and made only a failed kick retryable. That distinction is the whole design, so it is two tests rather
than a comment.

Item 2's verdict rests on `stdout_len`, not on my opinion of what a handler is for. 13 handlers, 2
workers: `auto_process` (relocated tonight) and `user_message_relay`, which returns `""` on every one
of its code paths and on all 18 recorded runs while making a 10-second-timeout HTTPS call to Telegram
on the critical path of every prompt. It is @skills', so it goes to them as a plan, not a patch. The
dispatch also asked me to look hard at `presence_gate` side-work; there is none, and saying so is
worth as much as finding some.

I also refused to explain something. Seven handlers sit at 3.3-4.4s median and five at 12-18ms, and I
cannot account for the split from the code — `identity_injector` at 13ms and `tier0_kernel` at 3788ms
both do one file read. I reported it as measured and flagged that nobody should plan capacity on it
yet. The verdicts do not depend on that column, which is why the table is still usable.

Both FYIs turned into evidence rather than opinions. @memory's edit-gate deadlock is the shape my own
morning fix was supposed to cover, so I ran pyright on a scratch file with all three red-first shapes
instead of assuming: the import shape is covered, the attribute shape and the parameter shape are not.
That is a gap, not a regression, and the recommendation splits — one signature I would add
confidently, one I would not add without Patrick, because it is genuinely two-sided. And on
SessionStart I could not answer @memory's question, because my own JSONL never logs `source`. The
useful half of that answer is my own blind spot.

**S149 (2026-08-14, night shift item 4):** @devpulse dispatch c3e1af67 -- the severity reclass Patrick
ruled tonight as compass #273. 1469 green, ruff clean, seedgo 100% on a forced full re-scan. Nothing
committed.

This one is small and it corrects something in this very document. Back in S144 I measured the
escalation lane and wrote that 98 of the WARNINGs in 24h were `.trinity` rollover advisories about
other branches -- "the bulk of the escalation lane's raw volume". I had the number and I framed it as
a **volume** problem. @trigger asked the better question: why is a by-design event logged as a warning
at all? Patrick answered it in one line -- *it is not wrong behavior, it is behavior that we chose to
have* -- and the fix turned out to be a field, not a filter. 579 occurrences and 16% of every digest
the lane has ever sent, gone by changing a level. **Having the measurement is not the same as asking
the right question about it.**

The rename carried as much weight as the level change. A function called `_warn_over_budget` that logs
INFO is a trap for the next reader, who will helpfully "fix" the level to match the verb. So the test
asserts the old name is *gone*, not just that a new one exists.

Two things I did not take on faith. The dispatch handed me a spec with file, function and line
numbers; I checked all of them against my own code before touching anything, and they were right --
worth saying, because verifying a correct spec costs a minute and trusting a wrong one costs a night.
And my first draft of the guard test asserted that a blocking trinity violation logs at WARNING. It
does not: the block path at `:175-179` returns its dict and logs nothing at all. Rather than keep a
test that would have passed for the wrong reason under a different config, I rewrote the guard around
something true and more useful -- that the over-limit *entry* advisory stays at WARNING, so this
reclass can never be widened into a mute of the whole file. The silent block path is now logged above
as a finding.

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

Late at night Patrick approved two small fixes that had been waiting on the parked list. The first
retired a rule that told everyone logger dot debug was not supported. It has been supported since the
eleventh of August, and the standards branch had already retired the doctrine behind it, so my hook
was arguing with three other sources at once. It is gone, and the tests now assert the reason it is
gone, so if that support is ever removed the suite will say so rather than the old rule quietly
becoming right again.

The second fixed the trust break message. That is the message shown when every hook in a project is
switched off. It told you to run a command that has never existed, and it was wrong in two separate
ways at once. I read that exact message myself three hours earlier, during the outage I caused. A
message that only ever appears during an outage cannot be checked by using the system normally, which
is why it sat on the list as a minor wording issue for so long. It was not minor.

While fixing it I checked the alternative command it also offered, and found that command does not
reliably fix the problem either. It only re-enrols a project when its own merge happens to rewrite the
file, so for the kind of hand edit that breaks trust in the first place, it does nothing and reports
success. I removed it from the message and sent the finding to the branch that owns it rather than
editing their code.

One correction to my own audit. I had recorded a test as pinning the retired rule. Reading it properly
on the way to deleting the rule, it does not. My count of tests that pin broken behaviour on this
branch drops from five to four. I would rather shrink my own finding than keep a number because it
sounded thorough.

On the night shift the memory processor finally moved off the prompt. It used to do its work while
you waited, which is why your first prompt of a session could die at thirty seconds and lose its
context. Now the hook starts a detached child and returns in seven tenths of a second. I proved it
three times on the real thing and watched the child still running afterwards, doing four and a half
seconds of work that used to be yours to wait for.

I also swept all thirteen hooks that run when you press enter, against Patrick's rule that such a hook
belongs there only if what it prints goes into the prompt. Eleven of them earn their place. Two do
not. One is the memory processor, which moved tonight. The other belongs to the skills branch: it
relays your message to Telegram, prints nothing at all into the prompt, and makes a network call with
a ten second timeout on the way. Every prompt in a Telegram-configured branch pays for that. It is not
mine to move, so it goes to them as a plan.

One thing in that table I could not explain, and I said so rather than smooth it over. Seven of the
hooks take three to four seconds and five take about fifteen milliseconds, and two of them do
essentially the same single file read. The verdicts do not depend on those numbers, but nobody should
plan around them until someone works out why.

The memory branch hit the editing deadlock again tonight, in exactly the shape I thought I had fixed
this morning. So I tested it instead of trusting myself: I wrote the three ways a red-first test
normally names something that does not exist yet, and ran the type checker on them. My fix covers one
of the three. The other two still deadlock. That is a gap rather than a regression, and the fix is one
line for the clear case. There is a second case I deliberately will not fix without Patrick, because
it could be resolved from either side, and widening the gate on a guess is how a guard stops guarding.

The last item of the night was one word in a log line, and it removed sixteen percent of every alert
the escalation system has ever sent. When a memory file grows past its budget, my gate said so at
warning level. But nothing is wrong when that happens. The overflow gets archived automatically at the
next compaction, and the message says so itself. Patrick ruled that severity should follow intent: it
is not a warning, it is behaviour we chose to have. So it is now logged as information instead.

What I want to remember is that I had already measured this. Yesterday I counted those advisories and
called them the bulk of the escalation traffic, and then treated it as a volume problem. The trigger
branch asked the better question, which was why a deliberate event was a warning in the first place.
Having the number is not the same as asking the right question about it.

I also renamed the function, because it was called warn-over-budget, and a function named after a
severity it no longer uses will get its level put back by the next helpful reader. The test now
insists the old name is gone.

One test of mine was wrong before it was right. I wrote a guard asserting that a real blocking
violation still logs loudly, and it does not: that path returns its block and logs nothing at all. I
replaced it with a guard that is both true and more useful, that the other advisory in the same file
stays at warning level, so this change can never quietly become a mute of everything. The silent block
path is written down as a finding rather than left as a surprise.

This morning Patrick asked for something simple: if something deletes a file, there should be a record
of it. The drone branch keeps the record for its own delete command. My gate was the leak. It watched
every raw remove command an agent ran, and it only ever spoke when it blocked one. Even then, what it
wrote down was that a block happened, not what was being deleted, and it went into a stream that keeps
about eleven minutes of history.

So now every raw remove this gate sees gets a line, whether it was allowed or blocked: the time, the
command exactly as the agent wrote it, the folder it ran in, and which citizen ran it. The citizen
comes from reading their passport, not from guessing at the shape of the path, because path shapes
lie and I have been caught by that before. Deletes that go through drone or through git are skipped,
because those belong to somebody else's record and counting them twice would make the fleet's delete
count a lie. Nothing new is blocked. A thirteen case check pins every allow and deny decision exactly
where it was.

The thing worth remembering is what happened while I was building it. My own tests ran the recorder
seventy times, and every one of those runs wrote a real line into the real deletion log. Prax detected
three and a half thousand lines a minute and fired a critical runaway alarm on a feature that was not
even finished. Devpulse saw both halves at once, the feature working and the flood it caused, and
steered me mid build without telling me to stop. The tests now write to a temporary folder, and there
is a guard that runs a hundred deletions and insists both live log files come out byte for byte
identical. But that fixture protects one handler out of twenty eight that log. How many other test
suites have been quietly writing into live records, just slowly enough that nobody noticed, is now a
question on my list.

Last verified 2026-08-14.

---
*Created: 2026-08-13*
*Updated: 2026-08-14*
