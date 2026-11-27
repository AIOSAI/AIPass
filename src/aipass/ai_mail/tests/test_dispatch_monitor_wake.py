# =================== AIPass ====================
# Name: test_dispatch_monitor_wake.py
# Description: Tests for the dispatch monitor's wake-back - the sender wake, its log, the manager mail and the decline
# Version: 1.3.4
# Created: 2026-10-08
# Modified: 2026-11-26
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's wake-back: wake_sender, main()'s wake, its report, the cloud lane."""

# Split out of test_dispatch_monitor.py on 2026-10-08 to keep that file under the
# 1,200-line target: who is woken or mailed when a dispatch completes.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(shared) — main()'s attempts and the bounce: tests/test_dispatch_monitor.py

import json
import os
import time
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.cloud as cloud_mod
import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import (
    MAX_WAKE_DEPTH,
    wake_sender,
    main,
)
from aipass.ai_mail.apps.handlers.dispatch.wake import DispatchStatus
from aipass.ai_mail.tests.support_dispatch_monitor import _assert_sent_as_ai_mail, _assert_sent_from, _foreign_project

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


def _report() -> dict:
    """The one completion report main() wrote, read back from disk."""
    written = list(mod.report_mod.reports_dir().glob("*.json"))
    assert len(written) == 1, f"expected one report, got {written}"
    return json.loads(written[0].read_text(encoding="utf-8"))


# === Wake-back tests (TDPLAN-0012) ==========================================


class TestWakeSender:
    """wake_sender guards and wake-back dispatch."""

    def test_skips_empty_sender(self, monkeypatch, tmp_path):
        """Empty sender returns skipped_sender and logs why."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        result = wake_sender("", "@target", 0)
        assert result == "skipped_sender"
        log.info.assert_called_once_with("[monitor] Wake-back skipped — no sender")

    def test_skips_whitespace_sender(self, monkeypatch, tmp_path):
        """Whitespace-only sender returns skipped_sender and logs why."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        result = wake_sender("   ", "@target", 0)
        assert result == "skipped_sender"
        log.info.assert_called_once_with("[monitor] Wake-back skipped — no sender")

    def test_skips_self_wake(self, monkeypatch, tmp_path):
        """Sender equal to completed agent returns skipped_self and names the sender."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        result = wake_sender("@trigger", "@trigger", 0)
        assert result == "skipped_self"
        log.info.assert_called_once_with(
            "[monitor] Wake-back skipped — sender %s is the completed agent (self-wake)", "@trigger"
        )

    def test_skips_self_wake_case_insensitive(self, monkeypatch, tmp_path):
        """Self-wake guard is case-insensitive; the log keeps the sender as written."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        result = wake_sender("Trigger", "@TRIGGER", 0)
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
        wake_sender("@prax", "@trigger", 0)
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
        result = wake_sender("@prax", "@target", 0)
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
        result = wake_sender("@prax", "@target", 0)
        assert result == "blocked_depth"
        log.warning.assert_called_once_with(
            "[monitor] Wake-back skipped — depth %d >= max %d", MAX_WAKE_DEPTH, MAX_WAKE_DEPTH
        )

    def test_depth_cap_over_max_blocks(self, monkeypatch, tmp_path):
        """Depth above max also blocks, and the warning carries the depth read."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        monkeypatch.setenv("AIPASS_WAKE_DEPTH", str(MAX_WAKE_DEPTH + 5))
        result = wake_sender("@prax", "@target", 0)
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

        result = wake_sender("@trigger", "@target", 0)
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

        wake_sender("@prax", "@target", 1, run_line="run: claude · m (observed; flag) session s")
        _, kwargs = mock_wake.call_args
        assert "@target" in kwargs["custom_message"]
        assert kwargs["custom_message"].endswith("\nrun: claude · m (observed; flag) session s")
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

        result = wake_sender("@prax", "@target", 0)
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

        result = wake_sender("@trigger", "@target", 0)
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

        result = wake_sender("@prax", "@target", 0)
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

        wake_sender("@trigger", "@target", 0)
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

        result = wake_sender("@prax", "@target", 1)
        assert result == "success"
        mock_wake.assert_called_once()
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@prax", "@target", 1
        )


