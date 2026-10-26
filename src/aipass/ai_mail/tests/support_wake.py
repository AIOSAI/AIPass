# =================== AIPass ====================
# Name: support_wake.py
# Description: Shared helpers for test_wake.py and its split siblings - the wake fixtures and spawn recorder
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-25
# =============================================

"""Helpers for the tests of apps/handlers/dispatch/wake.py (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json

import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod


def _make_wake_fixtures(tmp_path, monkeypatch):
    """Helper: set up branch directory, registry, and monkeypatched module constants."""
    branch_path = tmp_path / "src" / "aipass" / "testbranch"
    branch_path.mkdir(parents=True)
    (branch_path / ".ai_mail.local").mkdir()

    registry_file = tmp_path / "AIPASS_REGISTRY.json"
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

    return branch_path


def _patch_wake_deps(monkeypatch, resolve_claude=False, **overrides):
    """Monkeypatch all wake_branch dependencies with sane defaults; override as needed.

    The claude binary is stubbed unless *resolve_claude*: a CI runner has no claude to find.
    """
    defaults = {
        "check_lock": lambda p: None,
        "clean_zombies": lambda: 0,
        "branch_occupant": lambda p: None,
        "acquire_lock": lambda p, pid: (True, "ok"),
        "check_pid_alive": lambda pid: True,
        # Stubbed: a unit test must not read the fleet's real .central.json files.
        "_refresh_recipient_dashboard": lambda path, email, status: None,
    }
    if not resolve_claude:
        defaults["_find_claude_bin"] = lambda: "claude"
    defaults.update(overrides)
    for attr, val in defaults.items():
        monkeypatch.setattr(wake_mod, attr, val)

    monkeypatch.setattr("aipass.ai_mail.apps.handlers.dispatch.wake.time.sleep", lambda _: None)
    monkeypatch.delenv("INVOCATION_ID", raising=False)


class _FakeProc:
    """Minimal stand-in for subprocess.Popen return value."""

    def __init__(self, pid: int = 55555):
        self.pid = pid


def _make_scheduled_fixtures(tmp_path, monkeypatch, email="@testbranch", citizen_class="manager"):
    """Branch + registry + passport for scheduled-lane tests; a non-default `email` shares the directory."""
    branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
    if email != "@testbranch":
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        data = json.loads(registry_file.read_text(encoding="utf-8"))
        data["branches"].append({"name": email.lstrip("@").upper(), "email": email, "path": str(branch_path)})
        registry_file.write_text(json.dumps(data), encoding="utf-8")

    trinity = branch_path / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    (trinity / "passport.json").write_text(
        json.dumps({"identity": {"citizen_class": citizen_class}}),
        encoding="utf-8",
    )
    return branch_path


def _record_spawn_routes(monkeypatch):
    """Capture both spawn routes so a test can name which one a wake took.

    tmux goes through subprocess.run; the headless monitor through subprocess.Popen.
    """
    calls: dict = {"tmux": [], "popen": []}

    def _fake_run(cmd, **kwargs):
        calls["tmux"].append(list(cmd))

        class _Done:
            returncode = 0
            stderr = ""

        return _Done()

    def _fake_popen(cmd, **kwargs):
        calls["popen"].append({"cmd": list(cmd), "env": dict(kwargs.get("env") or {})})
        return _FakeProc()

    monkeypatch.setattr(wake_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(wake_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr("subprocess.Popen", _fake_popen)
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.notify.send_notification",
        lambda *a, **kw: None,
        raising=False,
    )
    return calls


def _claude_args(popen_cmd: list) -> list:
    """The claude command a monitor spawn was handed (everything after '--')."""
    return popen_cmd[popen_cmd.index("--") + 1 :]
