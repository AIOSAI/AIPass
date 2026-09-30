# =================== AIPass ====================
# Name: test_send_helpers.py
# Description: Tests for email send handler and send_args dispatch resolution
# Version: 1.0.3
# Created: 2026-04-25
# Modified: 2026-09-29
# =============================================

"""Tests for apps/handlers/email/send.py and apps/handlers/email/send_args.py."""

# Covers send_to_single, send_to_broadcast, collect_interactive_input,
# resolve_dispatch_target and parse_send_args.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(logging) — send_to_single()'s exact console/log wording, only its return value
# seedgo: no-test-needed(logging) — send_to_single()'s trigger-import warning; its central-update warning is pinned
# seedgo: no-test-needed(shared) — send_to_single()'s refused path: tests/test_refused_sends.py
# seedgo: no-test-needed(shared) — send_to_single()'s upsert key: tests/test_upsert.py

import io

import pytest
from pathlib import PureWindowsPath
from unittest.mock import patch, MagicMock

import aipass.ai_mail.apps.handlers.email.send as send_mod
from aipass.ai_mail.apps.handlers.email.send import (
    send_to_single,
    send_to_broadcast,
    collect_interactive_input,
)
from aipass.ai_mail.apps.handlers.email.send_args import (
    parse_send_args,
    resolve_dispatch_target,
)


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.send.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _silence_send_args_json_handler():
    """Prevent log_operation in send_args from writing real JSON files."""
    with patch("aipass.ai_mail.apps.handlers.email.send_args.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


# ---- send_to_single tests ------------------------------------


def _make_user_info(tmp_path) -> dict:
    """Build a minimal user_info dict for send tests."""
    return {
        "email_address": "@trigger",
        "display_name": "TRIGGER",
        "mailbox_path": str(tmp_path / "trigger" / ".ai_mail.local"),
        "timestamp_format": "%Y-%m-%d %H:%M:%S",
    }


def test_send_to_single_happy_path(tmp_path, recorded_bus):
    """Successful single send returns (True, None) and fires email_sent once."""
    email_file = str(tmp_path / "email_file.json")
    mock_create = MagicMock(return_value=email_file)
    mock_load = MagicMock(return_value={"subject": "Test", "message": "Body"})
    mock_deliver = MagicMock(return_value=(True, ""))
    mock_callback = MagicMock()
    mock_log = MagicMock()
    mock_update = MagicMock()

    success, error = send_to_single(
        to_branch="@backup",
        subject="Test subject",
        message="Test body",
        user_info=_make_user_info(tmp_path),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=mock_deliver,
        on_delivered_callback=mock_callback,
        log_operation_fn=mock_log,
        update_central_fn=mock_update,
    )

    assert success is True
    assert error is None
    mock_create.assert_called_once()
    mock_load.assert_called_once_with(email_file)
    mock_deliver.assert_called_once()
    mock_log.assert_called_once_with("email_sent", {"to": "@backup", "subject": "Test subject", "auto_execute": False})
    assert recorded_bus.fires == [("email_sent", {"to": "@backup", "subject": "Test subject", "auto_execute": False})]


def test_send_to_single_a_failed_central_update_is_logged_not_fatal(tmp_path, monkeypatch):
    """The mail landed, so a failed central update keeps (True, None) and warns naming the recipient.

    Leg 3: was owed. Its proof is its mutant: the recipient dropped from the warning.
    """
    logger = MagicMock()
    monkeypatch.setattr(send_mod, "logger", logger)
    failure = OSError("central unwritable")

    success, error = send_to_single(
        to_branch="@backup",
        subject="Test subject",
        message="Test body",
        user_info=_make_user_info(tmp_path),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        create_email_file_fn=MagicMock(return_value=str(tmp_path / "email_file.json")),
        load_email_file_fn=MagicMock(return_value={"subject": "Test", "message": "Body"}),
        deliver_email_to_branch_fn=MagicMock(return_value=(True, "")),
        on_delivered_callback=MagicMock(),
        log_operation_fn=MagicMock(),
        update_central_fn=MagicMock(side_effect=failure),
    )

    assert (success, error) == (True, None)
    logger.warning.assert_called_once_with("[send] update_central_fn failed after send to %s: %s", "@backup", failure)


def test_send_to_single_load_fails(tmp_path):
    """Returns (False, error) when email file cannot be loaded."""
    mock_create = MagicMock(return_value=str(tmp_path / "email_file.json"))
    mock_load = MagicMock(return_value=None)
    mock_deliver = MagicMock()
    mock_log = MagicMock()

    success, error = send_to_single(
        to_branch="@backup",
        subject="Test",
        message="Body",
        user_info=_make_user_info(tmp_path),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=mock_deliver,
        on_delivered_callback=None,
        log_operation_fn=mock_log,
        update_central_fn=None,
    )

    assert success is False
    assert error is not None
    assert "could not be loaded" in error
    mock_deliver.assert_not_called()


def test_send_to_single_delivery_fails(tmp_path, recorded_bus):
    """Returns (False, error) when delivery function reports failure, and fires nothing."""
    mock_create = MagicMock(return_value=str(tmp_path / "email_file.json"))
    mock_load = MagicMock(return_value={"subject": "Test", "message": "Body"})
    mock_deliver = MagicMock(return_value=(False, "Branch offline"))
    mock_log = MagicMock()

    success, error = send_to_single(
        to_branch="@backup",
        subject="Test",
        message="Body",
        user_info=_make_user_info(tmp_path),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=mock_deliver,
        on_delivered_callback=None,
        log_operation_fn=mock_log,
        update_central_fn=None,
    )

    assert success is False
    assert error == "Branch offline"
    assert recorded_bus.fires == [], "a refused send must not announce email_sent"


def test_send_to_single_sets_auto_execute(tmp_path, recorded_bus):
    """auto_execute flag is set on email_data before delivery and carried on the email_sent fire."""
    captured_data = {}

    def mock_deliver(to, data, on_delivered=None):
        """Capture delivery data for assertion."""
        captured_data.update(data)
        return (True, "")

    mock_create = MagicMock(return_value=str(tmp_path / "email.json"))
    mock_load = MagicMock(return_value={"subject": "Test", "message": "Body"})

    send_to_single(
        to_branch="@flow",
        subject="Test",
        message="Body",
        user_info=_make_user_info(tmp_path),
        auto_execute=True,
        no_memory_save=True,
        reply_to=None,
        dispatched_to="@flow",
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=mock_deliver,
        on_delivered_callback=None,
        log_operation_fn=MagicMock(),
        update_central_fn=None,
    )

    assert captured_data["auto_execute"] is True
    assert captured_data["dispatched_to"] == "@flow"
    assert captured_data["no_memory_save"] is True
    assert recorded_bus.fires == [("email_sent", {"to": "@flow", "subject": "Test", "auto_execute": True})]


# ---- send_to_broadcast tests ---------------------------------


def test_send_to_broadcast_happy_path(tmp_path, recorded_bus):
    """Successful broadcast returns (True, success_count, total, results) and fires once."""
    branches = [
        {"email": "@flow", "name": "FLOW"},
        {"email": "@backup", "name": "BACKUP"},
    ]
    mock_create = MagicMock(return_value=str(tmp_path / "broadcast.json"))
    mock_load = MagicMock(return_value={"subject": "Announce", "message": "Hello all"})
    mock_deliver = MagicMock(return_value=(True, ""))
    mock_log = MagicMock()

    ok, success_count, total, results = send_to_broadcast(
        subject="Announce",
        message="Hello all",
        user_info=_make_user_info(tmp_path),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        branches=branches,
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=mock_deliver,
        log_operation_fn=mock_log,
        update_central_fn=None,
    )

    assert ok is True
    assert success_count == 2
    assert total == 2
    assert isinstance(results, list)
    assert len(results) == 2
    assert recorded_bus.fires == [("email_broadcast_sent", {"recipients": 2, "successful": 2, "subject": "Announce"})]


def test_send_to_broadcast_load_fails(tmp_path):
    """Returns failure when email file cannot be loaded."""
    branches = [{"email": "@flow", "name": "FLOW"}]
    mock_create = MagicMock(return_value=str(tmp_path / "broadcast.json"))
    mock_load = MagicMock(return_value=None)
    mock_log = MagicMock()

    ok, success_count, total, error = send_to_broadcast(
        subject="Announce",
        message="Hello",
        user_info=_make_user_info(tmp_path),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        branches=branches,
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=MagicMock(),
        log_operation_fn=mock_log,
        update_central_fn=None,
    )

    assert ok is False
    assert success_count == 0
    assert "could not be loaded" in error


def test_send_to_broadcast_partial_failure(tmp_path, recorded_bus):
    """Partial delivery failure returns correct counts, and the fire carries them."""
    branches = [
        {"email": "@flow", "name": "FLOW"},
        {"email": "@backup", "name": "BACKUP"},
        {"email": "@memory", "name": "MEMORY"},
    ]
    mock_create = MagicMock(return_value=str(tmp_path / "broadcast.json"))
    mock_load = MagicMock(return_value={"subject": "Test", "message": "Body"})
    # First and third succeed, second fails
    mock_deliver = MagicMock(side_effect=[(True, ""), (False, "offline"), (True, "")])
    mock_log = MagicMock()

    ok, success_count, total, results = send_to_broadcast(
        subject="Test",
        message="Body",
        user_info=_make_user_info(tmp_path),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        branches=branches,
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=mock_deliver,
        log_operation_fn=mock_log,
        update_central_fn=None,
    )

    assert ok is True  # At least one succeeded
    assert success_count == 2
    assert total == 3
    assert results[1][1] is False  # Second branch failed
    assert results[1][2] == "offline"
    assert recorded_bus.fires == [("email_broadcast_sent", {"recipients": 3, "successful": 2, "subject": "Test"})]


# ---- collect_interactive_input tests --------------------------


class _Terminal(io.StringIO):
    """A stdin that says it is a terminal, answers input() from a script, and counts reads."""

    reads = 0

    def isatty(self) -> bool:
        return True

    def readline(self, size: int = -1) -> str:
        self.reads += 1
        return super().readline(size)


class _InterruptedTerminal(_Terminal):
    """A terminal whose user presses Ctrl-C at the first prompt."""

    def readline(self, size: int = -1) -> str:
        self.reads += 1
        raise KeyboardInterrupt


def test_collect_interactive_input_refuses_without_a_terminal(monkeypatch):
    """No TTY means nobody can answer the prompt -- refuse instead of blocking.

    `drone @ai_mail email` with no args reached this function through a routed
    subprocess whose stdin is an open pipe nobody writes to, so input() blocked
    until drone's 30s timeout killed it (measured live, APLAN-0006). EOFError
    never came: the pipe was open, just silent. The guard has to be the terminal
    check, because "no input yet" and "no input ever" are indistinguishable here.
    """
    branches = [{"email": "@flow", "name": "FLOW"}]
    # A pipe with an answer waiting in it: the guard must refuse before reading it.
    pipe = io.StringIO("1\n")
    monkeypatch.setattr("sys.stdin", pipe)

    result = collect_interactive_input(branches)

    assert result is None
    assert pipe.tell() == 0, "must not prompt without a TTY"


def test_collect_interactive_input_still_prompts_on_a_terminal(monkeypatch):
    """A real terminal is unaffected -- the guard must not disable interactive send."""
    branches = [{"email": "@flow", "name": "FLOW"}]
    terminal = _Terminal("1\nSubject\n")
    monkeypatch.setattr("sys.stdin", terminal)

    result = collect_interactive_input(branches)

    # MEASURED 2026-09-08: the third prompt raises EOFError, so the result is
    # None and ``result["to"]`` was never reached. The ``or`` meant this unit
    # proved nothing about the guard it is named for. What the guard must not do
    # is swallow the prompt, so that is what is asserted — and the None it
    # returns after the cancel is pinned rather than tolerated.
    # Driven through sys.stdin (the edge input() reads) rather than builtins.input:
    # both answers consumed proves the recipient and subject prompts both ran.
    # Three prompts read: recipient, subject, and the message prompt that met EOF.
    # (A tell() taken after read() equalled the script length whatever the product read.)
    assert terminal.reads == 3, "the no-TTY guard must not disable the prompt on a real terminal"
    assert terminal.read() == ""
    assert result is None


def test_collect_interactive_input_cancelled_on_eof(monkeypatch):
    """Returns None when input raises EOFError (cancelled).

    isatty is pinned True in these three: pytest's stdin is not a terminal, so
    without it the no-TTY guard returns None first and each one would pass
    without ever reaching the branch it names.
    _Terminal is what pins it now: a stdin that says it is a terminal.
    """
    branches = [{"email": "@flow", "name": "FLOW"}]
    terminal = _Terminal("")
    monkeypatch.setattr("sys.stdin", terminal)

    result = collect_interactive_input(branches)

    assert result is None
    assert terminal.reads == 1, "the recipient prompt must have been reached and met end of input"


def test_collect_interactive_input_cancelled_on_keyboard_interrupt(monkeypatch):
    """Returns None when input raises KeyboardInterrupt."""
    branches = [{"email": "@flow", "name": "FLOW"}]
    terminal = _InterruptedTerminal("")
    monkeypatch.setattr("sys.stdin", terminal)

    result = collect_interactive_input(branches)

    assert result is None
    assert terminal.reads == 1, "the recipient prompt must have been reached and interrupted"


def test_collect_interactive_input_invalid_selection(monkeypatch):
    """Returns None when user enters non-numeric selection."""
    branches = [{"email": "@flow", "name": "FLOW"}]
    terminal = _Terminal("abc\nSubject\n")
    monkeypatch.setattr("sys.stdin", terminal)

    result = collect_interactive_input(branches)

    assert result is None
    assert terminal.read() == "Subject\n", "only the selection is read; a bad one stops before the subject"


# ---- resolve_dispatch_target tests ----------------------------


def test_resolve_dispatch_target_no_auto_execute():
    """Returns None when auto_execute is False."""
    result = resolve_dispatch_target("@flow", False)

    assert result is None


def test_resolve_dispatch_target_email_address():
    """Returns the branch email when auto_execute is True and branch starts with @."""
    result = resolve_dispatch_target("@flow", True)

    assert result == "@flow"


def test_resolve_dispatch_target_path_with_registry_lookup(tmp_path):
    """Returns registry email when path resolves via get_branch_info_fn."""
    mock_fn = MagicMock(return_value={"email": "@trigger", "name": "TRIGGER"})

    result = resolve_dispatch_target(str(tmp_path / "trigger"), True, get_branch_info_fn=mock_fn)

    assert result == "@trigger"
    mock_fn.assert_called_once()


def test_resolve_dispatch_target_path_without_registry(tmp_path):
    """Returns fallback @dirname when no registry function provided."""
    result = resolve_dispatch_target(str(tmp_path / "flow"), True, get_branch_info_fn=None)

    assert result == "@flow"


def test_resolve_dispatch_target_path_registry_not_found(tmp_path):
    """Returns fallback @dirname when registry lookup returns None."""
    mock_fn = MagicMock(return_value=None)

    result = resolve_dispatch_target(str(tmp_path / "backup"), True, get_branch_info_fn=mock_fn)

    assert result == "@backup"


def test_resolve_dispatch_target_tilde_path():
    """Handles ~ prefixed paths by extracting the directory name."""
    result = resolve_dispatch_target("~/Projects/flow", True, get_branch_info_fn=None)

    assert result == "@flow"


def test_resolve_dispatch_target_knows_a_windows_drive_path():
    """A drive-letter path is a path, not an address (mutant: drop the PureWindowsPath test)."""
    windows_path = str(PureWindowsPath("C:\\") / "work" / "src" / "ai_mail")
    looked_up = []

    result = resolve_dispatch_target(windows_path, True, get_branch_info_fn=looked_up.append)

    assert result == "@ai_mail"
    assert len(looked_up) == 1


# ---- parse_send_args multi-arg message tests (S84 fix) --------


def test_parse_send_args_joins_split_message():
    """When message body is split into multiple args, all are joined."""
    result = parse_send_args(["@target", "Subject", "Line one", "Line two", "Line three"])
    assert result["mode"] == "direct"
    assert result["subject"] == "Subject"
    assert result["message"] == "Line one Line two Line three"


def test_parse_send_args_single_message_unchanged():
    """Single message arg is not altered."""
    result = parse_send_args(["@target", "Subject", "Complete body here"])
    assert result["mode"] == "direct"
    assert result["message"] == "Complete body here"


def test_parse_send_args_multiline_body_preserved():
    """A single arg with embedded newlines passes through intact."""
    body = "First line\nSecond line\nThird line"
    result = parse_send_args(["@target", "Subject", body])
    assert result["message"] == body


# ---- Broadcast aggregates ONCE -------------------------------------
#
# update_central() rescans every branch inbox from the repo root; it takes no
# arguments and derives everything itself, so calling it per recipient computes
# the same global answer N times over. On 2026-08-27 an 18-recipient @all spent
# ~55s of its ~60s doing exactly that -- 19 full-tree scans -- and was killed by
# drone's 60s cap after every message had already been delivered.


def test_broadcast_aggregates_central_once_not_per_recipient(tmp_path, recorded_bus):
    """One @all send = one central aggregation, whatever the recipient count.

    Red-first: the loop passed on_delivered to every delivery, so an 18-branch
    broadcast aggregated 19 times (once per recipient, once after the loop).
    """
    branches = [{"email": f"@b{i}", "name": f"B{i}"} for i in range(18)]

    # One counter for EVERY aggregation, whoever triggers it.
    aggregations = MagicMock()

    def per_recipient_callback(*_args, **_kwargs):
        aggregations()

    branch_path = str(tmp_path / "branch" / "path")

    def deliver(_email, _data, on_delivered=None):
        if on_delivered is not None:
            on_delivered(branch_path, 1, 0, 1)
        return True, ""

    ok, success_count, total, results = send_to_broadcast(
        subject="Announce",
        message="Hello all",
        user_info=_make_user_info(tmp_path),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        branches=branches,
        create_email_file_fn=MagicMock(return_value=str(tmp_path / "broadcast.json")),
        load_email_file_fn=MagicMock(return_value={"subject": "Announce", "message": "Hello all"}),
        deliver_email_to_branch_fn=deliver,
        log_operation_fn=MagicMock(),
        update_central_fn=per_recipient_callback,
    )

    assert ok is True
    assert success_count == 18, "every recipient must still be delivered"
    assert len(results) == 18
    assert aggregations.call_count == 1, (
        f"broadcast aggregated {aggregations.call_count}x for 18 recipients; the scan is global and must run once"
    )
    assert recorded_bus.events() == ["email_broadcast_sent"], "one broadcast announces once, not per recipient"
