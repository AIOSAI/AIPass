# =================== AIPass ====================
# Name: host_state_test.py
# Description: teaching template - touching live host state and proving you put it back
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""TEACHING TEMPLATE - THE HOST-STATE TEST. A worked example. Not a file to deploy.

DO NOT STAMP THIS FILE.
Copying it into a branch's test directory is the exact failure this pack was
built to correct. The standard v5 replaces - test_quality v4 - shipped six
reference templates, branches stamped them, and five of those stamped families
now total 1,411 tests across the fleet. Measured, only 5 of the 48 test-function
names appearing in six or more branches still shared a shape: stamped once, then
every copy drifted somewhere different. The same standard scored a project by
searching its test files for 99 pattern substrings, so the cheapest way to score
well was to write the strings rather than the tests. This file teaches a SHAPE
and shows its reasoning, so that you write your own fixture around your own
host state. If you catch yourself renaming a service at the top of a copy of
this file, stop - that is the stamping happening again.

WHAT A HOST-STATE TEST IS FOR
On 2026-09-07 a test parametrized over a list of gated verbs drove them through
a real `main()` with nothing patched on the seam. The refusal gate held, so the
test was green. It was green the way an unfired gun is safe. On the red-first
run - and on every mutation run that removes the gate - `main()` reached the
real implementation, which runs `systemctl --user stop` and `disable` and then
deletes the unit files. daemon-tick.timer stopped at 11:46:40 and did not come
back. No scheduler tick ran for twenty-three hours. Two citizens missed their
windows.

The ruling that came out of it is narrower than "do not touch the host":

    tests can't disable processes, they should restore to exact same state
    before the test. The test is fine and good that it can enter something.

So TOUCHING THE REAL THING IS ALLOWED. Leaving it changed is the defect. This
template is about the restore, never about the reach.

THE CURES, CHEAPEST FIRST - AND THE ORDER IS THE POINT
Most sites never need the fixture at the bottom of this file. Reach for the
heavy pattern last, not first:

  1. PATCH THE SEAM SO THE EFFECT NEVER HAPPENS. If what you are testing is
     that your caller ASKS for the stop - the argv it builds, the verb it
     routes, the refusal that stops it asking at all - then the real stop is
     not part of the claim. Put a stand-in on the effectful call and assert the
     interaction. Nothing reaches the machine, so nothing has to be put back,
     and the test cannot leave damage behind even when it fails halfway.
  2. `monkeypatch.setenv` / `delenv` / `chdir`. pytest restores these itself,
     by contract, on every path including a failing one and an erroring one.
     If the state you need to move is an environment variable or the working
     directory, YOU ARE ALREADY DONE - using these IS the cure, and hand-rolling
     a fixture around `os.environ` is strictly worse code that this pack's
     `host_state` rule will flag while the monkeypatch spelling acquits.
  3. ONLY THEN the snapshot fixture below, for state pytest knows nothing
     about: a service manager, a crontab, a file under the real `~`, a lock a
     daemon holds. It costs a fixture, a document and two assertions, and you
     pay that only when the test must genuinely touch the real thing.

THE ASSERTION THAT WOULD HAVE CAUGHT THE INCIDENT
A restore in a `finally` is not evidence that the state came back. It is
evidence that a line ran. `systemctl disable` removes the unit file, so the
matching `enable`/`start` a teardown fires afterwards can be a silent no-op -
the teardown reports nothing wrong because it was never asked to check. The
whole difference between the wrong shape and the right one below is one line:
the restore READS THE HOST BACK and compares it against the snapshot.

Put that assertion in a FIXTURE's teardown rather than inline in a `try`. An
`assert` in a test's own `finally` masks the failure that was already
propagating out of the `try`; the same assert in a yield fixture is reported by
pytest as a separate ERROR alongside the test's own outcome, so a reader sees
both what failed and that the machine is now dirty.

