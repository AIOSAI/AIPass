# =================== AIPass ====================
# Name: test_dispatch_monitor_wake.py
# Description: Tests for the dispatch monitor's wake-back - the sender wake, its log, the manager mail and the decline
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's wake-back: _wake_sender, _log_wake_result, main()'s wake."""

# Split out of test_dispatch_monitor.py on 2026-10-08 to keep that file under the
# 1,200-line target: who is woken or mailed when a dispatch completes.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — main()'s attempts and the bounce: tests/test_dispatch_monitor.py

import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import (
    MAX_WAKE_DEPTH,
    _log_wake_result,
    _wake_sender,
    main,
)
from aipass.ai_mail.apps.handlers.dispatch.wake import DispatchStatus
from aipass.ai_mail.tests.support_dispatch_monitor import _assert_sent_as_ai_mail

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


# === Wake-back tests (TDPLAN-0012) ==========================================


class TestWakeSender:
    """_wake_sender guards and wake-back dispatch."""

    def test_skips_empty_sender(self, monkeypatch, tmp_path):
        """Empty sender returns skipped_sender and logs why."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        result = _wake_sender("", "@target", 0)
        assert result == "skipped_sender"
        log.info.assert_called_once_with("[monitor] Wake-back skipped — no sender")

    def test_skips_whitespace_sender(self, monkeypatch, tmp_path):
        """Whitespace-only sender returns skipped_sender and logs why."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        result = _wake_sender("   ", "@target", 0)
        assert result == "skipped_sender"
        log.info.assert_called_once_with("[monitor] Wake-back skipped — no sender")

    def test_skips_self_wake(self, monkeypatch, tmp_path):
        """Sender equal to completed agent returns skipped_self and names the sender."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        result = _wake_sender("@trigger", "@trigger", 0)
        assert result == "skipped_self"
        log.info.assert_called_once_with(
            "[monitor] Wake-back skipped — sender %s is the completed agent (self-wake)", "@trigger"
        )

    def test_skips_self_wake_case_insensitive(self, monkeypatch, tmp_path):
        """Self-wake guard is case-insensitive; the log keeps the sender as written."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        result = _wake_sender("Trigger", "@TRIGGER", 0)
        assert result == "skipped_self"
        log.info.assert_called_once_with(
            "[monitor] Wake-back skipped — sender %s is the completed agent (self-wake)", "Trigger"
        )

    def test_wake_back_carries_empty_sender(self, monkeypatch, tmp_path):
        """Wake-back session carries empty sender to terminate the chain."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)
        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )
        _wake_sender("@prax", "@trigger", 0)
        _, kwargs = mock_wake.call_args
        assert mock_wake.call_args.args == ("@prax",)
        assert kwargs["auto"] is True
        assert kwargs["sender"] == ""
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@prax", "@trigger", 0
        )

    def test_any_citizen_reaches_wake_branch(self, monkeypatch, tmp_path):
        """Any citizen sender reaches wake_branch."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)
        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )
        result = _wake_sender("@prax", "@target", 0)
        assert result == "success"
        mock_wake.assert_called_once()
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@prax", "@target", 0
        )

    def test_depth_cap_blocks(self, monkeypatch, tmp_path):
        """AIPASS_WAKE_DEPTH >= MAX_WAKE_DEPTH returns blocked_depth and warns with both numbers."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.setenv("AIPASS_WAKE_DEPTH", str(MAX_WAKE_DEPTH))
        result = _wake_sender("@prax", "@target", 0)
        assert result == "blocked_depth"
        log.warning.assert_called_once_with(
            "[monitor] Wake-back skipped — depth %d >= max %d", MAX_WAKE_DEPTH, MAX_WAKE_DEPTH
        )

    def test_depth_cap_over_max_blocks(self, monkeypatch, tmp_path):
        """Depth above max also blocks, and the warning carries the depth read."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.setenv("AIPASS_WAKE_DEPTH", str(MAX_WAKE_DEPTH + 5))
        result = _wake_sender("@prax", "@target", 0)
        assert result == "blocked_depth"
        log.warning.assert_called_once_with(
            "[monitor] Wake-back skipped — depth %d >= max %d", MAX_WAKE_DEPTH + 5, MAX_WAKE_DEPTH
        )

    def test_success_on_wake(self, monkeypatch, tmp_path):
        """Successful wake_branch call returns success."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        result = _wake_sender("@trigger", "@target", 0)
        assert result == "success"
        _, kwargs = mock_wake.call_args
        assert mock_wake.call_args.args == ("@trigger",)
        assert kwargs["auto"] is True
        assert kwargs["sender"] == ""
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@trigger", "@target", 0
        )

    def test_wake_back_message_names_completed_target(self, monkeypatch, tmp_path):
        """Wake-back custom_message names the completed target and exit code,
        not the generic mail-check prompt — the woken lead was told nothing
        about which target finished (@daemon, 077cd1cf)."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        _wake_sender("@prax", "@target", 1)
        _, kwargs = mock_wake.call_args
        assert "@target" in kwargs["custom_message"]
        assert "1" in kwargs["custom_message"]
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@prax", "@target", 1
        )

    def test_blocked_locked_on_lock_failure(self, monkeypatch, tmp_path):
        """wake_branch failing with lock-related message returns blocked_locked."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "lock: Active agent (PID 1234)"
        mock_wake = MagicMock(return_value=(mock_status, False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        result = _wake_sender("@prax", "@target", 0)
        assert result == "blocked_locked"
        log.info.assert_called_once_with(
            "[monitor] Wake-back blocked — sender %s has active lock: %s", "@prax", "lock: Active agent (PID 1234)"
        )

    def test_blocked_occupied_on_interactive(self, monkeypatch, tmp_path):
        """wake_branch failing with occupancy message returns blocked_occupied."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "blocked: Cannot spawn — interactive session running"
        mock_wake = MagicMock(return_value=(mock_status, False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        result = _wake_sender("@trigger", "@target", 0)
        assert result == "blocked_occupied"
        log.info.assert_called_once_with(
            "[monitor] Wake-back blocked — sender %s has interactive session: %s",
            "@trigger",
            "blocked: Cannot spawn — interactive session running",
        )

    def test_failed_on_exception(self, monkeypatch, tmp_path):
        """Exception during wake returns failed and warns with the error."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)
        boom = RuntimeError("broken")

        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            MagicMock(side_effect=boom),
        )

        result = _wake_sender("@prax", "@target", 0)
        assert result == "failed"
        log.warning.assert_called_once_with("[monitor] Wake-back failed for %s: %s", "@prax", boom)

    def test_depth_incremented_before_wake(self, monkeypatch, tmp_path):
        """AIPASS_WAKE_DEPTH is incremented before calling wake_branch."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.setenv("AIPASS_WAKE_DEPTH", "1")

        captured_depth = []

        def capture_wake(*args, **kwargs):
            captured_depth.append(os.environ.get("AIPASS_WAKE_DEPTH"))
            mock_status = MagicMock()
            mock_status.summary = "ok"
            return mock_status, True

        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            capture_wake,
        )

        _wake_sender("@trigger", "@target", 0)
        assert captured_depth == ["2"]
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@trigger", "@target", 0
        )

    def test_wake_called_on_failure_exit(self, monkeypatch, tmp_path):
        """Wake fires on non-zero exit code too."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        result = _wake_sender("@prax", "@target", 1)
        assert result == "success"
        mock_wake.assert_called_once()
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@prax", "@target", 1
        )


