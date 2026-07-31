# =================== AIPass ====================
# Name: test_suspend.py
# Description: Tests for the /suspend control verb + resume-heartbeat logic — DPLAN-0270 P5
# Version: 1.0.0
# Created: 2026-07-30
# Modified: 2026-07-30
# =============================================

"""
Tests for the /suspend control verb and its resume-heartbeat companion
(DPLAN-0270 P5).

- /suspend <duration> (e.g. "8h", "45m") — single-wake mode: ack, arm the RTC
  alarm via sudo rtcwake, call systemctl suspend, no heartbeat state set.
- /suspend (no arg) — heartbeat mode: ack, arm + suspend for the configured
  interval, sets heartbeat state so the resume signal drives re-arm/stay-awake.
- Failure paths: rtcwake sudoers grant missing (abort, no suspend attempt),
  systemctl suspend grant missing (best-effort disarm the alarm we just armed).
- Malformed duration argument is rejected with a usage message, no subprocess calls.
- _check_resume_signal (run()'s poll-loop hook): no-op when no heartbeat is
  active, detects a fresh resume signal and starts the grace window, stays
  awake if a control command landed since resume, re-arms if the grace
  window elapses with no command.

All subprocess calls are mocked — no real systemctl/rtcwake/sudo ever runs.
"""

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from aipass.skills.lib.telegram.apps.handlers.base_bot import (
    BaseBot,
    RESUME_WALLCLOCK_JUMP_SECONDS,
    RTCWAKE_BIN,
    SUSPEND_GRACE_WINDOW_SECONDS,
    SUSPEND_HEARTBEAT_DEFAULT_MINUTES,
)


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


def _cpe(cmd, stderr=b""):
    return subprocess.CalledProcessError(1, cmd, stderr=stderr)


class _SteppedClock:
    """time.time() mock that holds each value until advance() is called — immune to
    incidental internal time.time() calls (e.g. Python logging's LogRecord timestamp),
    unlike a plain side_effect=[...] list which those calls would silently exhaust."""

    def __init__(self, *values):
        self._values = values
        self._i = 0

    def __call__(self, *_args, **_kwargs):
        return self._values[self._i]

    def advance(self):
        self._i += 1


# =============================================
# duration parsing
# =============================================