THE HARD-KILL LIMIT, WHICH NOTHING IN-PROCESS CAN CLOSE
A `finally` does not run when the process is killed. SIGKILL, an OOM kill, a
pulled plug: teardown is skipped, and every in-process restore ever written is
skipped with it. So no fixture in this file - or in yours - is a guarantee.

Two properties are what remain, and both are cheap:

  - THE SNAPSHOT IS A DOCUMENT, WRITTEN UNDER `tmp_path` BEFORE THE STATE IS
    CHANGED. A snapshot held only in a local variable dies with the process
    that held it. A snapshot on disk outlives the kill, so a human - or the
    next run - can still read what the machine was supposed to look like.
  - THE RESTORE IS IDEMPOTENT: running it twice produces the same result as
    running it once, so a later run can safely finish an interrupted one
    without knowing how far the interrupted one got. That property is bought by
    writing the restore to NAME THE STATE IT WANTS rather than the change it
    makes. `set_service(name, "active")` twice is `set_service(name, "active")`;
    `toggle(name)` twice is a no-op that undoes itself. It is shown below, not
    claimed.

WHEN NOT TO REACH FOR ANY OF THIS
- Nothing outside the test can observe the change. A dict you built in the test
  is not host state.
- The write is under `tmp_path`. pytest created that directory and pytest
  removes it; a write there is not the machine, and the `host_state` rule
  acquits it for that reason.
- You are about to snapshot something you could simply not touch. The best
  restore is the effect that never happened - see cure 1.

