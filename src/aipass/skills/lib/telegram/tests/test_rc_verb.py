# =================== AIPass ====================
# Name: test_rc_verb.py
# Description: Tests for the /rc control verb — Remote Control recovery
# Version: 1.0.0
# Created: 2026-08-07
# Modified: 2026-08-07
# =============================================

"""
Tests for the /rc <target> control verb.

Two layers:

- remote_control.py pane parsing, exercised against pane text captured from a
  REAL Claude Code v2.1.224 TUI on 2026-08-07 (connected, disconnected,
  palette open, status panel open, mid-turn). Invented pane strings would
  only prove the regexes match themselves; these fixtures are what the
  terminal actually rendered, box-drawing and all.
- The BaseBot orchestration: target resolution, the refusals (no target, no
  session, busy, wrong palette entry), and the three outcome shapes
  (recovered / already-connected / failed).

The safety rules under test are the ones devpulse live-proved before this was
built: never Enter without verifying the palette's top entry, never leave the
modal status panel open in someone else's session, never claim success from
the absence of an error.
"""

from unittest.mock import patch, MagicMock

import pytest

from aipass.skills.lib.telegram.apps.handlers import remote_control as rc
from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot

# =============================================
# REAL CAPTURED PANE FIXTURES (v2.1.224, 2026-08-07)
# =============================================

_DIVIDER = "─" * 80

# Connected and idle: the finished-turn spinner reads past tense with no
# ellipsis, and the footer carries the bare "/rc" indicator on the right.
PANE_CONNECTED_IDLE = "\n".join(
    [
        "  39",
        "  40",
        "✻ Sautéed for 3s",
        _DIVIDER,
        "❯ ",
        _DIVIDER,
        "  [Count numbers one through forty] @skills (dev) │ Opus 5 (1M context) │ 96% │ $0.41          /rc",
        "  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents",
    ]
)

# Disconnected: identical footer minus the indicator — that absence is the
# whole signal, which is why the check is anchored to the footer only.
PANE_DISCONNECTED = "\n".join(
    [
        "✻ Sautéed for 3s",
        "❯ /remote-control",
        "  ⎿  Remote Control disconnected.",
        _DIVIDER,
        "❯ ",
        _DIVIDER,
        "  [Count numbers one through forty] @skills (dev) │ Opus 5 (1M context) │ 96% │ $0.41",
        "  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents",
    ]
)

# Palette open after typing "/rc" — /remote-control ranked top, other
# fuzzy matches below it, one with a wrapped continuation line.
PANE_PALETTE_RC_TOP = "\n".join(
    [
        "  40",
        "",
        "  /remote-control (rc)          Disconnect Remote Control",
        "  /deep-research                [dynamic workflow] Deep research harness — fan-out web searches,",
        "  /.archive:docs                Execute the Claude Code Docs helper script (user)",
        "  /verify                       Verify that a code change actually does what it's supposed to by",
        "                                exercising it end-to-end and observing behaviour.",
        _DIVIDER,
        "❯ /rc",
        _DIVIDER,
        "  [Count numbers one through forty] @skills (dev) │ Opus 5 (1M context) │ 96% │ $0.41          /rc",
        "  ⏵⏵ bypass permissions on (shift+tab to cycle)",
    ]
)

# The 2026-07-31 failure mode: fuzzy match put something else on top.
PANE_PALETTE_WRONG_TOP = PANE_PALETTE_RC_TOP.replace(
    "  /remote-control (rc)          Disconnect Remote Control\n"
    "  /deep-research                [dynamic workflow] Deep research harness — fan-out web searches,",
    "  /deep-research                [dynamic workflow] Deep research harness — fan-out web searches,\n"
    "  /remote-control (rc)          Disconnect Remote Control",
)

