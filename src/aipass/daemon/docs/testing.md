# Testing

How the daemon test suite is run, and the two hard rules — no writes into another citizen's tree, no host state changes — that keep a mutation run from doing real damage.

[<- daemon README](../README.md)

---

## Test Suite

The live count is whatever pytest reports; every number on this page is a dated measurement kept
for its story, not a claim about today. Two runs, and they must agree:

```
.venv/bin/python -m pytest src/aipass/daemon -c pyproject.toml --rootdir=. -q   # the CI shape, from the repo root
python -m pytest -q                                                             # from the branch directory
```

**2026-09-11 (FPLAN-0543, DPLAN-0338 wave 1a):** 616 → **698 passed** from both rootdirs. The
82 new cases pin command jobs: validation in `test_discovery.py`, the subprocess and fire path and
the runstate row in `test_run_module.py`, and the queue preview in `test_scheduler_bot.py`. 20 of
20 mutants went red, and each harness restored the tree byte-identical. `tests/conftest.py` gained
`_seal_command_launcher`, an autouse seal on `command_job.LAUNCHER`, so no test can start the
real drone or send a real mail. That seal was not mutation-run: removing it would do exactly that.
The counts below are the 2026-09-08 baseline.

All numbers below re-measured 2026-09-08 (FPLAN-0527), not carried.

- **534 test functions** across 19 test files; parametrization expands these to **598 cases**
  (`.venv/bin/python -m pytest src/aipass/daemon -c pyproject.toml --rootdir=. -q` →
  `598 passed in 25.51s`, 0 failed, 0 skipped; **598 passed in 25.63s** from the branch directory)
- **DPLAN-0332's own 59 pins are NOT in that count.** They are written, green and
  mutation-proved (17/17 red) but parked at `docs.local/pending/test_recovery.py.pending`:
  the test-write gate (the owner, 2026-09-01, DPLAN-0323) refuses new test files and daemon
  cannot flip it. They were not appended into an existing test file instead — the gate names
  that as its deliberate residual, and using it would be routing around a human ruling.
  The ask is with @devpulse.
- Re-run with `activity_collector.get_branch_paths` forced to `[]` — the CI condition, where a
  checkout has no registry — also **596 passed**. Any test that exercises a name gate pins the
  roster it resolves against; the dev machine's registry is not a fixture (learned from CI red
  on b681c085, cured in 5c132a5e)
- 10/10 modules covered — every module under `apps/modules/` is imported by at least one live test file
- **57 of 61 public functions tested** (seedgo's count; was 47/51 before ruling 6 added
  the catch-up, MISSED and slot surfaces, and 54/58 before wave 2b added the argument gate)
- Seedgo audit **100%**, every scored category at 100 including Trinity, with 22 bypass rows
- The bypass list holds **22 rows**. The `apps/daemon_wakeup.py` *encapsulation* row added by
  a6956b0f is **gone** — seedgo cured the derivation (251f2eb9) and Encapsulation now scores 100
  with no row for that file, so it is not needed. The row still present for `daemon_wakeup.py` is
  the long-standing *architecture* one (entry-point script outside the 3-layer structure).
- *Unverified:* the old "99% with the bypass list emptied" figure was not re-measured tonight —
  emptying the list is a seedgo-side change, out of scope for a docs pass.

*Last Updated: 2026-09-15*

## The suite may not write into another citizen's tree

Found by @devpulse on 2026-09-09, not by me: Vera-Studio's live
`.daemon/last_wake_prompt.txt` held exactly the 16 bytes `tend your branch` —
`test_run_blocked_contract.py`'s `_job()` default prompt, mtime 2026-09-08
20:45:18, the minute the daemon suite ran during the PR #759 landing. The path is
`_fire_job` → `recovery.record_wake_prompt` → `_branch_daemon_dir`, which resolves
`@vera` through `discovery.active_citizens()` to the **real** Vera-Studio tree and
writes. The `FakeStatus` seam stops a wake reaching a live tmux; nothing stopped the
transcript reaching a live branch.

**Sealed on the seam, session-wide** (`_seal_branch_wake_prompt`), not on the row that
bit. Nine real citizen emails appear as fixture owners in this suite — `@commons`,
`@backup`, `@vera`, `@devpulse`, `@daemon`, `@seedgo`, `@baud`, `@flow`, `@api` — so a
guard scoped to one test module would have left it open for the tenth. The fixture
returns a tmp directory rather than `None`, so a test can still assert the
branch-side write *happened*; only its destination changes.