class TestNoLogFileInTheTargetsLogs:
    """Trigger's watcher reads every .log in a logs/ dir: the monitor leaves none there."""

    def test_a_finished_dispatch_leaves_no_log_file_and_reports_its_wake_result(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, _ = main_argv

        def agent_ran(cmd, stdout_log, *args, **kwargs):
            Path(stdout_log).write_text("{}", encoding="utf-8")
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", agent_ran)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "wake_sender", MagicMock(return_value="success"))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root", MagicMock(return_value=tmp_path / "repo")
        )

        with pytest.raises(SystemExit):
            main()

        logs_dir = Path(lock_file).parent.parent / "logs"
        assert sorted(p.name for p in logs_dir.iterdir()) == ["dispatch_stdout.out"]
        assert _report()["wake_result"] == "success"


class TestWakeBackIntegration:
    """Wake-back wired into main() — fires after lock cleanup on both paths."""

    def test_wake_called_on_success(self, monkeypatch, main_argv, tmp_path):
        """wake_sender called with correct args after successful agent run."""
        argv, lock_file, stderr_log = main_argv

        wake_calls = []

        def track_wake(sender, branch_email, exit_code, target_home, run_line=""):
            wake_calls.append((sender, branch_email, exit_code, target_home))
            return "success"

        bounce = MagicMock()
        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "wake_sender", track_wake)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert len(wake_calls) == 1
        assert wake_calls[0] == ("@sender", "@test_branch", 0, Path(lock_file).parent.parent)
        bounce.assert_not_called()
        assert _report()["wake_result"] == "success"

    def test_wake_called_on_failure(self, monkeypatch, main_argv, tmp_path):
        """wake_sender called after all attempts fail (in addition to bounce)."""
        argv, lock_file, stderr_log = main_argv

        wake_calls = []
        mock_bounce = MagicMock()

        def track_wake(sender, branch_email, exit_code, target_home, run_line=""):
            wake_calls.append((sender, branch_email, exit_code, target_home))
            return "success"

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(side_effect=[(1, False), (1, False), (1, False)]))
        monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "wake_sender", track_wake)
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
        reported = _report()
        assert (reported["wake_result"], reported["exit_code"]) == ("success", wake_calls[0][2])

    def test_the_report_names_target_sender_exit_code_and_wake_result(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, stderr_log = main_argv

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(return_value=(0, False)))
        bounce = MagicMock()
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "wake_sender", MagicMock(return_value="success"))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit):
            main()

        reported = _report()
        assert (reported["target"], reported["sender"], reported["exit_code"], reported["wake_result"]) == (
            "@test_branch",
            "@sender",
            0,
            "success",
        )
        bounce.assert_not_called()


