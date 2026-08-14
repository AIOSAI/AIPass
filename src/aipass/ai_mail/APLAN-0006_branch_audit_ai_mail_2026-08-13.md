# APLAN-0006: Branch audit - ai_mail

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
| **Last verified** | 2026-08-13 (S141) |
| **Open items** | 9 (0 blocking) |
| **Tests** | 1074 pass, 0 fail, 0 skip (36 test files) |
| **Seedgo** | 100% (45 standards, 35 files) |
| **Seedgo with bypass OFF** | 99% -- 18 violations across 7 standards |
| **Bypass entries** | 18 (51 -> 17 by measured prune, +1 added with `help_flags.py`) |
| **Ruff** | clean |
| **Type errors** | 0 |
| **Test map** | 105 public functions, 105 tested (100%) |
| **Commands run live** | 41 invocations, 12 of them error paths (4 command surfaces deliberately not run — listed below) |

YELLOW, not GREEN: nothing is down, the suite is green and every command runs — but a live
sweep found a command that **hung for 30 seconds** and a reply-routing defect that was
sitting in my own test suite as an assertion. Both are fixed today; the colour records that
the numbers did not see either of them.

## Current State

### Summary
- 41 command invocations executed for real this audit, 12 of them error paths. Two real
  defects found, both fixed and live-proven; seven smaller gaps logged.
- **Not run, on purpose — this audit does not cover them:** `email @all` (broadcasts to 17
  branches), `dispatch @target "..."` (spawns a live agent in another branch),
  `dispatch daemon` (starts the polling daemon), `close all` (would close the round's own
  dispatch mail). Each has unit coverage; none has a live result today, and the score above
  should not be read as covering them.
- **Neither defect was visible in the metrics.** 1048 tests were green while
  `drone @ai_mail email` blocked for 30s, and green *because* `test_error_dispatch.py:39`
  asserted the reply-routing bug as correct behaviour. Third time this branch has recorded
  that shape (learning 71); first time it was found by running the command instead.
- The bypass registry went 51 -> 17 on a two-lane measurement, and the score is 100% before
  and after. This branch has **zero `tests/*` rules**, which is exactly the class that made
  the naive signal wrong 5 times in 6 for @seedgo — so the two lanes agreed here, and that
  agreement is a property of this registry, not a general result.

### Architecture
Entry point `apps/ai_mail.py` auto-discovers `apps/modules/*.py` and offers each command to
every module until one returns `True`. 3 modules (`email`, `email_send`, `dispatch`), 8
handler directories. Mail is JSON files: `.ai_mail.local/inbox.json` per branch, `sent/`
copies, `fcntl`/`msvcrt` locking on inbox writes.

Two things about the layout that are easy to misread:
- `apps/handlers/json/json_handler.py` is a **re-export shim** over
  `json_utils/json_handler.py`, existing only because seedgo's architecture standard
  requires that exact path. Not a duplicate implementation — 32 call sites use the shim, 6
  use `json_utils` directly.
- `apps/handlers/persistence/` and `apps/handlers/trigger/` contain nothing but
  `__init__.py`. Empty scaffolding, no callers.

### What Works Well
- 1053 tests green in 14s, 0 skips, ruff clean, 0 type errors, 100% of public functions
  covered by the test map.
- Exit-code discipline holds under live fire: `0` success, `1` unroutable, `2` routed-but-
  failed, verified on 11 separate error paths (bad id on view/reply/close, unknown branch,
  unknown command, missing args, privileged-claim refusal).
- **The verified-caller rail works and refuses in the right order.** `dispatch wake
  @nosuchbranch --sender @daemon` is refused for the *claim* before the branch is even
  resolved — the same "refusal ahead of the data it does not need" shape as learning 73.
  The control run with no claim reaches resolution and fails there instead.
- `upsert_key` collapsing verified live: two sends, one inbox slot, `x2` on the row.
- `--from @seedgo` on a plain send authors as @seedgo and buys nothing, exactly as the
  README's claim-vs-credential table says it should.

## Issues Found

### Open

- [ ] **No per-subcommand help.** `view --help`, `reply --help`, `close --help`,
  `sent --help`, `contacts --help` and `inbox --help` all print the identical email-module
  help. `view latest`, `close all` and the id arguments are documented nowhere the user
  would look for them. The `subcommand_help` standard scores this 100%, so the audit number
  cannot see it.
