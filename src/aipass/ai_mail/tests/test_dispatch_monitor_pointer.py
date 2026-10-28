# =================== AIPass ====================
# Name: test_dispatch_monitor_pointer.py
# Description: Tests for the dispatch monitor's session-pointer aware retry loop
# Version: 1.3.0
# Created: 2026-10-08
# Modified: 2026-10-28
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's session-pointer aware retry loop and reconciliation, Claude, Codex and OpenCode."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — main()'s attempts and the bounce: tests/test_dispatch_monitor.py

import json
import sqlite3
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import (
    cmd_for_attempt,
    main,
    parse_codex_stream,
    parse_opencode_stream,
    reconcile_pointer,
    run_with_startup_check,
)

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


# A session id is single-use: the CLI refuses an id that already exists, so an identical retry is fatal.


@pytest.fixture
def pointer_home(tmp_path, monkeypatch):
    """Point the home directory at tmp_path so transcript paths land under the sandbox.
    Path.home() answers from HOME on POSIX and USERPROFILE on Windows, so no pathlib patch is needed.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "this platform must answer Path.home() from the environment"
    return home


def _plant_transcript(branch_path, session_id):
    """Create the transcript file Claude would have written for a session."""
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
    The rebuilt command must match wake.py's shape: `--resume <id>` leads, the form verified against the CLI.
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
    """Unknown is neither "spent" nor "free": attempt 2 takes a new id, as strike 3 does."""
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
    """No home means no transcript can be located, so the id's state is unknown: new id."""
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
    """A -c landing is never written down.

    -c picks by file mtime; recording it would make every later dispatch resume a guess on purpose.
    """
    branch = tmp_path / "branch"
    branch.mkdir()
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "landed-by-mtime", "is_error": False}), encoding="utf-8")

    reconcile_pointer(branch, str(stdout_log), _C_CMD)

    assert mod.session_pointer.read_pointer(branch) is None, "a -c landing must leave the branch pointerless"


