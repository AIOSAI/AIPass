# =================== AIPass ====================
# Name: test_stop_verb.py
# Description: Tests for /stop control verb, slash-injection guard, and pending-hygiene timeout
# Version: 1.0.0
# Created: 2026-07-31
# Modified: 2026-07-31
# =============================================

"""
Tests for the devpulse-dispatched /stop hardening (2026-07-31 live incident).

- /stop is intercepted before injection: resolves the mirrored tmux session
  and sends a real Escape keypress, never injects raw text.
- Slash guard: any other unregistered '/xyz' gets a leading space before
  injection (TUI treats as plain text) instead of morphing into an unrelated
  registered command. Exact-match passthrough allowlist still injects as-is.
- Pending hygiene: an undelivered pending gives up after
  PENDING_STUCK_TIMEOUT_SECONDS instead of spinning "Processing..." forever.
"""

import json
import time

import pytest
from unittest.mock import patch, MagicMock

from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot


# =============================================
# HELPERS
# =============================================


@pytest.fixture
def _patch_base_bot_deps(tmp_path):
    patches = [
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path),
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.signal.signal"),
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.atexit.register"),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


def _make_bot(tmp_path, _patch_base_bot_deps, branch_name=None):
    workdir = tmp_path / "workdir"
    workdir.mkdir(exist_ok=True)
    with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
        bot = BaseBot(
            bot_id="test_bot",
            bot_token="123:FAKETOKEN",
            work_dir=workdir,
            bot_name="Test Bot",
            allowed_user_ids=[111],
            branch_name=branch_name,
        )
    bot.send_message = MagicMock(return_value={"ok": True, "message_id": 1})
    return bot