- [ ] **`--from` is missing from `email --help`.** It is in the README, in the code and in
  daily use; the module's own FLAGS block lists `--dispatch`, `--reply-to`,
  `--no-memory-save` and `--upsert-key` and stops there. The one flag with a security story
  attached is the one the help does not mention.
- [ ] **`--model` help names retired models** — "Claude Opus 4.6", "Claude Sonnet 4.6",
  "Claude Haiku 4.5". Learning 68 was written in this branch about exactly this: a comment
  that names a model dates the value. The help text does it in the user-facing surface.
- [ ] **`dispatch wake`'s failure line points the wrong way.** It prints "❌ Wake failed —
  see the step status **above**" and the step status replays *below* it, because drone
  captures stdout and stderr whole and replays stdout first. The README documents this
  ordering hazard and this line still walks into it.
- [ ] **`dispatch status` reports "No dispatches recorded yet"** although this branch has
  been dispatched repeatedly. The log is `.ai_mail.local/dispatch_log.json` and it records
  dispatches this branch *sends*, not ones it receives — so the output is technically true
  and reads as broken. Either name the direction in the output or show received dispatches.
- [ ] **`apps/handlers/__init__.py` fails the `cli` standard in the checklist lane** (not in
  the audit lane, and no bypass covers it). A package init file is being asked for a
  `--help` flag. Fires on every hook run that touches it. **@seedgo's checker, not mine.**
- [ ] **The checklist lane still checks `(disabled)` files.**
  `apps/handlers/email/dashboard_sync(disabled).py` fails `deep_nesting`, `handlers` and
  `naming`. The house rule mandates `name(disabled).py` instead of deletion, so every branch
  that follows the rule accumulates permanent checklist noise. **@seedgo's, and fleet-wide.**
- [ ] **`apps/handlers/persistence/` and `apps/handlers/trigger/` are empty.** Only
  `__init__.py` in each, no callers. Scaffolding that outlived its purpose. Removal is the
  house-rule `.archive/` move, not a delete — needs a moment's care, so logged not done.
- [ ] **DPLAN-0138 inbox backdoor classes still open** — ad-hoc direct inbox writes and the
  `_deliver_via_reply_path()` bypass (no lock, no notification). Carried forward, unchanged
  this session.

### Resolved

- [x] **A help flag after the first argument was discarded and the command RAN**
  (S141, seedgo `help_flag_safety`, DPLAN-0291 rule E) — all three modules gated help at
  `args[0]` only, scoring 0/100 on the standard and 97% overall. Not a regression: the
  standard shipped the same day, recalibrated after @api proved router normalisation
  insufficient (the standalone `__main__` path calls `handle_command` with raw argv and
  never touches the router). On a messaging branch this was the `rm` class @drone hit:
  `dispatch @target "Subject" "Body" --help` fell through to `_orchestrate_dispatch_send`
  and would have **sent the mail and woken the branch** it was asked to describe. `email`,
  `close all` and `reply` had the same shape against the mailbox. Fix is a local
  `apps/handlers/cli/help_flags.py` — `wants_help()`, a pure predicate scanning the whole
  sequence: `--help`/`-h` by **exact** match anywhere, bare `help` only at position 0
  (none of the three modules owns a `help` verb). Exact match is what keeps real mail
  intact — a body reading "run --help for usage" arrives as one quoted argument and still
  sends; a body that is *exactly* `--help` explains instead, which is the
  explain-over-execute ruling on nonsense input. 21 tests, 8 red-first, each asserting
  help printed **and** the send/wake target never called — asserting only the first would
  pass on code that explains itself after sending. Live-proven against a nonexistent
  target so a failed guard could not wake anyone: both probes printed help, exit 0, and
  left **no sent record**; the control send with `--help` inside a longer body delivered
  normally. Same pattern and same reasoning as @memory, @trigger and @drone.