class TestLogWakeResult:
    """_log_wake_result writes to dispatch_wake.log."""

    def test_creates_log_file(self, tmp_path):
        """Log file created under target's logs/ directory."""
        lock = tmp_path / "branch" / ".ai_mail.local" / ".dispatch.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("{}", encoding="utf-8")
        logs_dir = tmp_path / "branch" / "logs"

        _log_wake_result("@target", "@sender", 0, "success", str(lock))

        log_file = logs_dir / "dispatch_wake.log"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "target=@target" in content
        assert "sender=@sender" in content
        assert "exit_code=0" in content
        assert "wake_result=success" in content

    def test_appends_to_existing(self, tmp_path):
        """Subsequent calls append, not overwrite."""
        lock = tmp_path / "branch" / ".ai_mail.local" / ".dispatch.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("{}", encoding="utf-8")
        logs_dir = tmp_path / "branch" / "logs"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "dispatch_wake.log"
        log_file.write_text("existing line\n", encoding="utf-8")

        _log_wake_result("@target", "@sender", 0, "success", str(lock))

        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "existing line"
        assert "wake_result=success" in lines[1]

    def test_all_result_values(self, tmp_path):
        """All result enum values are logged correctly."""
        lock = tmp_path / "branch" / ".ai_mail.local" / ".dispatch.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("{}", encoding="utf-8")

        for result_tag in (
            "success",
            "blocked_occupied",
            "blocked_locked",
            "blocked_depth",
            "skipped_sender",
            "failed",
        ):
            _log_wake_result("@t", "@s", 0, result_tag, str(lock))

        log_file = tmp_path / "branch" / "logs" / "dispatch_wake.log"
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 6


