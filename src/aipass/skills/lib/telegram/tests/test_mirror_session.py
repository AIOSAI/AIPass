# =================== AIPass ====================
# Name: test_mirror_session.py
# Description: Tests for TDPLAN-0009 FINISH — mirror session launch, transcript resolver, create→attach
# Version: 1.0.0
# Created: 2026-06-29
# Modified: 2026-06-29
# =============================================

"""
Tests for the mirror session system (TDPLAN-0009 FINISH).

Covers:
  - launch_mirror_session: tmux session with --dangerously-skip-permissions
  - start_service: systemd user service start
  - create_bot mirror params: shared_session, attach_only, chat_id in config
  - _resolve_active_transcript: PID-based transcript detection
  - _write_mirror_mapping: transcript-change detection and rewrite
  - _config_chat_id initialization
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot
from aipass.skills.lib.telegram.apps.handlers.bot_factory import (
    launch_mirror_session,
    start_service,
)


# =============================================
# Fixtures
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


def _make_bot(tmp_path, _patch_base_bot_deps, attach_only=False, shared_session=None):
    workdir = tmp_path / "workdir"
    workdir.mkdir(exist_ok=True)
    with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path):
        bot = BaseBot(
            bot_id="mirror_test",
            bot_token="123:FAKETOKEN",
            work_dir=workdir,
            bot_name="Mirror Test Bot",
            allowed_user_ids=[111],
            branch_name="api",
            shared_session=shared_session,
            attach_only=attach_only,
        )
    bot.send_message = MagicMock(return_value={"ok": True, "message_id": 1})
    return bot


# =============================================
# 1. launch_mirror_session
# =============================================


class TestLaunchMirrorSession:
    """Tests for launch_mirror_session() in bot_factory."""

    def test_creates_tmux_session_with_skip_perms(self):
        """tmux new-session created and claude launched with skip-permissions."""
        no_session = MagicMock(returncode=1)
        ok = MagicMock(returncode=0)
        side = [no_session, ok, ok, ok]

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", side_effect=side),
            patch("time.sleep"),
        ):
            result = launch_mirror_session(
                session_name="telegram-api",
                bot_id="api",
                work_dir="/tmp/test",
            )

        assert result is True

    def test_claude_launched_with_correct_flags(self):
        """AIPASS_SESSION_TYPE=interactive-mirror and skip-perms flag set."""
        calls_made = []
        first_call = True

        def _track(*args, **kwargs):
            """Record subprocess.run calls for assertion."""
            nonlocal first_call
            calls_made.append(args[0] if args else kwargs.get("args", []))
            if first_call:
                first_call = False
                return MagicMock(returncode=1)
            result = MagicMock(returncode=0)
            return result

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", side_effect=_track),
            patch("time.sleep"),
        ):
            launch_mirror_session(
                session_name="telegram-api",
                bot_id="api",
                work_dir="/tmp/test",
            )

        send_keys_calls = [c for c in calls_made if "send-keys" in c]
        claude_cmd = send_keys_calls[-1][-2]
        assert "interactive-mirror" in claude_cmd

    def test_idempotent_if_session_exists(self):
        """Returns True without creating if session already exists."""
        has_session = MagicMock(returncode=0)

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", return_value=has_session
        ) as mock_run:
            result = launch_mirror_session(session_name="telegram-api", bot_id="api", work_dir="/tmp/test")

        assert result is True
        assert mock_run.call_count == 1

    def test_returns_false_when_tmux_not_found(self):
        """Returns False when tmux is not installed."""
        with patch(
            "aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", side_effect=FileNotFoundError
        ):
            result = launch_mirror_session(session_name="telegram-api", bot_id="api", work_dir="/tmp/test")

        assert result is False


# =============================================
# 2. start_service
# =============================================


class TestStartService:
    """Tests for start_service() in bot_factory."""

    def test_starts_systemd_service(self):
        """Calls systemctl --user start telegram-bot@{bot_id}."""
        mock_result = MagicMock(returncode=0)
        with patch(
            "aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = start_service("api")

        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["systemctl", "--user", "start", "telegram-bot@api"]

    def test_returns_false_on_failure(self):
        """Returns False when systemctl returns non-zero."""
        mock_result = MagicMock(returncode=1, stderr="unit not found")
        with patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", return_value=mock_result):
            assert start_service("api") is False

    def test_returns_false_on_timeout(self):
        """Returns False on TimeoutExpired."""
        import subprocess

        err = subprocess.TimeoutExpired(cmd="", timeout=10)
        with patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", side_effect=err):
            assert start_service("api") is False


# =============================================
# 3. create_bot mirror params
# =============================================


class TestCreateBotMirror:
    """Tests for create_bot() with mirror params."""

    @pytest.fixture
    def _mock_create_deps(self):
        """Mock all external deps of create_bot."""
        bot_info = {"username": "test_bot", "id": 123}
        branch_info = {"name": "api", "path": "/home/test/api"}
        patches = [
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.validate_token", return_value=bot_info),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.validate_branch", return_value=branch_info),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.get_bot", return_value=None),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.get_bot_by_branch", return_value=None),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.ensure_registry"),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory._api_set_secret"),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.register_bot", return_value=True),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.set_bot_commands"),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.build_botfather_commands", return_value=[]),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.enable_service", return_value=True),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.start_bot_process", return_value=True),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.launch_mirror_session", return_value=True),
            patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.start_service", return_value=True),
            # BOT_CONFIG_DIR is redirected per test by the conftest autouse fixture;
            # the tests that read the written file override it with their own tmp_path.
        ]
        mocks = {}
        started = []
        for p in patches:
            m = p.start()
            started.append(p)
            name = p.attribute if hasattr(p, "attribute") and p.attribute else str(p).split(".")[-1].rstrip("'>)")
            mocks[name] = m
        yield mocks
        for p in started:
            p.stop()

    def test_config_includes_mirror_fields(self, _mock_create_deps, tmp_path):
        """Config written with shared_session, attach_only, chat_id."""
        from aipass.skills.lib.telegram.apps.handlers.bot_factory import create_bot

        with patch("aipass.skills.lib.telegram.apps.handlers.config.BOT_CONFIG_DIR", tmp_path):
            result = create_bot(
                bot_id="api",
                bot_token="123:FAKE",
                branch_name="api",
                shared_session="telegram-api",
                attach_only=True,
                chat_id=42,
            )

        assert result is not None
        config_file = tmp_path / "api.json"
        assert config_file.exists()
        config = json.loads(config_file.read_text())
        assert config["shared_session"] == "telegram-api"
        assert config["attach_only"] is True
        assert config["chat_id"] == 42

    def test_launches_mirror_session_when_attach_only(self, _mock_create_deps, tmp_path):
        """launch_mirror_session called when shared_session + attach_only."""
        from aipass.skills.lib.telegram.apps.handlers.bot_factory import create_bot

        with patch("aipass.skills.lib.telegram.apps.handlers.config.BOT_CONFIG_DIR", tmp_path):
            create_bot(
                bot_id="api",
                bot_token="123:FAKE",
                branch_name="api",
                shared_session="telegram-api",
                attach_only=True,
            )

        _mock_create_deps["launch_mirror_session"].assert_called_once()

    def test_starts_via_systemd_when_mirror(self, _mock_create_deps, tmp_path):
        """Mirror bot started via start_service, not start_bot_process."""
        from aipass.skills.lib.telegram.apps.handlers.bot_factory import create_bot

        with patch("aipass.skills.lib.telegram.apps.handlers.config.BOT_CONFIG_DIR", tmp_path):
            create_bot(
                bot_id="api",
                bot_token="123:FAKE",
                branch_name="api",
                shared_session="telegram-api",
                attach_only=True,
            )

        _mock_create_deps["start_service"].assert_called_once()
        _mock_create_deps["start_bot_process"].assert_not_called()

    def test_starts_via_popen_when_not_mirror(self, _mock_create_deps, tmp_path):
        """Non-mirror bot still uses start_bot_process."""
        from aipass.skills.lib.telegram.apps.handlers.bot_factory import create_bot

        with patch("aipass.skills.lib.telegram.apps.handlers.config.BOT_CONFIG_DIR", tmp_path):
            create_bot(
                bot_id="api",
                bot_token="123:FAKE",
                branch_name="api",
            )

        _mock_create_deps["start_bot_process"].assert_called_once()
        _mock_create_deps["launch_mirror_session"].assert_not_called()


# =============================================
# 4. Transcript resolution and mapping rewrite
# =============================================


class TestMirrorMappingRewrite:
    """Tests for transcript-change detection in _write_mirror_mapping."""

    def test_mapping_rewrites_on_transcript_change(self, tmp_path, _patch_base_bot_deps):
        """When transcript path changes, mapping is rewritten with new cursor."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, attach_only=True, shared_session="api")
        bot._active_chat_id = 42
        bot.session_name = "api"

        mapping_dir = tmp_path / ".aipass" / "telegram_bots"

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch.object(bot, "_resolve_active_transcript", return_value=("/path/a.jsonl", 10)):
                bot._write_mirror_mapping()

            assert bot._mirror_mapping_written is True
            assert bot._last_transcript_path == "/path/a.jsonl"
            data1 = json.loads((mapping_dir / "bot-mirror_test.json").read_text())
            assert data1["transcript_line_after"] == 10

            with patch.object(bot, "_resolve_active_transcript", return_value=("/path/b.jsonl", 5)):
                bot._write_mirror_mapping()

            data2 = json.loads((mapping_dir / "bot-mirror_test.json").read_text())
            assert data2["transcript_line_after"] == 5
            assert bot._last_transcript_path == "/path/b.jsonl"

    def test_mapping_not_rewritten_same_transcript(self, tmp_path, _patch_base_bot_deps):
        """When transcript path unchanged, mapping is not rewritten."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, attach_only=True, shared_session="api")
        bot._active_chat_id = 42
        bot.session_name = "api"

        mapping_dir = tmp_path / ".aipass" / "telegram_bots"

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch.object(bot, "_resolve_active_transcript", return_value=("/path/a.jsonl", 10)):
                bot._write_mirror_mapping()
                mtime1 = (mapping_dir / "bot-mirror_test.json").stat().st_mtime

            import time

            time.sleep(0.05)

            with patch.object(bot, "_resolve_active_transcript", return_value=("/path/a.jsonl", 20)):
                bot._write_mirror_mapping()
                mtime2 = (mapping_dir / "bot-mirror_test.json").stat().st_mtime

        assert mtime1 == mtime2

    def test_mapping_rewrites_when_transcript_none(self, tmp_path, _patch_base_bot_deps):
        """When transcript is None both times, still written only once."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, attach_only=True, shared_session="api")
        bot._active_chat_id = 42
        bot.session_name = "api"

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch.object(bot, "_resolve_active_transcript", return_value=(None, 0)):
                bot._write_mirror_mapping()
                assert bot._mirror_mapping_written is True
                bot._write_mirror_mapping()

    def test_last_transcript_path_updated(self, tmp_path, _patch_base_bot_deps):
        """_last_transcript_path updated after successful write."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, attach_only=True, shared_session="api")
        bot._active_chat_id = 42
        bot.session_name = "api"

        assert bot._last_transcript_path is None

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch.object(bot, "_resolve_active_transcript", return_value=("/path/transcript.jsonl", 15)):
                bot._write_mirror_mapping()

        assert bot._last_transcript_path == "/path/transcript.jsonl"


# =============================================
# 5. Transcript resolver
# =============================================


class TestResolveActiveTranscript:
    """Tests for _resolve_active_transcript."""

    def test_returns_none_when_no_projects_dir(self, tmp_path, _patch_base_bot_deps):
        """Returns (None, 0) when projects dir does not exist."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        with patch("pathlib.Path.home", return_value=tmp_path):
            path, count = bot._resolve_active_transcript()
        assert path is None
        assert count == 0

    def test_returns_none_when_no_jsonl_files(self, tmp_path, _patch_base_bot_deps):
        """Returns (None, 0) when projects dir exists but no JSONL files."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        slug = str(bot.work_dir).replace("\\", "-").replace("/", "-")
        projects_dir = tmp_path / ".claude" / "projects" / slug
        projects_dir.mkdir(parents=True, exist_ok=True)

        with patch("pathlib.Path.home", return_value=tmp_path):
            path, count = bot._resolve_active_transcript()
        assert path is None
        assert count == 0

    def test_falls_back_to_recent_mtime(self, tmp_path, _patch_base_bot_deps):
        """Uses most recent JSONL when PID check fails and file is < 5min old."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        slug = str(bot.work_dir).replace("\\", "-").replace("/", "-")
        projects_dir = tmp_path / ".claude" / "projects" / slug
        projects_dir.mkdir(parents=True, exist_ok=True)

        transcript = projects_dir / "abc123.jsonl"
        transcript.write_text('{"type":"message"}\n{"type":"response"}\n')

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.object(bot, "_get_tmux_pane_pid", return_value=None),
        ):
            path, count = bot._resolve_active_transcript()

        assert path == str(transcript)
        assert count == 2

    def test_ignores_old_files(self, tmp_path, _patch_base_bot_deps):
        """JSONL files older than 5 minutes are not selected."""
        import os

        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        slug = str(bot.work_dir).replace("\\", "-").replace("/", "-")
        projects_dir = tmp_path / ".claude" / "projects" / slug
        projects_dir.mkdir(parents=True, exist_ok=True)

        transcript = projects_dir / "old.jsonl"
        transcript.write_text('{"type":"message"}\n')
        old_time = 1000000.0
        os.utime(transcript, (old_time, old_time))

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch.object(bot, "_get_tmux_pane_pid", return_value=None),
        ):
            path, count = bot._resolve_active_transcript()

        assert path is None
        assert count == 0


