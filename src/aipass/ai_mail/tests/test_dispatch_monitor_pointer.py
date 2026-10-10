# =================== AIPass ====================
# Name: test_dispatch_monitor_pointer.py
# Description: Tests for the dispatch monitor's session-pointer aware retry loop
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-10
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's session-pointer aware retry loop and reconciliation."""

# Split out of test_dispatch_monitor.py on 2026-10-08 to keep that file under the
# 1,200-line target: which session each attempt aims at, and what gets written down.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — main()'s attempts and the bounce: tests/test_dispatch_monitor.py

import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import cmd_for_attempt, main, reconcile_pointer

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


# --- session-pointer aware retry loop ---------------------------------
#
# wake.py now emits --resume <id> and --session-id <id> where it only ever
# emitted -c. Every place the monitor reasoned about "-c" had to learn the
# new flags, and one of them (the attempt loop) had to learn that a session
# id is single-use: the CLI refuses an id that already exists, so re-running
# an identical command is fatal where it used to be free.


@pytest.fixture
def pointer_home(tmp_path, monkeypatch):
    """Point the home directory at tmp_path so transcript paths land under the sandbox.

    Path.home() answers from HOME on POSIX and USERPROFILE on Windows, so the
    environment moves it for this test without replacing pathlib for every
    reader in the process (ai_mail, leg 6).
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "this platform must answer Path.home() from the environment"
    return home


def _plant_transcript(branch_path, session_id):
    """Create the transcript file Claude would have written for a session.

    ``transcript_file`` returns None when this machine cannot name its home
    directory — an absent answer rather than a path. Asserted rather than
    assumed: every caller here runs under the fake-home fixture, so a None means
    that fixture did not take, and failing on the assert names that cause
    instead of an AttributeError on the next line.
    """
    transcript = mod.session_pointer.transcript_file(branch_path, session_id)
    assert transcript is not None, "fake home not in effect — transcript_file could not name a path"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}\n", encoding="utf-8")
    return transcript


def test_attempt_1_is_the_command_as_built(tmp_path, pointer_home):
    """Strike 1 changes nothing — wake.py already decided where this lands."""
    cmd = ["claude", "--resume", "abc", "-p", "hi"]
    built, mode = cmd_for_attempt(cmd, 1, tmp_path)
    assert built == cmd
    assert mode == "resume"


def test_attempt_2_converts_a_consumed_session_id_to_resume(tmp_path, pointer_home):
    """THE regression guard: attempt 1 created the session, so the id is spent.

    Re-sending it gets "Session ID <id> is already in use" and no output at
    all — three strikes would fail instantly instead of recovering.

    The rebuilt command must match wake.py's shape exactly: `--resume <id>`
    leads, because that is the form verified against the CLI. Swapping the
    flag where --session-id sat would trail it after `-p <prompt>` — an
    argument order nobody has ever run.
    """
    branch = tmp_path / "branch"
    branch.mkdir()
    _plant_transcript(branch, "abc-123")
    cmd = ["claude", "-p", "hi", "--session-id", "abc-123"]

    built, mode = cmd_for_attempt(cmd, 2, branch)

    assert built == ["claude", "--resume", "abc-123", "-p", "hi"]
    assert "--session-id" not in built
    assert mode == "resume"


def test_attempt_2_resume_leads_even_for_a_long_command(tmp_path, pointer_home):
    """Position is what this pins: --resume sits at index 1, never after -p."""
    branch = tmp_path / "branch"
    branch.mkdir()
    _plant_transcript(branch, "abc-123")
    cmd = [
        "/usr/bin/claude",
        "-p",
        "check inbox",
        "--model",
        "opus",
        "--max-turns",
        "100",
        "--output-format",
        "json",
        "--session-id",
        "abc-123",
    ]

    built, _ = cmd_for_attempt(cmd, 2, branch)

    assert built[:3] == ["/usr/bin/claude", "--resume", "abc-123"]
    assert built[3:] == ["-p", "check inbox", "--model", "opus", "--max-turns", "100", "--output-format", "json"]


def test_attempt_2_leaves_a_command_with_nothing_but_a_session_id_alone(tmp_path, pointer_home):
    """Degenerate input: no binary to lead with, so there is nothing to rebuild."""
    branch = tmp_path / "branch"
    branch.mkdir()
    _plant_transcript(branch, "abc-123")
    cmd = ["--session-id", "abc-123"]

    built, _ = cmd_for_attempt(cmd, 2, branch)

    assert built == cmd


def test_attempt_2_leaves_an_unconsumed_session_id_alone(tmp_path, pointer_home):
    """No transcript means attempt 1 never got far enough to claim the id."""
    branch = tmp_path / "branch"
    branch.mkdir()
    cmd = ["claude", "-p", "hi", "--session-id", "abc-123"]

    built, mode = cmd_for_attempt(cmd, 2, branch)

    assert built == cmd
    assert mode == "fresh"


def test_attempt_2_mints_a_new_id_when_the_transcript_cannot_be_checked(tmp_path, pointer_home, monkeypatch):
    """Unknown is neither "spent" nor "free": attempt 2 takes a new id, as strike 3 does.

    Before leg 10 a stat failure answered "no transcript", so attempt 2 re-sent
    an id that attempt 1 may already have claimed, the "already in use" failure
    the comment beside it said it prevented. Resuming the id would be as wrong
    the other way. Its proof is the mutant that answers False again
    (ai_mail, leg 10).
    """
    branch = tmp_path / "branch"
    branch.mkdir()

    class _UnstatableTranscript:
        def is_file(self):
            raise OSError("stat failed")

    unstatable = MagicMock(return_value=_UnstatableTranscript())
    monkeypatch.setattr(mod.session_pointer, "transcript_file", unstatable)
    cmd = ["claude", "-p", "hi", "--session-id", "abc-123"]

    built, mode = cmd_for_attempt(cmd, 2, branch)

    unstatable.assert_called_once_with(branch, "abc-123")
    assert mode == "fresh"
    assert "abc-123" not in built
    assert "--resume" not in built
    new_id = built[built.index("--session-id") + 1]
    assert built == ["claude", "-p", "hi", "--session-id", new_id]
    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == new_id
    assert pointer["set_by"] == "monitor-retry-fresh"


def test_attempt_2_mints_a_new_id_when_there_is_no_home(tmp_path, pointer_home, monkeypatch):
    """No home means no transcript can be located, so the id's state is unknown: new id.

    Before leg 11 this answered "no transcript" and re-sent the id, the same
    defect leg 10 cured for a stat failure. Its proof is the mutant that answers
    False again (ai_mail, leg 11).
    """
    branch = tmp_path / "branch"
    branch.mkdir()
    no_home = MagicMock(return_value=None)
    monkeypatch.setattr(mod.session_pointer, "transcript_file", no_home)
    cmd = ["claude", "-p", "hi", "--session-id", "abc-123"]

    built, mode = cmd_for_attempt(cmd, 2, branch)

    no_home.assert_called_once_with(branch, "abc-123")
    assert mode == "fresh"
    assert "abc-123" not in built
    new_id = built[built.index("--session-id") + 1]
    assert built == ["claude", "-p", "hi", "--session-id", new_id]
    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == new_id
    assert pointer["set_by"] == "monitor-retry-fresh"


def test_attempt_2_of_a_dash_c_run_is_unchanged(tmp_path, pointer_home):
    """The -c path has no id to consume — retrying it is free, as before."""
    cmd = ["claude", "-c", "-p", "hi"]
    built, mode = cmd_for_attempt(cmd, 2, tmp_path)
    assert built == cmd
    assert mode == "resume"


def test_attempt_3_mints_a_new_id_and_repoints_the_branch(tmp_path, pointer_home):
    """Strike 3 abandons the bad session but keeps its own crash-safety."""
    branch = tmp_path / "branch"
    branch.mkdir()
    cmd = ["claude", "--resume", "old-id", "-p", "hi", "--model", "opus"]

    built, mode = cmd_for_attempt(cmd, 3, branch)

    assert mode == "fresh"
    assert "--resume" not in built and "old-id" not in built
    assert "--session-id" in built
    new_id = built[built.index("--session-id") + 1]
    assert new_id != "old-id"
    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == new_id
    assert pointer["set_by"] == "monitor-retry-fresh"


def test_attempt_3_replaces_a_spent_minted_id(tmp_path, pointer_home):
    """A fresh run that failed twice must not re-send the id it already used."""
    branch = tmp_path / "branch"
    branch.mkdir()
    cmd = ["claude", "-p", "hi", "--session-id", "spent-id"]

    built, _ = cmd_for_attempt(cmd, 3, branch)

    assert "spent-id" not in built
    assert built[built.index("--session-id") + 1] != "spent-id"


def test_attempt_3_still_spawns_when_the_pointer_cannot_be_written(tmp_path, pointer_home, monkeypatch):
    """A pointer write is never worth losing the last attempt over."""
    branch = tmp_path / "branch"
    branch.mkdir()
    write_pointer = MagicMock(return_value=False)
    monkeypatch.setattr(mod.session_pointer, "write_pointer", write_pointer)

    built, mode = cmd_for_attempt(["claude", "-c", "-p", "hi"], 3, branch)

    assert mode == "fresh"
    assert "-c" not in built
    assert "--session-id" in built
    new_id = built[built.index("--session-id") + 1]
    write_pointer.assert_called_once_with(branch, new_id, "monitor-retry-fresh")


def test_attempt_3_of_an_unbound_command_is_unchanged(tmp_path, pointer_home):
    """Nothing to abandon and no id to burn — leave it exactly as it is."""
    cmd = ["claude", "-p", "hi", "--model", "opus"]
    built, mode = cmd_for_attempt(cmd, 3, tmp_path)
    assert built == cmd
    assert mode == "fresh"


def test_attempt_1_of_a_dash_r_run_is_labelled_a_resume(tmp_path, pointer_home):
    """-r is --resume's short form; the CLI accepts it and so must the attempt label."""
    cmd = ["claude", "-r", "abc", "-p", "hi"]
    assert cmd_for_attempt(cmd, 1, tmp_path) == (cmd, "resume")


