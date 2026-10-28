# =================== AIPass ====================
# Name: test_wake.py
# Description: Tests for wake dispatch handler
# Version: 1.6.0
# Created: 2026-03-29
# Modified: 2026-10-28
# =============================================

"""Tests for apps/handlers/dispatch/wake.py's wake_branch: the spawn, session pointer, model, provider and marking."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — DEFAULT_PROMPT's exact literal text
# seedgo: no-test-needed(shared) — DispatchStatus, pid_lock and resolve_branch(): tests/test_wake_helpers.py
# seedgo: no-test-needed(shared) — the manager lanes and the dashboard refresh: tests/test_wake_managers.py

import json
import sqlite3
import subprocess
import pytest
from pathlib import Path as _Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod
from aipass.ai_mail.apps.handlers.dispatch import register as register_mod
from aipass.ai_mail.apps.handlers.dispatch.wake import (
    KNOWN_MODEL_ALIASES,
    DEFAULT_MODEL,
    wake_branch,
)
from aipass.ai_mail.tests.support_wake import (
    _FakeProc,
    _claude_args,
    _make_scheduled_fixtures,
    _make_wake_fixtures,
    _patch_wake_deps,
    _record_spawn_routes,
)

pytestmark = pytest.mark.usefixtures("wake_log_operation_suppressed")


class TestWakeBranchSpawnEnv:
    """Ensure wake_branch() spawn_env includes ~/.local/bin for restricted-PATH envs."""

    def test_spawn_env_includes_local_bin(self, tmp_path, monkeypatch):
        """spawn_env PATH includes ~/.local/bin even when not in os.environ PATH."""
        branch_path = tmp_path / "src" / "aipass" / "testbranch"
        branch_path.mkdir(parents=True)
        (branch_path / ".ai_mail.local").mkdir()
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        import json

        registry_file.write_text(
            json.dumps({"branches": [{"name": "TESTBRANCH", "email": "@testbranch", "path": str(branch_path)}]}),
            encoding="utf-8",
        )

        monkeypatch.setattr(wake_mod, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", registry_file)
        monkeypatch.setattr(wake_mod, "PAUSE_FILE", tmp_path / ".aipass" / "autonomous_pause")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", tmp_path / "safety_config.json")
        monkeypatch.setattr(wake_mod, "MONITOR_SCRIPT", tmp_path / "dispatch_monitor.py")
        (tmp_path / "dispatch_monitor.py").touch()

        from pathlib import Path as _Path

        local_bin = str(_Path.home() / ".local" / "bin")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.delenv("INVOCATION_ID", raising=False)

        captured_envs: list = []

        def fake_popen(cmd, **kwargs):
            """Capture spawn_env without launching a real process."""
            captured_envs.append(kwargs.get("env", {}))

            class FakeProc:
                pid = 99999

            return FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        # The liveness probe and occupancy scan stay walls in front of host pids and live sessions.
        pid_alive = MagicMock(return_value=True)
        monkeypatch.setattr(wake_mod, "check_pid_alive", pid_alive)
        monkeypatch.setattr(wake_mod, "clean_zombies", lambda: 0)
        occupied = MagicMock(return_value=None)
        monkeypatch.setattr(wake_mod, "branch_occupant", occupied)
        monkeypatch.setattr(wake_mod, "acquire_lock", lambda p, pid: (True, "ok"))
        sleep = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.dispatch.wake.time.sleep", sleep)
        # send_notification appends to the live feed, so it stays patched.
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)

        # The test owns the binary: a CI runner has no claude anywhere.
        claude_bin = tmp_path / "bin" / "claude"
        claude_bin.parent.mkdir()
        claude_bin.touch()
        which = MagicMock(side_effect=lambda name: str(claude_bin) if name == "claude" else None)
        monkeypatch.setattr(wake_mod.shutil, "which", which)

        wake_mod.wake_branch("@testbranch", fresh=True)

        which.assert_any_call("claude")

        sleep.assert_called_once_with(2)
        notify.assert_called_once_with(
            "@testbranch waking", "Manual wake: check inbox", source="testbranch", kind="wake"
        )
        assert len(captured_envs) == 1, "Popen must be called exactly once"
        pid_alive.assert_called_once_with(99999)
        occupied.assert_called_once_with(branch_path)
        env = captured_envs[0]
        assert local_bin in env.get("PATH", ""), f"~/.local/bin not in spawn_env PATH: {env.get('PATH', '')}"


class TestWakeBranch:
    """Tests for wake_branch() — all remaining code paths."""

    def test_auto_pause_file_blocks(self, tmp_path, monkeypatch):
        """auto=True with PAUSE_FILE existing returns failure."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        pause = tmp_path / ".aipass" / "autonomous_pause"
        pause.parent.mkdir(parents=True, exist_ok=True)
        pause.touch()
        status, ok = wake_branch("@testbranch", auto=True)
        assert ok is False
        assert any(s[0] == "fail" and "pause" in s[1] for s in status.steps)

    def test_resolve_fails(self, tmp_path, monkeypatch):
        """Branch not found returns failure."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        status, ok = wake_branch("@nonexistent")
        assert ok is False
        assert any(s[0] == "fail" and "resolve" in s[1] for s in status.steps)

    def test_an_unreadable_registry_refuses_rather_than_waking_an_external_namesake(self, tmp_path, monkeypatch):
        """A scheduled wake never lands on another root's citizen because the AIPass registry cannot be read."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")
        namesake = tmp_path / "Elsewhere" / "testbranch"
        namesake.mkdir(parents=True)
        external = [{"email": "@testbranch", "path": str(namesake)}]
        monkeypatch.setattr(wake_mod, "_external_citizens", lambda root: external)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", scheduled=True, sender="@daemon")

        assert ok is False
        resolve = status.find_step("resolve")
        assert resolve is not None
        assert resolve[0] == "fail"
        assert resolve[2].startswith("@testbranch not resolved: AIPASS_REGISTRY.json could not be read")
        assert calls["popen"] == [] and calls["tmux"] == []

    @pytest.mark.parametrize("where", ["caller_project", "hosted_project"])
    def test_an_unreadable_project_registry_refuses_rather_than_waking_a_namesake(self, tmp_path, monkeypatch, where):
        """A project registry that cannot be read stops resolution before the external tier."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        lab = tmp_path / "projects" / "lab"
        (lab / "vera").mkdir(parents=True)
        (lab / "LAB_REGISTRY.json").write_text("{not json", encoding="utf-8")
        namesake = tmp_path / "Elsewhere" / "vera"
        namesake.mkdir(parents=True)
        external = [{"email": "@vera", "path": str(namesake)}]
        monkeypatch.setattr(wake_mod, "_external_citizens", lambda root: external)
        if where == "caller_project":
            monkeypatch.setenv("AIPASS_CALLER_CWD", str(lab / "vera"))
        else:
            monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@vera", admin=where == "hosted_project")

        assert ok is False
        resolve = status.find_step("resolve")
        assert resolve is not None
        assert resolve[0] == "fail"
        assert resolve[2].startswith("@vera not resolved: LAB_REGISTRY.json could not be read")
        assert calls["popen"] == [] and calls["tmux"] == []

    def test_manager_target_skips_wake(self, tmp_path, monkeypatch):
        """Target with citizen_class=manager returns True (mail only, no wake)."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        trinity = branch_path / ".trinity"
        trinity.mkdir(parents=True, exist_ok=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "manager"}}),
            encoding="utf-8",
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert any(s[1] == "manager" for s in status.steps)

    def test_unreadable_passport_fails_closed_as_a_manager(self, tmp_path, monkeypatch):
        """A passport that exists but cannot be read never lets the target be woken (treated as a manager)."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        trinity = branch_path / ".trinity"
        trinity.mkdir(parents=True, exist_ok=True)
        (trinity / "passport.json").write_text("{not json", encoding="utf-8")
        _patch_wake_deps(monkeypatch, clean_zombies=lambda: 0)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch")

        assert ok is True
        manager = status.find_step("manager")
        assert manager is not None
        assert manager[0] == "info"
        assert calls["popen"] == [] and calls["tmux"] == []

    def test_manager_daemon_scheduled_wake_spawns_interactive(self, tmp_path, monkeypatch):
        """Manager + sender=@daemon bypasses the gate and spawns an interactive tmux session, never headless."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        trinity = branch_path / ".trinity"
        trinity.mkdir(parents=True, exist_ok=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "manager"}}),
            encoding="utf-8",
        )
        _patch_wake_deps(monkeypatch, clean_zombies=lambda: 0)
        tmux_calls = []

        def _fake_run(cmd, **kwargs):
            tmux_calls.append(list(cmd))

            class _Done:
                returncode = 0
                stderr = ""

            return _Done()

        monkeypatch.setattr(wake_mod.shutil, "which", lambda name: "/usr/bin/tmux")
        monkeypatch.setattr(wake_mod.subprocess, "run", _fake_run)
        status, ok = wake_branch("@testbranch", custom_message="continue the work", sender="@daemon")
        assert ok is True
        assert any(s[0] == "ok" and s[1] == "manager" for s in status.steps)
        assert any(s[0] == "ok" and s[1] == "spawn" and "tmux" in s[2] for s in status.steps)
        assert [c[:2] for c in tmux_calls] == [
            ["tmux", "new-session"],
            ["tmux", "set-option"],
            ["tmux", "send-keys"],
        ]
        prompt_file = branch_path / ".daemon" / "last_wake_prompt.txt"
        assert prompt_file.read_text(encoding="utf-8") == "continue the work"

    def test_manager_daemon_wake_fails_without_tmux(self, tmp_path, monkeypatch):
        """Manager + sender=@daemon with no tmux binary fails loud (no silent headless fallback)."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        trinity = branch_path / ".trinity"
        trinity.mkdir(parents=True, exist_ok=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "manager"}}),
            encoding="utf-8",
        )
        _patch_wake_deps(monkeypatch, clean_zombies=lambda: 0)
        which = MagicMock(return_value=None)
        monkeypatch.setattr(wake_mod.shutil, "which", which)
        status, ok = wake_branch("@testbranch", sender="@daemon")
        assert ok is False
        assert any(s[0] == "fail" and s[1] == "tmux" for s in status.steps)
        which.assert_any_call("tmux")

    def test_non_manager_target_continues(self, tmp_path, monkeypatch):
        """Target with non-manager citizen_class proceeds to spawn."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        trinity = branch_path / ".trinity"
        trinity.mkdir(parents=True, exist_ok=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "aipass_framework"}}),
            encoding="utf-8",
        )
        _patch_wake_deps(monkeypatch, clean_zombies=lambda: 0)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert not any(s[1] == "manager" for s in status.steps)
        notify.assert_called_once_with(
            "@testbranch waking", "Manual wake: check inbox", source="testbranch", kind="wake"
        )

    def test_missing_passport_continues(self, tmp_path, monkeypatch):
        """No passport.json — wake proceeds normally."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, clean_zombies=lambda: 0)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert not any(s[1] == "manager" for s in status.steps)
        notify.assert_called_once_with(
            "@testbranch waking", "Manual wake: check inbox", source="testbranch", kind="wake"
        )

    def test_zombie_check_warns_but_continues(self, tmp_path, monkeypatch):
        """Zombie detected adds warning but dispatch continues."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, clean_zombies=lambda: 2)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert any(s[0] == "warn" and "zombie" in s[2].lower() for s in status.steps)
        notify.assert_called_once_with(
            "@testbranch waking", "Manual wake: check inbox", source="testbranch", kind="wake"
        )

    def test_lock_exists_auto_true_fails(self, tmp_path, monkeypatch):
        """Lock active + auto=True returns failure."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(
            monkeypatch,
            check_lock=lambda p: {"pid": 111, "timestamp": "2026-01-01T00:00:00"},
            clean_zombies=lambda: 0,
        )
        status, ok = wake_branch("@testbranch", auto=True)
        assert ok is False
        assert any(s[0] == "fail" and "lock" in s[1] for s in status.steps)

    def test_a_held_lock_warns_not_woken_logs_it_and_promises_nothing(self, tmp_path, monkeypatch):
        """15:17:08 @seedgo: a live lock printed an info row, logged nothing, and the mail was never read."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(
            monkeypatch,
            check_lock=lambda p: {"pid": 111, "timestamp": "2026-01-01T00:00:00"},
            clean_zombies=lambda: 0,
        )
        log = MagicMock()
        monkeypatch.setattr(wake_mod, "logger", log)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", auto=False)

        assert ok is True, "the mail is delivered; the bool still means 'did what it should'"
        assert calls["popen"] == []
        assert status.busy_detail() == (
            "@testbranch busy (PID 111, since 2026-01-01T00:00:00) — NOT woken; the mail waits in its inbox"
        )
        assert status.find_step("delivery") is None, "no promise that the running session reads it"
        assert any("NOT WOKEN" in c.args[0] for c in log.warning.call_args_list)

    def test_a_free_lock_leaves_no_busy_detail(self, tmp_path, monkeypatch):
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch")

        assert ok is True and status.busy_detail() == ""

    def test_branch_occupied_blocks(self, tmp_path, monkeypatch):
        """Interactive session running -> blocked."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        occupied = MagicMock(return_value="claude")
        _patch_wake_deps(monkeypatch, branch_occupant=occupied)
        status, ok = wake_branch("@testbranch")
        occupied.assert_called_once_with(branch_path)
        assert ok is False
        assert any(s[0] == "fail" and "blocked" in s[1] for s in status.steps)

    def test_the_occupancy_row_names_the_cli_it_found(self, tmp_path, monkeypatch):
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, branch_occupant=lambda p: "codex")

        status, ok = wake_branch("@testbranch")

        assert ok is False
        step = status.find_step("occupancy")
        assert step[0] == "warn" and step[2].startswith("Interactive codex session in ")

    def test_fresh_true_no_continue_flag(self, tmp_path, monkeypatch):
        """fresh=True -> claude_cmd does NOT include '-c' flag."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)
        status, ok = wake_branch("@testbranch", fresh=True)
        assert ok is True
        assert captured_cmds
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        assert "-c" not in claude_part
        notify.assert_called_once_with(
            "@testbranch waking", "Manual wake: check inbox", source="testbranch", kind="wake"
        )

    def test_fresh_false_has_continue_flag(self, tmp_path, monkeypatch):
        """fresh=False -> claude_cmd includes '-c' flag."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)
        status, ok = wake_branch("@testbranch", fresh=False)
        assert ok is True
        assert captured_cmds
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        assert "-c" in claude_part
        notify.assert_called_once_with(
            "@testbranch waking", "Manual wake: check inbox", source="testbranch", kind="wake"
        )

    def test_custom_message_sets_prompt(self, tmp_path, monkeypatch):
        """custom_message uses 'Hi. <message>' instead of DEFAULT_PROMPT."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)
        status, ok = wake_branch("@testbranch", custom_message="Run the audit")
        assert ok is True
        assert captured_cmds
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        p_idx = claude_part.index("-p")
        prompt = claude_part[p_idx + 1]
        assert prompt.startswith("Hi. Run the audit")
        notify.assert_called_once_with("@testbranch waking", "Run the audit", source="testbranch", kind="wake")

    def test_prompt_does_not_ask_agent_to_delete_lock(self, tmp_path, monkeypatch):
        """Monitor owns lock cleanup — the prompt must not also tell the agent to delete it.

        A dual-delete race let a second monitor spawn onto a lock removed mid-run.
        """
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)
        status, ok = wake_branch("@testbranch")
        assert ok is True
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        p_idx = claude_part.index("-p")
        prompt = claude_part[p_idx + 1]
        assert "delete" not in prompt.lower()
        assert ".dispatch.lock" not in prompt
        notify.assert_called_once_with(
            "@testbranch waking", "Manual wake: check inbox", source="testbranch", kind="wake"
        )

    def test_prompt_instructs_synchronous_subagents(self, tmp_path, monkeypatch):
        """Prompt tells the agent to run sub-agents in the foreground (headless mode kills orphaned background tasks)."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)
        status, ok = wake_branch("@testbranch")
        assert ok is True
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        p_idx = claude_part.index("-p")
        prompt = claude_part[p_idx + 1]
        assert "synchronously" in prompt.lower()
        notify.assert_called_once_with(
            "@testbranch waking", "Manual wake: check inbox", source="testbranch", kind="wake"
        )

    def test_prompt_puts_the_spec_before_the_build(self, tmp_path, monkeypatch):
        """Prompt sends the builder to the standards and the test template first, the checklist last."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        notified: list = []
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: notified.append(kw.get("kind")),
            raising=False,
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert notified == ["wake"]  # the real feed was never written
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        p_idx = claude_part.index("-p")
        prompt = claude_part[p_idx + 1]
        spec_at = prompt.find("Before you build:")
        assert spec_at != -1
        assert "src/aipass/seedgo/docs/aipass_standards.md" in prompt
        assert "src/aipass/seedgo/templates/test_template_v1.md" in prompt
        assert spec_at < prompt.find("IMPORTANT: run any sub-agents")
        assert prompt.find("checklist last") > spec_at

    def test_spawn_file_not_found(self, tmp_path, monkeypatch):
        """FileNotFoundError during Popen -> fail step."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        def _fail_popen(*a, **kw):
            raise FileNotFoundError("python not found")

        monkeypatch.setattr("subprocess.Popen", _fail_popen)
        status, ok = wake_branch("@testbranch")
        assert ok is False
        assert any(s[0] == "fail" and "spawn" in s[1] for s in status.steps)

    def test_spawn_generic_exception(self, tmp_path, monkeypatch):
        """Generic exception during Popen -> fail step with class name."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        def _fail_popen(*a, **kw):
            raise RuntimeError("something broke")

        monkeypatch.setattr("subprocess.Popen", _fail_popen)
        status, ok = wake_branch("@testbranch")
        assert ok is False
        assert any(s[0] == "fail" and "RuntimeError" in s[2] for s in status.steps)

    def test_lock_acquisition_fails_before_spawn(self, tmp_path, monkeypatch):
        """Lock fails before spawn -> fail step, returns False (lock-before-spawn)."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, acquire_lock=lambda p, pid: (False, "Lock file already exists"))
        status, ok = wake_branch("@testbranch")
        assert ok is False
        assert any(s[0] == "fail" and "lock-acquire" in s[1] for s in status.steps)

    def test_alive_check_fails_cleans_up_lock(self, tmp_path, monkeypatch):
        """Agent dies immediately -> cleans up lock, returns False."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        pid_alive = MagicMock(return_value=False)
        _patch_wake_deps(monkeypatch, check_pid_alive=pid_alive)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        lock_dir = branch_path / ".ai_mail.local"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / ".dispatch.lock"
        lock_file.write_text("{}", encoding="utf-8")
        status, ok = wake_branch("@testbranch")
        pid_alive.assert_called_once_with(_FakeProc().pid)
        assert ok is False
        assert any(s[0] == "fail" and "alive" in s[1] for s in status.steps)
        assert not lock_file.exists()

    def test_successful_full_path(self, tmp_path, monkeypatch):
        """All steps OK -> returns (status, True) with all expected steps."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        notify = MagicMock()
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.notify.send_notification", notify)
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert status.success is True
        labels = [s[1] for s in status.steps]
        assert "resolve" in labels
        assert "pre-flight" in labels
        assert "lock" in labels
        assert "occupancy" in labels
        assert "spawn" in labels
        assert "lock-acquire" in labels
        assert "alive" in labels
        notify.assert_called_once_with(
            "@testbranch waking", "Manual wake: check inbox", source="testbranch", kind="wake"
        )

    def test_notification_failure_does_not_break_success(self, tmp_path, monkeypatch):
        """Exception in send_notification is caught — overall success unchanged."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())

        def _fail_notify(*a, **kw):
            raise RuntimeError("dbus not found")

        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            _fail_notify,
            raising=False,
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True


