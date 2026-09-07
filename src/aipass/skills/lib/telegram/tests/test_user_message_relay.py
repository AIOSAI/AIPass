# =================== AIPass ====================
# Name: test_user_message_relay.py
# Description: Tests for user message relay — UserPromptSubmit hook handler
# Version: 1.2.0
# Created: 2026-07-14
# Modified: 2026-08-28
# =============================================

"""
Tests for user_message_relay — the UserPromptSubmit hook handler that posts
user messages from non-TG doors to the branch TG chat.

Tests cover:
  - find_bot_for_cwd: env var priority, CWD matching, missing dirs, no match,
    real bot_factory naming ({bot_id}.json), offset/control-file exclusion,
    missing-chat_id fallback to sole allowed_user_id, ambiguous/no-fallback skip
  - send_user_message: formatting, truncation, network errors
  - _is_system_noise: system notifications, task notifications, local-command
    output, Caveat line, dispatch wake prompts
  - handle(): skip subagent, skip empty, skip system noise, skip TG-origin,
    skip dupe, happy path (switch pinned ON — the gate itself is covered by
    test_relay_switch_gate.py)
  - Dedup: consecutive identical messages skipped, different messages pass
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

import aipass.skills.lib.telegram.apps.handlers.user_message_relay as relay_mod
from aipass.skills.apps.handlers.json import json_handler as jh
from aipass.skills.lib.telegram.apps.handlers.user_message_relay import (
    _is_pending_tg_message,
    _is_system_noise,
    find_bot_for_cwd,
    handle,
    send_user_message,
)


# =============================================
# FIXTURES
# =============================================


@pytest.fixture(autouse=True)
def _reset_dedup():
    """Reset the dedup hash between tests."""
    relay_mod._last_relay_hash = ""
    yield
    relay_mod._last_relay_hash = ""


@pytest.fixture(autouse=True)
def _switch_on(tmp_path, monkeypatch):
    """Pin the skills switch ON in a temp dir for this whole file.

    handle() consults the skills off-switch first (relay v1.5.0). Without this
    these tests read the LIVE switch_state.json, so every relay assertion would
    silently depend on whether telegram happens to be switched on on this
    machine — and with telegram off since 2026-08-18 they would all fail while
    the relay itself is perfectly correct. This file tests relay behaviour; the
    gate has its own file, test_relay_switch_gate.py.

    The redirect is the AIPASS_TEST_LOG_DIR seam the fleet json service reads
    per call (DPLAN-0325); the directory is measured off the service so it
    cannot drift from where the switch actually looks.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    state_dir = jh.get_json_path("switch", "data").parent
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "switch_state.json").write_text(
        json.dumps({"skills": {"telegram": {"enabled": True}}}), encoding="utf-8"
    )


@pytest.fixture()
def bot_dirs(tmp_path):
    """Create mirror + pending dirs with a test bot file."""
    mirror = tmp_path / "mirror"
    pending = tmp_path / "pending"
    mirror.mkdir()
    pending.mkdir()

    work = tmp_path / "branch_workdir"
    work.mkdir()

    bot_data = {
        "chat_id": 42,
        "bot_token": "123:FAKETOKEN",
        "work_dir": str(work),
        "bot_id": "test_bot",
    }
    (mirror / "test_bot.json").write_text(json.dumps(bot_data))

    with (
        patch.object(relay_mod, "MIRROR_DIR", mirror),
        patch.object(relay_mod, "PENDING_DIR", pending),
    ):
        yield {"mirror": mirror, "pending": pending, "work": work, "bot_data": bot_data}


# =============================================
# 1. find_bot_for_cwd
# =============================================


