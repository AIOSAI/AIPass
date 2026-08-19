# =================== AIPass ====================
# Name: test_control_verbs.py
# Description: Tests for TG control verbs v1 (/start /kill /status) — DPLAN-0270 P1
# Version: 1.0.0
# Created: 2026-07-29
# Modified: 2026-07-29
# =============================================

"""
Tests for TG control verbs v1 on the base bot (DPLAN-0270 P1, v1.1).

- /start <branch> (default aipass) wakes a terminal agent: reports already-running
  without spawning a second, resolves branch path via registry, spawns tmux +
  claude -c (falls back to plain claude), confirms "woke <branch>".
- /kill <branch> kills the tmux session, confirms result, or reports not-running.
- /status (control bots only) lists aipass-* tmux sessions with branch + PID + alive.
- Control verbs apply to control bots (branch_name is None OR "aipass" — the
  deployed base bot's persisted config sets branch_name="aipass", so it must
  be treated as the control bot it is). Other branch bots fall through
  unchanged (plain /start welcome text preserved, /kill is not intercepted).
"""

from unittest.mock import patch, MagicMock

import pytest

from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot, CONTROL_SESSION_PREFIX


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
            bot_id="base",
            bot_token="123:FAKETOKEN",
            work_dir=workdir,
            bot_name="AIPass Bot",
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
# /start
# =============================================


class TestControlStart:
    def test_bare_start_spawns_nothing(self, tmp_path, _patch_base_bot_deps):
        """Every Telegram client sends a bare /start when a chat is opened.

        It is a greeting, not a command. It previously defaulted to @aipass and
        spawned an INTERACTIVE `claude -c || claude` in that branch's home; the
        ghost then tripped wake.py's occupancy gate and @aipass's real headless
        dispatch wake was REFUSED (6 measured occurrences, 07-29 to 08-11).
        This test replaces test_start_default_branch_is_aipass, which pinned it.
        """
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch("subprocess.run", return_value=_run(returncode=1)) as mock_run,
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch",
                return_value={"name": "aipass", "path": "/tmp/aipass"},
            ) as mock_validate,
        ):
            bot._handle_control_start(chat_id=1, branch_arg="")

        mock_run.assert_not_called()  # no has-session, no new-session, no send-keys
        mock_validate.assert_not_called()  # never even resolves a branch
        sent = bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "start" in sent.lower()
        assert "aipass" not in sent.lower().replace("@aipass's", "")  # names no default target

    def test_bare_start_does_not_name_a_default_branch(self, tmp_path, _patch_base_bot_deps):
        """The reply must ask for a branch, not silently pick one."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", return_value=_run(returncode=1)):
            bot._handle_control_start(chat_id=1, branch_arg="   ")

        sent = bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "<branch>" in sent or "branch" in sent.lower()

    def test_explicit_start_still_spawns(self, tmp_path, _patch_base_bot_deps):
        """The fix must not break the real verb: /start <branch> still wakes it."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        branch_info = {"name": "skills", "path": "/tmp/skills"}

        with (
            patch("subprocess.run", return_value=_run(returncode=1)) as mock_run,
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch",
                return_value=branch_info,
            ),
        ):
            bot._handle_control_start(chat_id=1, branch_arg="skills")

        assert mock_run.call_count == 3
        new_session_call = mock_run.call_args_list[1]
        assert new_session_call.args[0][4] == f"{CONTROL_SESSION_PREFIX}skills"
        bot.send_message.assert_called_once_with(1, "woke skills")  # type: ignore[union-attr]

    def test_start_already_running_does_not_spawn_second(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", return_value=_run(returncode=0)) as mock_run:
            bot._handle_control_start(chat_id=1, branch_arg="skills")

        # Only the has-session check — no new-session, no send-keys
        assert mock_run.call_count == 1
        bot.send_message.assert_called_once_with(1, "'skills' is already running.")  # type: ignore[union-attr]

    def test_start_unknown_branch_reports_registry_miss(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch("subprocess.run", return_value=_run(returncode=1)),
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch",
                return_value=None,
            ),
        ):
            bot._handle_control_start(chat_id=1, branch_arg="nonexistent")

        bot.send_message.assert_called_once_with(  # type: ignore[union-attr]
            1, "Branch '@nonexistent' not found in registry."
        )

    def test_start_branch_bot_falls_through_to_welcome(self, tmp_path, _patch_base_bot_deps):
        """On a branch bot, /start is NOT a control verb — plain welcome text unchanged."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="devpulse")

        with patch("subprocess.run", return_value=_run(returncode=0)) as mock_run:
            handled = bot._dispatch_command(chat_id=1, parsed=("start", ""))

        assert handled is True
        # Falls through to handle_standard_command — no tmux calls at all
        mock_run.assert_not_called()
        sent_text = bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "Available commands" in sent_text


# =============================================
# /kill
# =============================================


class TestControlKill:
    def test_kill_running_session(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", return_value=_run(returncode=0)) as mock_run:
            bot._handle_control_kill(chat_id=1, branch_arg="skills")

        assert mock_run.call_count == 2
        kill_call = mock_run.call_args_list[1]
        assert kill_call.args[0] == ["tmux", "kill-session", "-t", f"{CONTROL_SESSION_PREFIX}skills"]
        bot.send_message.assert_called_once_with(1, "killed skills")  # type: ignore[union-attr]

    def test_kill_not_running(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", return_value=_run(returncode=1)) as mock_run:
            bot._handle_control_kill(chat_id=1, branch_arg="skills")

        assert mock_run.call_count == 1
        bot.send_message.assert_called_once_with(1, "'skills' is not running.")  # type: ignore[union-attr]

    def test_bare_kill_kills_nothing(self, tmp_path, _patch_base_bot_deps):
        """A destructive verb must never pick a target for you.

        /kill shared the same `or "aipass"` default as /start, one line below it,
        so a bare /kill would have killed @aipass's live session. Replaces
        test_kill_default_branch_is_aipass, which pinned that.
        """
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", return_value=_run(returncode=0)) as mock_run:
            bot._handle_control_kill(chat_id=1, branch_arg="")

        mock_run.assert_not_called()
        sent = bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "branch" in sent.lower()

    def test_kill_branch_bot_not_intercepted(self, tmp_path, _patch_base_bot_deps):
        """On a branch bot, /kill is not a registered control verb or standard command."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="devpulse")

        with patch("subprocess.run", return_value=_run(returncode=0)) as mock_run:
            handled = bot._dispatch_command(chat_id=1, parsed=("kill", ""))

        assert handled is False
        mock_run.assert_not_called()