class TestParseSuspendDuration:
    def test_no_arg_is_heartbeat_mode(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._parse_suspend_duration("") == (None, None)

    def test_hours(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._parse_suspend_duration("8h") == (8 * 3600, None)

    def test_minutes(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._parse_suspend_duration("45m") == (45 * 60, None)

    def test_malformed_arg_rejected(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        seconds, err = bot._parse_suspend_duration("tomorrow")
        assert seconds is None
        assert err is not None and "Bad duration" in err


# =============================================
# /suspend — single-wake mode
# =============================================


class TestSuspendSingleWake:
    def test_single_wake_acks_before_arming(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        call_order = []
        bot.send_message.side_effect = lambda *a, **k: call_order.append("ack")  # type: ignore[union-attr]

        with patch("subprocess.run", side_effect=lambda *a, **k: call_order.append("subprocess")) as mock_run:
            bot._handle_control_suspend(chat_id=1, arg="8h")

        assert call_order[0] == "ack"
        assert call_order.count("subprocess") == 2  # rtcwake, then systemctl suspend
        assert mock_run.call_args_list[0].args[0] == ["sudo", "-n", RTCWAKE_BIN, "-m", "no", "-s", str(8 * 3600)]
        assert mock_run.call_args_list[1].args[0] == ["systemctl", "suspend"]

    def test_single_wake_does_not_set_heartbeat_state(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run"):
            bot._handle_control_suspend(chat_id=1, arg="45m")

        assert bot._suspend_heartbeat_active is False

    def test_malformed_duration_sends_error_no_subprocess(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run") as mock_run:
            bot._handle_control_suspend(chat_id=1, arg="nonsense")

        mock_run.assert_not_called()
        assert "Bad duration" in bot.send_message.call_args[0][1]  # type: ignore[union-attr]


# =============================================
# /suspend — heartbeat mode
# =============================================


class TestSuspendHeartbeatMode:
    def test_heartbeat_mode_sets_state_and_acks(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run") as mock_run:
            bot._handle_control_suspend(chat_id=42, arg="")

        assert bot._suspend_heartbeat_active is True
        assert bot._suspend_chat_id == 42
        expected_interval = SUSPEND_HEARTBEAT_DEFAULT_MINUTES * 60
        assert mock_run.call_args_list[0].args[0] == [
            "sudo",
            "-n",
            RTCWAKE_BIN,
            "-m",
            "no",
            "-s",
            str(expected_interval),
        ]
        ack_text = bot.send_message.call_args_list[0].args[1]  # type: ignore[union-attr]
        assert "Heartbeat" in ack_text


# =============================================
# arm/suspend failure paths
# =============================================


class TestArmAndSuspendFailures:
    def test_rtcwake_missing_grant_aborts_before_suspend(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", side_effect=_cpe(["sudo"], stderr=b"sudo: a password is required")) as mock_run:
            bot._handle_control_suspend(chat_id=1, arg="8h")

        assert mock_run.call_count == 1  # only the rtcwake attempt, never systemctl suspend
        error_text = bot.send_message.call_args_list[-1].args[1]  # type: ignore[union-attr]
        assert "rtcwake sudoers grant" in error_text
        assert "install_suspend_grants.sh" in error_text

    def test_rtcwake_failure_clears_heartbeat_flag(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", side_effect=_cpe(["sudo"])):
            bot._handle_control_suspend(chat_id=1, arg="")

        assert bot._suspend_heartbeat_active is False

    def test_suspend_failure_disarms_alarm_and_reports(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["systemctl", "suspend"]:
                raise _cpe(cmd, stderr=b"Interactive authentication required.")
            return MagicMock()

        with patch("subprocess.run", side_effect=side_effect) as mock_run:
            bot._handle_control_suspend(chat_id=1, arg="8h")

        # rtcwake arm, systemctl suspend (fails), rtcwake disable (best-effort disarm)
        assert mock_run.call_count == 3
        assert mock_run.call_args_list[2].args[0] == ["sudo", "-n", RTCWAKE_BIN, "-m", "disable"]
        error_text = bot.send_message.call_args_list[-1].args[1]  # type: ignore[union-attr]
        assert "login1.suspend polkit grant" in error_text
        assert bot._suspend_heartbeat_active is False


# =============================================
# _check_resume_signal (poll-loop hook)
# =============================================


class TestCheckResumeSignal:
    def test_noop_when_no_heartbeat_active(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._suspend_heartbeat_active is False

        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE") as mock_file:
            bot._check_resume_signal()
            mock_file.read_text.assert_not_called()

    def test_fresh_resume_signal_starts_grace_window(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 1

        signal_file = tmp_path / "resume_signal.json"
        signal_file.write_text(json.dumps({"resumed_at": 1000.0}))

        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", signal_file):
            bot._check_resume_signal()

        assert bot._suspend_last_resume_seen == 1000.0
        assert bot._suspend_resume_pending_since is not None

    def test_missing_signal_file_is_noop(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 1

        missing = tmp_path / "does_not_exist.json"
        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing):
            bot._check_resume_signal()  # must not raise

        assert bot._suspend_resume_pending_since is None

    def test_stays_awake_when_command_arrived_since_resume(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_last_resume_seen = 1000.0
        bot._suspend_resume_pending_since = 1000.0
        bot._last_control_command_at = 1050.0  # a command landed after resume

        signal_file = tmp_path / "resume_signal.json"
        signal_file.write_text(json.dumps({"resumed_at": 1000.0}))

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", signal_file),
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.time.time",
                return_value=1000.0 + SUSPEND_GRACE_WINDOW_SECONDS + 1,
            ),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        assert bot._suspend_heartbeat_active is False
        mock_run.assert_not_called()  # no re-arm — stayed awake
        bot.send_message.assert_called_once_with(7, "Staying awake — command received.")  # type: ignore[union-attr]

    def test_rearms_when_grace_window_elapses_with_no_command(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_last_resume_seen = 1000.0
        bot._suspend_resume_pending_since = 1000.0
        bot._last_control_command_at = 500.0  # last command was BEFORE resume

        signal_file = tmp_path / "resume_signal.json"
        signal_file.write_text(json.dumps({"resumed_at": 1000.0}))

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", signal_file),
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.time.time",
                return_value=1000.0 + SUSPEND_GRACE_WINDOW_SECONDS + 1,
            ),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        assert mock_run.call_args_list[0].args[0][:5] == ["sudo", "-n", RTCWAKE_BIN, "-m", "no"]
        assert bot._suspend_heartbeat_active is True  # still armed, heartbeat continues

    def test_within_grace_window_takes_no_action_yet(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_last_resume_seen = 1000.0
        bot._suspend_resume_pending_since = 1000.0
        bot._last_control_command_at = 0.0

        signal_file = tmp_path / "resume_signal.json"
        signal_file.write_text(json.dumps({"resumed_at": 1000.0}))

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", signal_file),
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.time.time",
                return_value=1000.0 + 10,  # well inside the grace window
            ),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        mock_run.assert_not_called()
        bot.send_message.assert_not_called()  # type: ignore[union-attr]
        assert bot._suspend_resume_pending_since == 1000.0


# =============================================
# wall-clock-jump resume detection (DPLAN-0270 P5 hardening — primary signal,
# file hook proven unreliable: systemd never ran it across 5 real suspends)
# =============================================


class TestWallClockJumpResumeDetection:
    def test_normal_idle_gap_does_not_look_like_resume(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7

        missing = tmp_path / "no_signal.json"
        clock = _SteppedClock(1000.0, 1000.0 + 30)  # a normal long-poll iteration
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=clock),
        ):
            bot._check_resume_signal()  # establishes the baseline loop mark
            clock.advance()
            bot._check_resume_signal()  # normal-length gap

        assert bot._suspend_resume_pending_since is None

    def test_large_gap_triggers_resume_with_no_signal_file_at_all(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7

        missing = tmp_path / "no_signal.json"
        clock = _SteppedClock(1000.0, 1000.0 + RESUME_WALLCLOCK_JUMP_SECONDS + 1)
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=clock),
        ):
            bot._check_resume_signal()  # baseline mark
            clock.advance()
            bot._check_resume_signal()  # frozen for a real-suspend-sized gap

        assert bot._suspend_resume_pending_since is not None

    def test_inactive_heartbeat_still_updates_loop_mark(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._suspend_heartbeat_active is False

        with patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", return_value=1234.0):
            bot._check_resume_signal()

        assert bot._suspend_last_loop_mark == 1234.0


# =============================================
# stale-stamp baseline fix — a pre-existing resume_signal.json from earlier
# manual testing must not be misread as a fresh resume right after activation
# =============================================


class TestStaleStampBaseline:
    def test_pre_existing_stamp_not_treated_as_fresh_after_activation(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        signal_file = tmp_path / "resume_signal.json"
        signal_file.write_text(json.dumps({"resumed_at": 500.0}))  # stale, from earlier manual testing

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", signal_file),
            patch("subprocess.run"),
        ):
            bot._handle_control_suspend(chat_id=7, arg="")  # activates heartbeat mode

        assert bot._suspend_last_resume_seen == 500.0  # baselined to the current stamp, not None

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", signal_file),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", return_value=600.0),
        ):
            bot._check_resume_signal()

        assert bot._suspend_resume_pending_since is None  # the stale stamp must not look fresh


# =============================================
# spurious-wake absorption — wake mid-heartbeat, grace window, no command,
# re-arm + re-suspend on its own (DPLAN-0270 P5: "absorb spurious wakes
# rather than chase hardware")
# =============================================


class TestSpuriousWakeAbsorption:
    def test_rearms_after_grace_window_with_no_signal_file_present(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7

        missing = tmp_path / "no_signal.json"
        t0 = 1000.0
        wake_at = t0 + RESUME_WALLCLOCK_JUMP_SECONDS + 5
        after_grace = wake_at + SUSPEND_GRACE_WINDOW_SECONDS + 1
        clock = _SteppedClock(t0, wake_at, after_grace)

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=clock),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()  # baseline mark before the (spurious) suspend
            clock.advance()
            bot._check_resume_signal()  # wall-clock jump detected — grace window starts
            clock.advance()
            bot._check_resume_signal()  # grace window elapses, no command — re-arm

        assert mock_run.call_args_list[0].args[0][:5] == ["sudo", "-n", RTCWAKE_BIN, "-m", "no"]
        assert bot._suspend_heartbeat_active is True  # absorbed the spurious wake, heartbeat continues

    def test_does_not_re_detect_while_grace_window_already_pending(self, tmp_path, _patch_base_bot_deps):
        """A slow iteration (e.g. network hiccup) during an active grace window must not
        be mistaken for a second fresh resume and reset the window."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_resume_pending_since = 1000.0

        missing = tmp_path / "no_signal.json"
        clock = _SteppedClock(1000.0, 1000.0 + RESUME_WALLCLOCK_JUMP_SECONDS + 5)
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=clock),
        ):
            bot._check_resume_signal()  # sets the loop mark mid-grace-window
            clock.advance()
            bot._check_resume_signal()  # big gap here, but a window is already pending

        assert bot._suspend_resume_pending_since == 1000.0  # untouched — still the original window


# =============================================
# gating — control bots only
# =============================================


class TestSuspendGating:
    def test_dispatch_routes_suspend_for_control_bot(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch.object(bot, "_handle_control_suspend") as mock_handler:
            handled = bot._dispatch_command(chat_id=1, parsed=("suspend", "8h"))

        assert handled is True
        mock_handler.assert_called_once_with(1, "8h")

    def test_branch_bot_does_not_get_suspend_verb(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="devpulse")

        with patch.object(bot, "_handle_control_suspend") as mock_handler:
            bot._dispatch_command(chat_id=1, parsed=("suspend", ""))

        mock_handler.assert_not_called()

    def test_suspend_in_custom_commands_for_control_bot_only(self, tmp_path, _patch_base_bot_deps):
        control_bot = _make_bot(tmp_path, _patch_base_bot_deps)
        branch_bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="devpulse")

        assert "suspend" in control_bot.get_custom_commands()
        assert "suspend" not in branch_bot.get_custom_commands()