class TestWakeBackIntegration:
    """Wake-back wired into main() — fires after lock cleanup on both paths."""

    def test_wake_called_on_success(self, monkeypatch, main_argv, tmp_path):
        """_wake_sender called with correct args after successful agent run."""
        argv, lock_file, stderr_log = main_argv

        wake_calls = []

        def track_wake(sender, branch_email, exit_code):
            wake_calls.append((sender, branch_email, exit_code))
            return "success"

        bounce = MagicMock()
        log_result = MagicMock()
        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "_wake_sender", track_wake)
        monkeypatch.setattr(mod, "_log_wake_result", log_result)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert len(wake_calls) == 1
        assert wake_calls[0] == ("@sender", "@test_branch", 0)
        bounce.assert_not_called()
        log_result.assert_called_once_with("@test_branch", "@sender", 0, "success", str(lock_file))

    def test_wake_called_on_failure(self, monkeypatch, main_argv, tmp_path):
        """_wake_sender called after all attempts fail (in addition to bounce)."""
        argv, lock_file, stderr_log = main_argv

        wake_calls = []
        mock_bounce = MagicMock()

        def track_wake(sender, branch_email, exit_code):
            wake_calls.append((sender, branch_email, exit_code))
            return "success"

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(1, False), (1, False), (1, False)]))
        monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "_wake_sender", track_wake)
        log_result = MagicMock()
        monkeypatch.setattr(mod, "_log_wake_result", log_result)
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

        mock_bounce.assert_called_once()
        assert len(wake_calls) == 1
        assert wake_calls[0][2] != 0
        log_result.assert_called_once_with("@test_branch", "@sender", wake_calls[0][2], "success", str(lock_file))

    def test_log_wake_result_called(self, monkeypatch, main_argv, tmp_path):
        """_log_wake_result called with wake result after main completes."""
        argv, lock_file, stderr_log = main_argv

        log_calls = []
        bounce = MagicMock()

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "_wake_sender", MagicMock(return_value="success"))
        monkeypatch.setattr(mod, "_log_wake_result", lambda *a: log_calls.append(a))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit):
            main()

        assert len(log_calls) == 1
        branch_email, sender, exit_code, result, lf = log_calls[0]
        assert branch_email == "@test_branch"
        assert sender == "@sender"
        assert exit_code == 0
        assert result == "success"
        bounce.assert_not_called()


# === Wake-back honesty: manager senders (VERA field report) =================
#
# wake_branch's manager gate delivers the mail and skips the wake by design, but
# returns (status, True) — so _wake_sender read success=True and logged
# "woken after ... completed" for a wake that never happened. The status object
# was honest; the bool was not. These pin the honest tag.


