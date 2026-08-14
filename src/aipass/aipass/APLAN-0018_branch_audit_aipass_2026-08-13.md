# APLAN-0018: Branch audit - aipass

Tag: audit, branch-audit, aipass

> Branch audit @aipass -- living document tracking health, issues, improvements

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
| **Last verified** | 2026-08-13 (S112, evening) |
| **Open items** | 4 (1 mine, 1 other branch, 2 tracked//known) |
| **Tests** | 1,024 pass, 0 fail |
| **Seedgo** | **100% overall, help_flag_safety 100%** (0 type errors, ruff clean) |
| **Bypass entries** | 27 -- pruned from 85, every survivor lane-measured |
| **CLI score** | Nav 5/5, Output 5/5 (all 19 probed surfaces exit-correct) |

GREEN as of S112. Both YELLOW causes are closed: the help-probe write path is
fixed at every door (router AND the standalone `__main__`), and the bypass file
is pruned 85 -> 27 against a two-lane control.

## Current State

### Summary
- The concierge CLI + its own maintainer. Ships as the `aipass` binary on PATH,
  NOT via `drone @aipass` (drone cannot resolve it).
- 28 files checked, 5,295 lines across modules, 74/74 public functions tested.
- Version 2.7.16, read live from pyproject.toml (no stale metadata).
- `aipass doctor`: 33 pass, 10 warnings, 0 errors.

### Architecture
Thin entry-point router (`apps/aipass.py`) auto-discovers `apps/modules/*.py`
exposing `handle_command()`; modules delegate file work to `apps/handlers/`.
14 modules (doctor, init_flow, install, help_chat, new_project, adopt, trust,
profile, read, handoff, feedback + 2 internal `_doctor_*`).

### What Works Well
- Every documented README command runs; all 19 probed surfaces return correct
  exit codes (0 on success, 1 only on genuine unknown-command).
- Version resolution is self-truing from the repo pyproject (L103 fix holding).
- Test coverage: 74/74 public functions mapped, suite runs in ~40s.
- `@drone`-target misuse (`aipass @drone`) gives a correct, friendly redirect.

## Issues Found

### Open

- [ ] **cross-os gap #9 (owner: aipass)** -- pre-flight prints real exceptions
      as "Unknown command", which hid gap #1 for hours. Local todo #9.

### Resolved in S112 (2026-08-13, evening)

- [x] **The standalone door: `init_flow.py agent --help` would have created an
      agent named `--help`** (S112). My S111 router fix was correct but not
      sufficient -- `init_flow.py` ends in
      `handle_command("init", sys.argv[1:])`, so a direct run never touches the
      router. Found by @seedgo's help_flag_safety checker after @api proved the
      router-normalises exemption wrong; my score had dropped 100 -> 92.
      Fixed with a pure `wants_help()` predicate
      (`apps/handlers/help_flag.py`) called INSIDE `handle_command` after the
      ownership check. CLASS SWEEP: all **15 gates across 13 modules** carried
      the same `args[0]`-only shape and were all rewritten, not just the named
      one. Live-proven with seedgo's exact repro, both spellings, both
      invocation forms -- prints help, creates nothing.
- [x] **Bypass pruned 85 -> 27** (S112) -- see the two-lane note below. Closes
      todo #10.
- [x] **Branch-prompt line corrected** (S112) -- the "no bypass.json edits"
      line contradicted Patrick's S46 ruling; @devpulse ruled S46 stands and
      the prompt line was simply wrong. Rewritten citing S46, with the
      two-lane measurement requirement attached. Closes todo #8.

### Resolved in S111 (2026-08-13, morning)

- [x] ~~**Dead bypass rules**~~ -- resolved in S112. **Two corrections to my own
      S111 figures, both from reading a truncated list or measuring one lane:**
      the total was 84, not 82; live was 18, not 15; and dead-in-both-lanes is
      50, not 59. S111 said seedgo's advisory under-reports at 41 vs my 59 --
      the under-report is real and @seedgo has since fixed the advisory, but my
      59 was itself an over-count.
- [ ] **`doctor.py` (1,239 lines) and `init_flow.py` (1,196 lines) are the two
      largest modules** and both carry a `modules` size bypass. Load-bearing
      today, but they are the branch's split candidates. (Still open.)

### Resolved

- [x] **Trailing `--help` executed the verb it asked about** (S111, 2026-08-13)
      -- root cause `apps/aipass.py:276`: the guard inspected only
      `remaining[0]`, so `--help` in any later position fell through to
      dispatch. Live-proven damage before the fix:
      `aipass trust <dir> --help` ran the enrollment write,
      `aipass revoke <path> --help` ran the revoke.
      Code-proven and deliberately NOT fired: `aipass init agent --help` would
      `drone @spawn create` an agent literally named `--help`;
      `aipass init update --help` would write a real scaffold refresh into cwd;
      `aipass install run --help` / `aipass init run --help` entered the
      install/init flow. Fixed with a position-free guard, 4 red-first tests,
      verified live on all six shapes. Free-text help unaffected.
- [x] **README drift** (S111) -- test count 977 -> 981, `aipass trust prune`
      shipped in the CLI help but was absent from the README, Last Updated
      stamp refreshed.

## What Needs Doing

### @aipass to handle (dispatch)

- [x] ~~Prune the bypass rules~~ -- done S112, 85 -> 27, two-lane control.
- [ ] cross-os gap #9 -- make pre-flight print real exceptions instead of
      "Unknown command". **The only open item I own.**

### devpulse to handle

- [x] ~~Ruling on the bypass-edit contradiction (todo #8)~~ -- RULED
      2026-08-13: S46 stands, the branch-prompt line was wrong. Line rewritten
      citing S46; todo #8 closed.
- [x] ~~@seedgo advisory under-reports~~ -- routed to @seedgo, and the advisory
      now ships the warning + a "measure first, this is a place to start
      looking, not a finding" caveat. Confirmed live in today's audit output.
      Worth noting the fix ALSO corrected me: its new checklist-lane warning is
      what caught 9 rules my own single-lane measurement would have deleted.
- [x] ~~@skills -- interactive-session root cause~~ -- routed to @skills with
      my evidence; devpulse confirmed nothing further owed from me.

### Tracked elsewhere

- [ ] Wifi wlan0 drops, deferred by Patrick -- 3 orphan NM profiles still live
      (verified 2026-08-13: `Wu-Tang LAN`, `Wu-Tang LAN 1`, `Wu-Tang LAN 2`;
      active is `Wu-Tang LAN 3`). Local todo #7.
- [ ] `doctor` structure warnings for 6 `projects/*` agents (placement
      convention) -- project agents, not my lane.

## FIRST-CLASS ITEM: why my wakes land interactive

**Verdict: the premise is inverted. My wake path is provably headless. The
interactive session is created by a different system, and it BLOCKS my wake.**

Owner: **@skills**, file
`src/aipass/skills/lib/telegram/apps/handlers/base_bot.py`. Not my tree, and
not @ai_mail's.

Evidence, verified by me directly (not just the investigating sub-agent):

1. `ai_mail/apps/handlers/dispatch/wake.py:777-805` -- BOTH spawn branches
   build `claude ... -p ...  --output-format json`. Headless, always.
2. The only interactive lane is `_spawn_manager_interactive`, gated on
   `citizen_class == "manager"` AND `sender == "@daemon"`. My passport says
   `aipass_framework` (shared with 7+ other branches) and I have no
   `.daemon/schedule.json`. I never reach it.
3. `base_bot.py:1867` -- `branch = branch_arg.strip().lstrip("@").lower() or
   "aipass"`. A **bare `/start` on the Telegram control bot defaults to
   @aipass**, then lines 1890-1896 run
   `tmux new-session -d` + `send-keys "claude -c || claude"` -- a bare
   `claude`, **no `-p`**, detached in my directory with nobody attached.
   `/start` is the button every Telegram client sends when a chat is opened.
4. That empty session then trips the occupancy gate at `wake.py:741-747`:
   `BLOCKED @aipass -- interactive session`.

Log proof (`system_logs/`): 6 `Control /start` events naming
`session 'aipass-aipass'` in my path (2026-07-29, 08-02, 08-07 x2, 08-08,
08-11), each followed by `[wake] BLOCKED @aipass` (08-02 19:29, 08-04 19:17,
08-08 23:39, 23:49). Fleet block tally: @devpulse 102, @vera 15, @aipass 10,
@trigger 4, @drone 3, @prax 1, @daemon 1, @baud 1.

So the empty interactive sessions Patrick keeps killing are the Telegram
control bot's `/start` default, not a broken wake. This session itself was
woken headless by `dispatch-aipass.service`.

**Honest caveat:** two early blocks (2026-07-18 14:22/14:31 and 2026-07-19
00:21) predate the control-verb mechanism in the bot log and I cannot attribute
them. Most likely a manual `claude` run in the directory; no evidence survives
to name it, and I am not inventing an author.

## Dispatch Log

| Date | Action | Result |
|------|--------|--------|
| 2026-08-13 | Full self-audit (fleet round, DPLAN-0291) | YELLOW -- 981 tests green, seedgo 100/97, 1 write-bug found + fixed |
| 2026-08-13 | Root-cause: interactive wakes | Premise inverted -- owner is @skills `/start` default; routed to @skills by devpulse, nothing further owed |
| 2026-08-13 | Round-to-100 (S112) | GREEN -- 1,024 green, overall 100, help_flag_safety 100, 15 gates swept, bypass 85 -> 27 |

## Relationships
- **Related DPLANs:** DPLAN-0291 (fleet audit round)
- **Related FPLANs:** FPLAN-0382 (bypass sweep, w1 -- my one function-scoped rule)
- **Owner branch:** @aipass
- **Seedgo:** `drone @seedgo audit aipass @aipass`

## Notes

**S112 (2026-08-13, evening):** Round-to-100 pass. Overall 99 -> 100,
help_flag_safety 92 -> 100, tests 981 -> 1,024 (+43), ruff clean.

*The class sweep mattered more than the named finding.* @seedgo and @devpulse
both named ONE module (`init_flow.py`). Grepping the class found the
`args[0]`-only shape in **15 gates across 13 modules** -- every module I own.
`init_flow` was simply the only one whose standalone `__main__` made it
reachable without the router, so it was the only one the checker could see.
The other 14 were one `__main__` block away from the same bug.

*Two-lane bypass measurement -- the method, and why one lane is not enough.*
@seedgo's advisory now warns that the audit lane walks `apps/` and never
`tests/`, so a `tests/*` rule reads dead there while still suppressing findings
in the checklist lane the edit hook runs. That warning was correct and it
changed the answer: I ran the audit-lane control (`audit_branch` with
`bypass_rules=[]`) AND a checklist-lane control (`drone @seedgo checklist`
per-directory with the bypass array emptied, restored in a `finally`). The
checklist lane produced 31 FAIL pairs and **saved 9 rules from wrongful
deletion** that the audit lane had called dead -- 2 `permission_flags` rules on
`tests/`, and 7 rules across `shared/json_handler.py`, `shared/json_ops.py`,
`shared/registry_discovery.py`. Had I pruned on S111's single-lane evidence I
would have deleted all 9. Final: 85 -> 27, score unchanged at 100% (which is
itself the proof the 58 removed rules suppressed nothing).

*A vacuous control that looked clean.* My first checklist sweep ran
`checklist src/aipass/aipass` and reported **0** FAIL pairs -- I nearly took
that as "everything is dead, delete freely". The directory mode does not
recurse and the branch root holds no `.py` files, so it had checked nothing.
The tell was that it contradicted a single-file run minutes earlier. A control
that returns a clean sweep is exactly the one to re-run before trusting.

*Prax doctrine held.* Every canary ran with `subprocess.run/Popen`,
`update_project`, `adopt_project`, `create_project`, `enroll` and `revoke`
stubbed BEFORE the red run, so 14 failing tests recorded the attempted action
without a single real spawn, scaffold or enrollment. The `trust` canary uses a
real `tmp_path` directory with a real `.aipass/hooks.json` so the probe
actually reaches the enrollment call site -- an earlier version passed for the
wrong reason (the path did not exist) and proved nothing.

**S111 (2026-08-13):** Full self-audit, fleet round wave 8.

Method for the two-number seedgo score, since there is no `--no-bypass` flag:
called `audit_branch(branch, [])` directly (non-incremental, so no cache
pollution) via `discover_branches()`. That doubles as the control rule C asks
for -- the score moved 100% -> 97%, proving the lane really does read the
registry, so a rule showing no violation with bypasses off is genuinely inert.
Per-rule mapping then classified all 82 rules.

Rule E check (all three `--help` shapes): `aipass --help` and
`aipass <verb> --help` were always safe; the third shape,
`aipass <verb> <arg> --help`, was NOT -- it executed the verb. Found by
code-reading the write paths first, then proving it live only against
non-existent paths so nothing was actually enrolled or revoked. This is the
worst variant to have as the concierge humans type at, which is why I fixed it
rather than logging it.

Near-miss worth recording: my first exit-code sweep piped through `head`, and
SIGPIPE made `aipass --help`, `profile`, `trust` and `read` all look like they
exited 1. Re-measured untruncated -- all 0. I would have filed four false
findings.

Second near-miss: `nmcli ... | head -12` truncated the profile list and made
the 3 orphan wifi profiles look cleaned up. Full grep proved all three still
live; todo #7 stands as written.

## Listen (TTS-friendly summary)

Updated the evening of August thirteenth. The aipass branch is now green. All
one thousand and twenty four tests pass, the seedgo audit scores one hundred
percent overall, and the help flag safety standard is back to one hundred after
dropping to ninety two this morning.

This evening closed the hole that this morning's fix missed. I had guarded the
router, but the init flow module can also be run directly as a file, and that
path hands its arguments straight to the module without ever touching the
router. Through that door, asking for help on the agent command would have
created an agent literally named dash dash help. Seedgo caught it, and it had
been hidden behind an exemption seedgo itself had shipped that morning.

The important part was not the one module I was sent. I grepped for the same
shape across everything I own and found it in fifteen gates across thirteen
modules. Only the init flow one was reachable without the router, so it was the
only one anybody could see. The rest were one line away from the same bug. All
fifteen now go through a single shared predicate that treats a help flag as a
question no matter where it appears.

I also pruned my bypass file from eighty five rules down to twenty seven. That
needed two separate control runs, not one. Seedgo had warned that its audit
lane never looks at the tests folder, so a rule can look dead there while it is
still doing real work in the checklist lane that the edit hook runs. That
warning was right, and it saved nine rules I would otherwise have deleted. My
own numbers from this morning were wrong in two places and I have corrected
them in this document rather than quietly restating them.

One item stays open and it is mine: the cross platform pre flight prints real
exceptions as unknown command, which once hid another gap for hours.

The important find this session was a real bug in my own command line. Asking
for help could perform an action. If you typed aipass trust, then a directory,
then dash dash help, it did not print help. It enrolled that directory. The
same shape would have created an agent literally named dash dash help, or
written a scaffold refresh into whatever folder you were standing in. The guard
only looked at the first argument, so a help flag anywhere later slipped
through to the real command. I fixed it, wrote four tests that failed first,
and proved all six dangerous shapes now print help instead of acting. For the
front door that humans type at, that is the one bug you least want.

On the question devpulse asked, about my wakes opening interactive sessions:
the premise turns out to be backwards. My wake is always headless. The empty
sessions Patrick keeps killing come from the Telegram control bot, where a bare
slash start command defaults to my branch and opens a plain claude session in
my directory. That session then blocks the real headless wake. The owner is the
skills branch, not mine, and not mail.

Two things need a decision from devpulse. First, my branch prompt forbids
editing my own bypass file while an earlier ruling from Patrick explicitly
allows it, so sixty seven dead bypass rules are still sitting there unpruned.
Second, seedgo's own list of dead bypass rules under reports. It found forty
one and named only test files. A control run proves fifty nine, including
twenty two that are not tests.

Last verified 2026-08-13.

---
*Created: 2026-08-13*
*Updated: 2026-08-13*
