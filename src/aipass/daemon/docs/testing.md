[<- Back to the README](../README.md)

# Testing

How the daemon test suite is run, and the two hard rules — no writes into another citizen's tree, no host state changes — that keep a mutation run from doing real damage.

---

## Running the suite

The live count is whatever pytest reports. Two runs, and they must agree:

```
.venv/bin/python -m pytest src/aipass/daemon -c pyproject.toml --rootdir=. -q   # the CI shape, from the repo root
python -m pytest -q                                                             # from the branch directory
```

- A test that exercises a name gate pins the roster it resolves against. The dev machine's
  registry is not a fixture: a CI checkout has no registry, so `activity_collector.get_branch_paths`
  answers `[]` there.
- Every `tests/test_*.py` file runs in CI. The recovery lane's own pins (`recovery.py`) are held
  outside `tests/`, because a new test file needs the test-write gate's permission; they come in
  when the gate allows the file.
- A parked suite is named here, with its reason and what has to be true to un-park it: a silently
  skipped suite reads as coverage that does not exist.

## The seals

`tests/conftest.py` holds one autouse seal per route by which a test could reach live state.
Each sits on the seam, session-wide, not on the row that first reached it: the next test to use
the route has no reason to know the seal exists.

| seal | seam | what it keeps the suite out of |
|---|---|---|
| `_seal_timer_host_state` | `timer_install._run_systemctl`, `_UNIT_DIR`, `_STATE_DIR` | the user's systemd and `~/.aipass` |
| `_seal_runstate_file` | `runstate.RUNSTATE_FILE` | the live `daemon_json/daemon_runstate.json` |
| `_seal_branch_wake_prompt` | `recovery._branch_daemon_dir` | every other citizen's `.daemon/` |
| `_seal_command_launcher` | `command_job.LAUNCHER` | the real drone, and real mail |

## The suite may not write into another citizen's tree

A fire writes the wake transcript twice: to the daemon's own `daemon_json` and to the owner's
`.daemon/last_wake_prompt.txt`, which `_branch_daemon_dir` resolves through
`discovery.active_citizens()` to the **real** branch tree. Real citizen addresses (`@commons`,
`@backup`, `@vera`, `@devpulse`, `@daemon`, `@seedgo`, `@baud`, `@flow`, `@api`) appear as
fixture owners, so `_seal_branch_wake_prompt` redirects every branch-side write to a tmp
directory. It returns that directory rather than `None`, so a test can still assert the
branch-side write *happened*; only its destination changes.

**The sentinel tells a test from a real fire, precisely.** The live scheduler runs while the
suite runs — a ~2 minute timer against a ~30 second suite — and a genuine fire legitimately
rewrites a branch's transcript. But `record_wake_prompt` always writes **both** destinations
with the same text, and the suite's `daemon_json` copy is sealed to tmp. So a branch file that
changed *and* now matches `daemon_json` is a real tick from another process; one that changed
and does not match is this suite. That discriminator lets the sentinel be strict without crying
wolf.

## The suite may not move host state

A test may touch the real thing, but it never disables a process: it leaves the host exactly as
it found it.

`tests/test_cli_routing.py` runs the real router over every verb in `GATED_VERBS`, and two of
those verbs are `install-timer` and `uninstall-timer`. The argument gate's refusal comes first, so
the verb never runs. Without the gate (a red-first run, or any mutation run that disables it)
`_install()` and `_uninstall()` would execute, and an uninstalled timer stops every tick, so no
MISSED line can be written either. The seal is what stands between that and the user's systemd.

**The seal.** `_seal_timer_host_state` is **autouse, unconditional**, and patches the three seams
by which `timer_install` can change host state:

| seam | what it covers |
|---|---|
| `_run_systemctl` | every stop / disable / enable / start / daemon-reload |
| `_UNIT_DIR` | where unit files are copied to and unlinked from |
| `_STATE_DIR` | the `~/.aipass` mkdir |

It is session-wide rather than on the two gated verbs, because the defect is not *"two rows reach
systemd"* — it is *"a test can reach systemd at all"*, and the next verb added to `GATED_VERBS`
would inherit the hole silently. Every test runs with `_run_systemctl` as a
`MagicMock(return_value=True)` (the fixture yields it, so a test can read its calls) and
`_UNIT_DIR` / `_STATE_DIR` under that test's own `tmp_path`. The one exception is a test that asks
for `systemctl_on_path` (`test_timer_install.py`): it keeps the real wrapper, and the seal moves
the other door instead. PATH becomes an empty directory, so the only `systemctl` the wrapper can
find is the stub that fixture lays. The live host's `systemctl` is unreachable either way.

**The sentinel.** `_host_state_sentinel` (session-scoped, autouse) snapshots the live timer at
session start and asserts it unchanged at session end. It is the backstop for a route nobody has
thought of yet — a test that shells `drone @daemon uninstall-timer`, a helper calling `systemctl`
directly. It does **not** restore: a sentinel that quietly put the timer back would hide the
defect it exists to report. A suite cannot pass and take the scheduler down in the same run.
`_runstate_sentinel` fails a session that put fixture rows into the live runstate (it compares
job keys, not bytes, because a real tick mid-session legitimately rewrites real rows), and
`_branch_wake_prompt_sentinel` for every citizen's wake transcript.

## Making a mutation run safe

A mutation run is the dangerous case, because the whole point of one is to disable a guard and see
what still passes — and the guard being disabled is often the one holding the verb back.

- **A harness that shells out to `pytest` is safe with nothing to remember.** The seals are
  autouse and apply to every test (function-scoped, one fresh `tmp_path` each), so every
  subprocess run that collects from `tests/` inherits them.
- **A harness that imports `timer_install` and calls a verb directly is not.** It bypasses the
  conftest entirely and must patch the three seams itself (`_run_systemctl`, `_UNIT_DIR`,
  `_STATE_DIR`), as `_seal_timer_host_state` does. A harness that replaces the gate call and runs
  the pins in-process without them uninstalls the live scheduler.
- **Choose each mutation so the assertion is exercised without the destructive path running.**
  Remove the gate patch to prove the verb executes, disable `shutil.copy2` to prove the
  sealed-dir assertion is live, redirect the test's `live_dir` to prove the live comparison bites,
  doctor the sentinel's end reading to prove the session fails. Never re-run the unsealed world to
  prove it dangerous: repeating the damage is not evidence, it is a second outage.
