"""Tests for email send handler -- send_to_single, send_to_broadcast, collect_interactive_input,
and resolve_dispatch_target from send_args."""

import pytest
from unittest.mock import patch, MagicMock

from aipass.ai_mail.apps.handlers.email.send import (
    send_to_single,
    send_to_broadcast,
    collect_interactive_input,
)
from aipass.ai_mail.apps.handlers.email.send_args import (
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


def _make_user_info() -> dict:
    """Build a minimal user_info dict for send tests."""
    return {
        "email_address": "@trigger",
        "display_name": "TRIGGER",
        "mailbox_path": "/tmp/trigger/.ai_mail.local",
        "timestamp_format": "%Y-%m-%d %H:%M:%S",
    }


def test_send_to_single_happy_path():
    """Successful single send returns (True, None)."""
    mock_create = MagicMock(return_value="/tmp/email_file.json")
    mock_load = MagicMock(return_value={"subject": "Test", "message": "Body"})
    mock_deliver = MagicMock(return_value=(True, ""))
    mock_callback = MagicMock()
    mock_log = MagicMock()
    mock_update = MagicMock()

    success, error = send_to_single(
        to_branch="@backup",
        subject="Test subject",
        message="Test body",
        user_info=_make_user_info(),
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
    mock_load.assert_called_once_with("/tmp/email_file.json")
    mock_deliver.assert_called_once()
    mock_log.assert_called_once_with("email_sent", {"to": "@backup", "subject": "Test subject", "auto_execute": False})


def test_send_to_single_load_fails():
    """Returns (False, error) when email file cannot be loaded."""
    mock_create = MagicMock(return_value="/tmp/email_file.json")
    mock_load = MagicMock(return_value=None)
    mock_deliver = MagicMock()
    mock_log = MagicMock()

    success, error = send_to_single(
        to_branch="@backup",
        subject="Test",
        message="Body",
        user_info=_make_user_info(),
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


def test_send_to_single_delivery_fails():
    """Returns (False, error) when delivery function reports failure."""
    mock_create = MagicMock(return_value="/tmp/email_file.json")
    mock_load = MagicMock(return_value={"subject": "Test", "message": "Body"})
    mock_deliver = MagicMock(return_value=(False, "Branch offline"))
    mock_log = MagicMock()

    success, error = send_to_single(
        to_branch="@backup",
        subject="Test",
        message="Body",
        user_info=_make_user_info(),
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


def test_send_to_single_sets_auto_execute():
    """auto_execute flag is set on email_data before delivery."""
    captured_data = {}

    def mock_deliver(to, data, on_delivered=None):
        """Capture delivery data for assertion."""
        captured_data.update(data)
        return (True, "")

    mock_create = MagicMock(return_value="/tmp/email.json")
    mock_load = MagicMock(return_value={"subject": "Test", "message": "Body"})

    send_to_single(
        to_branch="@flow",
        subject="Test",
        message="Body",
        user_info=_make_user_info(),
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


# ---- send_to_broadcast tests ---------------------------------


def test_send_to_broadcast_happy_path():
    """Successful broadcast returns (True, success_count, total, results)."""
    branches = [
        {"email": "@flow", "name": "FLOW"},
        {"email": "@backup", "name": "BACKUP"},
    ]
    mock_create = MagicMock(return_value="/tmp/broadcast.json")
    mock_load = MagicMock(return_value={"subject": "Announce", "message": "Hello all"})
    mock_deliver = MagicMock(return_value=(True, ""))
    mock_log = MagicMock()

    ok, success_count, total, results = send_to_broadcast(
        subject="Announce",
        message="Hello all",
        user_info=_make_user_info(),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        branches=branches,
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=mock_deliver,
        on_delivered_callback=None,
        log_operation_fn=mock_log,
        update_central_fn=None,
    )

    assert ok is True
    assert success_count == 2
    assert total == 2
    assert isinstance(results, list)
    assert len(results) == 2


def test_send_to_broadcast_load_fails():
    """Returns failure when email file cannot be loaded."""
    branches = [{"email": "@flow", "name": "FLOW"}]
    mock_create = MagicMock(return_value="/tmp/broadcast.json")
    mock_load = MagicMock(return_value=None)
    mock_log = MagicMock()

    ok, success_count, total, error = send_to_broadcast(
        subject="Announce",
        message="Hello",
        user_info=_make_user_info(),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        branches=branches,
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=MagicMock(),
        on_delivered_callback=None,
        log_operation_fn=mock_log,
        update_central_fn=None,
    )

    assert ok is False
    assert success_count == 0
    assert "could not be loaded" in error


def test_send_to_broadcast_partial_failure():
    """Partial delivery failure returns correct counts."""
    branches = [
        {"email": "@flow", "name": "FLOW"},
        {"email": "@backup", "name": "BACKUP"},
        {"email": "@memory", "name": "MEMORY"},
    ]
    mock_create = MagicMock(return_value="/tmp/broadcast.json")
    mock_load = MagicMock(return_value={"subject": "Test", "message": "Body"})
    # First and third succeed, second fails
    mock_deliver = MagicMock(side_effect=[(True, ""), (False, "offline"), (True, "")])
    mock_log = MagicMock()

    ok, success_count, total, results = send_to_broadcast(
        subject="Test",
        message="Body",
        user_info=_make_user_info(),
        auto_execute=False,
        no_memory_save=False,
        reply_to=None,
        dispatched_to=None,
        branches=branches,
        create_email_file_fn=mock_create,
        load_email_file_fn=mock_load,
        deliver_email_to_branch_fn=mock_deliver,
        on_delivered_callback=None,
        log_operation_fn=mock_log,
        update_central_fn=None,
    )

    assert ok is True  # At least one succeeded
    assert success_count == 2
    assert total == 3
    assert results[1][1] is False  # Second branch failed
    assert results[1][2] == "offline"


# ---- collect_interactive_input tests --------------------------


def test_collect_interactive_input_refuses_without_a_terminal():
    """No TTY means nobody can answer the prompt -- refuse instead of blocking.

    `drone @ai_mail email` with no args reached this function through a routed
    subprocess whose stdin is an open pipe nobody writes to, so input() blocked
    until drone's 30s timeout killed it (measured live, APLAN-0006). EOFError
    never came: the pipe was open, just silent. The guard has to be the terminal
    check, because "no input yet" and "no input ever" are indistinguishable here.
    """
    branches = [{"email": "@flow", "name": "FLOW"}]

    with patch("sys.stdin.isatty", return_value=False):
        with patch("builtins.input", side_effect=AssertionError("must not prompt without a TTY")):
            result = collect_interactive_input(branches)

    assert result is None


def test_collect_interactive_input_still_prompts_on_a_terminal():
    """A real terminal is unaffected -- the guard must not disable interactive send."""
    branches = [{"email": "@flow", "name": "FLOW"}]

    with patch("sys.stdin.isatty", return_value=True):
        with patch("builtins.input", side_effect=["1", "Subject", EOFError, "y"]):
            result = collect_interactive_input(branches)

    assert result is None or result["to"] == "@flow"


def test_collect_interactive_input_cancelled_on_eof():
    """Returns None when input raises EOFError (cancelled).

    isatty is pinned True in these three: pytest's stdin is not a terminal, so
    without it the no-TTY guard returns None first and each one would pass
    without ever reaching the branch it names.
    """
    branches = [{"email": "@flow", "name": "FLOW"}]

    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=EOFError):
        result = collect_interactive_input(branches)

    assert result is None


def test_collect_interactive_input_cancelled_on_keyboard_interrupt():
    """Returns None when input raises KeyboardInterrupt."""
    branches = [{"email": "@flow", "name": "FLOW"}]

    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=KeyboardInterrupt):
        result = collect_interactive_input(branches)

    assert result is None


def test_collect_interactive_input_invalid_selection():
    """Returns None when user enters non-numeric selection."""
    branches = [{"email": "@flow", "name": "FLOW"}]

    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="abc"):
        result = collect_interactive_input(branches)

    assert result is None


# ---- resolve_dispatch_target tests ----------------------------


def test_resolve_dispatch_target_no_auto_execute():
    """Returns None when auto_execute is False."""
    result = resolve_dispatch_target("@flow", False)

    assert result is None


def test_resolve_dispatch_target_email_address():
    """Returns the branch email when auto_execute is True and branch starts with @."""
    result = resolve_dispatch_target("@flow", True)

    assert result == "@flow"


def test_resolve_dispatch_target_path_with_registry_lookup():
    """Returns registry email when path resolves via get_branch_info_fn."""
    mock_fn = MagicMock(return_value={"email": "@trigger", "name": "TRIGGER"})

    result = resolve_dispatch_target("/home/user/trigger", True, get_branch_info_fn=mock_fn)

    assert result == "@trigger"
    mock_fn.assert_called_once()


def test_resolve_dispatch_target_path_without_registry():
    """Returns fallback @dirname when no registry function provided."""
    result = resolve_dispatch_target("/home/user/flow", True, get_branch_info_fn=None)

    assert result == "@flow"


def test_resolve_dispatch_target_path_registry_not_found():
    """Returns fallback @dirname when registry lookup returns None."""
    mock_fn = MagicMock(return_value=None)

    result = resolve_dispatch_target("/home/user/backup", True, get_branch_info_fn=mock_fn)

    assert result == "@backup"


def test_resolve_dispatch_target_tilde_path():
    """Handles ~ prefixed paths by extracting the directory name."""
    result = resolve_dispatch_target("~/Projects/flow", True, get_branch_info_fn=None)

    assert result == "@flow"


# ---- parse_send_args multi-arg message tests (S84 fix) --------


def test_parse_send_args_joins_split_message():
    """When message body is split into multiple args, all are joined."""
    from aipass.ai_mail.apps.handlers.email.send_args import parse_send_args

    result = parse_send_args(["@target", "Subject", "Line one", "Line two", "Line three"])
    assert result["mode"] == "direct"
    assert result["subject"] == "Subject"
    assert result["message"] == "Line one Line two Line three"


def test_parse_send_args_single_message_unchanged():
    """Single message arg is not altered."""
    from aipass.ai_mail.apps.handlers.email.send_args import parse_send_args

    result = parse_send_args(["@target", "Subject", "Complete body here"])
    assert result["mode"] == "direct"
    assert result["message"] == "Complete body here"


def test_parse_send_args_multiline_body_preserved():
    """A single arg with embedded newlines passes through intact."""
    from aipass.ai_mail.apps.handlers.email.send_args import parse_send_args

    body = "First line\nSecond line\nThird line"
    result = parse_send_args(["@target", "Subject", body])
    assert result["message"] == body