HOW THIS FILE IS ORGANISED
The subject is defined inline, so the file is self-contained - it imports pytest
and the standard library and nothing else. `SERVICE_TABLE` is a module-level
dict standing in for the host's service manager; in your file it is `systemctl`,
the crontab, or a config under the real home. It is not a toy: a module-level
mapping really is process-global, so a test that changes it and walks away
really does leak into every later test in the session, which is what makes the
proofs at the bottom real rather than illustrated. The `wrong_*` and `right_*`
functions are deliberately NOT named `test_*`, so neither pytest nor this pack's
own reader collects them; they are read, and they are executed by the collected
tests at the bottom against a deliberately broken effect, which is what proves
the wrong shapes stay green where the right one goes red.
"""

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Sequence
from unittest.mock import patch

import pytest

# =============================================================================
# THE SUBJECT UNDER TEST - defined here so this file is self-contained
# =============================================================================

#: The host's service table. Process-global on purpose: this is the property
#: that makes an unrestored change leak into every later test in the session.
SERVICE_TABLE: Dict[str, str] = {"daemon-tick.timer": "active", "mail-relay.service": "active"}


def set_service(name: str, state: str) -> None:
    """Put one unit into `state`.

    THIS SIGNATURE IS WHY THE RESTORE CAN BE IDEMPOTENT. It names the state it
    wants, not the change it makes. Calling it twice with the same arguments is
    calling it once. A `toggle(name)` seam cannot be restored from a document,
    because replaying the document would undo the restore.
    """
    SERVICE_TABLE[name] = state


def service_state(name: str) -> str:
    """What the table says this unit is doing, or "" when the unit is gone."""
    return SERVICE_TABLE.get(name, "")


def pause_timer(name: str) -> None:
    """The caller under test: it stops one timer through the effectful seam."""
    set_service(name, "inactive")


class DisablingHost:
    """A DELIBERATELY BROKEN effect: stopping a unit also deletes it.

    `systemctl disable` is exactly this shape - it stops the unit AND removes
    the unit file, so every later `start` is a silent no-op with nothing to
    start. The stop reports success. The restore reports success. The machine
    is down. Only a restore that READS BACK can tell the difference, and that
    is the single line this template exists to teach.
    """

    def __init__(self) -> None:
        """Start with nothing deleted."""
        self.deleted: set = set()

    def __call__(self, name: str, state: str) -> None:
        """Stop a unit and delete it, or refuse to bring a deleted unit back."""
        if state == "inactive":
            SERVICE_TABLE[name] = "inactive"
            self.deleted.add(name)
            return
        if name in self.deleted:
            return
        SERVICE_TABLE[name] = state


# =============================================================================
# THE SNAPSHOT AS A DOCUMENT - the half a SIGKILL cannot take away
# =============================================================================


def snapshot_to(document: Path, names: Sequence[str]) -> Dict[str, str]:
    """Record what `names` are doing right now, to a file, and return it.

    WRITTEN BEFORE ANYTHING IS CHANGED, AND WRITTEN TO DISK. A snapshot living
    only in a local variable dies with the process holding it, which is the
    exact moment it was needed. On disk it survives the kill, so a human or the
    next run can still see what the machine was supposed to look like.
    """
    recorded = {name: service_state(name) for name in names}
    document.write_text(json.dumps(recorded, indent=2, sort_keys=True), encoding="utf-8")
    return recorded


def restore_from(document: Path) -> Dict[str, str]:
    """Put every unit named in `document` back where the document says, and return it.

    IDEMPOTENT, AND THAT IS A PROPERTY OF THE SEAM RATHER THAN OF THIS LOOP.
    Every write names an absolute state read out of the document, so running
    this twice lands on the same table as running it once - which is what lets
    a later run finish an interrupted one without knowing how far it got.

    A missing document answers `{}` rather than raising: "there is nothing to
    put back" is a real answer, and a teardown that explodes on a snapshot the
    kill took with it is a second failure hiding the first.
    """
    if not document.is_file():
        return {}
    recorded: Dict[str, str] = json.loads(document.read_text(encoding="utf-8"))
    for name, state in recorded.items():
        set_service(name, state)
    return recorded


# =============================================================================
# THE FIXTURES - where a restore belongs, because it runs for a FAILING test too
# =============================================================================


@pytest.fixture(autouse=True)
def service_table_restored(tmp_path: Path) -> Iterator[None]:
    """This file's own belt: the whole table snapshotted and put back around every test.

    A template that teaches a restore and then let its own module-level state
    drift between tests would be teaching by counterexample. It is also what
    makes the proofs below honest - they deliberately leave the timer stopped,
    and this is what stops that from reaching the next test.
    """
    document = tmp_path / "service_table_snapshot.json"
    recorded = snapshot_to(document, tuple(SERVICE_TABLE))
    try:
        yield
    finally:
        restore_from(document)
        # READ BACK, ALWAYS. `restore_from` returning normally says a loop ran.
        # This says the machine agrees.
        assert SERVICE_TABLE == recorded


@pytest.fixture
def timer_paused(tmp_path: Path) -> Iterator[Path]:
    """Stop one timer for one test, and put it back - checked, not assumed.

    THE ORDER OF THESE FOUR LINES IS THE WHOLE PATTERN. Snapshot to a document
    first, so the record exists before there is anything to regret. Change the
    state inside the `try`, so an exception raised between the change and the
    yield still reaches the teardown. Hand the document to the test. Restore in
    the `finally`, and then ASSERT the restore landed - a teardown that only
    calls the restore is a teardown that cannot report a restore that did
    nothing.
    """
    document = tmp_path / "timer_snapshot.json"
    recorded = snapshot_to(document, ("daemon-tick.timer",))
    try:
        pause_timer("daemon-tick.timer")
        yield document
    finally:
        restore_from(document)
        assert service_state("daemon-tick.timer") == recorded["daemon-tick.timer"]


# =============================================================================
# THE WRONG SHAPES - read these first
# =============================================================================


def wrong_a_changes_the_host_and_walks_away(effect: Callable[..., Any]) -> None:
    """WRONG. It stops the timer, asserts the stop, and never puts anything back.

    Not named `test_*` on purpose, so pytest walks past it and so does this
    pack's reader.
    """
    # THE DEFECT, AND IT IS THE INCIDENT IN TWO LINES. The assertion is true,
    # the test is green, and the timer is still down when the process exits.
    # Nothing here is wrong about the reach - stopping the timer is a fair
    # thing for this test to do. What is missing is the second half.
    effect("daemon-tick.timer", "inactive")
    assert service_state("daemon-tick.timer") == "inactive"


def wrong_b_restores_and_assumes(effect: Callable[..., Any]) -> None:
    """WRONG for a subtler reason: it restores in a `finally` and never checks that the restore landed.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    before = service_state("daemon-tick.timer")
    try:
        effect("daemon-tick.timer", "inactive")
        assert service_state("daemon-tick.timer") == "inactive"
    finally:
        # THE DEFECT. This looks like the cure and reviews like the cure. It
        # restores through the SAME seam it changed through, and that seam is
        # allowed to fail quietly: `disable` deleted the unit, so `start` has
        # nothing to start and says so to nobody. The call returns, the
        # `finally` completes, the test is green, and the machine is down.
        effect("daemon-tick.timer", before)


