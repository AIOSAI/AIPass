# APLAN-0008: Branch audit - trigger

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
| **Health** | YELLOW |
| **Last verified** | 2026-08-14 (S77) |
| **Open items** | 12 (2 closed S76/S77, 1 added awaiting @hooks) |
| **Tests** | 1029 pass, 0 fail (957 → 962 audit → 977 coercion → 1015 help-flag → 1020 sole-owner → 1029 twin) |
| **Seedgo** | 100% with bypasses / 98% without (44 standards), 0 type errors |
| **Bypass entries** | 26 — 25 measured live in-audit, +1 for the new help-flag predicate, 0 dead, 0 `tests/*` rules |
| **Live command sweep** | 37 CLI paths + 14 event types fired, incl. 14 error paths |
| **Escalation digests (24h)** | 14 sent, **1 actionable by the recipient** |

**Why YELLOW, not GREEN:** every headline number is green and three fixes landed
today, but the audit measured an escalation lane whose signal-to-noise is 1 in 14,
a test suite that silently rewrites live operational state, and a `fire` command
that reported success while the handler crashed. The numbers could not see any of
the three.

## Current State

### Summary
- Event bus + error dispatch for the fleet: pub/sub (`fire`/`on`/`off`), medic error
  detection with an 8-gate dispatch pipeline, log watching, error registry, and the
  repeat-signature escalation digest lane.
- 6 modules, 21 handlers, 27 test files, 1015 tests. 106/106 public functions tested.
- The persistent watcher (`trigger-log-watcher.service`) is the branch's real product:
  everything else is CLI around what that daemon does 24/7.

### Architecture
`apps/trigger.py` (entry, routes only) -> `apps/modules/` (CLI + business logic) ->
`apps/handlers/` (implementation). Live state deliberately sits off the `json_handler`
trio filenames. Two log watchers (branch logs, system logs) feed one registry.

### What Works Well
- **The reload sentinel is live and behaving.** Shipped last night (FPLAN-0404). Every
  code fix this branch shipped today was carried into the running watcher without anyone
  remembering to restart it — **11 real reloads on 2026-08-13**, all attributable:
  `core.py` ×2 (09:33, 17:0x), `startup.py, log_watcher.py`, `log_events.py`,
  `__init__.py, help_flags.py`, and `medic.py` ×6 (three of those are the mutation check
  described in Resolved — reverting a live module's gate to watch a canary go red
  bounces the daemon each time, which is correct behaviour and worth knowing before you
  do it). The 25-hour stale-code gap that cost this branch two misdiagnoses cannot recur
  silently.
  **Correction to this entry as first written (S74).** It said the trail records "four
  firings, all real". It records **97 lines**: 86 on 08-12 and 11 today. 56 of the 08-12
  lines are a failure class I never reported — `reload check failed, watcher continues on
  current code: disk gone` — and the other 30 were build-loop restarts. I wrote "four"
  from the tail of the file without counting it. The failures are all inside one
  6-minute window (23:38:50–23:44:26) while the sentinel itself was being built, and
  their median spacing is **0.02s**, which no 30-second periodic checker produces: that
  is many concurrent sentinel instances, i.e. test-spawned threads writing into the live
  operational trail. Learning 73 again, in the one file I have been citing as the
  sentinel's audit record. Re-measured today: a full 1015-test run adds **0 lines**, so
  the shipped suite is clean here and the pollution is historical — but the trail is not
  the pure service record the first draft implied.
- **The 8-gate medic pipeline works end-to-end, proven live this audit by accident.**
  Firing `plan_file_moved` with wrong kwargs crashed the handler; the crash was logged,
  the log watcher caught it, `error_detected` fired, and gate 2 (branch muted)
  suppressed the dispatch with a record in `logs/medic_suppressed.jsonl`. Detection,
  attribution, gating and audit trail all fired without being asked to.
- **All 37 CLI paths and all 14 event types return without crashing**, including the
  14 deliberate error paths.