class TestFindBotForCwd:
    def test_finds_by_cwd_match(self, bot_dirs):
        result = find_bot_for_cwd(str(bot_dirs["work"]))
        assert result is not None
        assert result["chat_id"] == 42
        assert result["bot_token"] == "123:FAKETOKEN"

    def test_finds_by_cwd_subdirectory(self, bot_dirs):
        sub = bot_dirs["work"] / "some" / "subdir"
        sub.mkdir(parents=True)
        result = find_bot_for_cwd(str(sub))
        assert result is not None
        assert result["chat_id"] == 42

    def test_returns_none_no_match(self, bot_dirs):
        result = find_bot_for_cwd("/tmp/nowhere")
        assert result is None

    def test_env_var_priority(self, bot_dirs):
        with patch.dict("os.environ", {"AIPASS_BOT_ID": "test_bot"}):
            result = find_bot_for_cwd("/tmp/anywhere")
        assert result is not None
        assert result["bot_id"] == "test_bot"

    def test_env_var_missing_bot(self, tmp_path):
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        with (
            patch.object(relay_mod, "MIRROR_DIR", mirror),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "pending"),
            patch.dict("os.environ", {"AIPASS_BOT_ID": "nonexistent"}),
        ):
            result = find_bot_for_cwd("/tmp")
        assert result is None

    def test_skips_bot_without_chat_id(self, tmp_path):
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        (mirror / "bad.json").write_text(json.dumps({"bot_token": "tok", "work_dir": "/tmp"}))
        with (
            patch.object(relay_mod, "MIRROR_DIR", mirror),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "pending"),
        ):
            result = find_bot_for_cwd("/tmp")
        assert result is None

    def test_skips_corrupt_json(self, tmp_path):
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        (mirror / "bad.json").write_text("not json{{{")
        with (
            patch.object(relay_mod, "MIRROR_DIR", mirror),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "pending"),
        ):
            result = find_bot_for_cwd("/tmp")
        assert result is None

    def test_real_bot_factory_naming_resolves(self, tmp_path):
        """MIRROR_DIR shadow files are named {bot_id}.json — no 'bot-' prefix."""
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        work = tmp_path / "work"
        work.mkdir()
        bot_data = {"chat_id": 7235222625, "bot_token": "tok", "work_dir": str(work), "bot_id": "devpulse"}
        (mirror / "devpulse.json").write_text(json.dumps(bot_data))
        with (
            patch.object(relay_mod, "MIRROR_DIR", mirror),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "pending"),
        ):
            result = find_bot_for_cwd(str(work))
        assert result is not None
        assert result["bot_id"] == "devpulse"

    def test_offset_and_lock_files_excluded(self, tmp_path):
        """Non-bot json siblings (*_offset.json, control files) never match."""
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        work = tmp_path / "work"
        work.mkdir()
        (mirror / "devpulse_offset.json").write_text(json.dumps({"offset": 123, "updated": "now"}))
        (mirror / "prax_monitor_control.json").write_text(json.dumps({"paused": False, "level": "all"}))
        bot_data = {"chat_id": 7235222625, "bot_token": "tok", "work_dir": str(work), "bot_id": "devpulse"}
        (mirror / "devpulse.json").write_text(json.dumps(bot_data))
        with (
            patch.object(relay_mod, "MIRROR_DIR", mirror),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "pending"),
        ):
            result = find_bot_for_cwd(str(work))
        assert result is not None
        assert result["chat_id"] == 7235222625

    def test_missing_chat_id_falls_back_to_sole_allowed_user(self, tmp_path):
        """A private Telegram chat's chat_id equals its sole authorized user_id."""
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        work = tmp_path / "work"
        work.mkdir()
        bot_data = {
            "bot_token": "tok",
            "work_dir": str(work),
            "bot_id": "devpulse",
            "allowed_user_ids": [7235222625],
        }
        (mirror / "devpulse.json").write_text(json.dumps(bot_data))
        with (
            patch.object(relay_mod, "MIRROR_DIR", mirror),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "pending"),
        ):
            result = find_bot_for_cwd(str(work))
        assert result is not None
        assert result["chat_id"] == 7235222625

    def test_missing_chat_id_multiple_allowed_users_skips(self, tmp_path):
        """Can't safely guess which user's chat — ambiguous, so skip silently."""
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        work = tmp_path / "work"
        work.mkdir()
        bot_data = {
            "bot_token": "tok",
            "work_dir": str(work),
            "bot_id": "shared",
            "allowed_user_ids": [111, 222],
        }
        (mirror / "shared.json").write_text(json.dumps(bot_data))
        with (
            patch.object(relay_mod, "MIRROR_DIR", mirror),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "pending"),
        ):
            result = find_bot_for_cwd(str(work))
        assert result is None

    def test_missing_chat_id_no_allowed_users_skips(self, tmp_path):
        """No chat_id and no allowed_user_ids to fall back on — skip, no crash."""
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        work = tmp_path / "work"
        work.mkdir()
        bot_data = {"bot_token": "tok", "work_dir": str(work), "bot_id": "sync_test", "allowed_user_ids": []}
        (mirror / "sync_test.json").write_text(json.dumps(bot_data))
        with (
            patch.object(relay_mod, "MIRROR_DIR", mirror),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "pending"),
        ):
            result = find_bot_for_cwd(str(work))
        assert result is None

    def test_missing_dirs_no_crash(self, tmp_path):
        with (
            patch.object(relay_mod, "MIRROR_DIR", tmp_path / "nope1"),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "nope2"),
        ):
            result = find_bot_for_cwd("/tmp")
        assert result is None

    def test_pending_dir_fallback(self, tmp_path):
        mirror = tmp_path / "mirror"
        pending = tmp_path / "pending"
        mirror.mkdir()
        pending.mkdir()
        work = tmp_path / "work"
        work.mkdir()
        bot_data = {"chat_id": 99, "bot_token": "tok", "work_dir": str(work)}
        (pending / "bot-pend.json").write_text(json.dumps(bot_data))
        with (
            patch.object(relay_mod, "MIRROR_DIR", mirror),
            patch.object(relay_mod, "PENDING_DIR", pending),
        ):
            result = find_bot_for_cwd(str(work))
        assert result is not None
        assert result["chat_id"] == 99