class TestWakeBackManagerHonesty:
    """A manager sender is mailed, never woken — the log must say exactly that."""

    @staticmethod
    def _manager_gate_status():
        """Real DispatchStatus as wake_branch's manager gate leaves it."""
        status = DispatchStatus()
        status.ok("resolve", "@devpulse → /repo/src/aipass/devpulse")
        status.info("manager", "@devpulse is a manager — mail only, wake skipped")
        return status

    @staticmethod
    def _patch_wake(monkeypatch, status, success):
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)
        mock_wake = MagicMock(return_value=(status, success))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )
        return mock_wake

    def test_manager_sender_returns_mailed_manager(self, monkeypatch, tmp_path):
        """The gate's True must not be reported as a successful wake.

        Tag changed from skipped_manager to mailed_manager on 2026-08-21: the
        manager is no longer merely skipped, it is mailed. "Skipped" was the
        honest tag for a silent drop and is the wrong word for a delivery.
        """
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        monkeypatch.setattr(
            mod.subprocess, "run", MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        )
        result = _wake_sender("@devpulse", "@ai_mail", 0)
        assert result == "mailed_manager"
        log.info.assert_called_once_with(
            "[monitor] Wake-back mailed to manager %s (%s exit %d)", "@devpulse", "@ai_mail", 0
        )

    def test_manager_wake_back_never_claims_woken(self, monkeypatch, tmp_path):
        """No log line may assert the manager was woken — it says MAILED instead."""
        mock_logger = MagicMock()
        monkeypatch.setattr(mod, "logger", mock_logger)
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        monkeypatch.setattr(
            mod.subprocess, "run", MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        )

        _wake_sender("@devpulse", "@ai_mail", 0)

        formats = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
        assert not any("woken after" in f for f in formats), f"claimed a wake: {formats}"
        assert any("mailed" in f.lower() for f in formats), f"no mail logged: {formats}"

    def test_daemon_bypassed_manager_still_reports_success(self, monkeypatch, tmp_path):
        """The @daemon self-wake exception records manager as ok — that IS a real wake."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        status = DispatchStatus()
        status.ok("manager", "@devpulse manager gate bypassed — daemon-scheduled self-wake")
        status.ok("spawn", "agent started")
        self._patch_wake(monkeypatch, status, True)
        result = _wake_sender("@devpulse", "@ai_mail", 0)
        assert result == "success"
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@devpulse", "@ai_mail", 0
        )

    def test_builder_sender_unaffected(self, monkeypatch, tmp_path):
        """A normal citizen has no manager step and still reports success."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        status = DispatchStatus()
        status.ok("resolve", "@prax → /repo/src/aipass/prax")
        status.ok("spawn", "agent started")
        self._patch_wake(monkeypatch, status, True)
        result = _wake_sender("@prax", "@ai_mail", 0)
        assert result == "success"
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@prax", "@ai_mail", 0
        )

    def test_manager_sender_is_mailed_not_silently_dropped(self, monkeypatch, tmp_path):
        """P0: a manager was TOLD it would be woken and then silently was not.

        The blocklist is correct and stays — two claudes on one session id kills
        the running job (the OSPREY kill). The bug is the silent return: the
        wake-back message was built and dropped on the floor, so a manager learned
        a dispatch finished only if the agent volunteered an email. Ten consecutive
        skipped_manager lines in canary's dispatch_wake.log, and @devpulse confirmed
        it live twice tonight (@ai_mail and @drone back to back).
        """
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        sent = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(mod.subprocess, "run", sent)

        result = _wake_sender("@devpulse", "@ai_mail", 0)

        assert result == "mailed_manager"
        assert sent.called, "manager wake-back sent no mail — the silent drop"
        argv = sent.call_args.args[0]
        assert argv[:3] == ["drone", "@ai_mail", "send"]
        assert argv[3] == "@devpulse"
        log.warning.assert_not_called()

    def test_manager_mail_names_target_and_exit_code(self, monkeypatch, tmp_path):
        """The mail must carry what the dropped wake-back carried: WHICH target
        finished and how. A manager cannot verify or hand off the next phase
        without it (@daemon, 077cd1cf)."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        sent = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(mod.subprocess, "run", sent)

        _wake_sender("@devpulse", "@ai_mail", 3)

        body = " ".join(sent.call_args.args[0][4:])
        assert "@ai_mail" in body
        assert "3" in body
        log.info.assert_called_once_with(
            "[monitor] Wake-back mailed to manager %s (%s exit %d)", "@devpulse", "@ai_mail", 3
        )

    def test_manager_mail_failure_is_not_reported_as_delivered(self, monkeypatch, tmp_path):
        """If the send fails the manager still learns nothing — that must not wear
        the same tag as a delivered mail. Same lesson as the gate's True."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        monkeypatch.setattr(
            mod.subprocess, "run", MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr="boom"))
        )

        result = _wake_sender("@devpulse", "@ai_mail", 0)
        assert result == "failed_manager_mail"
        log.warning.assert_called_once_with(
            "[monitor] Wake-back mail to manager %s FAILED (exit %d): %s", "@devpulse", 1, "boom"
        )

    def test_non_manager_wake_back_sends_no_mail(self, monkeypatch, tmp_path):
        """An ordinary citizen is woken, not mailed. The mail exists only because
        the wake cannot happen — adding it everywhere would double every wake-back."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        status = DispatchStatus()
        status.ok("resolve", "@prax → /repo/src/aipass/prax")
        status.ok("spawn", "agent started")
        self._patch_wake(monkeypatch, status, True)
        sent = MagicMock()
        monkeypatch.setattr(mod.subprocess, "run", sent)

        result = _wake_sender("@prax", "@ai_mail", 0)
        assert result == "success"
        assert not sent.called
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@prax", "@ai_mail", 0
        )

    def test_skipped_manager_reaches_the_wake_log(self, monkeypatch, tmp_path):
        """The honest tag is what lands in dispatch_wake.log, and a good write logs no failure."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        lock_file = tmp_path / ".ai_mail.local" / ".dispatch.lock"
        lock_file.parent.mkdir(parents=True)
        lock_file.write_text("{}", encoding="utf-8")

        _log_wake_result("@ai_mail", "@devpulse", 0, "skipped_manager", str(lock_file))

        written = (tmp_path / "logs" / "dispatch_wake.log").read_text(encoding="utf-8")
        assert "wake_result=skipped_manager" in written
        log.info.assert_not_called()
        assert "sender=@devpulse" in written