# =============================================
# 6. _config_chat_id init
# =============================================


class TestConfigChatId:
    """Tests for _config_chat_id initialization."""

    def test_config_chat_id_initialized_to_none(self, tmp_path, _patch_base_bot_deps):
        """BaseBot.__init__ initializes _config_chat_id to None."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._config_chat_id is None

    def test_config_chat_id_settable(self, tmp_path, _patch_base_bot_deps):
        """_config_chat_id can be set after construction."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._config_chat_id = 42
        assert bot._config_chat_id == 42


# =============================================
# A host without tmux (FPLAN-0554 round three)
# =============================================


class TestLaunchMirrorSessionWithoutTmux:
    """has-session already refuses a missing tmux. These are the three calls after it."""

    def test_new_session_without_tmux_returns_false(self):
        side = [MagicMock(returncode=1), FileNotFoundError("tmux")]
        with patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", side_effect=side) as mock_run:
            result = launch_mirror_session(session_name="telegram-api", bot_id="api", work_dir="/tmp/test")

        assert result is False
        assert mock_run.call_count == 2

    def test_export_send_keys_without_tmux_returns_false(self):
        """A session nobody typed into is not a mirror session - True would claim one."""
        side = [MagicMock(returncode=1), MagicMock(returncode=0), FileNotFoundError("tmux")]
        with patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", side_effect=side) as mock_run:
            result = launch_mirror_session(session_name="telegram-api", bot_id="api", work_dir="/tmp/test")

        assert result is False
        assert mock_run.call_count == 3

    def test_claude_send_keys_without_tmux_returns_false(self):
        side = [MagicMock(returncode=1), MagicMock(returncode=0), MagicMock(returncode=0), FileNotFoundError("tmux")]
        with patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.subprocess.run", side_effect=side) as mock_run:
            result = launch_mirror_session(session_name="telegram-api", bot_id="api", work_dir="/tmp/test")

        assert result is False
        assert mock_run.call_count == 4