# =============================================================================
# THE RIGHT SHAPE - and why it is different
# =============================================================================


def right_a_restores_and_proves_it(effect: Callable[..., Any]) -> None:
    """RIGHT. The same restore, plus the one line that turns it into evidence.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    before = service_state("daemon-tick.timer")
    try:
        effect("daemon-tick.timer", "inactive")
        assert service_state("daemon-tick.timer") == "inactive"
    finally:
        effect("daemon-tick.timer", before)

        # THE LINE THAT WOULD HAVE CAUGHT THE INCIDENT. It reads the host back
        # and compares it against what was recorded before anything moved. A
        # restore that did nothing is now a red test instead of a quiet
        # twenty-three hours.
        #
        # Inline like this it has one flaw, which is why the fixture above is
        # the shape to copy: an AssertionError raised HERE replaces whatever
        # was already propagating out of the `try`, so the reader learns the
        # machine is dirty and loses the reason it got dirty. In a fixture
        # teardown pytest reports both.
        assert service_state("daemon-tick.timer") == before


# =============================================================================
# THE TESTS - the only functions in this file pytest collects
# =============================================================================


def test_the_cheapest_cure_is_a_patched_seam_that_never_reaches_the_host() -> None:
    """Pins pause_timer through a patched seam: the one call it makes is asserted and the table never moves."""
    # CURE 1, AND THE ONE TO REACH FOR FIRST. The claim here is about what the
    # caller ASKS for, and that claim needs no real stop at all. In your file
    # the target is your module's dotted path - patch("mybranch.daemon.set_service").
    before = service_state("daemon-tick.timer")

    with patch(f"{__name__}.set_service") as effect:
        pause_timer("daemon-tick.timer")

    effect.assert_called_once_with("daemon-tick.timer", "inactive")
    assert service_state("daemon-tick.timer") == before


def test_monkeypatch_setenv_is_undone_when_its_block_ends() -> None:
    """Pins the pytest contract cure 2 rests on: a variable set through monkeypatch is gone after the block."""
    # CURE 2, AND THIS IS REAL HOST STATE - the interpreter's environment is
    # process-wide, so a raw `os.environ[...] = ...` here would be seen by every
    # later test in the session. The context-manager form is used so the restore
    # can be OBSERVED inside one unit; the `monkeypatch` fixture gives the same
    # guarantee at teardown, where a single unit cannot watch it happen.
    name = "SEEDGO_HOST_STATE_TEMPLATE"
    assert name not in os.environ

    with pytest.MonkeyPatch.context() as patched:
        patched.setenv(name, "1")
        assert os.environ[name] == "1"

    assert name not in os.environ


def test_monkeypatch_chdir_returns_the_process_to_where_it_started(tmp_path: Path) -> None:
    """Pins the other half of cure 2: monkeypatch.chdir moves the process, and leaving the block moves it back."""
    # ALSO REAL. `os.chdir` moves the whole interpreter, not this test, so a
    # later test resolving a relative path lands somewhere else entirely.
    started_at = Path.cwd()

    with pytest.MonkeyPatch.context() as patched:
        patched.chdir(tmp_path)
        assert Path.cwd().resolve() == tmp_path.resolve()

    assert Path.cwd() == started_at


def test_pause_timer_stops_the_timer_and_the_fixture_holds_the_state_to_return_to(timer_paused: Path) -> None:
    """Pins pause_timer against the real table: inactive inside the test, with the snapshot document naming active."""
    # CURE 3, THE ONE THAT ACTUALLY TOUCHES THE THING. The test says what it
    # came to say about the real state, and the document on disk - not a local
    # variable - is what says how to undo it.
    assert service_state("daemon-tick.timer") == "inactive"
    assert json.loads(timer_paused.read_text(encoding="utf-8")) == {"daemon-tick.timer": "active"}


def test_the_snapshot_document_finishes_a_restore_the_process_never_got_to(tmp_path: Path) -> None:
    """Pins the hard-kill property: the document alone restores the timer, and applying it twice changes nothing."""
    document = tmp_path / "interrupted_snapshot.json"
    snapshot_to(document, ("daemon-tick.timer",))
    pause_timer("daemon-tick.timer")

    # THE KILL, MODELLED HONESTLY RATHER THAN SIMULATED. A test cannot SIGKILL
    # its own process and still report a result, so what is pinned here is the
    # only thing that matters about a kill: the teardown never ran, the state
    # is half-changed, and the document is the only thing left.
    assert service_state("daemon-tick.timer") == "inactive"
    assert document.is_file()

    # A LATER RUN FINISHES THE JOB FROM THE DOCUMENT ALONE.
    assert restore_from(document) == {"daemon-tick.timer": "active"}
    assert service_state("daemon-tick.timer") == "active"

    # IDEMPOTENCE, SHOWN RATHER THAN CLAIMED. The second application lands on
    # the same table as the first, so a run that cannot tell whether an earlier
    # run got halfway can simply apply the whole document again.
    after_one = dict(SERVICE_TABLE)
    assert restore_from(document) == {"daemon-tick.timer": "active"}
    assert dict(SERVICE_TABLE) == after_one


def test_wrong_a_changes_the_host_and_walks_away_leaves_the_timer_stopped() -> None:
    """Proof: wrong_a_changes_the_host_and_walks_away returns green with the timer still inactive."""
    wrong_a_changes_the_host_and_walks_away(set_service)

    # THE DAMAGE, VISIBLE FROM OUTSIDE THE TEST THAT DID IT. This is the whole
    # incident: a green test and a stopped timer are not mutually exclusive.
    assert service_state("daemon-tick.timer") == "inactive"

    # The right shape reaches just as far and hands the machine back.
    set_service("daemon-tick.timer", "active")
    right_a_restores_and_proves_it(set_service)
    assert service_state("daemon-tick.timer") == "active"


def test_wrong_b_restores_and_assumes_accepts_a_restore_that_did_nothing() -> None:
    """Proof: wrong_b_restores_and_assumes stays green against DisablingHost where right_a goes red."""
    # The restore ran. The restore did nothing. Nothing in the wrong shape can
    # tell those apart, so it is green with the timer still down.
    wrong_b_restores_and_assumes(DisablingHost())
    assert service_state("daemon-tick.timer") == "inactive"

    # One more line, and the same broken effect is named.
    set_service("daemon-tick.timer", "active")
    with pytest.raises(AssertionError):
        right_a_restores_and_proves_it(DisablingHost())

    # And it still passes against the effect that is correct, which is what
    # stops it from being a test that simply always fails.
    set_service("daemon-tick.timer", "active")
    right_a_restores_and_proves_it(set_service)