# Already-connected: Enter opened the modal status panel instead of reconnecting.
PANE_STATUS_PANEL = "\n".join(
    [
        "  31",
        "  32",
        "▔" * 80,
        "   Remote Control",
        "",
        "   This session is available in the Claude mobile app and at "
        "https://claude.ai/code/session_01AyccHTTotv3qxpLYBUn7q2.",
        "",
        "     Disconnect this session",
        "     Show QR code  Scan with your phone to open this session",
        "   ❯ Continue",
        "",
        "   Enter to select · Esc to continue",
    ]
)

# Mid-turn. Note the spinner carries NO elapsed counter yet — the first
# seconds of a turn render "✶ Thinking…" alone.
PANE_BUSY = "\n".join(
    [
        "❯ /remote-control",
        "  ⎿  Remote Control disconnected.",
        "❯ count from 1 to 60 slowly, one per line",
        "✶ Thinking…",
        _DIVIDER,
        "❯ ",
        _DIVIDER,
        "  [Count numbers one through forty] @skills (dev) │ Opus 5 (1M context) │ 96% │ $0.41",
        "  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents",
    ]
)

# Same, several seconds later, once the elapsed counter appears.
PANE_BUSY_WITH_ELAPSED = PANE_BUSY.replace("✶ Thinking…", "✽ Scampering… (21s)")

# Recovered: the reconnect echo plus the restored footer indicator.
PANE_RECOVERED = "\n".join(
    [
        "❯ /remote-control",
        "",
        "  /remote-control is active · Continue here, on your phone, or at "
        "https://claude.ai/code/session_01AyccHTTotv3qxpLYBUn7q2",
        _DIVIDER,
        "❯ ",
        _DIVIDER,
        "  @skills (dev) │ Opus 5 (1M context) │ ...                                                    /rc",
        "  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents",
    ]
)


# =============================================
# SESSION RESOLUTION
# =============================================


class TestResolveAgentSession:
    def test_exact_session_name_wins(self):
        assert rc.resolve_agent_session("vera", ["vera", "devpulse", "aipass-aipass"]) == "vera"

    def test_falls_back_to_aipass_prefix(self):
        assert rc.resolve_agent_session("aipass", ["vera", "devpulse", "aipass-aipass"]) == "aipass-aipass"

    def test_exact_match_beats_prefixed_match(self):
        # Both "skills" and "aipass-skills" exist — the bare session is the
        # agent's own, and must not be shadowed by the control-verb one.
        assert rc.resolve_agent_session("skills", ["aipass-skills", "skills"]) == "skills"

    def test_sigil_and_case_are_ignored(self):
        assert rc.resolve_agent_session("@Vera", ["vera"]) == "vera"
        assert rc.resolve_agent_session("  DEVPULSE ", ["devpulse"]) == "devpulse"

    def test_unknown_target_returns_none(self):
        assert rc.resolve_agent_session("nobody", ["vera", "devpulse"]) is None

    def test_empty_target_returns_none(self):
        assert rc.resolve_agent_session("  @ ", ["vera"]) is None

    def test_no_sessions_returns_none(self):
        assert rc.resolve_agent_session("vera", []) is None


# =============================================
# PANE PARSING
# =============================================


class TestIndicatorDetection:
    def test_connected_pane_has_indicator(self):
        assert rc.rc_indicator_present(PANE_CONNECTED_IDLE) is True

    def test_disconnected_pane_has_no_indicator(self):
        assert rc.rc_indicator_present(PANE_DISCONNECTED) is False

    def test_recovered_pane_has_indicator(self):
        assert rc.rc_indicator_present(PANE_RECOVERED) is True

    def test_scrollback_rc_does_not_count_as_connected(self):
        # "/rc" echoed in the transcript must never read as a live connection —
        # this is the difference between reporting recovered and reporting the
        # truth when the reconnect silently failed.
        pane = PANE_DISCONNECTED.replace("❯ /remote-control", "❯ /rc")
        assert rc.rc_indicator_present(pane) is False

    def test_documented_rc_active_spelling_also_matches(self):
        pane = PANE_CONNECTED_IDLE.replace("$0.41          /rc", "$0.41          /rc active")
        assert rc.rc_indicator_present(pane) is True


