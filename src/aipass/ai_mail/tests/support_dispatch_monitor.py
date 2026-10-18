# =================== AIPass ====================
# Name: support_dispatch_monitor.py
# Description: Shared helpers for test_dispatch_monitor.py and its siblings - the one-identity send check, a main() run, a foreign project
# Version: 1.2.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Helper for the tests of apps/handlers/dispatch/dispatch_monitor.py (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod


def _run_main(monkeypatch, argv, tmp_path, attempts):
    """Run main() with attempt N played by attempts[N-1], which gets the stdout log path and returns the exit code."""
    queue = list(attempts)

    def fake_run(cmd, stdout_log, *args, **kwargs):
        return queue.pop(0)(stdout_log), False

    clock = MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock())
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "time", clock)
    monkeypatch.setattr("aipass.ai_mail.apps.handlers.paths.find_repo_root", MagicMock(return_value=tmp_path / "repo"))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    # The time mock records the pauses between attempts; nothing sleeps.
    return exc_info.value.code, clock


def _assert_sent_as_ai_mail(run_mock):
    """The one drone send ran in ai_mail's home under ai_mail's name: one identity claim."""
    sends = [c for c in run_mock.call_args_list if c.args and c.args[0][:3] == ["drone", "@ai_mail", "send"]]
    assert len(sends) == 1
    kwargs = sends[0].kwargs
    monitor_in_cwd = Path(kwargs["cwd"]) / "apps" / "handlers" / "dispatch" / "dispatch_monitor.py"
    assert monitor_in_cwd.resolve() == Path(mod.__file__).resolve()
    assert (kwargs.get("env") or {}).get("AIPASS_BRANCH_NAME") == "ai_mail"


def _foreign_project(tmp_path, *names):
    """Make tmp_path a project of its own, outside AIPass, whose registry lists `names` (branch dirs under it)."""
    branches = [{"name": n, "email": f"@{n}", "path": n} for n in names]
    (tmp_path / "FOREIGN_REGISTRY.json").write_text(json.dumps({"branches": branches}), encoding="utf-8")


def _assert_sent_from(run_mock, home):
    """The one drone send ran with `home` as its cwd."""
    sends = [c for c in run_mock.call_args_list if c.args and c.args[0][:3] == ["drone", "@ai_mail", "send"]]
    assert len(sends) == 1
    assert Path(sends[0].kwargs["cwd"]).resolve() == Path(home).resolve()