# === Wake-back honesty: manager senders (VERA field report) =================
#
# wake_branch's manager gate delivers the mail and skips the wake by design, but
# returns (status, True) — so wake_sender read success=True and logged
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
        result = wake_sender("@devpulse", "@ai_mail", 0)
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

        wake_sender("@devpulse", "@ai_mail", 0)

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
        result = wake_sender("@devpulse", "@ai_mail", 0)
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
        result = wake_sender("@prax", "@ai_mail", 0)
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

        result = wake_sender("@devpulse", "@ai_mail", 0)

        assert result == "mailed_manager"
        assert sent.called, "manager wake-back sent no mail — the silent drop"
        argv = sent.call_args.args[0]
        assert argv[:3] == ["drone", "@ai_mail", "send"]
        assert argv[3] == "@devpulse"
        assert argv[-2:] == ["--kind", "notice"]
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

        wake_sender("@devpulse", "@ai_mail", 3)

        body = " ".join(sent.call_args.args[0][4:])
        assert "@ai_mail" in body
        assert "3" in body
        log.info.assert_called_once_with(
            "[monitor] Wake-back mailed to manager %s (%s exit %d)", "@devpulse", "@ai_mail", 3
        )

    def test_manager_mail_carries_the_run_line(self, monkeypatch, tmp_path):
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        sent = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(mod.subprocess, "run", sent)

        wake_sender("@devpulse", "@ai_mail", 0, run_line="run: codex · gpt-6.1-sol (observed; flag) session t1")

        assert " ".join(sent.call_args.args[0][4:6]).endswith("run: codex · gpt-6.1-sol (observed; flag) session t1")

    def test_manager_mail_failure_is_not_reported_as_delivered(self, monkeypatch, tmp_path):
        """If the send fails the manager still learns nothing — that must not wear
        the same tag as a delivered mail. Same lesson as the gate's True."""
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        monkeypatch.setattr(
            mod.subprocess, "run", MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr="boom"))
        )

        result = wake_sender("@devpulse", "@ai_mail", 0)
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

        result = wake_sender("@prax", "@ai_mail", 0)
        assert result == "success"
        assert not sent.called
        log.info.assert_called_once_with(
            "[monitor] Wake-back: %s woken after %s completed (exit %d)", "@prax", "@ai_mail", 0
        )


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

        wake_sender and _mail_wake_back are the real ones
        (the autouse fixture mocks the first; restored here). Only the
        edges are faked: wake_branch, so nothing spawns, and subprocess.run, so
        no mail leaves. Whatever the monitor decides, those mocks record it.
        """
        monkeypatch.setenv("AIPASS_WAKE_DEPTH", "0")  # registers an undo: wake_sender bumps it
        wake = MagicMock(return_value=(wake_status, True))
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch", wake)
        sent = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(mod.subprocess, "run", sent)
        monkeypatch.setattr(mod, "wake_sender", wake_sender)
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        bounce = MagicMock(return_value=True)
        monkeypatch.setattr(mod, "_send_bounce", bounce)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(return_value=(exit_code, False)))
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=tmp_path / "repo"),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        return {"exit": exc_info.value.code, "wake": wake, "sent": sent, "log": log, "bounce": bounce}

    def test_declined_completion_neither_wakes_nor_mails_the_sender(self, monkeypatch, main_argv, tmp_path):
        """The fix, red on the old monitor: it ignored the flag and ran the full
        wake-back. The status is the MANAGER gate's on purpose — that is the one
        path where a wake attempt turns into mail, so BOTH halves are observable."""
        argv, lock_file, _ = main_argv

        got = self._run_main(monkeypatch, _declining(argv), self._manager_gate_status(), tmp_path)

        assert got["exit"] == 0, "completion must still run to its end"
        got["wake"].assert_not_called()
        assert _drone_sends(got["sent"]) == [], "a declined wake-back must send no mail"

    def test_without_the_flag_a_manager_sender_is_still_mailed(self, monkeypatch, main_argv, tmp_path):
        """The default is today's contract, byte for byte: wake attempt, gate, mail."""
        argv, lock_file, _ = main_argv

        got = self._run_main(monkeypatch, argv, self._manager_gate_status(), tmp_path)

        got["wake"].assert_called_once()
        assert got["wake"].call_args.args == ("@sender",)
        assert got["wake"].call_args.kwargs["sender"] == ""
        sends = _drone_sends(got["sent"])
        assert len(sends) == 1 and sends[0][3] == "@sender"
        assert _report()["wake_result"] == "mailed_manager"

    def test_the_wake_back_mail_is_sent_as_ai_mail(self, monkeypatch, main_argv, tmp_path):
        """The manager's wake-back mail is ai_mail's notice, under one claim (ai_mail, 2026-10-04).

        A monitor started in-process by another branch inherits that branch's
        name; "trigger" in the env stands in for it.
        """
        argv, _, _ = main_argv
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "trigger")

        got = self._run_main(monkeypatch, argv, self._manager_gate_status(), tmp_path)

        _assert_sent_as_ai_mail(got["sent"])

    def test_a_wake_back_to_a_manager_in_the_targets_other_project_is_sent_from_the_target_home(
        self, monkeypatch, main_argv, tmp_path
    ):
        """Shipped defect: sent from ai_mail's AIPass home, the fence refused 3 @vera wake-backs (e26abd25)."""
        argv, lock_file, _ = main_argv
        _foreign_project(tmp_path, "sender", "branch")

        got = self._run_main(monkeypatch, argv, self._manager_gate_status(), tmp_path)

        _assert_sent_from(got["sent"], Path(lock_file).parent.parent)
        assert _report()["wake_result"] == "mailed_manager"

    def test_without_the_flag_a_builder_sender_is_still_woken(self, monkeypatch, main_argv, tmp_path):
        argv, lock_file, _ = main_argv

        got = self._run_main(monkeypatch, argv, self._builder_status(), tmp_path)

        got["wake"].assert_called_once()
        assert got["wake"].call_args.args == ("@sender",)
        assert _drone_sends(got["sent"]) == []
        assert _report()["wake_result"] == "success"

    def test_a_declined_wake_back_logs_one_info_line_naming_target_and_sender(self, monkeypatch, main_argv, tmp_path):
        argv, _, _ = main_argv

        got = self._run_main(monkeypatch, _declining(argv), self._builder_status(), tmp_path)

        declined = [c for c in got["log"].info.call_args_list if c.args and "declined by caller" in c.args[0]]
        assert len(declined) == 1, f"expected one decline line, got {declined}"
        assert "@test_branch" in declined[0].args[1:]
        assert "@sender" in declined[0].args[1:]

    def test_a_declined_wake_back_is_reported_as_declined(self, monkeypatch, main_argv, tmp_path):
        """A quiet sender reads as a choice, not a lost wake."""
        argv, _, _ = main_argv

        self._run_main(monkeypatch, _declining(argv), self._builder_status(), tmp_path)

        reported = _report()
        assert (reported["wake_result"], reported["target"], reported["sender"]) == (
            "declined",
            "@test_branch",
            "@sender",
        )

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
        assert _report()["wake_result"] == "success"