# =============================================
# 2. send_user_message
# =============================================


class TestSendUserMessage:
    def test_sends_formatted_message(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        _urlopen = "aipass.skills.lib.telegram.apps.handlers.user_message_relay.urlopen"
        with patch(_urlopen, return_value=mock_resp) as mock_url:
            result = send_user_message("tok", 42, "hello world")
        assert result is True
        call_args = mock_url.call_args
        req = call_args[0][0]
        body = json.loads(req.data)
        assert body["chat_id"] == 42
        assert "hello world" in body["text"]
        assert body["disable_notification"] is True

    def test_origin_tag_in_message(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        _urlopen = "aipass.skills.lib.telegram.apps.handlers.user_message_relay.urlopen"
        with patch(_urlopen, return_value=mock_resp) as mock_url:
            send_user_message("tok", 42, "test", origin="TERM")
        body = json.loads(mock_url.call_args[0][0].data)
        assert body["text"].startswith("TERM\n")

    def test_truncation_at_4096(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        _urlopen = "aipass.skills.lib.telegram.apps.handlers.user_message_relay.urlopen"
        with patch(_urlopen, return_value=mock_resp) as mock_url:
            send_user_message("tok", 42, "x" * 5000)
        body = json.loads(mock_url.call_args[0][0].data)
        assert len(body["text"]) <= 4096

    def test_network_error_returns_false(self):
        with patch(
            "aipass.skills.lib.telegram.apps.handlers.user_message_relay.urlopen",
            side_effect=Exception("network down"),
        ):
            result = send_user_message("tok", 42, "test")
        assert result is False


# =============================================
# 3. handle() — hook handler
# =============================================


class TestHandle:
    def test_skips_identified_subagent(self):
        result = handle({"agent_id": "agent-123", "prompt": "hello"})
        assert result["exit_code"] == 0

    def test_allows_agent_type_claude(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            handle(
                {
                    "agent_type": "claude",
                    "agent_id": "",
                    "prompt": "hello",
                    "cwd": str(bot_dirs["work"]),
                }
            )
        mock_send.assert_called_once()

    def test_skips_empty_prompt(self):
        result = handle({"prompt": ""})
        assert result["exit_code"] == 0

    def test_skips_whitespace_only(self):
        result = handle({"prompt": "   "})
        assert result["exit_code"] == 0

    def test_skips_missing_prompt(self):
        result = handle({})
        assert result["exit_code"] == 0

    def test_skips_tg_origin(self):
        result = handle({"prompt": "Patrick via Telegram: hello"})
        assert result["exit_code"] == 0

    def test_skips_no_bot_found(self, tmp_path):
        with (
            patch.object(relay_mod, "MIRROR_DIR", tmp_path / "nope1"),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "nope2"),
        ):
            result = handle({"prompt": "hello", "cwd": "/tmp/nowhere"})
        assert result["exit_code"] == 0

    def test_happy_path_relays(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            result = handle({"prompt": "hello world", "cwd": str(bot_dirs["work"])})
        assert result["exit_code"] == 0
        mock_send.assert_called_once_with("123:FAKETOKEN", 42, "hello world")

    def test_happy_path_has_sound_key(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=True):
            result = handle({"prompt": "hello world", "cwd": str(bot_dirs["work"])})
        assert result["sound"] == "user message relay"

    def test_send_failure_no_sound_key(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=False):
            result = handle({"prompt": "hello world", "cwd": str(bot_dirs["work"])})
        assert "sound" not in result

    def test_skips_no_bot_found_no_sound_key(self, tmp_path):
        with (
            patch.object(relay_mod, "MIRROR_DIR", tmp_path / "nope1"),
            patch.object(relay_mod, "PENDING_DIR", tmp_path / "nope2"),
        ):
            result = handle({"prompt": "hello", "cwd": "/tmp/nowhere"})
        assert "sound" not in result

    def test_updates_dedup_hash_on_success(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=True):
            handle({"prompt": "hello", "cwd": str(bot_dirs["work"])})
        assert relay_mod._last_relay_hash != ""

    def test_skips_consecutive_duplicate(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            handle({"prompt": "hello", "cwd": str(bot_dirs["work"])})
            handle({"prompt": "hello", "cwd": str(bot_dirs["work"])})
        mock_send.assert_called_once()

    def test_allows_different_after_dupe(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            handle({"prompt": "hello", "cwd": str(bot_dirs["work"])})
            handle({"prompt": "world", "cwd": str(bot_dirs["work"])})
        assert mock_send.call_count == 2

    def test_no_dedup_on_send_failure(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=False) as mock_send:
            handle({"prompt": "hello", "cwd": str(bot_dirs["work"])})
            handle({"prompt": "hello", "cwd": str(bot_dirs["work"])})
        assert mock_send.call_count == 2

    def test_exception_returns_clean(self, bot_dirs):
        with patch.object(relay_mod, "find_bot_for_cwd", side_effect=RuntimeError("boom")):
            result = handle({"prompt": "hello", "cwd": "/tmp"})
        assert result["exit_code"] == 0

    def test_skips_system_notification(self):
        result = handle({"prompt": "[SYSTEM NOTIFICATION - NOT USER INPUT]\nSome event happened"})
        assert result["exit_code"] == 0

    def test_skips_task_notification(self):
        result = handle({"prompt": "Some text\n<task-notification>\n<task-id>abc</task-id>\n</task-notification>"})
        assert result["exit_code"] == 0

    def test_skips_local_command_output(self):
        result = handle({"prompt": "output\n<command-name>/help</command-name>"})
        assert result["exit_code"] == 0

    def test_skips_local_command_stdout(self):
        result = handle({"prompt": "ran a command\n<local-command-stdout>stuff</local-command-stdout>"})
        assert result["exit_code"] == 0

    def test_skips_caveat_line(self):
        prompt = "Caveat: messages below were generated by the user while running local commands\nsome output"
        result = handle({"prompt": prompt})
        assert result["exit_code"] == 0

    def test_skips_dispatch_wake(self):
        result = handle(
            {"prompt": ("Hi. Check inbox, process new emails, update memories when done. IMPORTANT: delete lock file")}
        )
        assert result["exit_code"] == 0

    def test_genuine_message_still_relays(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            handle({"prompt": "Can you fix that bug?", "cwd": str(bot_dirs["work"])})
        mock_send.assert_called_once()

    def test_skips_pending_tg_message(self, bot_dirs):
        pending_data = {
            "chat_id": 42,
            "bot_token": "123:FAKETOKEN",
            "bot_id": "test_bot",
            "injected_prompt": "hello from TG",
            "timestamp": time.time(),
        }
        (bot_dirs["pending"] / "bot-test_bot.json").write_text(json.dumps(pending_data))
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            result = handle({"prompt": "hello from TG", "cwd": str(bot_dirs["work"])})
        assert result["exit_code"] == 0
        mock_send.assert_not_called()

    def test_allows_message_no_pending(self, bot_dirs):
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            handle({"prompt": "hello from terminal", "cwd": str(bot_dirs["work"])})
        mock_send.assert_called_once()

    def test_allows_message_stale_pending(self, bot_dirs):
        pending_data = {
            "chat_id": 42,
            "bot_token": "123:FAKETOKEN",
            "bot_id": "test_bot",
            "injected_prompt": "hello from TG",
            "timestamp": time.time() - 300,
        }
        (bot_dirs["pending"] / "bot-test_bot.json").write_text(json.dumps(pending_data))
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            handle({"prompt": "hello from TG", "cwd": str(bot_dirs["work"])})
        mock_send.assert_called_once()

    def test_allows_message_delivered_pending(self, bot_dirs):
        pending_data = {
            "chat_id": 42,
            "bot_token": "123:FAKETOKEN",
            "bot_id": "test_bot",
            "injected_prompt": "hello from TG",
            "timestamp": time.time(),
            "delivered": True,
        }
        (bot_dirs["pending"] / "bot-test_bot.json").write_text(json.dumps(pending_data))
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            handle({"prompt": "hello from TG", "cwd": str(bot_dirs["work"])})
        mock_send.assert_called_once()

    def test_allows_message_different_text_pending(self, bot_dirs):
        pending_data = {
            "chat_id": 42,
            "bot_token": "123:FAKETOKEN",
            "bot_id": "test_bot",
            "injected_prompt": "something else entirely",
            "timestamp": time.time(),
        }
        (bot_dirs["pending"] / "bot-test_bot.json").write_text(json.dumps(pending_data))
        with patch.object(relay_mod, "send_user_message", return_value=True) as mock_send:
            handle({"prompt": "hello from terminal", "cwd": str(bot_dirs["work"])})
        mock_send.assert_called_once()


# =============================================
# 4. _is_pending_tg_message — unit tests
# =============================================


class TestIsPendingTgMessage:
    def test_matches_fresh_pending(self, bot_dirs):
        pending_data = {
            "injected_prompt": "test msg",
            "timestamp": time.time(),
        }
        (bot_dirs["pending"] / "bot-test_bot.json").write_text(json.dumps(pending_data))
        assert _is_pending_tg_message("test msg", {"bot_id": "test_bot"}) is True

    def test_no_match_different_text(self, bot_dirs):
        pending_data = {
            "injected_prompt": "other msg",
            "timestamp": time.time(),
        }
        (bot_dirs["pending"] / "bot-test_bot.json").write_text(json.dumps(pending_data))
        assert _is_pending_tg_message("test msg", {"bot_id": "test_bot"}) is False

    def test_no_match_stale(self, bot_dirs):
        pending_data = {
            "injected_prompt": "test msg",
            "timestamp": time.time() - 300,
        }
        (bot_dirs["pending"] / "bot-test_bot.json").write_text(json.dumps(pending_data))
        assert _is_pending_tg_message("test msg", {"bot_id": "test_bot"}) is False

    def test_no_match_delivered(self, bot_dirs):
        pending_data = {
            "injected_prompt": "test msg",
            "timestamp": time.time(),
            "delivered": True,
        }
        (bot_dirs["pending"] / "bot-test_bot.json").write_text(json.dumps(pending_data))
        assert _is_pending_tg_message("test msg", {"bot_id": "test_bot"}) is False

    def test_no_bot_id(self):
        assert _is_pending_tg_message("test", {}) is False

    def test_no_pending_file(self, bot_dirs):
        assert _is_pending_tg_message("test", {"bot_id": "nonexistent"}) is False

    def test_corrupt_pending_file(self, bot_dirs):
        (bot_dirs["pending"] / "bot-test_bot.json").write_text("not json{{{")
        assert _is_pending_tg_message("test", {"bot_id": "test_bot"}) is False

    def test_no_injected_prompt_field(self, bot_dirs):
        pending_data = {"timestamp": time.time()}
        (bot_dirs["pending"] / "bot-test_bot.json").write_text(json.dumps(pending_data))
        assert _is_pending_tg_message("test", {"bot_id": "test_bot"}) is False


# =============================================
# 5. _is_system_noise — unit tests
# =============================================


class TestIsSystemNoise:
    def test_system_notification_prefix(self):
        assert _is_system_noise("[SYSTEM NOTIFICATION - NOT USER INPUT]\nblah") is True

    def test_task_notification_tag(self):
        assert _is_system_noise("prefix\n<task-notification>\nstuff") is True

    def test_command_name_tag(self):
        assert _is_system_noise("<command-name>/foo</command-name>") is True

    def test_local_command_stdout_tag(self):
        assert _is_system_noise("<local-command-stdout>output</local-command-stdout>") is True

    def test_caveat_line(self):
        assert _is_system_noise("messages below were generated by the user while running local commands") is True

    def test_dispatch_wake_prefix(self):
        assert _is_system_noise("Hi. Check inbox, process new emails, update memories when done.") is True

    def test_genuine_message_passes(self):
        assert _is_system_noise("Can you fix that bug?") is False

    def test_empty_passes(self):
        assert _is_system_noise("") is False

    def test_partial_match_not_triggered(self):
        assert _is_system_noise("I got a SYSTEM NOTIFICATION today") is False

    def test_dispatch_prefix_mid_message_not_triggered(self):
        assert _is_system_noise("He said Hi. Check inbox, process new emails") is False