class TestPaletteVerification:
    def test_rc_on_top_is_accepted(self):
        assert rc.palette_top_entry_is_rc(PANE_PALETTE_RC_TOP) is True

    def test_other_command_on_top_is_rejected(self):
        assert rc.palette_top_entry_is_rc(PANE_PALETTE_WRONG_TOP) is False

    def test_no_palette_is_rejected(self):
        assert rc.palette_top_entry_is_rc(PANE_CONNECTED_IDLE) is False

    def test_wrapped_description_lines_are_not_treated_as_entries(self):
        rows = rc._palette_rows(PANE_PALETTE_RC_TOP)
        assert all(row.lstrip().startswith("/") for row in rows)
        assert rows[0].lstrip().startswith("/remote-control")


class TestBusyDetection:
    def test_spinner_without_elapsed_counter_is_busy(self):
        # The first seconds of a turn have no "(21s)" yet; keying on the
        # counter alone would read a fresh turn as idle and inject into it.
        assert rc.pane_is_busy(PANE_BUSY) is True

    def test_spinner_with_elapsed_counter_is_busy(self):
        assert rc.pane_is_busy(PANE_BUSY_WITH_ELAPSED) is True

    def test_finished_turn_is_not_busy(self):
        assert rc.pane_is_busy(PANE_CONNECTED_IDLE) is False

    def test_esc_to_interrupt_is_busy(self):
        pane = PANE_CONNECTED_IDLE.replace("✻ Sautéed for 3s", "  esc to interrupt")
        assert rc.pane_is_busy(pane) is True

    def test_ellipsis_in_transcript_scrollback_is_not_busy(self):
        # An old line ending in an ellipsis sits above the status block; if it
        # counted, the verb would refuse to ever run on that session.
        pane = PANE_CONNECTED_IDLE.replace("  39", "⎿  Reading files…")
        assert rc.pane_is_busy(pane) is False


class TestPanelAndUrl:
    def test_status_panel_detected(self):
        assert rc.status_panel_showing(PANE_STATUS_PANEL) is True

    def test_ordinary_pane_is_not_a_panel(self):
        assert rc.status_panel_showing(PANE_CONNECTED_IDLE) is False

    def test_session_url_extracted_from_panel(self):
        assert rc.extract_session_url(PANE_STATUS_PANEL) == ("https://claude.ai/code/session_01AyccHTTotv3qxpLYBUn7q2")

    def test_session_url_extracted_from_reconnect_echo(self):
        assert rc.extract_session_url(PANE_RECOVERED) == ("https://claude.ai/code/session_01AyccHTTotv3qxpLYBUn7q2")

    def test_no_url_returns_none(self):
        assert rc.extract_session_url(PANE_DISCONNECTED) is None


# =============================================
# BOT ORCHESTRATION
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


def _make_bot(tmp_path, branch_name=None):
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
    bot.send_message = MagicMock(return_value={"ok": True, "message_id": 7})
    bot.edit_message = MagicMock(return_value={"ok": True})
    return bot


def _last_reply(bot) -> str:
    """The text the bot last delivered, whether it edited or sent."""
    if bot.edit_message.called:
        return bot.edit_message.call_args.args[2]
    return bot.send_message.call_args.args[1]