**The sentinel tells a test from a real fire, precisely.** The live scheduler runs
while the suite runs — a ~2 minute timer against a ~30 second suite — and a genuine
fire legitimately rewrites a branch's transcript (@vera's did at 07:45:19 on 09-09).
But `record_wake_prompt` always writes **both** destinations with the same text, and
the suite's `daemon_json` copy is sealed to tmp. So a branch file that changed *and*
now matches `daemon_json` is a real tick from another process; one that changed and
does not match is this suite. That discriminator is what lets the sentinel be strict
without crying wolf.

Removing the seal reproduces the exact evidence — `tend your branch` back in Vera's
file — and the sentinel names it, plus a **second** escaped citizen the original
report had not found: `@commons`.

## The suite may not move host state

**The owner's ruling on 2026-09-08 (FPLAN-0524), in their words:** *"tests can't disable processes, they should restore to exact
same state before the test. The test is fine and good that it can enter something."*

**What went wrong.** `tests/test_cli_routing.py` runs the real router over every verb in
`GATED_VERBS`, and two of those verbs are `install-timer` and `uninstall-timer`. With the argument
gate in place the refusal comes first and the verb never runs — so the committed suite was safe.
Without it (a red-first run, or any mutation run that disables the gate) `_install()` and
`_uninstall()` executed against the user's real systemd. `journalctl --user` recorded seven
Started/Stopped pairs across four such runs on 2026-09-07, ending on a **Stop at 11:46:40**.
Nothing ticked for twenty-three hours: `@vera/release-watch` and `@daemon/inbox-sweep` both missed
their windows, and no MISSED line could be written, because writing one takes a tick. The suite
reported `594 passed` every time.

**The seal.** `tests/conftest.py` holds `_seal_timer_host_state` — **autouse, unconditional**,
patching the three seams by which `timer_install` can change host state:

| seam | what it covers |
|---|---|
| `_run_systemctl` | every stop / disable / enable / start / daemon-reload |
| `_UNIT_DIR` | where unit files are copied to and unlinked from |
| `_STATE_DIR` | the `~/.aipass` mkdir |

Session-wide rather than on the two rows that bit, because the defect is not *"two rows reach
systemd"* — it is *"a test can reach systemd at all"*, and the next verb added to `GATED_VERBS`
would inherit the hole silently. `TestRunSystemctl` is unaffected: it binds `_run_systemctl` by
direct import at module load, so it still exercises the real function against a patched
`subprocess.run`.

**The sentinel.** `_host_state_sentinel` (session-scoped, autouse) snapshots the live timer at
session start and asserts it unchanged at session end. It is the backstop for a route nobody has
thought of yet — a test that shells `drone @daemon uninstall-timer`, a helper calling `systemctl`
directly. It does **not** restore: a sentinel that quietly put the timer back would hide the
defect it exists to report. Proven by mutation — with the end-of-session reading doctored to
`active: inactive`, the run reports `14 passed, 1 error`. A suite can no longer pass and take the
scheduler down in the same run.

**If a test must reach the real timer**, it takes the `timer_host_state` fixture and only that: it
records `is-enabled` / `is-active` / the unit-file list, restores exactly what it recorded in a
`finally`, and then asserts the restore matched. Idempotent by construction — it restores *to a
recorded state* rather than toggling. No test needs it today; it is the contract for the next one.

## Making a mutation run safe

A mutation run is the dangerous case, because the whole point of one is to disable a guard and see
what still passes — and the guard being disabled is often the one holding the verb back.

- **A harness that shells out to `pytest` is safe with nothing to remember.** The seal is autouse
  and session-scoped, so every subprocess run inherits it. This is the shape used for FPLAN-0524's
  own four mutations.
- **A harness that imports `timer_install` and calls a verb directly is not.** It bypasses the
  conftest entirely and must take `timer_host_state`, or patch the three seams itself.
- **Say plainly what changed:** the FPLAN-0492 wave 2b harness (2026-09-07) had neither. It
  replaced the gate call and ran the pins in-process, which is exactly how the scheduler ended up
  uninstalled. The rule above is the line that changes.

Every mutation in FPLAN-0524 was chosen so the assertion is exercised without the destructive path
ever running: the gate patch removed (proves the verb executes), `shutil.copy2` disabled (proves
the sealed-dir assertion is live), the test's `live_dir` redirected (proves the live comparison
bites), and the sentinel's end reading doctored (proves the session fails). The unsealed world was
**not** re-run to prove it dangerous — 2026-09-07's journal already measured that, and repeating
the damage to re-derive a known fact is not evidence, it is a second outage.