class TestWakeSessionPointer:
    """Which session a dispatch lands in comes from a written pointer, not a mtime.

    `-c` follows the newest transcript, so any other session there re-points the next wake.
    """

    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        """Point Path.home at tmp_path so transcript paths land under the sandbox."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(_Path, "home", classmethod(lambda cls: home))
        return home

    def _plant_pointer(self, branch_path, fake_home, session_id):
        """Write a valid pointer AND the transcript it names (resume refuses an id with no transcript)."""
        wake_mod.session_pointer.write_pointer(branch_path, session_id, "test")
        transcript = wake_mod.session_pointer.transcript_file(branch_path, session_id)
        assert transcript is not None, "fake_home did not take — no home, no transcript path"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("{}\n", encoding="utf-8")
        return transcript

    def test_fresh_mints_an_id_and_records_it_before_spawning(self, tmp_path, monkeypatch, fake_home):
        """fresh=True passes --session-id, and the pointer names that same id."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", fresh=True)

        assert ok is True
        args = _claude_args(calls["popen"][0]["cmd"])
        assert "--session-id" in args
        spawned_id = args[args.index("--session-id") + 1]
        pointer = wake_mod.session_pointer.read_pointer(branch_path)
        assert pointer is not None
        assert pointer["session_id"] == spawned_id
        assert pointer["set_by"] == "wake-fresh"
        session_step = status.find_step("session")
        assert session_step is not None and session_step[0] == "ok"
        assert spawned_id[:8] in session_step[2]

    def test_non_fresh_with_a_valid_pointer_resumes_and_drops_c(self, tmp_path, monkeypatch, fake_home):
        """The pointed session is named explicitly — no mtime guess left in the command."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        self._plant_pointer(branch_path, fake_home, "11111111-2222-3333-4444-555555555555")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch")

        assert ok is True
        args = _claude_args(calls["popen"][0]["cmd"])
        assert "--resume" in args
        assert args[args.index("--resume") + 1] == "11111111-2222-3333-4444-555555555555"
        assert "-c" not in args
        session_step = status.find_step("session")
        assert session_step is not None and session_step[0] == "ok"
        assert "11111111" in session_step[2]

    def test_non_fresh_without_a_pointer_keeps_the_c_fallback(self, tmp_path, monkeypatch, fake_home):
        """No pointer = today's behaviour exactly. A wake is never worth failing over."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch")

        assert ok is True
        args = _claude_args(calls["popen"][0]["cmd"])
        assert "-c" in args
        assert "--resume" not in args
        assert "--session-id" not in args
        session_step = status.find_step("session")
        assert session_step is not None and session_step[0] == "info"

    def test_a_stale_pointer_falls_back_instead_of_resuming_a_dead_session(self, tmp_path, monkeypatch, fake_home):
        """Pointer with no transcript behind it: --resume would fail the dispatch."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        wake_mod.session_pointer.write_pointer(branch_path, "dead-session-id", "test")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        _, ok = wake_branch("@testbranch")

        assert ok is True
        args = _claude_args(calls["popen"][0]["cmd"])
        assert "-c" in args
        assert "dead-session-id" not in args

    def test_a_failing_pointer_write_still_spawns(self, tmp_path, monkeypatch, fake_home):
        """A read-only .ai_mail.local must cost precision, never the wake itself."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)
        write_pointer = MagicMock(return_value=False)
        monkeypatch.setattr(wake_mod.session_pointer, "write_pointer", write_pointer)

        status, ok = wake_branch("@testbranch", fresh=True)

        assert ok is True
        assert len(calls["popen"]) == 1
        args = _claude_args(calls["popen"][0]["cmd"])
        assert "--session-id" in args
        session_id = args[args.index("--session-id") + 1]
        write_pointer.assert_called_once_with(branch_path, session_id, "wake-fresh")
        assert status.find_step("session") is not None

    def test_the_rest_of_the_command_is_untouched(self, tmp_path, monkeypatch, fake_home):
        """Model, turn cap, permission mode and output format survive every route."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        wake_branch("@testbranch")  # -c fallback
        wake_branch("@testbranch", fresh=True)  # mint
        self._plant_pointer(branch_path, fake_home, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        wake_branch("@testbranch")  # resume

        assert len(calls["popen"]) == 3
        for spawn in calls["popen"]:
            args = _claude_args(spawn["cmd"])
            assert "-p" in args
            assert args[args.index("--model") + 1] == wake_mod.DEFAULT_MODEL
            assert args[args.index("--permission-mode") + 1] == "bypassPermissions"
            assert args[args.index("--output-format") + 1] == "json"
            assert "--max-turns" in args


# Fable is granted by NAME (fable_allowed), never by citizen_class.


@pytest.fixture
def granted(monkeypatch, tmp_path):
    """Point the grant at a written config, and hand back a writer for it (the real CONFIG_FILE is host state)."""

    def _write(entries):
        config = tmp_path / "safety_config.json"
        config.write_text(json.dumps({"fable_allowed": entries}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", config)
        return config

    return _write


class TestWakeModelPolicy:
    """resolve_wake_model() — Fable is granted by name, to @devpulse alone.

    Grant and refusal are pinned separately: they fail in opposite directions.
    """

    def test_a_granted_seat_may_ask_for_fable(self, granted):
        granted(["@devpulse"])

        assert wake_mod.resolve_wake_model("@devpulse", "fable").model == "fable"

    def test_a_seat_without_the_grant_is_refused_and_told_why(self, granted):
        """The refusal is RETURNED, not only logged: a log line is not read by whoever typed the command."""
        granted(["@devpulse"])

        decision = wake_mod.resolve_wake_model("@vera", "fable")

        assert decision.model == DEFAULT_MODEL
        assert "@vera" in decision.refusal, decision.refusal
        assert "fable" in decision.refusal.lower(), decision.refusal
        assert "2026-09-08" in decision.refusal, decision.refusal

    def test_manager_class_no_longer_buys_fable(self, granted):
        """A manager-class seat without the grant gets the default model.

        A refused "fable" request still wakes: the model is refused, not the wake."""
        granted(["@devpulse"])

        assert wake_mod.resolve_wake_model("@vera", None).model == DEFAULT_MODEL
        assert wake_mod.resolve_wake_model("@vera", "fable").model == DEFAULT_MODEL

    def test_nothing_requested_is_the_default_even_for_a_granted_seat(self, granted):
        """The grant is permission to ASK for Fable, not a standing assignment to it."""
        granted(["@devpulse"])

        assert wake_mod.resolve_wake_model("@devpulse", None).model == DEFAULT_MODEL

    def test_a_lighter_request_is_honoured_unchanged(self, granted):
        """The grant names who may run Fable; it never overrides a lighter request."""
        granted(["@devpulse"])

        assert wake_mod.resolve_wake_model("@devpulse", "sonnet").model == "sonnet"
        assert wake_mod.resolve_wake_model("@ai_mail", "haiku").model == "haiku"

    def test_the_full_fable_id_is_caught_too(self, granted):
        """`--model` takes both `fable` and `claude-fable-5`; the bare-alias compare would miss the full id."""
        granted(["@devpulse"])

        assert wake_mod.resolve_wake_model("@vera", "claude-fable-5").model == DEFAULT_MODEL

    def test_fable_is_refused_whatever_the_casing(self, granted):
        granted(["@devpulse"])

        assert wake_mod.resolve_wake_model("@vera", "FABLE").model == DEFAULT_MODEL

    def test_the_address_spelling_cannot_escape_the_grant(self, granted):
        """Dropping the @ or changing case must not promote OR demote a seat."""
        granted(["devpulse"])

        assert wake_mod.resolve_wake_model("@DevPulse", "fable").model == "fable"
        assert wake_mod.resolve_wake_model("devpulse", "fable").model == "fable"
        assert wake_mod.resolve_wake_model("@vera", "fable").model == DEFAULT_MODEL

    def test_fable_is_a_known_alias(self):
        """The lane names a model the CLI actually resolves."""
        assert "fable" in KNOWN_MODEL_ALIASES


def _tmux_line(calls, verb):
    """The single tmux invocation whose second word is `verb`, as one string."""
    matches = [c for c in calls["tmux"] if len(c) > 1 and c[1] == verb]
    assert len(matches) == 1, f"expected exactly one 'tmux {verb}', got {matches}"
    return " ".join(matches[0])


class TestUnattendedWakesBypassPermissions:
    """Every unattended lane carries bypassPermissions: nobody is present to approve a prompt."""

    def test_interactive_manager_lane_carries_the_bypass_flag(self, tmp_path, monkeypatch):
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon")

        assert ok is True
        assert "--permission-mode bypassPermissions" in _tmux_line(calls, "send-keys")

    def test_interactive_manager_lane_names_its_model_never_a_bare_claude(self, tmp_path, monkeypatch):
        """The lane states the model it means: no bare `claude` on this lane, ever."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon")

        assert ok is True
        assert f"--model {DEFAULT_MODEL}" in _tmux_line(calls, "send-keys")

    def test_headless_lane_still_bypasses(self, tmp_path, monkeypatch):
        """Regression guard: the lane that already complied must keep complying."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon", scheduled=True)

        assert ok is True
        cmd = calls["popen"][0]["cmd"]
        assert "--permission-mode" in cmd
        assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"


class TestDaemonSessionMarking:
    """A daemon-started session must be recognizably daemon work, or a human kills it as a leftover.

    Only the session name is guaranteed; the set-option marker may fail.
    """

    def test_session_name_is_unmistakably_a_daemon_wake(self, tmp_path, monkeypatch):
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon")

        assert ok is True
        new_session = [c for c in calls["tmux"] if c[1] == "new-session"][0]
        session = new_session[new_session.index("-s") + 1]
        assert session.startswith(wake_mod.DAEMON_SESSION_PREFIX)

    def test_the_session_name_that_got_killed_cannot_come_back(self, tmp_path, monkeypatch):
        """The `daemon-<branch>-...` shape read as a human's leftover tmux; the name must say a machine started it.

        The pin above reads DAEMON_SESSION_PREFIX, so it passes for any value; this one names the failed string.
        """
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon")

        assert ok is True
        new_session = [c for c in calls["tmux"] if c[1] == "new-session"][0]
        session = new_session[new_session.index("-s") + 1]
        assert not session.startswith("daemon-"), "this is the name a human already killed"
        assert "AIPASS" in session, "the name must say a machine started this, not a person"

    def test_marking_lands_before_the_agent_starts(self, tmp_path, monkeypatch):
        """A window is killable from the moment it exists, so marking precedes send-keys."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon")

        assert ok is True
        verbs = [c[1] for c in calls["tmux"]]
        assert verbs == ["new-session", "set-option", "send-keys"]

    def test_the_marker_is_queryable_and_names_the_branch(self, tmp_path, monkeypatch):
        """A user option any tool can read back, rather than string-matching a session-name prefix."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon")

        assert ok is True
        option = [c for c in calls["tmux"] if c[1] == "set-option"][0]
        assert "@aipass_daemon_wake" in option
        payload = json.loads(option[-1])
        assert payload["branch"] == "@testbranch"
        assert payload["sender"] == "@daemon"

    def test_a_marking_failure_warns_and_still_wakes(self, tmp_path, monkeypatch):
        """A failed label warns but never cancels the wake: the session is already alive."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        real_run = wake_mod.subprocess.run

        def _run(cmd, **kwargs):
            if len(cmd) > 1 and cmd[1] == "set-option":
                raise subprocess.CalledProcessError(1, cmd, stderr="no server running")
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(wake_mod.subprocess, "run", _run)

        status, ok = wake_branch("@testbranch", sender="@daemon")

        assert ok is True, "a failed label must not cancel the wake"
        assert "send-keys" in [c[1] for c in calls["tmux"]]
        mark = status.find_step("mark")
        assert mark is not None and mark[0] == "warn"

    def test_the_interactive_lane_is_not_written_to_the_dispatch_register(self, tmp_path, monkeypatch):
        """Deliberate: this lane has no monitor and no timeout, so a register row could never close.

        open_dispatch() needs expected_seconds; an invented one would only produce false overdue alarms."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        _record_spawn_routes(monkeypatch)

        opened = []
        monkeypatch.setattr(register_mod, "open_dispatch", lambda **kw: opened.append(kw) or "id", raising=True)

        status, ok = wake_branch("@testbranch", sender="@daemon")

        assert ok is True
        assert opened == [], "the interactive lane must not mint a dispatch nothing can close"


class TestModelPolicyReachesBothSpawnLanes:
    """The policy is decided once, above the fork; BOTH lanes must read that one decision."""

    def test_a_granted_seat_reaches_fable_down_the_tmux_lane(self, tmp_path, monkeypatch, granted):
        granted(["@testbranch"])
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon", model="fable")

        assert ok is True
        assert "--model fable" in _tmux_line(calls, "send-keys")

    def test_a_granted_seat_reaches_fable_down_the_headless_lane_too(self, tmp_path, monkeypatch, granted):
        """The scheduled lane never touches tmux, and the grant does not stop at the tmux door."""
        granted(["@testbranch"])
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon", scheduled=True, model="fable")

        assert ok is True
        cmd = calls["popen"][0]["cmd"]
        assert cmd[cmd.index("--model") + 1] == "fable"

    def test_an_ungranted_manager_spawns_on_the_default_down_the_tmux_lane(self, tmp_path, monkeypatch, granted):
        """Manager-class, scheduled through @daemon, asking for Fable, without the grant: default model."""
        granted(["@devpulse"])
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon", model="fable")

        assert ok is True
        assert f"--model {DEFAULT_MODEL}" in _tmux_line(calls, "send-keys")
        assert "fable" not in _tmux_line(calls, "send-keys")

    def test_an_ungranted_seat_asking_for_fable_spawns_on_the_default(self, tmp_path, monkeypatch, granted):
        granted(["@devpulse"])
        _make_scheduled_fixtures(tmp_path, monkeypatch, citizen_class="specialist")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", model="claude-fable-5")

        assert ok is True
        cmd = calls["popen"][0]["cmd"]
        assert cmd[cmd.index("--model") + 1] == DEFAULT_MODEL

    def test_the_model_decision_is_a_named_step(self, tmp_path, monkeypatch, granted):
        """Which model ran, readable from the status; the class is deliberately not printed (it decides nothing)."""
        granted(["@testbranch"])
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon", model="fable")

        step = status.find_step("model")
        assert step is not None
        assert step[0] == "ok"
        assert step[2] == "fable"

    def test_a_refusal_is_a_warn_step_naming_target_model_and_ruling(self, tmp_path, monkeypatch, granted):
        """Never silent: the caller sees the refusal in the dispatch output, not only in a log."""
        granted(["@devpulse"])
        _make_scheduled_fixtures(tmp_path, monkeypatch, citizen_class="specialist")
        _patch_wake_deps(monkeypatch)
        _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", model="fable")

        step = status.find_step("model")
        assert step is not None
        assert step[0] == "warn", step
        assert "@testbranch" in step[2], step[2]
        assert "fable" in step[2].lower(), step[2]
        assert "2026-09-08" in step[2], step[2]
        assert DEFAULT_MODEL in step[2], step[2]

    def test_the_refusal_step_appears_in_the_formatted_output(self, tmp_path, monkeypatch, granted):
        """find_step reads the record; this reads what a human is shown."""
        granted(["@devpulse"])
        _make_scheduled_fixtures(tmp_path, monkeypatch, citizen_class="specialist")
        _patch_wake_deps(monkeypatch)
        _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", model="fable")

        assert "may not run Fable" in status.format()

    def test_a_branch_with_no_passport_never_lands_on_fable(self, tmp_path, monkeypatch, granted):
        """End to end with nothing to read: a missing identity still cannot promote anyone."""
        granted(["@devpulse"])
        _make_wake_fixtures(tmp_path, monkeypatch)  # no .trinity/passport.json
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", model="fable")

        assert ok is True
        cmd = calls["popen"][0]["cmd"]
        assert cmd[cmd.index("--model") + 1] == DEFAULT_MODEL
        assert calls["tmux"] == []


class TestCodexWake:
    """provider="codex" spawns `codex exec` with the same prompt, its own model rule and its own pointer."""

    THREAD = "01a1746b-c9c8-7891-ae8e-666b368caf13"

    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(_Path, "home", classmethod(lambda cls: home))
        return home

    def _wake(self, tmp_path, monkeypatch, **kwargs):
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, _find_codex_bin=lambda: "codex")
        calls = _record_spawn_routes(monkeypatch)
        status, ok = wake_branch("@testbranch", provider="codex", **kwargs)
        return branch_path, calls, status, ok

    def _plant_codex_pointer(self, branch_path, home):
        wake_mod.session_pointer.write_pointer(branch_path, self.THREAD, "monitor-codex", provider="codex")
        day = home / ".codex" / "sessions" / "2026" / "10" / "25"
        day.mkdir(parents=True)
        (day / f"rollout-2026-10-25T11-56-24-{self.THREAD}.jsonl").write_text("{}\n", encoding="utf-8")

    def _tail(self, branch_path, args):
        return [
            "--json",
            "-o",
            str(branch_path / "logs" / "dispatch_last_message.txt"),
            "--dangerously-bypass-approvals-and-sandbox",
            args[-1],
        ]

    def test_a_fresh_codex_wake_with_a_model_spawns_exec_dash_m_and_writes_no_pointer(
        self, tmp_path, monkeypatch, fake_home
    ):
        branch_path, calls, status, ok = self._wake(tmp_path, monkeypatch, model="gpt-6.1-sol", fresh=True)

        assert ok is True
        args = _claude_args(calls["popen"][0]["cmd"])
        assert args == ["codex", "exec", "-m", "gpt-6.1-sol", *self._tail(branch_path, args)]
        assert args[-1].startswith("Hi. Check inbox") and "seedgo" in args[-1]
        assert wake_mod.session_pointer.read_pointer(branch_path) is None
        assert status.find_step("provider") == ("ok", "provider", "codex")
        assert status.find_step("model") == ("ok", "model", "gpt-6.1-sol")

    def test_a_codex_wake_without_a_model_passes_no_dash_m_and_says_config_default(
        self, tmp_path, monkeypatch, fake_home
    ):
        branch_path, calls, status, _ = self._wake(tmp_path, monkeypatch)

        args = _claude_args(calls["popen"][0]["cmd"])
        assert args == ["codex", "exec", *self._tail(branch_path, args)]
        assert status.find_step("model") == ("ok", "model", "codex config default")

    def test_a_codex_pointer_resumes_its_thread_by_id(self, tmp_path, monkeypatch, fake_home):
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        self._plant_codex_pointer(branch_path, fake_home)
        _patch_wake_deps(monkeypatch, _find_codex_bin=lambda: "codex")
        calls = _record_spawn_routes(monkeypatch)

        status, _ = wake_branch("@testbranch", provider="codex", model="gpt-6.1-sol")

        args = _claude_args(calls["popen"][0]["cmd"])
        assert args == ["codex", "exec", "resume", self.THREAD, "-m", "gpt-6.1-sol", *self._tail(branch_path, args)]
        assert status.find_step("session") == ("ok", "session", f"resuming {self.THREAD} (pointer)")

    def test_fresh_ignores_a_live_codex_pointer(self, tmp_path, monkeypatch, fake_home):
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        self._plant_codex_pointer(branch_path, fake_home)
        _patch_wake_deps(monkeypatch, _find_codex_bin=lambda: "codex")
        calls = _record_spawn_routes(monkeypatch)

        wake_branch("@testbranch", provider="codex", fresh=True)

        args = _claude_args(calls["popen"][0]["cmd"])
        assert args[:2] == ["codex", "exec"] and "resume" not in args

    def test_a_claude_pointer_never_becomes_a_codex_resume(self, tmp_path, monkeypatch, fake_home):
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        wake_mod.session_pointer.write_pointer(branch_path, self.THREAD, "wake-fresh")
        _patch_wake_deps(monkeypatch, _find_codex_bin=lambda: "codex")
        calls = _record_spawn_routes(monkeypatch)

        status, _ = wake_branch("@testbranch", provider="codex")

        args = _claude_args(calls["popen"][0]["cmd"])
        assert "resume" not in args and self.THREAD not in args
        assert status.find_step("session")[0] == "info"

    def test_the_monitor_is_told_codex_and_the_register_row_says_so(self, tmp_path, monkeypatch, fake_home):
        _, calls, _, _ = self._wake(tmp_path, monkeypatch)

        cmd = calls["popen"][0]["cmd"]
        assert "--provider=codex" in cmd[: cmd.index("--")]
        rows = register_mod.outstanding()
        assert [row["provider"] for row in rows] == ["codex"]

    def test_a_claude_wake_carries_no_provider_flag_and_registers_claude(self, tmp_path, monkeypatch, fake_home):
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, _ = wake_branch("@testbranch")

        cmd = calls["popen"][0]["cmd"]
        assert not any(arg.startswith("--provider") for arg in cmd)
        assert status.find_step("provider") == ("ok", "provider", "claude")
        assert [row["provider"] for row in register_mod.outstanding()] == ["claude"]

    def test_an_unknown_provider_fails_before_any_spawn(self, tmp_path, monkeypatch):
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", provider="gemini")

        assert ok is False
        assert status.find_step("provider")[0] == "fail" and "gemini" in status.find_step("provider")[2]
        assert calls["popen"] == []

    @pytest.mark.parametrize("lane", [{"scheduled": True}, {"admin": True}])
    def test_a_manager_wakes_headless_on_codex_in_the_scheduled_and_admin_lanes(self, tmp_path, monkeypatch, lane):
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, _find_codex_bin=lambda: "codex")
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", provider="codex", **lane)

        assert ok is True and status.find_step("manager")[0] == "ok"
        cmd = calls["popen"][0]["cmd"]
        assert "--provider=codex" in cmd[: cmd.index("--")]
        assert _claude_args(cmd)[:2] == ["codex", "exec"]
        assert calls["tmux"] == []
        assert [row["provider"] for row in register_mod.outstanding()] == ["codex"]

    @pytest.mark.parametrize("model, model_flag", [(None, ""), ("gpt-6.1-sol", "-m gpt-6.1-sol ")])
    def test_a_daemon_self_wake_of_a_manager_on_codex_runs_codex_in_tmux(
        self, tmp_path, monkeypatch, model, model_flag
    ):
        branch_path = _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, _find_codex_bin=lambda: "codex")
        calls = _record_spawn_routes(monkeypatch)

        _, ok = wake_branch("@testbranch", sender="@daemon", provider="codex", model=model)

        assert ok is True and calls["popen"] == []
        prompt_file = branch_path / ".daemon" / "last_wake_prompt.txt"
        line = _tmux_line(calls, "send-keys")
        assert f'codex {model_flag}--dangerously-bypass-approvals-and-sandbox "$(cat {prompt_file})"' in line
        assert "--permission-mode" not in line and "--model" not in line


def _plant_opencode_store(tmp_path, monkeypatch, rows):
    """A session_v2 table at OPENCODE_DB holding (id, directory) rows."""
    db = tmp_path / "opencode.db"
    with sqlite3.connect(db) as conn:
        conn.execute("create table if not exists session_v2 (id text primary key, directory text)")
        conn.executemany("insert into session_v2 values (?, ?)", rows)
    conn.close()
    monkeypatch.setenv("OPENCODE_DB", str(db))
    return db


class TestOpenCodeWake:
    """provider="opencode" spawns `opencode run --session <id>`, the id ours and pointed before the spawn."""

    HEAD = ["opencode", "run", "--standalone", "--format", "json", "--auto"]

    def _wake(self, tmp_path, monkeypatch, plant=None, **kwargs):
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        if plant:
            plant(branch_path)
        _patch_wake_deps(monkeypatch, _find_opencode_bin=lambda: "opencode")
        calls = _record_spawn_routes(monkeypatch)
        status, ok = wake_branch("@testbranch", provider="opencode", **kwargs)
        return branch_path, calls, status, ok

    def test_a_fresh_wake_with_a_model_passes_dash_m_and_no_session_so_opencode_mints_the_id(
        self, tmp_path, monkeypatch
    ):
        """02:16 measurement: the free tier answers 429 to a session id in any shape but OpenCode's own."""
        _plant_opencode_store(tmp_path, monkeypatch, [])
        branch_path, calls, status, ok = self._wake(tmp_path, monkeypatch, model="opencode/glm-5.3-flash-free")

        assert ok is True
        args = _claude_args(calls["popen"][0]["cmd"])
        assert args == [*self.HEAD, "-m", "opencode/glm-5.3-flash-free", args[-1]]
        assert args[-1].startswith("Hi. Check inbox") and "seedgo" in args[-1]
        assert wake_mod.session_pointer.read_pointer(branch_path) is None
        assert status.find_step("provider") == ("ok", "provider", "opencode")
        assert status.find_step("model") == ("ok", "model", "opencode/glm-5.3-flash-free")
        assert status.find_step("session")[2].startswith("fresh, OpenCode mints the id")

    def test_a_wake_without_a_model_passes_no_dash_m_and_says_opencode_default(self, tmp_path, monkeypatch):
        _plant_opencode_store(tmp_path, monkeypatch, [])
        _, calls, status, _ = self._wake(tmp_path, monkeypatch)

        args = _claude_args(calls["popen"][0]["cmd"])
        assert "-m" not in args and args[: len(self.HEAD)] == self.HEAD
        assert status.find_step("model") == ("ok", "model", "opencode default")

    def test_a_pointer_whose_session_is_in_the_store_for_this_branch_resumes_by_id(self, tmp_path, monkeypatch):
        sid = "ses_aipass_resume"
        branch_dir = str((tmp_path / "src" / "aipass" / "testbranch").resolve())

        def plant(branch_path):
            assert str(branch_path.resolve()) == branch_dir
            _plant_opencode_store(tmp_path, monkeypatch, [(sid, branch_dir)])
            wake_mod.session_pointer.write_pointer(branch_path, sid, "wake-fresh", provider="opencode")

        branch_path, calls, status, _ = self._wake(tmp_path, monkeypatch, plant=plant)

        args = _claude_args(calls["popen"][0]["cmd"])
        assert args == [*self.HEAD, "--session", sid, args[-1]]
        assert status.find_step("session") == ("ok", "session", f"resuming {sid} (pointer)")
        assert wake_mod.session_pointer.read_pointer(branch_path)["session_id"] == sid

    @pytest.mark.parametrize(
        "row, why",
        [(None, "not found in"), ("elsewhere", "belongs to")],
        ids=["absent-from-store", "another-directory"],
    )
    def test_a_pointer_the_store_does_not_vouch_for_starts_fresh_with_no_session_and_says_why(
        self, tmp_path, monkeypatch, row, why
    ):
        sid = "ses_aipass_stale"

        def plant(branch_path):
            rows = [] if row is None else [(sid, str(tmp_path / row))]
            _plant_opencode_store(tmp_path, monkeypatch, rows)
            wake_mod.session_pointer.write_pointer(branch_path, sid, "wake-fresh", provider="opencode")

        _, calls, status, _ = self._wake(tmp_path, monkeypatch, plant=plant)

        args = _claude_args(calls["popen"][0]["cmd"])
        assert "--session" not in args and sid not in args
        assert why in status.find_step("session")[2]

    def test_a_codex_pointer_starts_an_opencode_wake_fresh_with_the_resolvers_reason(self, tmp_path, monkeypatch):
        def plant(branch_path):
            _plant_opencode_store(tmp_path, monkeypatch, [])
            wake_mod.session_pointer.write_pointer(branch_path, "ses_codexish", "monitor-codex", provider="codex")

        _, calls, status, _ = self._wake(tmp_path, monkeypatch, plant=plant)

        args = _claude_args(calls["popen"][0]["cmd"])
        assert "ses_codexish" not in args
        assert "pointer is for codex, waking on opencode - starting fresh" in status.find_step("session")[2]

    def test_fresh_ignores_a_live_pointer_and_passes_no_session(self, tmp_path, monkeypatch):
        sid = "ses_aipass_live"

        def plant(branch_path):
            _plant_opencode_store(tmp_path, monkeypatch, [(sid, str(branch_path.resolve()))])
            wake_mod.session_pointer.write_pointer(branch_path, sid, "wake-fresh", provider="opencode")

        _, calls, _, _ = self._wake(tmp_path, monkeypatch, plant=plant, fresh=True)

        args = _claude_args(calls["popen"][0]["cmd"])
        assert sid not in args and "--session" not in args

    def test_the_monitor_is_told_opencode_and_the_register_row_says_so(self, tmp_path, monkeypatch):
        _plant_opencode_store(tmp_path, monkeypatch, [])
        _, calls, _, _ = self._wake(tmp_path, monkeypatch)

        cmd = calls["popen"][0]["cmd"]
        assert "--provider=opencode" in cmd[: cmd.index("--")]
        assert [row["provider"] for row in register_mod.outstanding()] == ["opencode"]

    @pytest.mark.parametrize(
        "model, config",
        [
            (None, ""),
            ("opencode/glm-5.3-flash-free", """OPENCODE_CONFIG_CONTENT='{"model": "opencode/glm-5.3-flash-free"}' """),
        ],
    )
    def test_a_daemon_self_wake_of_a_manager_on_opencode_runs_a_standalone_tui_with_the_model_inline(
        self, tmp_path, monkeypatch, model, config
    ):
        branch_path = _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, _find_opencode_bin=lambda: "opencode")
        calls = _record_spawn_routes(monkeypatch)

        _, ok = wake_branch("@testbranch", sender="@daemon", provider="opencode", model=model)

        assert ok is True and calls["popen"] == []
        prompt_file = branch_path / ".daemon" / "last_wake_prompt.txt"
        line = _tmux_line(calls, "send-keys")
        assert f' {config}opencode --standalone --auto --prompt "$(cat {prompt_file})" Enter' in line
        assert ("OPENCODE_CONFIG_CONTENT" in line) is bool(model)
        assert "--model" not in line and "-m " not in line