def test_a_command_ending_in_a_bare_session_id_flag_runs_as_built(tmp_path, pointer_home):
    """A truncated command reads as "no id", not as a crash on the way past."""
    cmd = ["claude", "-p", "hi", "--session-id"]
    assert cmd_for_attempt(cmd, 1, tmp_path) == (cmd, "fresh")


def test_attempt_3_of_a_dash_r_run_drops_the_flag_with_its_id(tmp_path, pointer_home):
    branch = tmp_path / "branch"
    branch.mkdir()

    built, _ = cmd_for_attempt(["claude", "-r", "abc-123", "-p", "hi", "--model", "opus"], 3, branch)

    assert built[:5] == ["claude", "-p", "hi", "--model", "opus"]
    assert "-r" not in built and "abc-123" not in built


def test_attempt_3_strips_every_binding_and_keeps_every_other_argument_in_order(tmp_path, pointer_home):
    branch = tmp_path / "branch"
    branch.mkdir()
    kept = ["-p", "check inbox", "--model", "opus", "--max-turns", "100", "--permission-mode", "bypassPermissions"]
    cmd = ["claude", "-c", "--resume", "abc-123", "--session-id", "def-456", *kept, "--output-format", "json"]

    built, _ = cmd_for_attempt(cmd, 3, branch)

    new_id = built[built.index("--session-id") + 1]
    assert built == ["claude", *kept, "--output-format", "json", "--session-id", new_id]


