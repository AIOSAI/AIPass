# host_state — did the test put the machine back?

> A test is allowed to reach the real thing. What it is not allowed to do is walk
> away leaving it changed. This rule is about the **restore**, never about the
> reach.

**Scope:** `branch_level` · **Severity:** advisory · **Species:** `SERVICE_CONTROL`,
`PROCESS_SIGNAL`, `HOME_WRITE`, `ENV_MUTATION`, `CWD_CHANGE`, `EFFECTFUL_VERB`,
`FIXTURE_NO_TEARDOWN`

---

## The ruling, first, because this is the part people get backwards

Patrick, 2026-09-08:

> "tests can't disable processes, they should restore to exact same state before
> the test. The test is fine and good that it can enter something."

Read that twice before you read the rest of this page. It is narrower than "do not
touch the host", and the narrowing is the whole rule. A test that starts a timer,
writes a file, sets a variable or drives a real entry point is doing something
useful — often the only thing that proves the behaviour at all. The defect is the
test that changes the machine and leaves it that way.

So: **touching the real thing is allowed. Leaving it changed is the defect.**

## Why this rule exists

@daemon's `tests/test_cli_routing.py` holds `TestUnknownArgumentIsRefused`. It
parametrises over a module-level `GATED_VERBS` list — which contains
`install-timer` and `uninstall-timer` — and drives each verb through the real
router:

```python
@pytest.mark.parametrize("verb", GATED_VERBS)        # holds "uninstall-timer"
def test_a_stray_positional_is_refused(self, verb):
    with patch.object(sys, "argv", ["daemon", verb, "not_a_real_subarg_xyz"]):
        with pytest.raises(SystemExit):
            _daemon_mod.main()          # nothing patched on the effectful seam
```

`sys.argv` is patched. The seam that matters is not. While the refusal gate exists
the verb never runs, so the test looks harmless — and on the day it was written it
was. On any run where the gate is **absent** — a red-first run, and every mutation
run that removes it — `main()` reaches `timer_install.py`, which runs
`systemctl --user stop`, then `disable`, then deletes the unit files.

That happened. As measurement, not anecdote: journalctl shows
`daemon-tick.timer` stopped at 11:46:40 on 2026-09-07 with no restart. No scheduler
tick ran for twenty-three hours. @vera's `release-watch` (10:00) and @daemon's
`inbox-sweep` (09:00) both missed their windows.

The test was not wrong to reach the router. It was wrong to reach it with nothing
patched and nothing put back.

## The six species

Five of them are ordinary, and each is a call in a test that reaches host state
with no restore and no patch on the seam.

**`SERVICE_CONTROL`** — a subprocess call driving a service manager:

```python
subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])   # flagged
```

Read from the first element of a literal argv, or the first word of a literal
command string, matched by basename against a fixed roster of host-control
programs: `systemctl`, `launchctl`, `sc`, `service`, `systemd-run`, `crontab`,
`shutdown`, `reboot`, `halt`, `killall`, `pkill`, `kill`, `update-rc.d`,
`chkconfig`. `os.system` counts as a runner alongside `subprocess`.

**`PROCESS_SIGNAL`** — a signal sent to a process the unit did not start:

```python
os.kill(pid_from_the_lockfile, signal.SIGTERM)                         # flagged
```

Narrow on purpose: `os.kill`, `os.killpg`, `signal.raise_signal` and nothing else.
`handle.terminate()` on a `Popen` the unit itself opened is correct teardown, and
telling the two apart needs the receiver.

**`HOME_WRITE`** — a filesystem mutation that lands under the real home:

```python
(Path.home() / ".config" / "daemon.json").write_text("{}")             # flagged
```

The mutating pathlib methods (`write_text`, `write_bytes`, `mkdir`, `unlink`,
`rmdir`, `touch`, `rename`, `replace`, `chmod`, `symlink_to`, `hardlink_to`) and
the `shutil` mutators (`copy`, `copy2`, `copyfile`, `copytree`, `move`, `rmtree`),
where the destination roots at `Path.home()`, `expanduser`, or a literal starting
with `~`. Reads are not mutations and are not read.

**`ENV_MUTATION`** — a change to the interpreter's environment:

```python
os.environ["AIPASS_BRANCH"] = "daemon"                                 # flagged
```

Assignment and `del` are found structurally, because neither has a call in it to
read. `os.putenv` and `os.environ.pop / setdefault / update / clear` are found by
name. The environment is process-wide, so this outlives the test and every later
test in the session sees it.

**`CWD_CHANGE`** — a working directory the whole process keeps:

```python
os.chdir(some_repo_root)                                               # flagged
```

`os.chdir` moves the process, not the test. A later test resolving a relative path
lands somewhere else.