# === Wake-back declined by the caller ========================================
#
# @daemon's inbox-sweep wakes a branch only to nudge it to read its own mail.
# A nudge owes no reply, yet on completion the monitor woke @daemon back to
# "check its reply" — a fresh session reading an empty inbox (4 wake-backs on
# 2026-09-10, 2 on 09-09). wake_branch(wake_back=False) now carries
# --no-wake-back between the four positionals and "--", and the monitor then
# neither wakes nor mails the sender. Everything else on completion stays.


def _declining(argv):
    """The same monitor argv with --no-wake-back where wake.py puts it: before '--'."""
    sep = argv.index("--")
    return [*argv[:sep], "--no-wake-back", *argv[sep:]]


def _drone_sends(run_mock):
    """Every `drone @ai_mail send ...` the run mock saw, as argv lists."""
    return [
        c.args[0]
        for c in run_mock.call_args_list
        if c.args and isinstance(c.args[0], list) and c.args[0][:3] == ["drone", "@ai_mail", "send"]
    ]


class TestWakeBackDeclinedByCaller:
    """--no-wake-back: completion runs, the sender is neither woken nor mailed."""

    @staticmethod
    def _manager_gate_status():
        """What wake_branch's manager gate returns — the path that MAILS the sender."""
        status = DispatchStatus()
        status.ok("resolve", "@sender → /repo/src/aipass/sender")
        status.info("manager", "@sender is a manager — wake skipped, caller must mail")
        return status

    @staticmethod
    def _builder_status():
        status = DispatchStatus()
        status.ok("resolve", "@sender → /repo/src/aipass/sender")
        status.ok("spawn", "agent started")
        return status

    @staticmethod
    def _run_main(monkeypatch, argv, wake_status, tmp_path, *, exit_code=0):
        """Drive main() to the end with the REAL wake-back chain behind it.

        _wake_sender, _mail_wake_back and _log_wake_result are the real ones
        (the autouse fixture mocks the first and last; restored here). Only the
        edges are faked: wake_branch, so nothing spawns, and subprocess.run, so
        no mail leaves. Whatever the monitor decides, those mocks record it.
        """
        monkeypatch.setenv("AIPASS_WAKE_DEPTH", "0")  # registers an undo: _wake_sender bumps it
        wake = MagicMock(return_value=(wake_status, True))
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch", wake)
        sent = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(mod.subprocess, "run", sent)
        mail = MagicMock(wraps=mod._mail_wake_back)
        monkeypatch.setattr(mod, "_mail_wake_back", mail)
        monkeypatch.setattr(mod, "_wake_sender", _wake_sender)
        monkeypatch.setattr(mod, "_log_wake_result", _log_wake_result)
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        bounce = MagicMock(return_value=True)
        monkeypatch.setattr(mod, "_send_bounce", bounce)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(exit_code, False)))
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        return {"exit": exc_info.value.code, "wake": wake, "sent": sent, "mail": mail, "log": log, "bounce": bounce}

    @staticmethod
    def _wake_log(lock_file):
        return (Path(lock_file).parent.parent / "logs" / "dispatch_wake.log").read_text(encoding="utf-8")

    def test_declined_completion_neither_wakes_nor_mails_the_sender(self, monkeypatch, main_argv, tmp_path):
        """The fix, red on the old monitor: it ignored the flag and ran the full
        wake-back. The status is the MANAGER gate's on purpose — that is the one
        path where a wake attempt turns into mail, so BOTH halves are observable."""
        argv, lock_file, _ = main_argv

        got = self._run_main(monkeypatch, _declining(argv), self._manager_gate_status(), tmp_path)

        assert got["exit"] == 0, "completion must still run to its end"
        got["wake"].assert_not_called()
        got["mail"].assert_not_called()
        assert _drone_sends(got["sent"]) == [], "a declined wake-back must send no mail"

    def test_without_the_flag_a_manager_sender_is_still_mailed(self, monkeypatch, main_argv, tmp_path):
        """The default is today's contract, byte for byte: wake attempt, gate, mail."""
        argv, lock_file, _ = main_argv

        got = self._run_main(monkeypatch, argv, self._manager_gate_status(), tmp_path)

        got["wake"].assert_called_once()
        assert got["wake"].call_args.args == ("@sender",)
        assert got["wake"].call_args.kwargs["sender"] == ""
        got["mail"].assert_called_once()
        sends = _drone_sends(got["sent"])
        assert len(sends) == 1 and sends[0][3] == "@sender"
        assert "wake_result=mailed_manager" in self._wake_log(lock_file)

    def test_the_wake_back_mail_is_sent_as_ai_mail(self, monkeypatch, main_argv, tmp_path):
        """The manager's wake-back mail is ai_mail's notice, under one claim (ai_mail, 2026-10-04).

        A monitor started in-process by another branch inherits that branch's
        name; "trigger" in the env stands in for it.
        """
        argv, _, _ = main_argv
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "trigger")

        got = self._run_main(monkeypatch, argv, self._manager_gate_status(), tmp_path)

        _assert_sent_as_ai_mail(got["sent"])

    def test_without_the_flag_a_builder_sender_is_still_woken(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, _ = main_argv

        got = self._run_main(monkeypatch, argv, self._builder_status(), tmp_path)

        got["wake"].assert_called_once()
        assert got["wake"].call_args.args == ("@sender",)
        assert _drone_sends(got["sent"]) == []
        assert "wake_result=success" in self._wake_log(lock_file)

    def test_a_declined_wake_back_logs_one_info_line_naming_target_and_sender(self, monkeypatch, main_argv, tmp_path):
        argv, _, _ = main_argv

        got = self._run_main(monkeypatch, _declining(argv), self._builder_status(), tmp_path)

        declined = [c for c in got["log"].info.call_args_list if c.args and "declined by caller" in c.args[0]]
        assert len(declined) == 1, f"expected one decline line, got {declined}"
        assert "@test_branch" in declined[0].args[1:]
        assert "@sender" in declined[0].args[1:]

    def test_a_declined_wake_back_is_recorded_as_declined_in_the_wake_log(self, monkeypatch, main_argv, tmp_path):
        """dispatch_wake.log still gets its line — with `declined` in place of a
        wake result, so a quiet sender reads as a choice, not a lost wake."""
        argv, lock_file, _ = main_argv

        self._run_main(monkeypatch, _declining(argv), self._builder_status(), tmp_path)

        written = self._wake_log(lock_file)
        assert "wake_result=declined" in written
        assert "target=@test_branch" in written
        assert "sender=@sender" in written

    def test_a_declined_wake_back_still_bounces_a_failure_to_the_sender(self, monkeypatch, main_argv, tmp_path):
        """The sender still rides argv because bounce mail reads it: declining
        the wake-back is not declining to hear that the dispatch FAILED."""
        argv, _, _ = main_argv

        got = self._run_main(monkeypatch, _declining(argv), self._builder_status(), tmp_path, exit_code=1)

        assert got["exit"] == 1
        got["bounce"].assert_called_once()
        assert got["bounce"].call_args.args[2] == "@sender"
        got["wake"].assert_not_called()

    def test_the_flag_is_read_only_before_the_separator(self, monkeypatch, main_argv, tmp_path):
        """Everything after '--' is the claude command; the same token there is
        claude's business and must not decline anything."""
        argv, lock_file, _ = main_argv

        got = self._run_main(monkeypatch, [*argv, "--no-wake-back"], self._builder_status(), tmp_path)

        got["wake"].assert_called_once()
        assert got["wake"].call_args.args == ("@sender",)
        assert "wake_result=success" in self._wake_log(lock_file)