_AIMED_CMD = ["claude", "--resume", "aimed-id", "-p", "hi"]
_C_CMD = ["claude", "-c", "-p", "hi"]


def test_reconcile_refuses_to_adopt_a_session_landed_on_by_bare_c(tmp_path, pointer_home):
    """THE RULING (the owner, 2026-08-20): a -c landing is never written down.

    -c picks by file mtime. Recording that choice would promote a guess into a
    durable record, and every later dispatch would resume it deliberately — so
    a branch whose newest transcript happened to be a human's chat would be
    married to that chat forever. One wrong landing becomes permanent.
    """
    branch = tmp_path / "branch"
    branch.mkdir()
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "landed-by-mtime", "is_error": False}), encoding="utf-8")

    reconcile_pointer(branch, str(stdout_log), _C_CMD)

    assert mod.session_pointer.read_pointer(branch) is None, "a -c landing must leave the branch pointerless"


def test_reconcile_writes_the_pointer_when_we_aimed_and_landed_elsewhere(tmp_path, pointer_home):
    """We named a session and the CLI reports a different one — record the truth.

    This is how a strike-3 remint reaches the pointer: we aimed, the id moved,
    and the branch must end up pointing at where its agent actually is.
    """
    branch = tmp_path / "branch"
    branch.mkdir()
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "actual-id", "is_error": False}), encoding="utf-8")

    reconcile_pointer(branch, str(stdout_log), _AIMED_CMD)

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == "actual-id"
    assert pointer["set_by"] == "monitor-reconciled"