- [x] **The dispatch footer told APLAN owners to close a standing record** (S141, mail
  a119ec12) — `footer.py`'s checklist is appended to every outgoing mail and said
  "CLOSE YOUR PLAN → drone @flow close", while the APLAN template says living documents
  are rarely closed. Both instructions arrived in the *same* dispatch for every branch in
  the audit round. Measured cost (@devpulse, DPLAN-0291 closeout): 4 branches stopped to
  ask which rule won, and @api closed its living audit doc the day it was created —
  findings archived, restored manually. I had assumed this banner was @hooks' (S129
  precedent, where a footer attributed to me lived in their loader) and checked before
  building: it is mine, `footer.py:27`. Of @devpulse's two options I took the reword
  rather than plan-type-aware injection, because this footer is appended to *every* mail
  and has no plan context to read a prefix from — the wording itself has to carry the
  exception. Now: "FPLAN/PPLAN only, never the master. APLANs STAY OPEN." Footer 1.2.0,
  1 red-first test asserting the exception is on the close line itself.
- [x] **`help_flags.py` needs a documented `json_structure` bypass** (S141) — the standard
  requires a `json_handler` import and a `log_operation()` call in every handler. This one
  is deliberately pure: it runs as the first statement in all three `handle_command`s, so
  logging there would make the help gate depend on the JSON layer it must run *ahead of*,
  and would write a line per CLI invocation for a non-event. All three peer branches hit
  this identically and bypassed it the same day. Added **with** the file and measured live
  (99% off / 100% on), so it is not a future prune candidate — the opposite of the 34 dead
  rules removed in S139.
- [x] **`drone @ai_mail email` with no args hung for 30 seconds** (S139) — found by running
  it. Interactive mode is a human path, and under drone the routed subprocess inherits an
  **open but silent** stdin pipe, so `input()` never raises `EOFError`; it blocks until
  drone's 30s routing timeout kills the command, exit 1. The existing handler already caught
  `EOFError` on every prompt and that was never going to help: once you are waiting on the
  first read, "no input yet" and "no input ever" are indistinguishable. Guard is
  `sys.stdin.isatty()`, checked before the first prompt, in **both** halves —
  `send.collect_interactive_input()` refuses, and `email_send._send_interactive()` refuses
  ahead of it so the 17-branch listing never prints and the exit code is 2 instead of a
  plain cancel. Live: 30s/exit 1 -> 2s/exit 2 with usage. 3 tests (1 red-first), and the two
  pre-existing `_send_interactive` tests went red on the guard and now pin `isatty` True —
  they would otherwise have passed without reaching the path they are named for.
- [x] **Error-dispatch replies routed to the dispatcher, not the sender in the From line**
  (S139) — reported by @drone via @devpulse, mail c4d41074. `build_error_report()` set
  `from: "@ai_mail"` and `reply_to: "@devpulse"`, and `reply.py` routes to
  `reply_to or from`, so a reply to `[ERROR] Send failed to ...` left the system mailbox
  that raised it. **My own suite asserted the bug** — `test_error_dispatch.py:39` pinned
  `reply_to == "@devpulse"` as correct, which is the third time this branch has recorded a
  test named after behaviour instead of contract (learning 71). Replacement tests assert
  the contract: `reply_to == from`, whatever From says. Live before/after in @drone's inbox:
  08:23:38 `reply_to=@devpulse`, 08:30:44 `reply_to=@ai_mail`.
- [x] **34 dead bypass rules removed, 51 -> 17** (S139) — see the table below. Score is 100%
  before and after the prune, which is the proof that nothing removed was suppressing.
- [x] **Two surviving bypass rules under-described what they suppress** (S139) —
  `dispatch_monitor.py`/`handlers` named only the @drone broker import and has silently been
  covering a second one since, `hooks.apps.modules.sandbox` at line 66 (the srt sandbox
  wrap). A file-scoped rule widens itself every time the file gains an import. Reason
  rewritten to name both. `inbox_ops.py`/`deep_nesting` claimed `load_inbox()` is depth 4;
  the checker reports depth 5 — the code drifted a level deeper than its own exception said.
- [x] **README drift** (S139) — claimed a live `dashboard_sync.py` (the file is
  `dashboard_sync(disabled).py`); omitted `verified_caller.py`, the handler that holds the
  privilege rail; omitted the `json/` shim and so implied a duplicate `json_handler`; listed
  a `test_dispatch_watchdog.py` that does not exist; test count 1034/1048 -> 1053.

### Bypass prune — how each class was proven dead

Method: empty the registry, run **both** lanes, diff. Audit lane = `audit aipass @ai_mail
--full` (walks `apps/`, 44 standards). Checklist lane = `checklist <file>` per file, which
is what the PostToolUse hook runs on every edit (32 standards). @seedgo's rule was that only
"file does not exist" is safe without measurement; everything else got measured.