# === The cloud lane (FPLAN-1249) =============================================
#
# No local agent: the monitor starts a cloud session, records it on the dispatch mail, polls
# `drone @git pr list` for the PR whose body carries the mail id, and writes the wake-back
# itself. pr list (FPLAN-1248) is mocked here, as are script and claude.

MAIL = "abc12345"
URL = "https://claude.ai/code/session_01ABC"


class _Clock:
    """time for the poll: sleep advances it, so a ceiling passes without waiting."""

    def __init__(self):
        self.now = 1000.0
        self.slept = 0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.slept += 1


URL12 = "https://github.com/o/r/pull/12"


def _pr(number, head="claude/fix-abc", sha="a1", base="dev", state="OPEN"):
    row = {"number": number, "head": head, "base": base, "state": state, "ci": "success", "title": f"T{number}"}
    return {**row, "head_sha": sha, "url": f"https://github.com/o/r/pull/{number}"}


def _cloud_run(tmp_path, monkeypatch, polls=(), view=True, delivered=True, ceiling=900):
    """Run the cloud lane with script, pr list and pr view faked; (result, argvs, mails sent, the mail after)."""
    inbox = tmp_path / "inbox.json"
    mail = {"id": MAIL, "subject": "S", "status": "new", "auto_execute": True, "cloud": {"requested": True}}
    inbox.write_text(json.dumps({"messages": [mail]}), encoding="utf-8")
    answers, argvs = list(polls), []

    def fake_cli(cmd, cwd=None, env=None, timeout=60):
        argvs.append(list(cmd))
        if cmd[0] == "script":
            said = f"Created cloud session: fix\nView: {URL}?from=cli&m=0\n" if view else "Error: no environment\n"
            Path(cmd[-1]).write_text(said, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[2:4] == ["pr", "list"]:
            rows = answers.pop(0) if answers else []
            if rows is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="gh: auth token expired")
            # As drone @git pr list answers: --state defaults to open, --base filters the base.
            flags = dict(zip(cmd[4::2], cmd[5::2]))
            rows = [r for r in rows if flags.get("--state") == "all" or r["state"] == "OPEN"]
            rows = [r for r in rows if "--base" not in flags or r["base"] == flags["--base"]]
            return SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr="")
        return SimpleNamespace(returncode=0, stdout=f"#{cmd[4]} T\n\ndispatch: {MAIL}\nDid the thing.", stderr="")

    monkeypatch.setattr(cloud_mod, "run_cli", fake_cli)
    monkeypatch.setattr(cloud_mod, "time", _Clock())
    mails: list = []
    cmd = cloud_mod.start_cmd("script", "claude", "env_1", "brief", str(tmp_path / "start.out"))
    cfg = {"mail": MAIL, "poll": 180, "ceiling": ceiling}
    result = cloud_mod.run(
        cmd,
        tmp_path,
        {},
        cfg,
        "@hooks",
        inbox,
        lambda s, b: mails.append((s, b)) or delivered,
        lambda: argvs.append(["released", json.loads(inbox.read_text(encoding="utf-8"))["messages"][0]["cloud"]]),
    )
    return result, argvs, mails, json.loads(inbox.read_text(encoding="utf-8"))["messages"][0]


