# =================== AIPass ====================
# Name: test_suspend.py
# Description: Tests for the /suspend control verb + resume-heartbeat logic — DPLAN-0270 P5
# Version: 2.0.2
# Created: 2026-07-30
# Modified: 2026-08-02
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
import os
import subprocess
import time
from unittest.mock import call, patch, MagicMock

import pytest

from aipass.skills.lib.telegram.apps.handlers.base_bot import (
    BaseBot,
    PENDING_STUCK_TIMEOUT_SECONDS,
    RESUME_WALLCLOCK_JUMP_SECONDS,
    RTCWAKE_BIN,
    SUSPEND_ACTIVE_HEARTBEAT_DEFAULT_MINUTES,
    SUSPEND_ACTIVE_WINDOW_DEFAULT_MINUTES,
    SUSPEND_EARLY_WAKE_MARGIN_SECONDS,
    SUSPEND_GRACE_WINDOW_SECONDS,
    SUSPEND_HEARTBEAT_DEFAULT_MINUTES,
)


@pytest.fixture
def _patch_base_bot_deps(tmp_path):
    patches = [
        patch("aipass.skills.lib.telegram.apps.handlers.base_bot.PENDING_DIR", tmp_path),
        # Must be redirected: the real stamp lives under ~/.aipass and a live bot on the
        # dev machine keeps it current, which would read as "human present" in every test.
        patch(
            "aipass.skills.lib.telegram.apps.handlers.base_bot.LAST_INBOUND_STAMP_FILE",
            tmp_path / "last_inbound.json",
        ),
        # _suspend_enabled() reads the real bot config otherwise — an ops kill-switch
        # flipped on this machine would silently ground the verb under the whole suite.
        patch("aipass.skills.lib.telegram.apps.handlers.config.load_bot_config", return_value={}),
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


# The resolver matches sessions against our own uid, so build the fixtures from it
# rather than hard-coding 1000 — CI does not run as Patrick. Windows has no
# os.getuid at all, so fall back to a fixed uid there and pin the resolver to the
# same value below (module-level getuid would kill collection on Windows).
_UID = str(os.getuid()) if hasattr(os, "getuid") else "1000"


@pytest.fixture(autouse=True)
def _pin_getuid(monkeypatch):
    # The /lock resolver calls os.getuid() only after the (mocked) loginctl
    # succeeds, so on Windows the mock walks it straight into a missing API.
    monkeypatch.setattr(os, "getuid", lambda: int(_UID), raising=False)


def _loginctl_stub(*, sessions="3 …\n", props=None, list_error=None, lock_error=None, dbus_error=None):
    """
    subprocess.run side_effect covering the whole /lock command tree.

    Fakes `loginctl list-sessions`, per-session `show-session`, `lock-session`
    and the `gdbus` screensaver fallback, so a test can fail any one of them
    independently without the others going missing.
    """
    if props is None:
        props = {"3": {"Type": "wayland", "State": "active", "User": _UID}}

    def _run(cmd, **kwargs):
        if cmd[:2] == ["loginctl", "list-sessions"]:
            if list_error:
                raise list_error
            return MagicMock(stdout=sessions)
        if cmd[:2] == ["loginctl", "show-session"]:
            return MagicMock(stdout="".join(f"{k}={v}\n" for k, v in props.get(cmd[2], {}).items()))
        if cmd[:2] == ["loginctl", "lock-session"]:
            if lock_error:
                raise lock_error
            return MagicMock(returncode=0)
        if cmd[0] == "gdbus":
            if dbus_error:
                raise dbus_error
            return MagicMock(returncode=0)
        raise AssertionError(f"unexpected command in the /lock path: {cmd}")

    return _run


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
        bot._suspend_grace_started_at = 1000.0
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
        # Cancelling disarms the pending RTC alarm; the one thing it must never do is re-arm.
        assert mock_run.call_args_list == [call(["sudo", "-n", RTCWAKE_BIN, "-m", "disable"], capture_output=True)]
        bot.send_message.assert_called_once_with(7, "Staying awake — activity detected.")  # type: ignore[union-attr]

    def test_rearms_when_grace_window_elapses_with_no_command(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_last_resume_seen = 1000.0
        bot._suspend_resume_pending_since = 1000.0
        bot._suspend_grace_started_at = 1000.0  # Telegram was already reachable at resume
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
        bot._suspend_grace_started_at = 1000.0
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
        poll_ok_at = wake_at + 50  # network back ~50s after resume, as measured on this box
        after_grace = poll_ok_at + SUSPEND_GRACE_WINDOW_SECONDS + 1
        clock = _SteppedClock(t0, wake_at, poll_ok_at, after_grace)

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=clock),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()  # baseline mark before the (spurious) suspend
            clock.advance()
            bot._check_resume_signal()  # wall-clock jump detected — awaiting first good poll
            bot._last_successful_poll_at = poll_ok_at  # run()'s loop records a reachable Telegram
            clock.advance()
            bot._check_resume_signal()  # grace window now starts, not before
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


# =============================================
# ROOT CAUSE 1 (incident 2026-08-02) — the grace window was control-verb-blind.
# Patrick chatting with @devpulse is a different PROCESS from the control bot,
# so presence has to cross processes via a shared stamp file.
# =============================================


def _stamp_inbound(tmp_path, at, bot_id="devpulse"):
    """Write the shared presence stamp as a sibling bot process would."""
    (tmp_path / "last_inbound.json").write_text(json.dumps({"last_inbound_at": at, "bot_id": bot_id}))


class TestCrossProcessHumanPresence:
    def test_allowed_user_message_writes_stamp(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch.object(bot, "_write_mirror_mapping"),
            patch.object(bot, "handle_message"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", return_value=9000.0),
        ):
            bot.process_update({"message": {"chat": {"id": 1}, "from": {"id": 111}, "text": "hi"}})

        assert json.loads((tmp_path / "last_inbound.json").read_text())["last_inbound_at"] == 9000.0

    def test_unauthorized_user_does_not_stamp(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch.object(bot, "_write_mirror_mapping"),
            patch.object(bot, "handle_message"),
        ):
            bot.process_update({"message": {"chat": {"id": 1}, "from": {"id": 999}, "text": "hi"}})

        assert not (tmp_path / "last_inbound.json").exists()

    def test_rate_limited_human_still_counts_as_present(self, tmp_path, _patch_base_bot_deps):
        """A throttled human is still a human — the stamp precedes the rate-limit bail-out."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch.object(bot, "_write_mirror_mapping"),
            patch.object(bot, "check_rate_limit", return_value=False),
            patch.object(bot, "handle_message") as mock_handle,
        ):
            bot.process_update({"message": {"chat": {"id": 1}, "from": {"id": 111}, "text": "hi"}})

        mock_handle.assert_not_called()
        assert (tmp_path / "last_inbound.json").exists()

    def test_presence_sees_sibling_bot_stamp(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        _stamp_inbound(tmp_path, 1050.0)

        assert bot._human_present_since(1000.0) is True

    def test_stamp_older_than_resume_is_not_presence(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        _stamp_inbound(tmp_path, 900.0)  # conversation happened BEFORE the suspend

        assert bot._human_present_since(1000.0) is False

    def test_missing_stamp_is_not_presence(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._read_inbound_stamp() == 0.0
        assert bot._human_present_since(1000.0) is False

    def test_corrupt_stamp_is_not_presence(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        (tmp_path / "last_inbound.json").write_text("{{{not json")

        assert bot._read_inbound_stamp() == 0.0

    def test_chat_with_another_bot_cancels_the_suspend_cycle(self, tmp_path, _patch_base_bot_deps):
        """THE incident regression: Patrick talks to @devpulse, the control bot must stay awake."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_resume_pending_since = 1000.0
        bot._suspend_grace_started_at = 1000.0
        bot._last_control_command_at = 0.0  # no control verb — only ordinary chat, on another bot
        _stamp_inbound(tmp_path, 1020.0)

        missing = tmp_path / "no_signal.json"
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.time.time",
                return_value=1000.0 + SUSPEND_GRACE_WINDOW_SECONDS + 1,
            ),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        assert bot._suspend_heartbeat_active is False
        assert mock_run.call_args_list == [call(["sudo", "-n", RTCWAKE_BIN, "-m", "disable"], capture_output=True)]
        bot.send_message.assert_called_once_with(7, "Staying awake — activity detected.")  # type: ignore[union-attr]


# =============================================
# ROOT CAUSE 2 (incident 2026-08-02) — wake cause was guessed from gap size.
# A 14s nap fell under the jump threshold, so the loop stayed armed invisibly.
# Now: compare the actual wake against the armed RTC time.
# =============================================


class TestWakeCauseClassification:
    def test_alarm_time_recorded_when_armed(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch("subprocess.run"),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", return_value=1000.0),
        ):
            bot._handle_control_suspend(chat_id=42, arg="")

        assert bot._suspend_alarm_at == 1000.0 + SUSPEND_HEARTBEAT_DEFAULT_MINUTES * 60

    def test_alarm_time_cleared_when_arming_fails(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", side_effect=_cpe(["sudo"])):
            bot._handle_control_suspend(chat_id=42, arg="")

        assert bot._suspend_alarm_at is None

    def test_short_nap_under_jump_threshold_is_still_detected(self, tmp_path, _patch_base_bot_deps):
        """The 14s nap that got missed: too small for the gap check, but the alarm was due."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_alarm_at = 1010.0

        missing = tmp_path / "no_signal.json"
        clock = _SteppedClock(1000.0, 1014.0)  # a 14s gap — far under RESUME_WALLCLOCK_JUMP_SECONDS
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=clock),
        ):
            bot._check_resume_signal()  # baseline, alarm not yet due
            clock.advance()
            bot._check_resume_signal()

        assert 1014.0 - 1000.0 < RESUME_WALLCLOCK_JUMP_SECONDS  # the old gap check could not see this
        assert bot._suspend_resume_pending_since == 1014.0

    def test_early_wake_cancels_the_whole_cycle(self, tmp_path, _patch_base_bot_deps):
        """Woke long before the armed alarm = a human did it. Don't absorb it, stop."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_alarm_at = 2500.0

        missing = tmp_path / "no_signal.json"
        clock = _SteppedClock(1000.0, 1200.0)  # lid opened 1300s before the alarm was due
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=clock),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()
            clock.advance()
            bot._check_resume_signal()

        assert bot._suspend_heartbeat_active is False
        assert bot._suspend_alarm_at is None
        assert mock_run.call_args_list == [call(["sudo", "-n", RTCWAKE_BIN, "-m", "disable"], capture_output=True)]
        bot.send_message.assert_called_once_with(7, "Staying awake — you woke the machine.")  # type: ignore[union-attr]

    def test_wake_at_alarm_time_is_our_own_rtc(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_alarm_at = 2500.0

        missing = tmp_path / "no_signal.json"
        clock = _SteppedClock(1000.0, 2500.0)
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=clock),
            patch("subprocess.run"),
        ):
            bot._check_resume_signal()
            clock.advance()
            bot._check_resume_signal()

        assert bot._suspend_heartbeat_active is True  # heartbeat continues, grace window pending
        assert bot._suspend_resume_pending_since == 2500.0

    def test_slightly_early_rtc_fire_is_not_read_as_human(self, tmp_path, _patch_base_bot_deps):
        """RTC hardware fires a little early; only a wake outside the margin means a human."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_alarm_at = 2500.0
        wake_at = 2500.0 - (SUSPEND_EARLY_WAKE_MARGIN_SECONDS / 2)

        missing = tmp_path / "no_signal.json"
        clock = _SteppedClock(1000.0, wake_at)
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", side_effect=clock),
            patch("subprocess.run"),
        ):
            bot._check_resume_signal()
            clock.advance()
            bot._check_resume_signal()

        assert bot._suspend_heartbeat_active is True
        assert bot._suspend_resume_pending_since == wake_at


# =============================================
# ROOT CAUSE 3 (incident 2026-08-02) — the post-resume window was unusable.
# DNS/network needs 45-60s after resume, so a window measured from resume
# detection was already half gone before a reply could even be sent.
# =============================================


class TestPostResumeGraceAnchor:
    def test_grace_does_not_start_before_telegram_is_reachable(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_resume_pending_since = 1000.0
        bot._last_successful_poll_at = 900.0  # last good poll was BEFORE the suspend

        missing = tmp_path / "no_signal.json"
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.time.time",
                return_value=1000.0 + SUSPEND_GRACE_WINDOW_SECONDS * 3,
            ),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        mock_run.assert_not_called()  # network still down — never re-arm blind
        assert bot._suspend_grace_started_at is None

    def test_grace_starts_at_first_successful_poll(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_resume_pending_since = 1000.0
        bot._last_successful_poll_at = 1055.0  # DNS came back 55s after resume

        missing = tmp_path / "no_signal.json"
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", return_value=1056.0),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        assert bot._suspend_grace_started_at == 1055.0
        mock_run.assert_not_called()

    def test_full_window_survives_a_late_network(self, tmp_path, _patch_base_bot_deps):
        """At resume+grace the machine must still be awake — the clock starts at the poll."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_resume_pending_since = 1000.0
        bot._suspend_grace_started_at = 1060.0  # anchored to the first good poll

        missing = tmp_path / "no_signal.json"
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch(
                "aipass.skills.lib.telegram.apps.handlers.base_bot.time.time",
                return_value=1000.0 + SUSPEND_GRACE_WINDOW_SECONDS + 1,  # old anchor would re-arm here
            ),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        mock_run.assert_not_called()
        assert bot._suspend_heartbeat_active is True

    def test_poll_loop_records_successful_poll(self, tmp_path, _patch_base_bot_deps):
        """The anchor is only meaningful if run() actually stamps it on a good poll."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        assert bot._last_successful_poll_at == 0.0

        def _one_poll(_offset):
            bot.state["running"] = False
            return []

        with (
            patch.object(bot, "_verify_connection_with_retry", return_value=True),
            patch.object(bot, "_set_command_menu"),
            patch.object(bot, "_boot_monitor"),
            patch.object(bot, "_check_lock", return_value=False),
            patch.object(bot, "_create_lock"),
            patch.object(bot, "clean_stale_pending"),
            patch.object(bot, "_load_offset", return_value=0),
            patch.object(bot, "poll_updates", side_effect=_one_poll),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", return_value=7777.0),
        ):
            bot.run()

        assert bot._last_successful_poll_at == 7777.0


# =============================================
# in-flight turn hold — never suspend out from under a reply that hasn't sent
# =============================================


def _write_pending(tmp_path, bot_id, delivered, timestamp):
    (tmp_path / f"bot-{bot_id}.json").write_text(
        json.dumps({"chat_id": 1, "delivered": delivered, "timestamp": timestamp})
    )


class TestTurnInFlightHold:
    def test_undelivered_pending_is_in_flight(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        _write_pending(tmp_path, "base", delivered=False, timestamp=time.time())

        assert bot._turn_in_flight() is True

    def test_sibling_bot_pending_counts(self, tmp_path, _patch_base_bot_deps):
        """The control bot must see a turn in flight on @devpulse, not just its own."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        _write_pending(tmp_path, "devpulse", delivered=False, timestamp=time.time())

        assert bot._turn_in_flight() is True

    def test_delivered_pending_is_not_in_flight(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        _write_pending(tmp_path, "base", delivered=True, timestamp=time.time())

        assert bot._turn_in_flight() is False

    def test_wedged_pending_cannot_block_forever(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        _write_pending(tmp_path, "base", delivered=False, timestamp=time.time() - PENDING_STUCK_TIMEOUT_SECONDS - 1)

        assert bot._turn_in_flight() is False

    def test_corrupt_pending_is_skipped(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        (tmp_path / "bot-base.json").write_text("{{{not json")

        assert bot._turn_in_flight() is False

    def test_rearm_held_while_turn_in_flight(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_resume_pending_since = 1000.0
        bot._suspend_grace_started_at = 1000.0
        now = 1000.0 + SUSPEND_GRACE_WINDOW_SECONDS + 1
        _write_pending(tmp_path, "devpulse", delivered=False, timestamp=now - 5)

        missing = tmp_path / "no_signal.json"
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", return_value=now),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        mock_run.assert_not_called()  # grace elapsed, but a reply is still owed
        assert bot._suspend_resume_pending_since == 1000.0  # window stays open, re-checked next poll

    def test_rearms_once_the_turn_completes(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        bot._suspend_resume_pending_since = 1000.0
        bot._suspend_grace_started_at = 1000.0
        now = 1000.0 + SUSPEND_GRACE_WINDOW_SECONDS + 1
        _write_pending(tmp_path, "devpulse", delivered=True, timestamp=now - 5)

        missing = tmp_path / "no_signal.json"
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.time.time", return_value=now),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        assert mock_run.call_args_list[0].args[0][:5] == ["sudo", "-n", RTCWAKE_BIN, "-m", "no"]


# =============================================
# suspend_enabled — ops kill-switch, no code edit needed to ground the verb
# =============================================


class TestSuspendEnabledFlag:
    def test_disabled_rejects_before_any_subprocess(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch(
                "aipass.skills.lib.telegram.apps.handlers.config.load_bot_config",
                return_value={"suspend_enabled": False},
            ),
            patch("subprocess.run") as mock_run,
        ):
            bot._handle_control_suspend(chat_id=1, arg="8h")

        mock_run.assert_not_called()
        assert bot._suspend_heartbeat_active is False
        assert "suspend_enabled=false" in bot.send_message.call_args[0][1]  # type: ignore[union-attr]

    def test_absent_flag_defaults_to_enabled(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch("aipass.skills.lib.telegram.apps.handlers.config.load_bot_config", return_value={"other": 1}),
            patch("subprocess.run") as mock_run,
        ):
            bot._handle_control_suspend(chat_id=1, arg="8h")

        assert mock_run.call_count == 2  # rtcwake, systemctl suspend

    def test_explicit_true_allows_suspend(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch(
                "aipass.skills.lib.telegram.apps.handlers.config.load_bot_config",
                return_value={"suspend_enabled": True},
            ),
            patch("subprocess.run") as mock_run,
        ):
            bot._handle_control_suspend(chat_id=1, arg="8h")

        assert mock_run.call_count == 2

    def test_unreadable_config_defaults_to_enabled(self, tmp_path, _patch_base_bot_deps):
        """A broken secrets store must not silently ground a verb ops depends on."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with (
            patch(
                "aipass.skills.lib.telegram.apps.handlers.config.load_bot_config",
                side_effect=Exception("secrets store down"),
            ),
            patch("subprocess.run") as mock_run,
        ):
            bot._handle_control_suspend(chat_id=1, arg="8h")

        assert mock_run.call_count == 2


# =============================================
# adaptive cadence (devpulse addendum 2026-08-02) — Jul 30-Aug 1's short beats
# were accidental (spurious wakes), but that duty-cycle IS the behaviour Patrick
# experienced as chat-behind-suspend working. Recreate it deliberately.
# =============================================


class TestAdaptiveHeartbeatCadence:
    def test_quiet_uses_the_long_beat(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        assert bot._suspend_heartbeat_seconds() == SUSPEND_HEARTBEAT_DEFAULT_MINUTES * 60

    def test_live_conversation_uses_the_short_beat(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        _stamp_inbound(tmp_path, time.time() - 60)  # spoke a minute ago

        assert bot._suspend_heartbeat_seconds() == SUSPEND_ACTIVE_HEARTBEAT_DEFAULT_MINUTES * 60

    def test_conversation_gone_cold_falls_back_to_the_long_beat(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        stale = time.time() - (SUSPEND_ACTIVE_WINDOW_DEFAULT_MINUTES * 60 + 60)
        _stamp_inbound(tmp_path, stale)

        assert bot._suspend_heartbeat_seconds() == SUSPEND_HEARTBEAT_DEFAULT_MINUTES * 60

    def test_chat_on_another_bot_tightens_this_bots_cadence(self, tmp_path, _patch_base_bot_deps):
        """The point of the shared stamp: talking to @devpulse speeds up the control bot's beats."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        _stamp_inbound(tmp_path, time.time() - 5, bot_id="devpulse")

        assert bot._suspend_heartbeat_seconds() == SUSPEND_ACTIVE_HEARTBEAT_DEFAULT_MINUTES * 60

    def test_all_three_cadence_knobs_are_config_driven(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        _stamp_inbound(tmp_path, time.time() - 600)  # 10m ago: outside default window, inside custom

        config = {
            "suspend_heartbeat_minutes": 40,
            "suspend_active_heartbeat_minutes": 2,
            "suspend_active_window_minutes": 45,
        }
        with patch("aipass.skills.lib.telegram.apps.handlers.config.load_bot_config", return_value=config):
            assert bot._suspend_heartbeat_seconds() == 2 * 60

            (tmp_path / "last_inbound.json").unlink()
            assert bot._suspend_heartbeat_seconds() == 40 * 60

    def test_config_failure_falls_back_to_defaults(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.config.load_bot_config",
            side_effect=Exception("secrets store down"),
        ):
            assert bot._suspend_heartbeat_seconds() == SUSPEND_HEARTBEAT_DEFAULT_MINUTES * 60

    def test_rearm_after_live_chat_uses_the_short_beat(self, tmp_path, _patch_base_bot_deps):
        """End to end: the re-arm the grace window fires picks up the adaptive interval."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_chat_id = 7
        now = time.time()
        bot._suspend_resume_pending_since = now - SUSPEND_GRACE_WINDOW_SECONDS - 10
        bot._suspend_grace_started_at = now - SUSPEND_GRACE_WINDOW_SECONDS - 10
        # Spoke before the resume — presence doesn't cancel, but the conversation is still warm.
        _stamp_inbound(tmp_path, now - SUSPEND_GRACE_WINDOW_SECONDS - 60)

        missing = tmp_path / "no_signal.json"
        with (
            patch("aipass.skills.lib.telegram.apps.handlers.base_bot.RESUME_SIGNAL_FILE", missing),
            patch("subprocess.run") as mock_run,
        ):
            bot._check_resume_signal()

        armed = mock_run.call_args_list[0].args[0]
        assert armed[:5] == ["sudo", "-n", RTCWAKE_BIN, "-m", "no"]
        assert armed[6] == str(SUSPEND_ACTIVE_HEARTBEAT_DEFAULT_MINUTES * 60)


# =============================================
# /lock — the verb that actually serves the use case /suspend was doing:
# password-lock + dark screen, agents keep running (devpulse 7fedf6e8)
# =============================================


class TestLockVerb:
    def test_lock_resolves_the_graphical_session_and_locks_it_by_id(self, tmp_path, _patch_base_bot_deps):
        """
        The bot runs as a `systemd --user` service with no XDG_SESSION_ID, so a
        bare `loginctl lock-session` has no ambient session to resolve. Naming
        the session explicitly is what makes the verb work from that context.
        """
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", side_effect=_loginctl_stub()) as mock_run:
            bot._handle_control_lock(chat_id=1)

        assert call(["loginctl", "lock-session", "3"], check=True, capture_output=True) in mock_run.call_args_list
        bot.send_message.assert_called_once_with(1, "🔒 Locked — agents stay awake.")  # type: ignore[union-attr]

    def test_lock_picks_the_x11_session_too(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        stub = _loginctl_stub(props={"7": {"Type": "x11", "State": "active", "User": _UID}}, sessions="7 …\n")

        with patch("subprocess.run", side_effect=stub) as mock_run:
            bot._handle_control_lock(chat_id=1)

        assert call(["loginctl", "lock-session", "7"], check=True, capture_output=True) in mock_run.call_args_list

    def test_lock_skips_tty_and_inactive_sessions(self, tmp_path, _patch_base_bot_deps):
        """A headless tty login and a backgrounded graphical session must not win."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        stub = _loginctl_stub(
            sessions="1 …\n2 …\n3 …\n",
            props={
                "1": {"Type": "tty", "State": "active", "User": _UID},
                "2": {"Type": "wayland", "State": "online", "User": _UID},
                "3": {"Type": "wayland", "State": "active", "User": _UID},
            },
        )

        with patch("subprocess.run", side_effect=stub) as mock_run:
            bot._handle_control_lock(chat_id=1)

        assert call(["loginctl", "lock-session", "3"], check=True, capture_output=True) in mock_run.call_args_list

    def test_lock_ignores_another_users_graphical_session(self, tmp_path, _patch_base_bot_deps):
        """Never lock someone else's desktop — with no session of ours, fall back to the bare call."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        other_uid = str(int(_UID) + 1)
        stub = _loginctl_stub(props={"3": {"Type": "wayland", "State": "active", "User": other_uid}})

        with patch("subprocess.run", side_effect=stub) as mock_run:
            bot._handle_control_lock(chat_id=1)

        assert call(["loginctl", "lock-session"], check=True, capture_output=True) in mock_run.call_args_list
        for call_args in mock_run.call_args_list:
            assert "lock-session" not in call_args.args[0] or len(call_args.args[0]) == 2

    def test_lock_falls_back_to_bare_call_when_listing_fails(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        stub = _loginctl_stub(list_error=_cpe(["loginctl"], stderr=b"boom"))

        with patch("subprocess.run", side_effect=stub) as mock_run:
            bot._handle_control_lock(chat_id=1)

        assert call(["loginctl", "lock-session"], check=True, capture_output=True) in mock_run.call_args_list
        bot.send_message.assert_called_once_with(1, "🔒 Locked — agents stay awake.")  # type: ignore[union-attr]

    def test_lock_survives_blank_lines_in_session_listing(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", side_effect=_loginctl_stub(sessions="\n\n3 …\n\n")) as mock_run:
            bot._handle_control_lock(chat_id=1)

        assert call(["loginctl", "lock-session", "3"], check=True, capture_output=True) in mock_run.call_args_list

    def test_lock_falls_back_to_dbus_when_loginctl_refuses(self, tmp_path, _patch_base_bot_deps):
        """Refusal from the service context is exactly the case the D-Bus path exists for."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        stub = _loginctl_stub(lock_error=_cpe(["loginctl"], stderr=b"Interactive authentication required."))

        with patch("subprocess.run", side_effect=stub) as mock_run:
            bot._handle_control_lock(chat_id=1)

        dbus_calls = [c for c in mock_run.call_args_list if c.args[0][0] == "gdbus"]
        assert len(dbus_calls) == 1
        assert "org.gnome.ScreenSaver.Lock" in dbus_calls[0].args[0]
        bot.send_message.assert_called_once_with(1, "🔒 Locked — agents stay awake.")  # type: ignore[union-attr]

    def test_lock_falls_back_to_dbus_when_loginctl_is_missing(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        # loginctl absent entirely — both the listing and the lock raise.
        stub = _loginctl_stub(list_error=FileNotFoundError(), lock_error=FileNotFoundError())

        with patch("subprocess.run", side_effect=stub) as mock_run:
            bot._handle_control_lock(chat_id=1)

        assert any(c.args[0][0] == "gdbus" for c in mock_run.call_args_list)
        bot.send_message.assert_called_once_with(1, "🔒 Locked — agents stay awake.")  # type: ignore[union-attr]

    def test_lock_reports_honestly_when_both_paths_fail(self, tmp_path, _patch_base_bot_deps):
        """No silent success — a screen that never locked must not be acked as locked."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        stub = _loginctl_stub(
            lock_error=_cpe(["loginctl"], stderr=b"refused"),
            dbus_error=_cpe(["gdbus"], stderr=b"no session bus"),
        )

        with patch("subprocess.run", side_effect=stub):
            bot._handle_control_lock(chat_id=1)

        bot.send_message.assert_called_once_with(  # type: ignore[union-attr]
            1, "Could not lock the screen — loginctl and the D-Bus fallback both failed."
        )

    def test_lock_needs_no_root_or_rtcwake(self, tmp_path, _patch_base_bot_deps):
        """No sudo, no rtcwake, no systemctl — that's the whole point of the verb."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", side_effect=_loginctl_stub()) as mock_run:
            bot._handle_control_lock(chat_id=1)

        for call_args in mock_run.call_args_list:
            assert call_args.args[0][0] not in ("sudo", "systemctl")
            assert RTCWAKE_BIN not in call_args.args[0]

    def test_lock_does_not_touch_suspend_state(self, tmp_path, _patch_base_bot_deps):
        """Locking must never disturb an active heartbeat — they're independent verbs."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)
        bot._suspend_heartbeat_active = True
        bot._suspend_alarm_at = 2500.0

        with patch("subprocess.run", side_effect=_loginctl_stub()):
            bot._handle_control_lock(chat_id=1)

        assert bot._suspend_heartbeat_active is True
        assert bot._suspend_alarm_at == 2500.0

    def test_lock_never_suspends(self, tmp_path, _patch_base_bot_deps):
        """Ruling #217: the machine stays awake. /lock must not sleep anything."""
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch("subprocess.run", side_effect=_loginctl_stub()) as mock_run:
            bot._handle_control_lock(chat_id=1)

        for call_args in mock_run.call_args_list:
            assert "suspend" not in " ".join(call_args.args[0])

    def test_lock_routed_for_control_bot(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps)

        with patch.object(bot, "_handle_control_lock") as mock_handler:
            handled = bot._dispatch_command(chat_id=1, parsed=("lock", ""))

        assert handled is True
        mock_handler.assert_called_once_with(1)

    def test_branch_bot_does_not_get_lock(self, tmp_path, _patch_base_bot_deps):
        bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="devpulse")

        with patch.object(bot, "_handle_control_lock") as mock_handler:
            bot._dispatch_command(chat_id=1, parsed=("lock", ""))

        mock_handler.assert_not_called()

    def test_lock_in_custom_commands_for_control_bot_only(self, tmp_path, _patch_base_bot_deps):
        control_bot = _make_bot(tmp_path, _patch_base_bot_deps)
        branch_bot = _make_bot(tmp_path, _patch_base_bot_deps, branch_name="devpulse")

        assert "lock" in control_bot.get_custom_commands()
        assert "lock" not in branch_bot.get_custom_commands()