# =============================================
# /status — control-sessions listing
# =============================================


class TestControlSessionsListing:
    def test_lists_aipass_prefixed_sessions_only(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        list_sessions_result = _run(returncode=0, stdout="aipass-skills\ntelegram-base\naipass-devpulse\n")
        pane_results = {
            f"{CONTROL_SESSION_PREFIX}skills": _run(returncode=0, stdout="12345 0\n"),
            f"{CONTROL_SESSION_PREFIX}devpulse": _run(returncode=0, stdout="67890 1\n"),
        }

        def _side_effect(cmd, **kwargs):
            if cmd[:2] == ["tmux", "list-sessions"]:
                return list_sessions_result
            if cmd[:2] == ["tmux", "list-panes"]:
                return pane_results[cmd[3]]
            raise AssertionError(f"Unexpected subprocess call: {cmd}")

        with patch("subprocess.run", side_effect=_side_effect):
            sessions = bot._list_aipass_sessions()

        assert len(sessions) == 2
        by_branch = {s["branch"]: s for s in sessions}
        assert by_branch["skills"]["pid"] == 12345
        assert by_branch["skills"]["alive"] is True
        assert by_branch["devpulse"]["pid"] == 67890
        assert by_branch["devpulse"]["alive"] is False

    def test_no_sessions_returns_empty_list(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", return_value=_run(returncode=1, stdout="")):
            sessions = bot._list_aipass_sessions()

        assert sessions == []

    def test_status_appends_sessions_text_for_base_bot(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch("subprocess.run", return_value=_run(returncode=1, stdout="")),
            patch.object(bot, "_build_registry_status", return_value=""),
        ):
            bot._dispatch_command(chat_id=1, parsed=("status", ""))

        sent_text = bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "AIPass sessions: none running." in sent_text

    def test_status_omits_sessions_text_for_branch_bot(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="devpulse")

        with (
            patch("subprocess.run", return_value=_run(returncode=1, stdout="")),
            patch.object(bot, "_build_registry_status", return_value=""),
        ):
            bot._dispatch_command(chat_id=1, parsed=("status", ""))

        sent_text = bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "AIPass sessions" not in sent_text


# =============================================
# Deployed control bot (branch_name="aipass") — v1.1 fix-forward
# =============================================


class TestControlBotAipassBranchName:
    """
    The deployed base bot's persisted config sets branch_name="aipass" (it is
    the same bot_id="base" process Patrick messages as "the AIPASS bot chat" —
    there is no separate bot/service). It must be treated as a control bot,
    not a plain branch bot, across all three verbs plus the command list.
    """

    def test_start_wakes_on_aipass_branch_name(self, tmp_path, _patch_base_bot_deps):
        """This class is about ROUTING: /start reaches the control handler here.

        It used to assert that on a bare ("start", "") — which only passed
        because bare /start spawned @aipass by default. Named the branch
        explicitly so the test proves routing, not the removed default.
        """
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="aipass")
        branch_info = {"name": "aipass", "path": "/home/patrick/Projects/AIPass/src/aipass/aipass"}

        with (
            patch("subprocess.run", return_value=_run(returncode=1)) as mock_run,
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.validate_branch",
                return_value=branch_info,
            ),
        ):
            handled = bot._dispatch_command(chat_id=1, parsed=("start", "aipass"))

        assert handled is True
        assert mock_run.call_count == 3
        bot.send_message.assert_called_once_with(1, "woke aipass")  # type: ignore[union-attr]

    def test_bare_start_on_aipass_branch_name_spawns_nothing(self, tmp_path, _patch_base_bot_deps):
        """Routing still happens on a bare /start — it just must not spawn."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="aipass")

        with patch("subprocess.run", return_value=_run(returncode=1)) as mock_run:
            handled = bot._dispatch_command(chat_id=1, parsed=("start", ""))

        assert handled is True
        mock_run.assert_not_called()

    def test_kill_works_on_aipass_branch_name(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="aipass")

        with patch("subprocess.run", return_value=_run(returncode=0)) as mock_run:
            handled = bot._dispatch_command(chat_id=1, parsed=("kill", "skills"))

        assert handled is True
        assert mock_run.call_count == 2
        bot.send_message.assert_called_once_with(1, "killed skills")  # type: ignore[union-attr]

    def test_status_appends_sessions_text_on_aipass_branch_name(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="aipass")

        with (
            patch("subprocess.run", return_value=_run(returncode=1, stdout="")),
            patch.object(bot, "_build_registry_status", return_value=""),
        ):
            bot._dispatch_command(chat_id=1, parsed=("status", ""))

        sent_text = bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "AIPass sessions: none running." in sent_text

    def test_get_custom_commands_includes_kill_but_not_create(self, tmp_path, _patch_base_bot_deps):
        """kill extends to the aipass branch name; create/cancel stay base-only."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="aipass")

        commands = bot.get_custom_commands()

        assert "kill" in commands
        assert "create" not in commands
        assert "cancel" not in commands

    def test_start_label_overridden_for_aipass_branch_name(self, tmp_path, _patch_base_bot_deps):
        """/help (a non-control-verb path) shows the corrected /start description."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="aipass")

        with patch("subprocess.run", return_value=_run(returncode=0)):
            bot._dispatch_command(chat_id=1, parsed=("help", ""))

        sent_text = bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "Wake a terminal agent" in sent_text
        assert "Welcome —" not in sent_text

    def test_branch_bot_start_label_unaffected(self, tmp_path, _patch_base_bot_deps):
        """Plain branch bots (e.g. devpulse) keep the original /start wording."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="devpulse")

        with patch("subprocess.run", return_value=_run(returncode=0)):
            bot._dispatch_command(chat_id=1, parsed=("help", ""))

        sent_text = bot.send_message.call_args[0][1]  # type: ignore[union-attr]
        assert "Welcome — what this bot is and how to use it" in sent_text