def test_reconcile_writes_the_pointer_when_we_aimed_and_landed_elsewhere(tmp_path, pointer_home):
    """We named a session and the CLI reports a different one — record the truth.
    This is how a strike-3 remint reaches the pointer.
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

    # pytest.raises cannot spell "must not raise": the oracle is that no pointer was invented on disk.
    reconcile_pointer(branch, str(stdout_log), _AIMED_CMD)

    write_pointer.assert_called_once_with(branch, "actual-id", "monitor-reconciled")
    assert mod.session_pointer.read_pointer(branch) is None


def test_main_third_attempt_is_fresh_for_a_resumed_dispatch(monkeypatch, main_argv, pointer_home, tmp_path):
    """End-to-end: --resume reaches strike 3 as a fresh, newly-minted session."""
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
    See test_reconcile_refuses_to_adopt_a_session_landed_on_by_bare_c.
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
    # A pointer IS written here: the retry mints a fresh session stamped monitor-retry-fresh.
    assert pointer is not None
    assert pointer["session_id"] != "bad-session", pointer
    assert pointer["set_by"] == "monitor-retry-fresh", pointer
    bounce.assert_called_once()
    assert bounce.call_args.args[0] == "@test_branch"


# Verbatim lines of a live `codex exec --json` wake of @canary (2026-10-25): the stream's
# skeleton, every agent_message, and its last event; the command_execution items are dropped.
CODEX_STREAM = [
    '{"type":"thread.started","thread_id":"01a1746b-c9c8-7891-ae8e-666b368caf13"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_6","type":"agent_message","text":"Canary has one new email, no active plans, and no open todos. I’ll read and process the mail, then save the outcome in memory. All findings here are canary test data.\\n"}}',
    '{"type":"item.completed","item":{"id":"item_11","type":"agent_message","text":"The probe asked for my provider/model, branch and working directory, and confirmation that memories loaded. I replied to @devpulse and the mail is closed. I identified as OpenAI Codex/GPT-6 from runtime instructions, with the exact backend variant unverified. I’ll now record this as session #59 using the memo skill.\\n"}}',
    '{"type":"item.completed","item":{"id":"item_22","type":"agent_message","text":"Session #59 is saved and verified. The inbox is empty, and memory health reports zero entry-size violations. The requested standards audit is still running; no code or tests were changed.\\n"}}',
    '{"type":"item.completed","item":{"id":"item_24","type":"agent_message","text":"Processed the probe, replied to @devpulse, and confirmed the inbox is empty.\\n\\nSaved session #59 in `.trinity/local.json`. Memory health passed; final checklist passed. Seedgo audit reported 100% (86/87 files cached).\\n\\nAll findings are canary test data."}}',
    '{"type":"turn.completed","usage":{"input_tokens":825068,"cached_input_tokens":783360,"cache_write_input_tokens":0,"output_tokens":1871,"reasoning_output_tokens":247}}',
]
CODEX_THREAD = "01a1746b-c9c8-7891-ae8e-666b368caf13"
CODEX_ERROR = '{"type":"error","message":"stream disconnected before completion"}'


def _codex_cmd(resume=False):
    head = ["codex", "exec", "resume", CODEX_THREAD] if resume else ["codex", "exec"]
    return [*head, "-m", "gpt-6.1-sol", "--json", "-o", "last.txt", "--dangerously-bypass-approvals-and-sandbox", "Hi."]


def _write_stream(path, lines):
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestTheCodexStream:
    def test_the_live_capture_yields_its_thread_its_last_message_and_success(self, tmp_path):
        log = tmp_path / "stdout.log"
        _write_stream(log, CODEX_STREAM)

        parsed = parse_codex_stream(str(log))

        assert parsed["session_id"] == CODEX_THREAD
        assert parsed["result"].startswith("Processed the probe, replied to @devpulse")
        assert parsed["result"].endswith("All findings are canary test data.")
        assert parsed["usage"]["output_tokens"] == 1871
        assert parsed["succeeded"] is True and parsed["error"] == ""

    def test_an_error_event_fails_the_turn_even_after_turn_completed(self, tmp_path):
        log = tmp_path / "stdout.log"
        _write_stream(log, [*CODEX_STREAM[:-1], CODEX_ERROR, CODEX_STREAM[-1]])

        parsed = parse_codex_stream(str(log))

        assert parsed["succeeded"] is False
        assert parsed["error"] == CODEX_ERROR

    def test_a_stream_without_turn_completed_is_a_failure(self, tmp_path):
        log = tmp_path / "stdout.log"
        _write_stream(log, CODEX_STREAM[:-1])

        assert parse_codex_stream(str(log))["succeeded"] is False


class TestTheCodexRetryLadder:
    def test_attempts_1_and_2_rerun_a_codex_resume_as_built(self, tmp_path):
        for attempt in (1, 2):
            assert cmd_for_attempt(_codex_cmd(resume=True), attempt, tmp_path, "codex") == (
                _codex_cmd(resume=True),
                "resume",
            )

    def test_strike_3_drops_resume_and_its_thread_and_keeps_the_tail(self, tmp_path, pointer_home):
        assert cmd_for_attempt(_codex_cmd(resume=True), 3, tmp_path, "codex") == (_codex_cmd(), "fresh")
        assert mod.session_pointer.read_pointer(tmp_path) is None, "Codex mints the id: no pointer is guessed"

    def test_strike_3_of_a_fresh_codex_run_is_unchanged(self, tmp_path):
        assert cmd_for_attempt(_codex_cmd(), 3, tmp_path, "codex") == (_codex_cmd(), "fresh")


class TestTheCodexStartupProbe:
    """Codex streams live, so any stdout byte is startup; Claude's ~/.claude probe is not consulted."""

    def _run(self, tmp_path, monkeypatch, script):
        import os
        import subprocess
        import sys

        monkeypatch.setattr(mod, "STARTUP_TIMEOUT", 3)
        monkeypatch.setattr(mod, "POLL_INTERVAL", 0.1)
        monkeypatch.setattr(mod.session_pointer, "transcript_dir", MagicMock(side_effect=AssertionError("probed")))
        return run_with_startup_check(
            [sys.executable, "-c", script],
            str(tmp_path / "stdout.log"),
            subprocess.DEVNULL,
            str(tmp_path),
            dict(os.environ),
            "@canary",
            provider="codex",
        )

    def test_a_first_stdout_line_counts_as_started(self, tmp_path, monkeypatch):
        script = "import time; print('{}', flush=True); time.sleep(1)"
        assert self._run(tmp_path, monkeypatch, script) == (0, False)

    def test_a_silent_codex_is_killed_at_the_startup_timeout(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, "import time; time.sleep(30)") == (-3, True)