def test_reconcile_adopts_a_minted_session_id(tmp_path, pointer_home):
    """--session-id counts as aiming just as much as --resume does."""
    branch = tmp_path / "branch"
    branch.mkdir()
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "minted-id"}), encoding="utf-8")

    reconcile_pointer(branch, str(stdout_log), ["claude", "-p", "hi", "--session-id", "minted-id"])

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == "minted-id"


def test_reconcile_does_not_rewrite_a_matching_pointer(tmp_path, pointer_home):
    """We landed where we aimed — no write, so set_by keeps naming who decided."""
    branch = tmp_path / "branch"
    branch.mkdir()
    mod.session_pointer.write_pointer(branch, "same-id", "wake-fresh")
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "same-id"}), encoding="utf-8")

    reconcile_pointer(branch, str(stdout_log), _AIMED_CMD)

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["set_by"] == "wake-fresh"


def test_reconcile_ignores_result_json_without_a_session_id(tmp_path, pointer_home):
    """Nothing to reconcile against; the existing pointer stands."""
    branch = tmp_path / "branch"
    branch.mkdir()
    mod.session_pointer.write_pointer(branch, "kept-id", "wake-fresh")
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"is_error": True}), encoding="utf-8")

    reconcile_pointer(branch, str(stdout_log), _AIMED_CMD)

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == "kept-id"


def test_reconcile_leaves_an_existing_pointer_alone_on_a_c_run(tmp_path, pointer_home):
    """A -c fallback must not disturb a pointer that is already there."""
    branch = tmp_path / "branch"
    branch.mkdir()
    mod.session_pointer.write_pointer(branch, "kept-id", "wake-fresh")
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "somewhere-else"}), encoding="utf-8")

    reconcile_pointer(branch, str(stdout_log), _C_CMD)

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == "kept-id"


def test_reconcile_survives_a_failing_pointer_write(tmp_path, pointer_home, monkeypatch):
    """Reconciliation is bookkeeping — it must never raise into the exit path."""
    branch = tmp_path / "branch"
    branch.mkdir()
    write_pointer = MagicMock(return_value=False)
    monkeypatch.setattr(mod.session_pointer, "write_pointer", write_pointer)
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "actual-id"}), encoding="utf-8")

    # Had no oracle: the trailing comment said "no raise" and nothing checked
    # it. pytest.raises cannot spell "must not raise", so the oracle is what
    # SURVIVED the refused write — no pointer was invented on disk to paper over
    # it, which is the failure mode a swallowed exception would hide.
    reconcile_pointer(branch, str(stdout_log), _AIMED_CMD)

    write_pointer.assert_called_once_with(branch, "actual-id", "monitor-reconciled")
    assert mod.session_pointer.read_pointer(branch) is None