class TestRcValidation:
    def test_missing_target_is_refused(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with patch.object(rc, "list_tmux_sessions") as mock_list:
            bot._handle_control_rc(chat_id=1, target_arg="")
        mock_list.assert_not_called()
        assert "Usage: /rc <target>" in _last_reply(bot)

    def test_unknown_target_lists_running_sessions(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with (
            patch.object(rc, "list_tmux_sessions", return_value=["vera", "devpulse"]),
            patch.object(rc, "send_literal") as mock_send,
        ):
            bot._handle_control_rc(chat_id=1, target_arg="nobody")
        mock_send.assert_not_called()
        reply = _last_reply(bot)
        assert "No tmux session for 'nobody'" in reply
        assert "devpulse, vera" in reply

    def test_non_control_bot_does_not_expose_rc(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, branch_name="skills")
        assert bot._dispatch_command(1, ("rc", "vera")) is False

    def test_control_bot_routes_rc(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with patch.object(BaseBot, "_handle_control_rc") as mock_handler:
            handled = bot._dispatch_command(1, ("rc", "vera"))
        assert handled is True
        mock_handler.assert_called_once_with(1, "vera")

    def test_rc_listed_in_control_bot_command_menu(self, tmp_path, _patch_base_bot_deps):
        control = _make_bot(tmp_path)
        branch = _make_bot(tmp_path, branch_name="skills")
        assert "rc" in control.get_custom_commands()
        assert "rc" not in branch.get_custom_commands()


class TestRcRecoveryWorker:
    """The worker runs inline here — the thread hop is the caller's business."""

    def test_busy_target_is_never_injected_into(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with (
            patch.object(rc, "capture_pane", return_value=PANE_BUSY),
            patch.object(rc, "IDLE_WAIT_SECONDS", 0),
            patch.object(rc, "send_literal") as mock_send,
        ):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        mock_send.assert_not_called()
        assert "mid-turn" in _last_reply(bot)

    def test_waits_out_a_busy_target_then_proceeds(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        panes = [PANE_BUSY, PANE_CONNECTED_IDLE, PANE_PALETTE_RC_TOP, PANE_RECOVERED]
        with (
            patch.object(rc, "capture_pane", side_effect=panes),
            patch.object(rc, "IDLE_POLL_SECONDS", 0),
            patch.object(rc, "PALETTE_SETTLE_SECONDS", 0),
            patch.object(rc, "CONNECT_SETTLE_SECONDS", 0),
            patch.object(rc, "send_literal", return_value=True) as mock_send,
            patch.object(rc, "send_key", return_value=True),
        ):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        mock_send.assert_called_once_with("vera", "/rc")
        assert "reconnected" in _last_reply(bot)

    def test_wrong_palette_entry_aborts_without_enter(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with (
            patch.object(rc, "capture_pane", side_effect=[PANE_CONNECTED_IDLE, PANE_PALETTE_WRONG_TOP]),
            patch.object(rc, "PALETTE_SETTLE_SECONDS", 0),
            patch.object(rc, "send_literal", return_value=True),
            patch.object(rc, "send_key") as mock_key,
            patch.object(rc, "clear_composer") as mock_clear,
        ):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        mock_key.assert_not_called()  # never Enter on an unverified palette
        mock_clear.assert_called_once_with("vera")
        reply = _last_reply(bot)
        assert "Aborted" in reply
        assert "Nothing was sent" in reply

    def test_only_rc_is_ever_typed(self, tmp_path, _patch_base_bot_deps):
        """Scope guard: this verb relays no arbitrary text into other agents."""
        bot = _make_bot(tmp_path)
        with (
            patch.object(rc, "capture_pane", side_effect=[PANE_DISCONNECTED, PANE_PALETTE_RC_TOP, PANE_RECOVERED]),
            patch.object(rc, "PALETTE_SETTLE_SECONDS", 0),
            patch.object(rc, "CONNECT_SETTLE_SECONDS", 0),
            patch.object(rc, "send_literal", return_value=True) as mock_send,
            patch.object(rc, "send_key", return_value=True),
        ):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        assert [call.args[1] for call in mock_send.call_args_list] == ["/rc"]

    def test_recovered_reports_indicator_and_url(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with (
            patch.object(rc, "capture_pane", side_effect=[PANE_DISCONNECTED, PANE_PALETTE_RC_TOP, PANE_RECOVERED]),
            patch.object(rc, "PALETTE_SETTLE_SECONDS", 0),
            patch.object(rc, "CONNECT_SETTLE_SECONDS", 0),
            patch.object(rc, "send_literal", return_value=True),
            patch.object(rc, "send_key", return_value=True),
        ):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        reply = _last_reply(bot)
        assert "reconnected" in reply
        assert "https://claude.ai/code/session_01AyccHTTotv3qxpLYBUn7q2" in reply

    def test_already_connected_dismisses_the_modal_panel(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with (
            patch.object(
                rc,
                "capture_pane",
                side_effect=[PANE_CONNECTED_IDLE, PANE_PALETTE_RC_TOP, PANE_STATUS_PANEL, PANE_CONNECTED_IDLE],
            ),
            patch.object(rc, "PALETTE_SETTLE_SECONDS", 0),
            patch.object(rc, "CONNECT_SETTLE_SECONDS", 0),
            patch.object(rc, "send_literal", return_value=True),
            patch.object(rc, "send_key", return_value=True) as mock_key,
            patch("time.sleep"),
        ):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        assert mock_key.call_args_list[-1].args == ("vera", "Escape")
        reply = _last_reply(bot)
        assert "already connected" in reply
        assert "⚠️" not in reply  # panel confirmed gone, so no warning

    def test_undismissed_panel_is_flagged_not_hidden(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with (
            patch.object(
                rc,
                "capture_pane",
                side_effect=[PANE_CONNECTED_IDLE, PANE_PALETTE_RC_TOP, PANE_STATUS_PANEL, PANE_STATUS_PANEL],
            ),
            patch.object(rc, "PALETTE_SETTLE_SECONDS", 0),
            patch.object(rc, "CONNECT_SETTLE_SECONDS", 0),
            patch.object(rc, "send_literal", return_value=True),
            patch.object(rc, "send_key", return_value=True),
            patch("time.sleep"),
        ):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        assert "may still be open" in _last_reply(bot)

    def test_absent_indicator_reports_failure_with_pane_tail(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with (
            patch.object(rc, "capture_pane", side_effect=[PANE_DISCONNECTED, PANE_PALETTE_RC_TOP, PANE_DISCONNECTED]),
            patch.object(rc, "PALETTE_SETTLE_SECONDS", 0),
            patch.object(rc, "CONNECT_SETTLE_SECONDS", 0),
            patch.object(rc, "send_literal", return_value=True),
            patch.object(rc, "send_key", return_value=True),
        ):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        reply = _last_reply(bot)
        assert "no connection" in reply
        assert "Pane showed:" in reply

    def test_capture_failure_is_reported_not_assumed(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with patch.object(rc, "capture_pane", return_value=None):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        assert "capture-pane failed" in _last_reply(bot)

    def test_send_failure_is_reported(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path)
        with (
            patch.object(rc, "capture_pane", return_value=PANE_DISCONNECTED),
            patch.object(rc, "send_literal", return_value=False),
        ):
            bot._run_rc_recovery(1, "vera", "vera", 7)
        assert "Failed to type /rc" in _last_reply(bot)


class TestTmuxWrappers:
    def test_list_sessions_parses_names(self):
        result = MagicMock(returncode=0, stdout="vera\ndevpulse\naipass-aipass\n")
        with patch("subprocess.run", return_value=result):
            assert rc.list_tmux_sessions() == ["vera", "devpulse", "aipass-aipass"]

    def test_list_sessions_empty_when_no_server(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            assert rc.list_tmux_sessions() == []

    def test_list_sessions_empty_when_tmux_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert rc.list_tmux_sessions() == []

    def test_capture_pane_returns_none_on_failure(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="no session")):
            assert rc.capture_pane("ghost") is None

    def test_send_literal_uses_literal_flag(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as mock_run:
            assert rc.send_literal("vera", "/rc") is True
        assert mock_run.call_args.args[0] == ["tmux", "send-keys", "-t", "vera", "-l", "/rc"]

    def test_send_key_sends_named_key(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as mock_run:
            assert rc.send_key("vera", "Enter") is True
        assert mock_run.call_args.args[0] == ["tmux", "send-keys", "-t", "vera", "Enter"]

    def test_clear_composer_sends_ctrl_u(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as mock_run:
            rc.clear_composer("vera")
        assert mock_run.call_args.args[0] == ["tmux", "send-keys", "-t", "vera", "C-u"]