| Class | n | Cause — verified, not inferred |
|---|---|---|
| `handlers`, same-branch | 12 | Standard now flags only **cross-branch** imports and handler→modules. The `find_repo_root` imports the reasons describe are still in the code, greppable, and now pass. All 3 surviving `handlers` rules are cross-branch. |
| `documentation` | 8 | Multiline-signature AST miss fixed upstream. Signatures unchanged on disk (`batch_close` still multiline + docstring) and the standard now passes them. |
| `deep_nesting`, depth 4 | 8 | Limit is now 5. Every live violation is depth 5+; every removed rule names only depth-4 functions. |
| `naming`, local variables | 5 | Plain locals no longer read as module constants. Lazy-import **function references** still are, so those 4 rules stayed live. |
| `modules` | 1 | A helper module without `handle_command()` no longer violates. |
| file gone | 1 | `apps/handlers/email/identity.py` — absent from the tree, no archive copy, zero references. The one free class. |

**Zero `tests/*` rules in this registry**, so the false-dead trap that caught @seedgo 5 times
in 6 had nothing to bite here. The two lanes returned the same verdict on all 51 rules
(checklist-only live set: empty). That is a fact about this registry and must not be
generalised to a branch that carries `tests/*` rules.

## What Needs Doing

### @ai_mail to handle (dispatch)
- [ ] Per-subcommand help for the email module's six subcommands — the `subcommand_help`
  standard will not ask for it, so it needs doing on purpose.
- [ ] Add `--from` to the `email --help` FLAGS block; drop the model version numbers from
  `--model` help and describe the tier instead.
- [ ] Reword the `dispatch wake` failure line so it stops claiming the steps are above it.
- [ ] Decide `dispatch status`: name the direction, or include received dispatches.
- [ ] Archive `apps/handlers/persistence/` and `apps/handlers/trigger/` once their emptiness
  is confirmed against every importer.

### @seedgo to handle
- [ ] `cli` standard fires on `apps/handlers/__init__.py` in the checklist lane — a package
  init cannot implement `--help`.
- [ ] The checklist lane checks `name(disabled).py` files. The house rule mandates that
  naming instead of deletion, so this is permanent noise in **every** branch that complies.

### devpulse to handle
- [ ] Nothing blocking from this branch. One data point for the round: the 51 -> 17 prune
  here is safe because the registry has no `tests/*` rules, which is the opposite of the
  wave-1 situation you flagged. The distinguishing question for any branch's prune is
  "does the registry contain `tests/*` rules?", not "how many rules were removed?".

### Tracked elsewhere
- DPLAN-0138 — inbox backdoor write paths.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Fix round to 100 (dispatch 9cbc0121) — `help_flag_safety` 0/100 on 3 modules | Fixed. 97% -> **100%**, standard 0 -> **100**. Tests 1053 -> 1074 (8 red-first). New `handlers/cli/help_flags.py` + 1 documented bypass. Live-proven against a nonexistent target; no mail sent, no branch woken |
| 2026-08-13 | Mail a119ec12 (@devpulse) — dispatch footer CLOSE-YOUR-PLAN vs APLAN convention | Mine, confirmed at `footer.py:27` before building (I had guessed @hooks — wrong, and S129 is why I checked). Reworded, footer 1.2.0, 1 red-first test |
| 2026-08-13 | Fleet audit round wave 3 (DPLAN-0291, dispatch 5465b3f0) | YELLOW — 1053 tests, seedgo 100% (99% bypass-off), 2 defects fixed and live-proven, 34 bypass rules pruned two-lane, 9 open items |
| 2026-08-13 | Mail c4d41074 (@devpulse, found by @drone) — error-dispatch reply routing | Confirmed and fixed. Live before/after in @drone's inbox. Two probe reports left in their inbox by this audit (08:23, 08:30) — flagged in the reply |
| 2026-08-12 | Mail 49df25ad (@devpulse) — Phase 5b accepted, committed d329ae0d | Closed. REPLIES ONLY confirmed as the permanent cross-project comms model |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round), DPLAN-0288 (spoof hole), DPLAN-0138
  (inbox backdoors), DPLAN-0287 (scheduled wake lane)
- **Related FPLANs:** FPLAN-0401 (admin lane + cross-project bridge, phases 1-5b),
  FPLAN-0398 (notification feed), FPLAN-0389 (upsert_key)