- **The `.jsonl` decision trails are hermetic under the shipped suite.** Both
  `escalation.jsonl` and `reload_sentinel.jsonl` are unchanged across a full test run
  (byte-identical at 962 tests, 0 added lines at 1015) — which is why the digest
  measurement below can be trusted. Their `json_handler` siblings are not (see Issues),
  and "hermetic under the suite" is not the same as "never written by a test": the
  sentinel trail carries 56 lines from build-time threads, above.
- **The bypass registry is honest.** 26 rules (25 in-audit + the help-flag predicate),
  each matched 1:1 to a real surviving violation with `bypass: []`; nothing dead,
  nothing un-bypassed, no `tests/*` rules. Un-bypassed score re-measured S74: 98%.

## Issues Found

### Open

- [ ] **THE ESCALATION LANE: 1 actionable digest in 14 (devpulse's elephant, measured).**
  Last 24h from `logs/escalation.jsonl`: **14 digests sent**, 8 distinct signatures,
  429 further sends correctly held by cooldown. Attribution:
  | Origin | Digests | Actionable by recipient? |
  |---|---|---|
  | @hooks — **PARKED on Patrick's word** | 7 | No — recipient cannot act, only close |
  | UNKNOWN branch — duplicate twins of the @hooks signatures | 4 | No — duplicate mail |
  | @seedgo `inbox_audit` unreadable backup path | 1 | **Yes** — real defect, they fixed it |
  | @flow `close_plan` -> `/tmp/flow_audit_scratch` | 1 | No — a branch doing what it was dispatched to do |
  | @skills Telegram DNS failure | 1 | No — transient network |
  **11 of 14 originate from one parked component.** Two of those signatures are
  `PreToolUse BLOCKED by pre_edit_gate` — a security gate *succeeding*, logged at
  WARNING. The lane escalates any repeating WARNING, so a gate working correctly
  reads as a repeating fault.
- [ ] **Medic mute exists and did not suppress any of it — and must not, naively.**
  Confirmed live: all **14 fleet branches are content-muted right now** (the audit
  round told every citizen to mute itself), and the lane sent 14 digests anyway.
  Counting deliberately runs *before* every dispatch gate, and sending is gated only
  on threshold/cooldown/suppression. **A naive mute-aware gate would have been worse
  than the disease:** @seedgo is muted too, so it would have silenced the single
  actionable digest of the day and kept nothing. A mute means "I am building, expect
  error lines", not "do not tell the operator" — and during a fleet round every
  branch is muted at once. Recorded so nobody builds the obvious fix.
- [ ] **The real gap is that the recipient has no off switch.** Medic has
  `errors suppress <id>` (compass #219 — suppression is real silence). The escalation
  lane has no equivalent: the only action a digest offers is closing the mail, the
  cooldown expires in 360 min, and it returns. Worse, *closing ends the thread*, so
  the next digest opens a fresh one and reads as new. That is the mechanism that
  trains close-without-reading. **Proposal (NOT built today):**
  `drone @trigger escalation suppress <signature> [why]` / `unsuppress`, mirroring the
  medic verb and doctrine, auditable in `escalation list`. It puts the judgement with
  the human who has it, per signature, and needs no parked-branch concept at all.
  A zero-code stopgap exists and has never been used: `ignore_branches` in
  `trigger_json/custom_config/trigger.config.json` — an operator call, not mine.
- [ ] **Escalation corpus is AT its cap: 500/500 signatures, 483 warning / 17 error**
  (re-read hours later: still 500/500, now 482 / 18 — the cap holds, the mix churns).
  Least-recently-seen pruning is live, so warning wallpaper is now evicting error
  history — the state budget, not just the mailbox, is being consumed by noise.
  Predicted in learning 72; now arrived.
- [ ] **The test suite rewrites live operational state.** Measured with an idle control
  window to separate daemon writes from suite writes: 4 files change only under the
  suite. It writes a fixture error (`message: "New error"`) into the **live 763KB
  `error_registry.json`** that medic dispatches from, and pushes **40 of the 100
  entries** out of the `escalation_log.json` ring buffer per run — so ~40% of that
  operational record is synthetic after every test run, and I ran the suite four times
  during this audit. The `.jsonl` trails are unaffected.
- [x] **RESOLVED S76 — `system_logs/` now has one owner** (Patrick's ruling, 2026-08-14).
  Both watchers registered it. `start_log_watcher()` now declines and returns None
  (`watchers/log_watcher.py:436`, owner named at `:40`); everything else in that module
  stays live, since it is still the reader the catch-up scan uses. The service needed no
  change — it already treats one watcher declining as fine. Two severity fixes fell out
  of it in my own code: the decline was logged at ERROR (`modules/log_events.py:80`),
  which would have fed my own watcher an error line on every service start, and the CLI
  called it a failure. 5 tests red-first, plus one rewritten that pinned the pre-ruling
  behaviour.
  **Correction, S77:** I attributed the HOOKS/UNKNOWN twin signatures to these two
  watchers. That was wrong, and my probe could not have caught it — a hand-written
  `system_logs/trigger_probe.log` has no branch-log counterpart, so it tested the
  observer's absence and nothing else. devpulse (`e9d92ed2`) found the twin still being
  minted at 00:44-00:46, after the restart. Real cause below.
- [x] **RESOLVED S77 — one line, written twice by prax, is now counted once**
  (devpulse `e9d92ed2`). Every prax call lands in BOTH
  `src/aipass/<branch>/logs/<module>.log` and `system_logs/<branch>_<module>.log`, and
  the branch watcher globs both trees. One reader, two files — not two readers. Proof it
  was never two watchers: escalation signatures `0249c13b4d64` (HOOKS, branch path) and
  `690de8d87cdc` (UNKNOWN, system path) carry the same three sample lines with
  *consecutive* sequence numbers 8514/8515. `_should_process()` now drops a system_logs
  file when `_system_log_branch_twin()` finds the branch copy already covering it
  (`apps/handlers/log_watcher.py:596`). Measured before choosing which copy to drop: 230
  of 243 system_logs files are twin-backed, 229 of those twins written within 1s of their
  system copy (the one outlier was a rotation artifact, its `.log.1` matched to the
  nanosecond). The 13 with no twin — `telegram-bot-*`, marketstand, scratch — keep being
  watched, which is now the only reason the directory is read at all.
  Second defect found while measuring: the branch prefixes were a hardcoded list of 11
  names against 17 branches, so @hooks, @backup, @commons, @daemon, @skills and @aipass
  were UNKNOWN by construction. `_known_branch_names()` reads the tree on a 60s TTL and
  the list stays only as a floor for an unreadable tree. 9 tests red-first, both fixes
  mutation-checked separately (reverting the skip put 3 red incl. `assert 2 == 1`;
  reverting the attribution put 1 red). Live-proven post-restart: two real prax WARNING
  lines dual-written to `trigger/logs/unknown_module.log` +
  `system_logs/trigger_unknown_module.log` produced ONE signature (`bbe941c70f5b`),
  branch TRIGGER, `total_count 2` — one count per line, attributed to the branch copy.
- [ ] **`medic.py` is 2 lines under a hard fail and has to be split.** The `modules`
  standard fails at 600 lines; the checker counts one more than `wc -l` (it splits on
  newline, so a trailing newline yields an extra element). The file was at 599 by `wc`
  — i.e. exactly at the limit — before today, so ANY edit trips it. Adding one import
  for the help gate did, and getting back under cost the explanatory comments I wanted
  to leave at the gate plus a stray double blank line in the import block. That is a
  cosmetic squeeze, not a fix: the next line added to this file fails the audit again.
  Split by domain (the ~150 lines of `print_help` / `print_introspection` rendering are
  the obvious first move, now that `handlers/cli/` exists). Found S74.
- [ ] **9 CLI error paths print a refusal and still exit 0** (`errors detail|suppress|
  unsuppress` with a bogus fingerprint, `errors detail|suppress` with no argument,
  `medic mute` with no branch, `fire` with no event). A script cannot tell refusal
  from success. Structural: `handle_command` returns True/False, and False makes the
  entry point print "Unknown command" — there is no third state for "handled, failed".
- [ ] **Two commands report success for work they did not do.**
  `medic unmute @notabranch` says "Unmuted @notabranch — dispatch resumed" for a
  branch that was never muted and is not a citizen; `escalation list <bogus-level>`
  silently lists everything instead of refusing the level.
- [ ] **`drone @trigger status` cannot answer the question it looks like it answers.**
  It reports the branch log watcher of the CLI process you just started — always
  `Active: False` — while the systemd watcher runs. README fixed this audit to point
  at `medic status`; the command itself still misleads.
- [ ] **13 checklist-lane findings on 9 test files**, re-measured unchanged since
  2026-08-09: log_structure 6, windows_compat 4, hardcoded_path 2, silent_catch 1.
  Invisible to the audit lane (it never enters `tests/`) and **not** bypass-suppressed —
  this registry holds zero `tests/*` rules.
- [ ] **Known-cause items still open**: UNKNOWN-branch circuit-breaker pollution;
  circuit-breaker state coherence (a CLI reset is unseen by the running service — the
  sentinel reloads on code change, JSON state has no re-read path); `_detect_log_level`
  substring-scanning for " ERROR " instead of reading the level field (self-feeds on
  router lines); rotation reset returning before `_mark_data_dirty()`.

### Resolved

- [x] **`help_flag_safety`: 6 modules gated help at `args[0]` only** (S74) — a flag one
  position later was discarded and the subcommand RAN. Worst case in this branch:
  `medic mute @branch --help` **muted the branch it was asked to describe** — 24 hours
  of silenced error dispatch, no unmute. Fleet-wide the same shape cost a 17-branch
  config reset and a real backup run the same day. Fixed in
  `branch_log_events.py`, `core.py`, `errors.py`, `log_events.py`, `medic.py`,
  `escalation.py` via a new `handlers/cli/help_flags.wants_help()`. Two design points
  that are not incidental: the gate sits **after** each module's ownership check (a
  module claiming any invocation carrying `--help` would hijack every other module's
  help at the entry point), and the bare word `help` counts **only at position 0**
  because this branch's own commands take it as a value — `errors suppress <id> help`
  is a reason, `fire evt message=help` is payload. Matching is exact so `message=--help`
  stays payload too. 38 tests (14 module canaries + 24 predicate), **12 red first**;
  the mute canary mocks the dispatch target so it can never perform a real mute.
  **Mutation-checked afterwards** (prompted by @drone reporting one of their own
  canaries went green having proved nothing): reverting `handle_command`'s gate put
  2 of the 3 medic canaries red on the right assertion, but the third passed —
  `_route_medic_module` has a second gate one layer up that caught it. A real
  behavioural test, proving a different gate than intended. Both gates reverted put all
  three red; restored from a copy, 40 medic tests and the full 1015 green after.
  Live-proven: `medic mute @trigger --help` printed help with the existing mute expiry
  unchanged at 16h 8m either side. seedgo `help_flag_safety` 0% → 100%, overall 97% →
  **100% with bypasses / 98% without**.
- [x] **`_coerce_value` typed `fire key=value` arguments by shape** (S73) — found by
  acting on @drone's request to check my own paths after they fixed the same root cause
  in `drone.py:481`, rather than reporting my paths clean from memory. The branch has
  zero `.isdigit()` calls, but `core.py:_coerce_value` tried `int()` then `float()` and
  kept whatever succeeded, so `fire error_detected fingerprint=00123456` delivered
  **int 123456** into a parameter `handle_error_detected` annotates `str` — type
  contract broken and a character of the user's token deleted. Rate is the same as
  theirs: `uuid4()[:8]` is all-digit 2.3% of the time, `sha1[:12]` 0.46%. Coercion is
  now by **lossless round trip** — a token types only when `str(number) == token`.
  That shape, rather than a leading-zero special case, because it also caught four
  mangles I was not hunting: `int()` accepts `1_0` (→ 10), `+5` and ` 5`; `float()`
  reshapes `1.50` and `1e3`. 16 tests, **10 red first**, live-proven through the real
  CLI. My first parametrize wrongly listed `"0"` as a token that must stay a string —
  `str(0) == "0"` is lossless, so a bare zero is a genuine int; caught in the red run,
  which is rule E arriving in my own test-writing rather than in old tests.
- [x] **`fire` reported success when every handler crashed** (S71) — found live: firing
  `plan_file_moved` with the wrong kwargs printed a green `Fired event:` while the
  handler raised. The bus isolates handler failures by design and that is correct, but
  isolation was indistinguishable from silence. `fire()` now returns
  `{event, handlers, ran, failed}` and the CLI prints it: *"0 handler(s) ran, 1 failed"*,
  and *"no handlers registered, nothing ran"* for a typo'd event name. Handler
  exceptions still never reach the caller. **Re-measured before blaming the handler:**
  `handle_plan_file_moved(src_path, dest_path)` is correct and @flow, its only live
  producer, calls it correctly — my invocation was wrong, and the defect was that
  nothing told me so.
- [x] **Four tests pinned `fire()` returning None** (S71) — the Rule E shape, second time
  in this branch (learning 74 was the first). They asserted an implementation detail;
  rewritten to the real invariants: does not raise, and reports what it did.
- [x] **`--version` reported 2.2.0 while the README published 2.6.0** (S71) — four
  documented releases, the escalation lane and the reload sentinel among them, shipped
  without the string moving. Nothing paired them. Now a single `__version__` constant,
  pinned to the README header by a test that is **mutation-proven** to fail on drift.
- [x] **`medic nonsense` reported "Unknown command: medic"** (S71) — naming the one word
  that was valid and hiding the one that was not. The entry point now names the whole
  invocation.
- [x] **38 orphaned `tmp*.tmp` files in `trigger_json/`** (S71) — 149KB of failed-atomic-
  write leftovers, all 4+ days old (none newer than Aug 9), removed after verifying
  every live `.json` hash was unchanged. The *cause* is not proven fixed, only quiet.
- [x] **Bypass registry re-measured, nothing pruned** (S71) — 25 rules, 25 live, 0 dead.
  Unlike other branches this wave there was nothing to cut; reporting the measurement
  rather than a cut, because "no change" is a result.

## What Needs Doing

### @trigger to handle (dispatch)

**Sequenced S73 after devpulse's ruling. Order is load-bearing, not preference:**

- [ ] **1. Build `escalation suppress <signature> [why]` / `unsuppress`** — the
      recipient's off switch. **RULED BUILD** by devpulse (S73): recipient-side,
      signature-scoped, reversible, auditable in `escalation list`, mirroring medic's
      compass #219 verb. Red-first at next wake — deliberately not on audit day.
- [ ] **2. Suite isolation** — mock `json_handler.log_operation` in the autouse fixture.
      Must land **before** item 3, or the cap gets decided against a corpus my own test
      runs are churning.
- [ ] **3. Escalation cap policy** at 500/500 — the question changes once 1 and 2 land,
      so measure then decide.
- [x] **Done S76** — `system_logs/` given one owner (Patrick's ruling). Halves the
      twin signatures; re-measure the digest volume after @hooks' reclass lands.
- [ ] **Awaiting @hooks** (spec sent via devpulse, not my code): `edit_gate.py:232`
      `logger.warning` → `logger.info` for the over-budget class. That class alone holds
      8 signatures / 579 occurrences and has sent **10 of the 62 digests this lane has
      ever produced** — 16%, all of it chosen behaviour that self-heals.

### devpulse to handle
- [x] **Ruled S73: build the suppress verb; `ignore_branches` stays unused.** Their
      reason is better than my own framing — branch-coarse silence on @hooks would
      blind us to a future real hooks fault, which is the failure I described and then
      nearly proposed a version of. The mute-aware gate is confirmed NOT to be built.
- [ ] Operator call (Patrick's queue, per devpulse): whether parked @hooks signatures
      get suppressed once the verb exists.

### Tracked elsewhere
- [ ] Report to @hooks: `PreToolUse BLOCKED by pre_edit_gate` is a gate *succeeding*,
      logged at WARNING. Their log level, their call — but it is 2 of my 8 signatures.
- [x] **@hooks: parked, so not mailed.** `PreToolUse BLOCKED by pre_edit_gate` at
      WARNING — devpulse ruled it a logging-level bug wearing an escalation costume,
      belongs at INFO, their line to change, and it alone would have cut 2 of my 14.
      Logged for Patrick's queue rather than dispatched to a branch with no reader.
- [x] **CLOSED by @drone (S73)** — they had reproduced it independently that morning
      (`04727185` → `Message not found: 4727185`) before reading my dispatch. They took
      both halves of the suggestion and went further: the `.isdigit()` guard is gone
      entirely, so one path decides by lookup instead of two deciding by shape, and the
      silent-wrong-mail collision (`00000002` resolving to display position 2) is gone
      with it. 6 tests red-first, 1034 suite green. Their request to check my own paths
      is what surfaced `_coerce_value` above.
- [x] Reported to @drone (S71, dispatched): `drone @ai_mail view <all-digit-id>` is
      eaten by the numeric-index shortcut at `drone.py:481` — `.isdigit()` fires on real
      IDs too, and the `str(n)` fallback strips the leading zero, so the not-found names
      an ID the user never typed. IDs are `uuid4()[:8]`, so (10/16)^8 = **2.3% of all
      messages** cannot be opened by their printed ID. Found live on my own inbox;
      `close` and `reply` are unaffected, which is the workaround.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fleet audit round (DPLAN-0291), wave 4 | YELLOW — 11 open, 6 resolved |
| 2026-08-13 | Reply to @devpulse (late — audit session ended unreported) | Sent, all numbers re-measured first |
| 2026-08-13 | Dispatched @drone — `view` eats all-digit message IDs | **Closed** — fixed by @drone, guard removed entirely |
| 2026-08-13 | devpulse verified wave 4, closed their half | Ruled: build the suppress verb, not on audit day |
| 2026-08-13 | `_coerce_value` lossless-round-trip fix (S73) | 977 green, seedgo 100%, live-proven |
| 2026-08-13 | Fix round to 100: `help_flag_safety` on 6 modules (S74) | 100% / 98%, 1015 green, 12 red first |
| 2026-08-14 | Night shift item 6: system_logs sole owner (S76) | Built, 1020 green, live-proven attributed |
| 2026-08-14 | Twin follow-up: prax dual-write counted once (S77) | Built, 1029 green, live-proven 1 signature / 2 lines |
| 2026-08-14 | Night shift item 4: severity reclass | **Spec sent** — label is emitter-side (@hooks), not mine |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round), DPLAN-0290 (night shift)
- **Related FPLANs:** FPLAN-0404 (reload sentinel, verified live here)
- **Owner branch:** @trigger
- **Seedgo:** `drone @seedgo audit aipass @trigger`

## Notes
Session notes, discoveries, changes. Stamp each entry: session number + date.

**S71 (2026-08-13):** Full branch audit. 37 CLI paths, 14 event types, 962 tests,
seedgo 100%/98%, 25 bypass rules all measured live. Four fixes landed red-first;
the version guard is mutation-proven. Nothing unexplained was found in the tree —
`drone @git status` showed only the APLAN stub I had just created, so rule B did
not apply here.

**S74 (2026-08-13):** Fix round to 100 — `help_flag_safety`, the standard that shipped
today and scored this branch 0/100 on it. Six modules, one shared predicate, 12 red
canaries first. The canary that matters is `medic mute @branch --help`: before the fix
it muted the branch, and the mute is the one action in this branch that silences another
citizen for a day with no way back. Two things the score could not see. The bypass
registry went 25 → 26: the new predicate cannot import `json_handler` (it runs first, on
every invocation, and logging there would write a line per CLI call), which is the same
call @memory made on the standard's own reference implementation — a rule I would rather
publish than quietly inherit. And `medic.py` was already sitting exactly at the 600-line
fail threshold, so a single import line failed the audit; I bought the two lines back
from my own comments and a stray blank rather than from the file's real problem, which
is that it needs splitting. Logged as open, because a cosmetic squeeze is not a fix.

**S73 (2026-08-13):** Wave 4 verified and closed by devpulse; the suppress verb is
RULED BUILD but explicitly not on audit day, so it is sequenced above and starts at the
next wake. The day's real lesson came from the other mail: @drone asked me to check my
own paths for their bug's shape, and checking rather than answering from memory found
`_coerce_value` doing the same thing one layer down. The finding travelled branch → bug
report → their fix → their advice → my own defect, and every step of that chain was
someone declining to take the previous step on trust.

**S71 addendum (2026-08-13, later):** the audit above shipped and the session ended
*without replying to the dispatch* — precisely the failure devpulse's rule A was
written about after @ai_mail hit it twice. Reply sent on the next wake, and every
headline number was re-measured from reality first rather than quoted from this
document: 962 pass / 0 fail, seedgo 100%, sentinel firing count now 4 (this file's
"restart counter 3" was already stale by two firings — its own fixes triggered them).
Nothing had drifted except in my favour, but quoting a document back at its author
would have been trusting my own memory, which is what put the branch here.

Three things the numbers could not see, and all three were found by *doing* rather
than reading: the escalation lane's 1-in-14 actionable rate came from parsing my own
trail, the live-state pollution came from running the suite against a hashed control
window, and the `fire` silence came from firing an event wrong by hand. The audit
found more by making things run than by inspecting them — which is the branch's own
first principle, and I had not been applying it to myself.

## Listen (TTS-friendly summary)

Trigger's audit is signed yellow. The numbers are green. Nine hundred and sixty two
tests pass, seedgo scores one hundred percent with bypasses and ninety eight without,
all twenty five bypass rules were proven to suppress a real finding, and every one of
the thirty seven command paths and fourteen event types runs without crashing. The
reload sentinel that shipped last night is alive and has already restarted the watcher
onto its own fix.

The yellow is for three things the numbers cannot see. The first is the escalation
digest lane. In the last twenty four hours it sent fourteen emails and exactly one of
them was something the recipient could act on. Eleven came from a single component
that is parked, meaning nobody can fix it, and four of those were the same problem
counted twice under two different names because two watchers own the same log
directory. Two more were a security gate reporting that it had successfully blocked
something. A digest lane with that ratio teaches the reader to close without reading,
which is exactly what makes it useless on the day it carries something real.

Muting does not stop it, and the audit found that the obvious fix would be worse than
the problem. Every branch in the fleet is muted right now because the audit round told
them all to mute, so a mute aware filter would have silenced the one useful email of
the day and kept nothing. The real gap is that the person receiving these has no way to
switch one off. Closing the mail does nothing and the same signature returns six hours
later. The proposal is a suppress command per signature, matching the one medic already
has, and it is written down rather than built.

The second finding is that the test suite writes into live operational files. It puts a
fake error into the real error registry and pushes forty of the hundred entries out of
an operational log every time it runs. The third is that the fire command reported
success while a handler crashed, which was found by firing an event wrong by hand
during this audit and is now fixed, along with a version string that had been wrong
through four releases.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