**`EFFECTFUL_VERB`** — the sixth, and the one that catches the incident. No AST
reader can follow `main()` into `systemctl`; that would be an interpreter, not a
reader. So the dangerous verbs are **derived from the branch's own production**: a
module under the target that reaches host control *and* publishes a
`COMMANDS`-style constant (`COMMANDS`, `HANDLED_COMMANDS`, `VERBS`, `SUBCOMMANDS`)
declares those verbs host-effectful. A unit that feeds one of them to an entry
point (`main`, `handle_command`, `route_command`, `run_cli`, `cli`) with nothing
patched on the seam is flagged, and the finding names the module that made the verb
dangerous:

```python
with patch.object(sys, "argv", ["daemon", "uninstall-timer"]):
    _daemon_mod.main()                                                 # flagged
```

Derived, never listed. A hardcoded roster of verb names would be stale the first
time a branch renamed one, and stale in the silent direction.

The verb does not have to be in the unit. A `parametrize` argvalues **name** is
resolved against the file's own module-level assignments — one hop, no chain
following, stopping at the file boundary — because the verb in the incident lives
in `GATED_VERBS` and a rule that read only the unit's own literals would have
missed the site it was written for. Decorators and body are both read, since the
same file drives the same twelve verbs through the same `main()` both ways.

### And the fixture species

**`FIXTURE_NO_TEARDOWN`** — a fixture that reaches host state by any of the five
direct species and hands its value over with nothing after the `yield`:

```python
@pytest.fixture
def stopped_timer():
    subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
    yield                                    # flagged: no teardown after the yield
```

A fixture is the *right* place to touch the host — it is the one place a restore
runs for a failing test too. This finds the half-built version: the setup landed,
the teardown never did, and the change outlives every test that uses it.

## What is never flagged

These acquittals are the whole difference between a rule and a nuisance.

**The seam is patched.** `patch`, `patch.object`, `patch.dict` or
`monkeypatch.setattr` naming the call, its module, or the module that makes the
verb effectful — anywhere in the unit.

```python
with patch("aipass.daemon.apps.timer_install.subprocess.run") as run:
    _daemon_mod.main()                                             # NOT flagged
```

A target held in a module-level constant is resolved one hop to its string, so
`patch(TIMER_SEAM)` acquits exactly what `patch("...timer_install...")` acquits.
That hop was added because @daemon wrote it the constant way first and the rule,
reading literals only, kept flagging all three of its cured sites — a rule should
not push an owner into inlining a constant they had every reason to keep.

**`monkeypatch.setenv`, `delenv` and `chdir`.** pytest restores those itself, by
contract, on every path including a failure. Using them **is** the cure, so they
are never a finding.

```python
def test_reads_the_branch(monkeypatch):
    monkeypatch.setenv("AIPASS_BRANCH", "daemon")                  # NOT flagged
```

**A path under `tmp_path`.** A write to a directory pytest created and removes is
not host state. `tmp_path`, `tmp_path_factory`, `tmpdir` and `tmpdir_factory` all
carry the acquittal, and so does a name assigned from a `tmp_path`-rooted
expression.

**A same-file fixture that restores `os.environ` after its yield.** A fixture that
touches and reads `os.environ` and does anything after handing its value over
acquits every unit in that file which requests it. @ai_mail's `clean_env` strips
four identity variables, yields, and puts all four back; twenty-nine units then set
one of those same four inside the test. Reading the units alone called all
twenty-nine unrestored when the file restores every one.

**A same-file fixture that calls `monkeypatch.chdir`.** That is a statement about
how monkeypatch works rather than a convenience: it records the working directory
at the moment it is called and restores *that* at teardown, so a raw `os.chdir`
deeper into the same test is undone too. @drone's `lock_dir` is exactly that shape,
and it is correct code.

**A change undone in the `finally` of a `try` in the same unit.** For environment
and working-directory changes, a mutation inside a `try` whose `finally` puts the
same thing back has been restored, on every path including the failing one:

```python
def test_reads_the_branch():
    try:
        os.environ["AIPASS_BRANCH"] = "daemon"  # NOT flagged — the finally has it
        assert read_branch() == "daemon"
    finally:
        del os.environ["AIPASS_BRANCH"]
```

The mutation has to sit inside the `try` for the `finally` to cover it, which is
also the only arrangement that is actually true.

**A fixture with a teardown after its yield.** A bare `yield` followed by restore
code is the correct pytest idiom and is not flagged. pytest runs a yield fixture's
teardown when the test **fails** as well as when it passes; `try`/`finally` buys
one extra case — an exception raised inside the fixture itself, between the change
and the yield — and not the case people reach for it for. Demanding it would have
convicted `clean_env`. Measured before that narrowing: 1 fixture row fleet-wide,
and it was that one. The rule asks the honest question instead — is there a
teardown at all.