- **Owner branch:** @ai_mail
- **Seedgo:** `drone @seedgo audit aipass @ai_mail`

## Notes

**S139 (2026-08-13):** First full audit. The theme is that this branch's headline numbers
were clean while two real defects sat underneath them, and neither number was lying — they
were measuring things that could not see the defects. 1048 tests passed while
`drone @ai_mail email` blocked for thirty seconds, because no test runs the command; the
suite mocks `collect_interactive_input` on both sides of it. And the suite was green partly
*because* it asserted the reply-routing bug: a test named after what the code did rather
than what it owed. That is learning 71 for the third time in this branch, but the first time
the discovery route was "run the thing" rather than "change the code and watch a test go
red". A live command sweep is not redundant with a green suite; it is the only thing that
sees what the suite never calls.

Second note, on the bypass prune. Going 51 -> 17 is a big cut on the same signal wave 1 got
burned by, so the number is not the argument — the causes are. Each removed class has a
mechanism behind it (`handlers` narrowed to cross-branch, `deep_nesting` limit moved 4 -> 5,
the documentation AST miss fixed), verified by checking that the code the reason describes is
still there and now passes, rather than by observing that a violation failed to appear. The
one thing that made this measurement easy is the one thing that does not generalise: this
registry has no `tests/*` rules at all. On a registry that has them, this exact method run
audit-lane-only would still be wrong.

Third, small but worth keeping: a file-scoped bypass rule silently absorbs new violations in
its file. `dispatch_monitor.py`'s `handlers` rule was written for one cross-branch import and
has since been covering a second, undocumented one. The rule never changed; the file did.

## Listen (TTS-friendly summary)

Ai mail is healthy but this audit is marked yellow rather than green, because running the
commands found two real problems that every number on the dashboard said were not there.

All one thousand and fifty three tests pass, the branch scores one hundred percent against
forty four standards, there are no type errors, and every public function is covered. Forty
one commands were run live this morning, twelve of them error paths, and the exit codes
behaved correctly on all of them. Four command surfaces were deliberately left alone,
because running them for real would broadcast to seventeen branches, spawn an agent in
someone else's branch, start a daemon, or close this round's own dispatch mail. The security rail that stops one branch impersonating
another on a wake is working, and it refuses the impersonation before it even looks up the
target, which is the right order.

The first defect: asking to send an email with no arguments made the command hang for thirty
seconds and then die. Sending with no arguments means interactive mode, which expects a
person at a keyboard. When another agent runs it, there is no keyboard, but there is still an
open input pipe that nobody ever writes to, so the code sat waiting for a person who does not
exist until the router timed it out. The code already handled the case where input ends, and
that was never going to help, because waiting forever and ending are not the same thing. It
now checks for a terminal before it asks the first question, and refuses in two seconds with
a usage line instead.

The second defect was reported by drone yesterday. When a send fails, ai mail automatically
files an error report, and that report said it came from ai mail but told replies to go to
devpulse instead. So drone replied to a message from ai mail and the answer landed on someone
else. What makes this one worth remembering is that ai mail's own test suite asserted the bug
as correct behaviour. The test was named after what the code did rather than what the code
owed, so a thousand passing tests sat on top of the defect and confirmed it. That is the third
time this branch has recorded that exact shape.

Both are fixed and both were proven by running them, not just by tests. The error report fix
was checked by looking in drone's actual inbox: the report from eight twenty three routes to
devpulse, the one from eight thirty routes back to ai mail.

The bypass registry was cut from fifty one exceptions to seventeen. Every removed rule was
measured in both places standards actually run, not just one, and the score is one hundred
percent before and after. Each group had a real reason for dying, such as a standard that
narrowed its scope or a detector bug that got fixed upstream. One important caveat for the
rest of the fleet: this was safe here because this registry has no rules pointing at test
files, and rules pointing at test files are exactly what fooled seedgo five times out of six.
The right question for any other branch is not how many rules were removed, it is whether the
registry has test file rules in it.

Nine items are open and none of them block anything. The largest is that six subcommands all
print the same help text, so several working features are documented nowhere a user would
look. Two more belong to seedgo rather than to ai mail: a standard that asks a package init
file to implement a help flag, and the file checker still checking files that have been
deliberately disabled, which affects every branch that follows the house rule.

Health is yellow. Last verified August thirteenth.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