def _run_codex_main(monkeypatch, main_argv, tmp_path, lines, exit_code=0):
    argv, lock_file, _ = main_argv
    argv = [*argv[: argv.index("--")], "--provider=codex", "--", *_codex_cmd()]
    runs = []

    def fake_run(cmd, stdout_log, *args, **kwargs):
        runs.append(kwargs.get("provider"))
        _write_stream(stdout_log, lines)
        return exit_code, False

    bounce = MagicMock(return_value=True)
    monkeypatch.setenv("AIPASS_DISPATCH_ID", "dsp-codex")
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr("aipass.ai_mail.apps.handlers.paths.find_repo_root", MagicMock(return_value=tmp_path / "repo"))
    with pytest.raises(SystemExit) as exc_info:
        main()
    return exc_info.value.code, runs, bounce, lock_file.parent.parent


class TestTheCodexMonitorRun:
    def test_a_clean_codex_run_records_the_minted_thread_as_a_codex_pointer(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        code, runs, bounce, branch_path = _run_codex_main(monkeypatch, main_argv, tmp_path, CODEX_STREAM)

        assert code == 0 and runs == ["codex"]
        bounce.assert_not_called()
        pointer = mod.session_pointer.read_pointer(branch_path)
        assert (pointer["session_id"], pointer["provider"], pointer["set_by"]) == (
            CODEX_THREAD,
            "codex",
            "monitor-codex",
        )
        report = tmp_path / ".dispatch_register_root" / ".aipass" / "dispatch_reports" / "dsp-codex.json"
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["result_excerpt"].startswith("Processed the probe")
        assert data["output_tokens"] == 1871

    def test_an_error_event_on_exit_0_bounces_verbatim_once_and_never_reruns(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        code, runs, bounce, branch_path = _run_codex_main(
            monkeypatch, main_argv, tmp_path, [*CODEX_STREAM[:-1], CODEX_ERROR]
        )

        assert code == 1
        assert len(runs) == 1, "the turn ran and may have acted; a re-run would repeat it"
        bounce.assert_called_once()
        assert CODEX_ERROR in bounce.call_args.args[1]
        assert mod.session_pointer.read_pointer(branch_path) is None


# Trimmed from the three `opencode run --format json` captures of 2026-10-28; every field the parser reads is kept.
OC_SESSION = "ses_e7e57a92affeZUOP0zXJKK1vns"
OPENCODE_STREAM = [
    json.dumps({"type": "step_start", "sessionID": OC_SESSION, "part": {"type": "step-start"}}),
    json.dumps(
        {
            "type": "tool_use",
            "sessionID": OC_SESSION,
            "part": {"tool": "shell", "state": {"status": "completed", "output": "aipass-allowed-probe\n"}},
        }
    ),
    json.dumps(
        {
            "type": "step_finish",
            "sessionID": OC_SESSION,
            "part": {
                "cost": 0.25,
                "tokens": {"input": 7143, "output": 70, "reasoning": 208, "cache": {"read": 70, "write": 0}},
            },
        }
    ),
    json.dumps({"type": "text", "sessionID": OC_SESSION, "part": {"type": "text", "text": "first part"}}),
    json.dumps({"type": "step_start", "sessionID": OC_SESSION, "part": {"type": "step-start"}}),
    json.dumps(
        {
            "type": "step_finish",
            "sessionID": OC_SESSION,
            "part": {
                "cost": 0.5,
                "tokens": {"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 0, "write": 3}},
            },
        }
    ),
    json.dumps(
        {"type": "text", "sessionID": OC_SESSION, "part": {"type": "text", "text": "THROW-OK\n\ndone  \nPINEAPPLE"}}
    ),
]
OPENCODE_NO_ROUTE = json.dumps(
    {
        "type": "error",
        "sessionID": "ses_e7e564578ffewyEQdwsPIW6u2I",
        "error": {"type": "provider.no-route", "message": "Model unavailable: opencode/no-such-model"},
    }
)
OPENCODE_FREE_LIMIT = [
    json.dumps({"type": "step_start", "sessionID": "ses_aipass1793176766", "part": {"type": "step-start"}}),
    json.dumps(
        {
            "type": "error",
            "sessionID": "ses_aipass1793176766",
            "error": {
                "type": "provider.free-limit",
                "message": "Free usage limit reached.",
                "status": 429,
                "retryAfterMs": 55232000,
            },
        }
    ),
]


def _opencode_cmd(session_id="ses_aipass_built"):
    return ["opencode", "run", "--standalone", "--format", "json", "--auto", "--session", session_id, "Hi."]


class TestTheOpenCodeStream:
    def test_a_text_run_yields_its_session_the_last_text_part_and_summed_usage_and_cost(self, tmp_path):
        log = tmp_path / "stdout.log"
        _write_stream(log, OPENCODE_STREAM)

        parsed = parse_opencode_stream(str(log))

        assert parsed["session_id"] == OC_SESSION
        assert parsed["result"] == "THROW-OK\n\ndone  \nPINEAPPLE"
        assert parsed["usage"] == {
            "input_tokens": 7153,
            "output_tokens": 75,
            "reasoning_tokens": 208,
            "cache_read_input_tokens": 70,
            "cache_creation_input_tokens": 3,
        }
        assert parsed["total_cost_usd"] == 0.75 and parsed["num_turns"] == 2
        assert parsed["succeeded"] is True and parsed["error"] == "" and parsed["rate_limited"] is False

    def test_the_no_route_error_is_a_failure_carried_verbatim_and_not_a_rate_limit(self, tmp_path):
        log = tmp_path / "stdout.log"
        _write_stream(log, [OPENCODE_NO_ROUTE])

        parsed = parse_opencode_stream(str(log))

        assert parsed["succeeded"] is False and parsed["error"] == OPENCODE_NO_ROUTE
        assert parsed["rate_limited"] is False and parsed["retry_after_s"] is None

    def test_the_free_limit_429_is_a_rate_limit_with_its_retry_after_in_seconds(self, tmp_path):
        log = tmp_path / "stdout.log"
        _write_stream(log, OPENCODE_FREE_LIMIT)

        parsed = parse_opencode_stream(str(log))

        assert parsed["succeeded"] is False and parsed["error"] == OPENCODE_FREE_LIMIT[1]
        assert parsed["rate_limited"] is True and parsed["retry_after_s"] == 55232

    def test_text_followed_by_an_error_event_is_still_a_failure(self, tmp_path):
        log = tmp_path / "stdout.log"
        _write_stream(log, [*OPENCODE_STREAM, OPENCODE_NO_ROUTE])

        assert parse_opencode_stream(str(log))["succeeded"] is False


class TestTheOpenCodeRetryLadder:
    def test_attempts_1_and_2_rerun_a_resume_as_built(self, tmp_path):
        for attempt in (1, 2):
            assert cmd_for_attempt(_opencode_cmd(), attempt, tmp_path, "opencode") == (_opencode_cmd(), "resume")

    def test_strike_3_of_a_resume_drops_the_session_pair_and_keeps_the_prompt(self, tmp_path, pointer_home):
        cmd, mode = cmd_for_attempt(_opencode_cmd(), 3, tmp_path, "opencode")

        assert (cmd, mode) == (["opencode", "run", "--standalone", "--format", "json", "--auto", "Hi."], "fresh")
        assert mod.session_pointer.read_pointer(tmp_path) is None, "OpenCode mints the id: no pointer is guessed"

    def test_a_fresh_run_stays_fresh_on_every_attempt(self, tmp_path):
        fresh = ["opencode", "run", "--standalone", "--format", "json", "--auto", "Hi."]
        for attempt in (1, 2, 3):
            assert cmd_for_attempt(fresh, attempt, tmp_path, "opencode") == (fresh, "fresh")


class TestTheOpenCodeStartupProbe:
    def test_a_first_stdout_line_counts_as_started_and_claudes_probe_is_never_consulted(self, tmp_path, monkeypatch):
        import os
        import subprocess
        import sys

        monkeypatch.setattr(mod, "STARTUP_TIMEOUT", 3)
        monkeypatch.setattr(mod, "POLL_INTERVAL", 0.1)
        monkeypatch.setattr(mod.session_pointer, "transcript_dir", MagicMock(side_effect=AssertionError("probed")))
        result = run_with_startup_check(
            [sys.executable, "-c", "import time; print('{}', flush=True); time.sleep(1)"],
            str(tmp_path / "stdout.log"),
            subprocess.DEVNULL,
            str(tmp_path),
            dict(os.environ),
            "@canary",
            provider="opencode",
        )
        assert result == (0, False)


def _run_opencode_main(monkeypatch, main_argv, tmp_path, lines, exit_code=0, flags=()):
    argv, lock_file, _ = main_argv
    argv = [*argv[: argv.index("--")], "--provider=opencode", *flags, "--", *_opencode_cmd(OC_SESSION)]
    runs = []

    def fake_run(cmd, stdout_log, stderr_fh, cwd, spawn_env, *args, **kwargs):
        runs.append({"provider": kwargs.get("provider"), "env": dict(spawn_env)})
        _write_stream(stdout_log, lines)
        return exit_code, False

    bounce = MagicMock(return_value=True)
    monkeypatch.setenv("AIPASS_DISPATCH_ID", "dsp-opencode")
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr("aipass.ai_mail.apps.handlers.paths.find_repo_root", MagicMock(return_value=tmp_path / "repo"))
    with pytest.raises(SystemExit) as exc_info:
        main()
    return exc_info.value.code, runs, bounce, lock_file.parent.parent


class TestTheOpenCodeMonitorRun:
    def test_a_clean_run_points_the_branch_at_its_session_and_reports_text_tokens_and_cost(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        code, runs, bounce, branch_path = _run_opencode_main(monkeypatch, main_argv, tmp_path, OPENCODE_STREAM)

        assert code == 0 and [run["provider"] for run in runs] == ["opencode"]
        bounce.assert_not_called()
        pointer = mod.session_pointer.read_pointer(branch_path)
        assert (pointer["session_id"], pointer["provider"]) == (OC_SESSION, "opencode")
        report = tmp_path / ".dispatch_register_root" / ".aipass" / "dispatch_reports" / "dsp-opencode.json"
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["result_excerpt"].startswith("THROW-OK")
        assert (data["output_tokens"], data["total_cost_usd"], data["num_turns"]) == (75, 0.75, 2)

    def test_exit_0_without_a_text_part_fails_once_and_never_reruns(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        code, runs, bounce, _ = _run_opencode_main(monkeypatch, main_argv, tmp_path, OPENCODE_STREAM[:3])

        assert code == 1 and len(runs) == 1
        bounce.assert_called_once()
        assert "without a text part" in bounce.call_args.args[1]

    def test_the_no_route_error_bounces_its_message_verbatim_after_one_attempt(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        code, runs, bounce, branch_path = _run_opencode_main(
            monkeypatch, main_argv, tmp_path, [OPENCODE_NO_ROUTE], exit_code=1
        )

        assert code == 1 and len(runs) == 1, "the stream named the failure; a re-run meets the same answer"
        assert OPENCODE_NO_ROUTE in bounce.call_args.args[1]

    def test_the_free_limit_429_bounces_as_a_rate_limit_naming_retry_after(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        code, runs, bounce, _ = _run_opencode_main(monkeypatch, main_argv, tmp_path, OPENCODE_FREE_LIMIT, exit_code=1)

        reason = bounce.call_args.args[1]
        assert code == 1 and len(runs) == 1
        assert reason.startswith("API rate limit (opencode 429, retryAfter 55232s")
        assert "provider.free-limit" in reason

    def test_a_parents_opencode_markers_are_stripped_and_the_store_override_is_kept(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        monkeypatch.setenv("OPENCODE", "1")
        monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_parent")
        monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "store.db"))

        _, runs, _, _ = _run_opencode_main(monkeypatch, main_argv, tmp_path, OPENCODE_STREAM)

        env = runs[0]["env"]
        assert "OPENCODE" not in env and "OPENCODE_SESSION_ID" not in env
        assert env["OPENCODE_DB"] == str(tmp_path / "store.db")

    def test_the_agent_env_names_the_branch_as_pwd_because_opencode_reads_pwd_not_the_cwd(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        """02:03 canary proof: an inherited PWD filed four canary sessions under the dispatcher's directory."""
        monkeypatch.setenv("PWD", str(tmp_path / "dispatcher"))

        _, runs, _, branch_path = _run_opencode_main(monkeypatch, main_argv, tmp_path, OPENCODE_STREAM)

        assert runs[0]["env"]["PWD"] == str(branch_path.resolve())

    def test_a_failed_first_attempt_still_points_the_branch_at_the_session_opencode_minted(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        """02:16: a 429 on a fresh run left no pointer, so the next resume could not find the session."""
        _, _, _, branch_path = _run_opencode_main(monkeypatch, main_argv, tmp_path, OPENCODE_FREE_LIMIT, exit_code=1)

        pointer = mod.session_pointer.read_pointer(branch_path)
        assert (pointer["session_id"], pointer["provider"], pointer["set_by"]) == (
            "ses_aipass1793176766",
            "opencode",
            "monitor-opencode",
        )

    def test_the_callers_config_is_set_after_the_strip_and_a_parents_own_never_survives(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"model": "parent/seat"}')
        config = '{"compaction": {"buffer": 180000}}'

        _, runs, _, _ = _run_opencode_main(
            monkeypatch, main_argv, tmp_path, OPENCODE_STREAM, flags=(f"--opencode-config={config}",)
        )
        assert runs[0]["env"]["OPENCODE_CONFIG_CONTENT"] == config

    def test_without_the_flag_a_parents_config_is_stripped(self, monkeypatch, main_argv, pointer_home, tmp_path):
        monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"model": "parent/seat"}')

        _, runs, _, _ = _run_opencode_main(monkeypatch, main_argv, tmp_path, OPENCODE_STREAM)

        assert "OPENCODE_CONFIG_CONTENT" not in runs[0]["env"]


class TestTheRunRecordAfterTheRun:
    def _plant_store(self, tmp_path, monkeypatch, model):
        db = tmp_path / "opencode.db"
        with sqlite3.connect(db) as conn:
            conn.execute("create table session_message (session_id text, type text, seq int, data text)")
            conn.execute("insert into session_message values (?, 'assistant', 1, ?)", (OC_SESSION, json.dumps(model)))
        conn.close()
        monkeypatch.setenv("OPENCODE_DB", str(db))

    def test_the_observed_model_comes_from_the_runtime_row_not_the_request(
        self, monkeypatch, main_argv, pointer_home, tmp_path
    ):
        self._plant_store(tmp_path, monkeypatch, {"model": {"id": "gpt-6.1-sol", "providerID": "openai"}})
        config = '--opencode-config={"model": "opencode/asked", "provider": {"secret": "k"}}'

        _, _, _, branch_path = _run_opencode_main(monkeypatch, main_argv, tmp_path, OPENCODE_STREAM, flags=(config,))

        pointer = mod.session_pointer.read_pointer(branch_path) or {}
        assert (pointer["model_requested"], pointer["selection_source"]) == ("opencode/asked", "inline_config")
        assert (pointer["model_provider"], pointer["model_observed"]) == ("openai", "gpt-6.1-sol")
        assert pointer["observed_at"] and "secret" not in json.dumps(pointer)
        wake_back = mod.wake_sender
        assert isinstance(wake_back, MagicMock)
        assert wake_back.call_args.kwargs["run_line"] == (
            f"run: opencode · openai/gpt-6.1-sol (observed; inline_config) session {OC_SESSION}"
        )

    def test_an_unseen_model_stays_pending_and_the_bounce_says_so(self, monkeypatch, main_argv, pointer_home, tmp_path):
        monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "missing.db"))

        _, _, bounce, branch_path = _run_opencode_main(
            monkeypatch, main_argv, tmp_path, OPENCODE_FREE_LIMIT, exit_code=1
        )

        pointer = mod.session_pointer.read_pointer(branch_path) or {}
        assert (pointer["model_observed"], pointer["observed_at"]) == ("pending", None)
        assert bounce.call_args.args[1].endswith(
            f"run: opencode · cli_default (requested, observed pending; cli_default) session {pointer['session_id']}"
        )


@pytest.mark.parametrize(
    "cmd, provider, config, expected",
    [
        (["claude", "-p", "Hi", "--model", "claude-opus-5-5"], "claude", "", ("claude-opus-5-5", "flag")),
        (["codex", "exec", "-m", "gpt-6.1-sol", "--json", "Hi"], "codex", "", ("gpt-6.1-sol", "flag")),
        (["opencode", "run", "-m", "openai/x", "Hi"], "opencode", '{"model": "y"}', ("openai/x", "flag")),
        (["opencode", "run", "Hi"], "opencode", '{"model": "y"}', ("y", "inline_config")),
        (["opencode", "run", "Hi"], "opencode", "not json", ("cli_default", "cli_default")),
        (["codex", "exec", "-m"], "codex", "", ("cli_default", "cli_default")),
    ],
)
def test_the_requested_model_and_its_source_come_from_the_argv(cmd, provider, config, expected):
    run = mod.requested_run(cmd, provider, config)

    assert (run["host_cli"], run["model_requested"], run["selection_source"]) == (provider, *expected)