## How to fix a flag

In this order of preference.

**1. Patch the seam, so the effect never happens.** This is the best answer for a
routing or refusal test, because such a test is about the router's decision and not
about systemd. Patch the module that does the work, or the `subprocess` call inside
it:

```python
with patch("aipass.daemon.apps.timer_install.subprocess.run") as run:
    with patch.object(sys, "argv", ["daemon", "uninstall-timer", "junk"]):
        with pytest.raises(SystemExit):
            _daemon_mod.main()
    assert not run.called          # and now the refusal is actually proven
```

**2. Use `monkeypatch`, which is restored for you.** For environment and working
directory there is no reason to write your own restore: `monkeypatch.setenv`,
`delenv`, `setattr` and `chdir` are undone at teardown on every path, including the
one where your test raises.

**3. When the test must really touch the host, snapshot and restore.** Some tests
have to — a timer install is only proven by installing something. Then the fixture
owns the state: it records what was there, yields, and puts it back.

```python
@pytest.fixture
def timer_state(tmp_path):
    """Snapshot the real unit state to a document, then put it back."""
    snapshot = tmp_path / "timer_state.json"
    snapshot.write_text(json.dumps(read_timer_state()))
    yield snapshot
    restore_timer_state(json.loads(snapshot.read_text()))   # idempotent by design
```

The full pattern, runnable, is `templates/host_state_test.py` in this pack. It
carries the part the sketch above leaves out: the teardown **asserts** the restore
landed instead of assuming it, against a subject modelled on `systemctl disable`,
where the stop deletes the unit file and the restoring start is a silent no-op. The
version that restores without reading back stays green with the timer down. That is
the incident, in seven collected units.

## The limit that matters most

**A `finally` does not run when the process is killed.** A SIGKILL — an OOM kill, a
`kill -9` on a hung run, a CI runner reclaiming its box — skips teardown entirely.
So *no in-process restore is a guarantee*, not a `finally`, not a yield fixture,
not `monkeypatch`. Everything above reduces the window. Nothing closes it.

That is why the snapshot/restore pattern lands its snapshot **as a document under
`tmp_path`** rather than holding it in a local variable, and why the restore is
written **idempotent** — run it twice and the result is the same. A restore that
survives outside the interpreter, and does not care how many times it runs, is one
a later run can finish after an interrupted one. That is the difference between a
window and a hole.

## `--help` in the argv is not an acquittal

Driving a host-effectful verb through a real entry point with `--help` appended is
still flagged, and that is deliberate. `--help` only saves the machine if
production's help gate fires before the work does. Relying on a guard inside
production is precisely the reliance that failed here: the incident is a test that
was safe *because the gate existed*, on the run where the gate did not.

## What this rule cannot see

Every limit below runs toward **fewer** flags, which is the safe direction for a
rule that accuses.

- **It does not follow calls.** An effect reached through a helper the unit calls,
  or through a fixture defined in another file, is invisible. So is a restore
  performed in one.
- **A runtime-assembled argv is not read.** Only a literal first element — or the
  first word of a literal command string — is evidence of which binary runs.
- **A verb whose module publishes no command set is not derived.** A module that
  reaches host state and declares no `COMMANDS`-style constant gives a reader no
  verb to look for, so the units that call it are not flagged.
- **A restore it is not shown is invisible.** An `atexit` hook, a session fixture in
  a conftest two directories up, an external supervisor putting the unit back — none
  of those are read.
- **A flagged site may be perfectly safe** for a reason the reader can see and this
  checker cannot. It nominates. A human decides.

## What it measured

At the time of writing, after the acquittals above: **3 rows fleet-wide over 18
branches** — @hooks 2, @skills 1. Before those acquittals, the same corpus produced
**38**.

Against @daemon at HEAD, before @daemon's own cure landed: **4 rows**. Those four
are the incident.

## Scoring

Subjects that leave the machine as they found it, over every subject the rule
judges — test units **and** fixtures — counted **per subject**: a unit carrying
three species is one unit a reader has to go and look at, not three. Counting
findings, or scoring fixture rows against a count of units alone, lets a project
fall below zero; a score that can go negative is one nobody believes twice.
Fixtures are reported under their own nodeid and deduped against the units.

**Advisory**: it reports a number and never fails a board.

A project with no test files reports `not_applicable` rather than zero — zero tests
measured is not zero quality found. A project whose test files are present but
unparseable says so explicitly, and is never reported as a project without tests.
Production files that could not be read are surfaced as their own check line,
because a hole and an unread file look identical from the outside.

*Design: DPLAN-0323 · Built under FPLAN-0525, from the FPLAN-0524 incident*