def test_main_third_attempt_is_fresh_for_a_resumed_dispatch(monkeypatch, main_argv, pointer_home, tmp_path):
    """End-to-end: --resume reaches strike 3 as a fresh, newly-minted session.

    The old `"-c" in claude_cmd` check would have left all three attempts
    identical, so a broken session could never be escaped.
    """
    argv, lock_file, stderr_log = main_argv
    argv = argv[:6] + ["claude", "--resume", "old-id", "--model", "opus"]
    calls: list[list[str]] = []

    def track_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return (1, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", track_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "time",
        MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()),
    )
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    assert len(calls) == 3
    assert "--resume" in calls[0] and "--resume" in calls[1]
    assert "--resume" not in calls[2]
    assert "--session-id" in calls[2]
    bounce.assert_called_once()
    assert bounce.call_args.args[0] == "@test_branch"


def _run_main_capturing_pointer(monkeypatch, argv, landed_session, tmp_path):
    """Drive main() to a clean exit with a result JSON naming `landed_session`."""

    def fake_run(cmd, stdout_log, *args, **kwargs):
        Path(stdout_log).write_text(json.dumps({"session_id": landed_session}), encoding="utf-8")
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_main_does_not_adopt_a_pointer_after_a_successful_c_run(monkeypatch, main_argv, pointer_home, tmp_path):
    """End-to-end of the ruling: a whole successful -c dispatch records nothing.

    The fixture's command is `claude -c`, so the session it landed in was chosen
    by file mtime. Writing that down would make the next dispatch resume it on
    purpose — see test_reconcile_refuses_to_adopt_a_session_landed_on_by_bare_c.
    The branch stays on -c until something dispatches it --fresh.
    """
    argv, lock_file, _ = main_argv
    branch_path = lock_file.parent.parent

    _run_main_capturing_pointer(monkeypatch, argv, "landed-by-mtime", tmp_path)

    assert mod.session_pointer.read_pointer(branch_path) is None


def test_main_reconciles_the_pointer_after_a_successful_aimed_run(monkeypatch, main_argv, pointer_home, tmp_path):
    """We aimed with --resume, so where the run actually landed IS recorded."""
    argv, lock_file, _ = main_argv
    branch_path = lock_file.parent.parent
    argv = [arg if arg != "-c" else "--resume" for arg in argv]
    argv.insert(argv.index("--resume") + 1, "aimed-id")

    _run_main_capturing_pointer(monkeypatch, argv, "landed-here", tmp_path)

    pointer = mod.session_pointer.read_pointer(branch_path)
    assert pointer is not None
    assert pointer["session_id"] == "landed-here"
    assert pointer["set_by"] == "monitor-reconciled"


def test_main_does_not_reconcile_after_a_failed_run(monkeypatch, main_argv, pointer_home, tmp_path):
    """A failed run's result JSON names a session not worth returning to."""
    argv, lock_file, stderr_log = main_argv
    branch_path = lock_file.parent.parent

    def fake_run(cmd, stdout_log, *args, **kwargs):
        Path(stdout_log).write_text(json.dumps({"session_id": "bad-session"}), encoding="utf-8")
        return (1, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "time",
        MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()),
    )
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    pointer = mod.session_pointer.read_pointer(branch_path)
    # MEASURED 2026-09-08: a pointer IS written — the retry mints a fresh
    # session and stamps it monitor-retry-fresh — so ``pointer is None`` never
    # held on this path and the assertion could not fail where it was aimed.
    assert pointer is not None
    assert pointer["session_id"] != "bad-session", pointer
    assert pointer["set_by"] == "monitor-retry-fresh", pointer
    bounce.assert_called_once()
    assert bounce.call_args.args[0] == "@test_branch"