def _pr_lists(argvs):
    return [a for a in argvs if a[2:4] == ["pr", "list"]]


class TestCloudLane:
    """cloud.run: the start, the session on the mail, the poll, the wake-back and the ceiling."""

    def test_the_session_id_parses_from_the_view_line_and_is_recorded_on_the_mail(self, monkeypatch, tmp_path):
        assert cloud_mod.parse_view(f"Created cloud session: x\nView: {URL}?from=cli&m=0\n") == (
            "session_01ABC",
            f"{URL}?from=cli&m=0",
        )

        _, _, _, mail = _cloud_run(tmp_path, monkeypatch)

        assert mail["cloud"]["session_id"] == "session_01ABC"
        assert mail["cloud"]["url"] == f"{URL}?from=cli&m=0"
        assert mail["cloud"]["requested"] is True

    def test_the_poll_reads_pr_list_by_the_mail_id_and_mails_one_wake_back_per_pr(self, monkeypatch, tmp_path):
        """A head outside claude/ is not the session's; the PR leaving the list ends the poll."""
        polls = [[], [_pr(12), _pr(99, head="feature/other")], [_pr(12)], []]

        result, argvs, mails, mail = _cloud_run(tmp_path, monkeypatch, polls)

        lists = _pr_lists(argvs)
        assert lists[0] == [
            "drone",
            "@git",
            "pr",
            "list",
            "--head",
            "claude/",
            "--marker",
            MAIL,
            "--state",
            "all",
            "--json",
        ]
        assert len(lists) == 4
        assert [s for s, _ in mails] == ["Cloud dispatch result: @hooks PR #12 (ci success)"]
        body = mails[0][1]
        for part in ("PR #12: T12", "Head: claude/fix-abc -> dev", "CI success", f"Session: {URL}", "Did the thing."):
            assert part in body
        assert mail["cloud"]["done"] is True
        assert mail["cloud"]["results"] == [
            {"number": 12, "head": "claude/fix-abc", "head_sha": "a1", "url": URL12, "state": "OPEN", "ci": "success"}
        ]
        assert mail["cloud"]["ended"] == "closed"
        assert (result["exit_code"], result["status"], result["wake_result"]) == (
            0,
            "completed (cloud PR #12)",
            "mailed",
        )

    def test_the_session_id_parses_from_a_coloured_or_renamed_label(self):
        """Under script's pty the label may carry colour codes or a new name; the URL alone is the session."""
        for said in (f"\x1b[1mView:\x1b[0m \x1b[4m{URL}?from=cli\x1b[0m\n", f"Open: {URL}?from=cli\n"):
            assert cloud_mod.parse_view(said) == ("session_01ABC", f"{URL}?from=cli"), said

    def test_a_pr_merged_before_its_first_sighting_is_mailed_and_ends_the_poll(self, monkeypatch, tmp_path):
        merged = [_pr(12, state="MERGED")]
        result, argvs, mails, mail = _cloud_run(tmp_path, monkeypatch, [merged] * 5)

        assert len(_pr_lists(argvs)) == 1
        assert [s for s, _ in mails] == ["Cloud dispatch result: @hooks PR #12 (ci success)"]
        assert "state MERGED" in mails[0][1]
        assert (mail["cloud"]["ended"], result["status"]) == ("closed", "completed (cloud PR #12)")

    def test_a_second_pr_merged_between_two_reads_is_still_mailed(self, monkeypatch, tmp_path):
        polls = [[_pr(12)], [_pr(12, state="MERGED"), _pr(13, state="MERGED")]]
        result, _, mails, _ = _cloud_run(tmp_path, monkeypatch, polls)

        assert [s.split(" PR ")[1] for s, _ in mails] == ["#12 (ci success)", "#13 (ci success)"]
        assert result["status"] == "completed (cloud PR #12, #13)"

    def test_a_pr_against_the_wrong_base_is_mailed_with_its_base(self, monkeypatch, tmp_path):
        polls = [[_pr(12, base="main")], [_pr(12, base="main", state="CLOSED")]]
        result, _, mails, _ = _cloud_run(tmp_path, monkeypatch, polls)

        assert [s for s, _ in mails] == ["Cloud dispatch result: @hooks PR #12 (ci success)"]
        assert "Head: claude/fix-abc -> main" in mails[0][1]
        assert result["status"] == "completed (cloud PR #12)"

    def test_five_failed_pr_list_reads_in_a_row_end_the_poll_failed_with_the_last_error(self, monkeypatch, tmp_path):
        result, argvs, mails, mail = _cloud_run(
            tmp_path, monkeypatch, [None, [], None, None, None, None, None], ceiling=3600
        )

        assert len(_pr_lists(argvs)) == 7
        assert [s for s, _ in mails] == ["Cloud dispatch failed: @hooks, pr list unreadable"]
        assert "5 drone @git pr list reads in a row failed" in mails[0][1]
        assert "gh: auth token expired" in mails[0][1] and f"Session: {URL}" in mails[0][1]
        assert result["status"].startswith("FAILED (pr list failed 5 times in a row: drone @git pr list")
        assert "gh: auth token expired" in result["status"] and result["wake_result"] == "mailed_failure"
        assert result["exit_code"] == cloud_mod.POLL_FAILED and mail["cloud"]["ended"] == "pr list failed"

    def test_the_timeout_mail_counts_the_failed_pr_list_reads(self, monkeypatch, tmp_path):
        _, _, mails, _ = _cloud_run(tmp_path, monkeypatch, [None, [], None])

        assert "2 of the 5 pr list reads failed" in mails[0][1]

    def test_the_brief_footer_tells_the_session_to_check_its_install(self):
        said = cloud_mod.brief("Do it.", "@hooks", MAIL)

        assert said.startswith("Do it.\n\n---\nYou are @hooks in a Claude Code cloud VM")
        assert (
            "First run `drone @hooks --help`; if AIPass is not installed, open the PR anyway with the setup output "
            "in the body." in said
        )

    def test_a_second_pr_after_a_steer_is_a_new_result(self, monkeypatch, tmp_path):
        _, _, mails, mail = _cloud_run(tmp_path, monkeypatch, [[_pr(12)], [_pr(12), _pr(13)]])

        assert [s.split(" PR ")[1] for s, _ in mails] == ["#12 (ci success)", "#13 (ci success)"]
        assert [r["number"] for r in mail["cloud"]["results"]] == [12, 13]

    def test_a_push_to_the_same_pr_is_a_new_result_and_the_mail_links_the_pr(self, monkeypatch, tmp_path):
        _, _, mails, mail = _cloud_run(tmp_path, monkeypatch, [[_pr(12)], [_pr(12)], [_pr(12, sha="b2")]])

        assert [s for s, _ in mails] == ["Cloud dispatch result: @hooks PR #12 (ci success)"] * 2
        assert "PR: #12 https://github.com/o/r/pull/12" in mails[0][1]
        assert [r["head_sha"] for r in mail["cloud"]["results"]] == ["b2"]

    def test_the_local_lock_is_released_once_the_session_is_on_the_mail_and_before_the_poll(
        self, monkeypatch, tmp_path
    ):
        _, argvs, _, _ = _cloud_run(tmp_path, monkeypatch, [[_pr(12)], []])

        released = [i for i, a in enumerate(argvs) if a[0] == "released"]
        assert len(released) == 1
        assert argvs[released[0]][1]["session_id"] == "session_01ABC"
        assert released[0] < argvs.index(_pr_lists(argvs)[0])

    def test_no_session_releases_nothing_early(self, monkeypatch, tmp_path):
        _, argvs, _, _ = _cloud_run(tmp_path, monkeypatch, view=False)

        assert not [a for a in argvs if a[0] == "released"]

    def test_a_result_mail_that_did_not_go_is_not_reported_as_mailed(self, monkeypatch, tmp_path):
        result, _, mails, _ = _cloud_run(tmp_path, monkeypatch, [[_pr(12)], []], delivered=False)

        assert len(mails) == 1
        assert (result["status"], result["wake_result"]) == ("completed (cloud PR #12)", "failed_result_mail")

    def test_the_ceiling_writes_the_timeout_mail_and_the_mail_stays_open(self, monkeypatch, tmp_path):
        result, argvs, mails, mail = _cloud_run(tmp_path, monkeypatch)

        assert len(_pr_lists(argvs)) == 900 // 180
        assert [s for s, _ in mails] == ["Cloud dispatch timeout: @hooks, no PR after 15 min"]
        assert f"Session: {URL}" in mails[0][1] and "the mail stays open" in mails[0][1]
        assert (mail["status"], mail["cloud"]["ended"]) == ("new", "ceiling")
        assert "done" not in mail["cloud"]
        assert (result["status"], result["wake_result"]) == ("TIMEOUT (cloud, no PR in 900s)", "mailed_timeout")

    def test_a_start_with_no_view_line_is_refused_with_its_reason_and_never_polls(self, monkeypatch, tmp_path):
        result, argvs, mails, mail = _cloud_run(tmp_path, monkeypatch, view=False)

        assert result["exit_code"] == cloud_mod.START_FAILED
        assert result["status"] == "REFUSED (no session id in the cloud start output)"
        assert [s for s, _ in mails] == ["Cloud dispatch refused: @hooks"]
        said = "no session id found in the start output; a session may still exist, check claude.ai/code"
        assert said in mails[0][1] and "Error: no environment" in mails[0][1]
        assert _pr_lists(argvs) == [] and "session_id" not in mail["cloud"]

    def test_the_monitor_runs_the_cloud_lane_in_place_of_an_agent_and_reports_its_wake_back(
        self, monkeypatch, main_argv, tmp_path
    ):
        """No local attempt, no bounce, no wake_sender: the lane's own mail is the wake-back."""
        argv, _, _ = main_argv
        sep = argv.index("--")
        cfg = json.dumps({"mail": MAIL, "poll": 180, "ceiling": 900})
        argv = [*argv[:sep], "--provider=cloud", f"--cloud={cfg}", "--", "script", "-qfec", "claude --cloud x", "log"]
        lane = MagicMock(
            return_value={
                "exit_code": 0,
                "status": "completed (cloud PR #12)",
                "wake_result": "mailed",
                "run_line": f"run: cloud · session {URL}",
            }
        )
        monkeypatch.setattr(cloud_mod, "run", lane)
        agent, bounce = MagicMock(), MagicMock()
        monkeypatch.setattr(mod, "run_with_startup_check", agent)
        monkeypatch.setattr(mod, "_send_bounce", bounce)
        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.paths.find_repo_root", MagicMock(return_value=tmp_path))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert lane.call_args.args[0] == ["script", "-qfec", "claude --cloud x", "log"]
        assert lane.call_args.args[3] == {"mail": MAIL, "poll": 180, "ceiling": 900}
        agent.assert_not_called()
        bounce.assert_not_called()
        mod.wake_sender.assert_not_called()
        assert (_report()["wake_result"], _report()["status"]) == ("mailed", "completed (cloud PR #12)")