def _run(returncode=0, stdout="", stderr=b""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# =============================================
# /stop
# =============================================


class TestStopVerb:
    def test_stop_sends_escape_and_confirms(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.session_name = "telegram-test_bot"

        with (
            patch.object(bot, "ensure_tmux_session", return_value=True),
            patch("subprocess.run", return_value=_run()) as mock_run,
        ):
            bot._handle_control_stop(chat_id=1)

        mock_run.assert_called_once_with(
            ["tmux", "send-keys", "-t", "telegram-test_bot", "Escape"],
            check=True,
            capture_output=True,
        )
        bot.send_message.assert_called_once_with(1, "stopped - session interrupted")  # type: ignore[union-attr]

    def test_stop_no_live_session(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch.object(bot, "ensure_tmux_session", return_value=False),
            patch("subprocess.run") as mock_run,
        ):
            bot._handle_control_stop(chat_id=1)

        mock_run.assert_not_called()
        bot.send_message.assert_called_once_with(1, "No live Claude session to stop.")  # type: ignore[union-attr]

    def test_stop_tmux_not_found(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.session_name = "telegram-test_bot"

        with (
            patch.object(bot, "ensure_tmux_session", return_value=True),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            bot._handle_control_stop(chat_id=1)

        bot.send_message.assert_called_once_with(1, "tmux not found on this machine.")  # type: ignore[union-attr]

    def test_stop_send_keys_fails(self, tmp_path, _patch_base_bot_deps):
        import subprocess

        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.session_name = "telegram-test_bot"

        with (
            patch.object(bot, "ensure_tmux_session", return_value=True),
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["tmux"], stderr=b"boom"),
            ),
        ):
            bot._handle_control_stop(chat_id=1)

        bot.send_message.assert_called_once_with(1, "Failed to stop — see logs.")  # type: ignore[union-attr]

    def test_stop_settles_undelivered_pending(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.session_name = "telegram-test_bot"

        bot.pending_file.parent.mkdir(parents=True, exist_ok=True)
        bot.pending_file.write_text(
            json.dumps(
                {
                    "chat_id": 1,
                    "message_id": 50,
                    "processing_message_id": 99,
                    "delivered": False,
                    "timestamp": time.time(),
                }
            )
        )

        with (
            patch.object(bot, "ensure_tmux_session", return_value=True),
            patch.object(bot, "_stop_heartbeat") as mock_stop_hb,
            patch.object(bot, "edit_message") as mock_edit,
            patch("subprocess.run", return_value=_run()),
        ):
            bot._handle_control_stop(chat_id=1)

        mock_stop_hb.assert_called_once()
        mock_edit.assert_called_once_with(1, 99, "⏹ Stopped by user")
        assert not bot.pending_file.exists()

    def test_stop_delivered_pending_not_edited(self, tmp_path, _patch_base_bot_deps):
        """A pending already marked delivered gets removed silently, no spurious edit."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.session_name = "telegram-test_bot"

        bot.pending_file.parent.mkdir(parents=True, exist_ok=True)
        bot.pending_file.write_text(
            json.dumps(
                {
                    "chat_id": 1,
                    "processing_message_id": 99,
                    "delivered": True,
                    "timestamp": time.time(),
                }
            )
        )

        with (
            patch.object(bot, "ensure_tmux_session", return_value=True),
            patch.object(bot, "edit_message") as mock_edit,
            patch("subprocess.run", return_value=_run()),
        ):
            bot._handle_control_stop(chat_id=1)

        mock_edit.assert_not_called()
        assert not bot.pending_file.exists()

    def test_stop_dispatches_via_dispatch_command(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch.object(bot, "_handle_control_stop") as mock_handler:
            handled = bot._dispatch_command(chat_id=1, parsed=("stop", ""))

        assert handled is True
        mock_handler.assert_called_once_with(1)

    def test_stop_works_on_branch_bot_not_just_control_bot(self, tmp_path, _patch_base_bot_deps):
        """/stop applies to every bot — unlike /start /kill /suspend it's not gated to control bots."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="devpulse")

        with patch.object(bot, "_handle_control_stop") as mock_handler:
            handled = bot._dispatch_command(chat_id=1, parsed=("stop", ""))

        assert handled is True
        mock_handler.assert_called_once_with(1)


# =============================================
# SLASH-INJECTION GUARD
# =============================================


class TestSlashInjectionGuard:
    @pytest.mark.parametrize("cmd", ["clear", "compact", "prep", "memo"])
    def test_default_allowlist_passes_through_unchanged(self, tmp_path, _patch_base_bot_deps, cmd):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        text = f"/{cmd}"
        assert bot._guard_slash_injection(text) == text

    def test_unregistered_command_gets_leading_space(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._guard_slash_injection("/notacommand hello") == " /notacommand hello"

    def test_plain_text_unaffected(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._guard_slash_injection("hello world") == "hello world"

    def test_configurable_allowlist_override(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.config.load_bot_config",
            return_value={"passthrough_commands": ["mycustom"]},
        ):
            assert bot._guard_slash_injection("/mycustom") == "/mycustom"
            assert bot._guard_slash_injection("/clear") == " /clear"

    def test_load_bot_config_failure_falls_back_to_default(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.config.load_bot_config",
            side_effect=Exception("secrets store down"),
        ):
            assert bot._guard_slash_injection("/clear") == "/clear"
            assert bot._guard_slash_injection("/notacommand") == " /notacommand"

    def test_handle_message_injects_passthrough_unchanged(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch.object(bot, "ensure_tmux_session", return_value=True),
            patch.object(bot, "clean_stale_pending"),
            patch.object(bot, "write_pending_file", return_value=True),
            patch.object(bot, "inject_message", return_value=True) as mock_inject,
            patch.object(bot, "_start_heartbeat"),
        ):
            bot.handle_message(1, "/clear", {"message_id": 100})

        mock_inject.assert_called_once_with("/clear")

    def test_handle_message_injects_unregistered_with_leading_space(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch.object(bot, "ensure_tmux_session", return_value=True),
            patch.object(bot, "clean_stale_pending"),
            patch.object(bot, "write_pending_file", return_value=True),
            patch.object(bot, "inject_message", return_value=True) as mock_inject,
            patch.object(bot, "_start_heartbeat"),
        ):
            bot.handle_message(1, "/notacommand hello", {"message_id": 100})

        mock_inject.assert_called_once_with(" /notacommand hello")


# =============================================
# PENDING HYGIENE TIMEOUT
# =============================================


class TestPendingStuckTimeout:
    def test_fail_stuck_pending_edits_placeholder_and_removes_file(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot.pending_file.parent.mkdir(parents=True, exist_ok=True)
        bot.pending_file.write_text(json.dumps({"chat_id": 1, "delivered": False}))

        with patch.object(bot, "edit_message") as mock_edit:
            bot._fail_stuck_pending(chat_id=1, processing_msg_id=99, elapsed=700.0)

        mock_edit.assert_called_once_with(1, 99, "⚠️ Not delivered — session busy or command swallowed.")
        assert not bot.pending_file.exists()

    def test_fail_stuck_pending_no_crash_if_file_missing(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch.object(bot, "edit_message") as mock_edit:
            bot._fail_stuck_pending(chat_id=1, processing_msg_id=99, elapsed=700.0)

        mock_edit.assert_called_once()
