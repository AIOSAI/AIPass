# =================== AIPass ====================
# Name: test_adopt.py
# Description: Tests for aipass adopt — project adoption handler
# Version: 1.0.0
# Created: 2026-07-20
# Modified: 2026-07-20
# =============================================

"""Tests for the adopt handler and module.

All file operations use tmp_path to stay fully isolated from the live
filesystem. dry_run tests assert zero filesystem mutation.
"""

import json
import subprocess
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.new_project.adopt import (
    GITIGNORE_MARKER,
    adopt_project,
)


@pytest.fixture()
def host_env(tmp_path):
    """Minimal AIPass host installation with an existing (pre-populated) project dir."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps({"metadata": {"id": "host-id"}, "branches": []}))
    projects = tmp_path / "projects"
    projects.mkdir()
    target = projects / "existing-site"
    target.mkdir()
    (target / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (target / "README.md").write_text("# existing-site\n\nReal content.\n", encoding="utf-8")
    return tmp_path, target


def _no_home():
    return patch(
        "aipass.aipass.apps.handlers.new_project.adopt._detect_aipass_home",
        return_value=None,
    )


# ---------------------------------------------------------------------------
# adopt_project — guards / refusals
# ---------------------------------------------------------------------------


def test_adopt_rejects_missing_target(tmp_path):
    with pytest.raises(RuntimeError, match="does not exist"):
        adopt_project(tmp_path / "nope")


def test_adopt_rejects_non_projects_child(tmp_path):
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}")
    outside = tmp_path / "elsewhere" / "myapp"
    outside.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="not <host>/projects/<name>"):
        adopt_project(outside)


def test_adopt_rejects_already_adopted(host_env):
    _, target = host_env
    (target / "EXISTING_SITE_REGISTRY.json").write_text("{}")
    with pytest.raises(RuntimeError, match="already adopted"):
        adopt_project(target, no_agent=True)


def test_adopt_rejects_agent_home_collision(host_env):
    _, target = host_env
    home = target / "src" / "existing_site" / "existing_site"
    home.mkdir(parents=True)
    (home / "stray.txt").write_text("junk\n", encoding="utf-8")
    with _no_home():
        with pytest.raises(RuntimeError, match="Name collision"):
            adopt_project(target, no_agent=False)


def test_adopt_allows_collision_with_no_agent(host_env):
    """An occupied agent-home path is fine when --no-agent skips the agent entirely."""
    _, target = host_env
    home = target / "src" / "existing_site" / "existing_site"
    home.mkdir(parents=True)
    (home / "stray.txt").write_text("junk\n", encoding="utf-8")
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        result = adopt_project(target, no_agent=True)
    assert result["agent_created"] is False


# ---------------------------------------------------------------------------
# adopt_project — gitignore safety
# ---------------------------------------------------------------------------


def test_adopt_creates_gitignore_when_absent(host_env):
    _, target = host_env
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        result = adopt_project(target, no_agent=True)
    assert result["gitignore_action"] == "created"
    content = (target / ".gitignore").read_text(encoding="utf-8")
    assert GITIGNORE_MARKER in content
    assert ".trinity/" in content


def test_adopt_appends_gitignore_when_marker_absent(host_env):
    _, target = host_env
    (target / ".gitignore").write_text("node_modules/\ndist/\n", encoding="utf-8")
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        result = adopt_project(target, no_agent=True)
    assert result["gitignore_action"] == "appended"
    content = (target / ".gitignore").read_text(encoding="utf-8")
    assert "node_modules/" in content
    assert GITIGNORE_MARKER in content
    assert ".trinity/" in content


def test_adopt_skips_gitignore_when_marker_present(host_env):
    _, target = host_env
    (target / ".gitignore").write_text(f"{GITIGNORE_MARKER}\n.trinity/\n", encoding="utf-8")
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        result = adopt_project(target, no_agent=True)
    assert result["gitignore_action"] == "already-safe"
    content = (target / ".gitignore").read_text(encoding="utf-8")
    assert content.count(GITIGNORE_MARKER) == 1


def test_adopt_gitignore_covers_symlinked_venv_and_registry_lock(host_env, tmp_path):
    """Live-verification regression: a symlinked .venv (not a real dir) and a
    registry lock file must both be actually ignored by real git, not just
    present as a string in the .gitignore content."""
    host, target = host_env
    aipass_home = tmp_path / "fake_aipass_home"
    (aipass_home / ".venv").mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=target, capture_output=True, text=True, check=True)

    with (
        patch(
            "aipass.aipass.apps.handlers.new_project.adopt._detect_aipass_home",
            return_value=str(aipass_home),
        ),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
    ):
        adopt_project(target, no_agent=True)

    venv_link = target / ".venv"
    assert venv_link.is_symlink()
    lock_file = target / ".EXISTING-SITE_REGISTRY.lock"
    lock_file.write_text("", encoding="utf-8")

    result = subprocess.run(
        ["git", "check-ignore", ".venv", ".EXISTING-SITE_REGISTRY.lock"],
        cwd=target,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert ".venv" in result.stdout.split()
    assert ".EXISTING-SITE_REGISTRY.lock" in result.stdout.split()


# ---------------------------------------------------------------------------
# adopt_project — additive scaffold, existing files untouched
# ---------------------------------------------------------------------------


def test_adopt_never_overwrites_existing_readme(host_env):
    _, target = host_env
    original = (target / "README.md").read_text(encoding="utf-8")
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        adopt_project(target, no_agent=True)
    assert (target / "README.md").read_text(encoding="utf-8") == original


def test_adopt_never_touches_existing_tracked_files(host_env):
    _, target = host_env
    original = (target / "index.html").read_text(encoding="utf-8")
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        adopt_project(target, no_agent=True)
    assert (target / "index.html").read_text(encoding="utf-8") == original


def test_adopt_writes_registry_and_settings(host_env):
    _, target = host_env
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        result = adopt_project(target, no_agent=True)
    assert result["registry_file"] == "EXISTING-SITE_REGISTRY.json"
    assert (target / "EXISTING-SITE_REGISTRY.json").exists()
    reg = json.loads((target / "EXISTING-SITE_REGISTRY.json").read_text())
    assert reg["metadata"]["name"] == "EXISTING-SITE"
    assert (target / ".claude" / "settings.json").exists()
    settings = json.loads((target / ".claude" / "settings.json").read_text())
    assert "env" not in settings


def test_adopt_no_agent_skips_spawn(host_env):
    _, target = host_env
    with (
        _no_home(),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
        patch("aipass.aipass.apps.handlers.new_project.spawn_agent") as mock_spawn,
    ):
        result = adopt_project(target, no_agent=True)
    mock_spawn.assert_not_called()
    assert result["agent_created"] is False
    assert result["agent_home"] is None


def test_adopt_with_agent_spawns(host_env):
    _, target = host_env
    spawn_ok = {
        "success": True,
        "branch_name": "EXISTING_SITE",
        "path": str(target / "src" / "existing_site" / "existing_site"),
        "files_copied": 12,
        "registry_updated": True,
        "validation_issues": [],
    }
    with (
        _no_home(),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            return_value=spawn_ok,
        ) as mock_spawn,
    ):
        result = adopt_project(target, no_agent=False)
    mock_spawn.assert_called_once()
    assert result["agent_created"] is True
    assert result["agent_home"] == str(target / "src" / "existing_site" / "existing_site")


def test_adopt_registry_minted_before_spawn(host_env):
    """Registry-first invariant: registry file exists on disk before spawn_agent is called."""
    _, target = host_env
    seen = {}

    def _check_registry_exists(**kwargs):
        seen["registry_present"] = (target / "EXISTING-SITE_REGISTRY.json").exists()
        return {
            "success": True,
            "branch_name": "EXISTING_SITE",
            "path": kwargs["target_path"],
            "files_copied": 1,
            "registry_updated": True,
            "validation_issues": [],
        }

    with (
        _no_home(),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            side_effect=_check_registry_exists,
        ),
    ):
        adopt_project(target, no_agent=False)
    assert seen["registry_present"] is True


# ---------------------------------------------------------------------------
# adopt_project — dry_run performs zero writes
# ---------------------------------------------------------------------------


def test_adopt_dry_run_writes_nothing(host_env):
    _, target = host_env
    before = sorted(p.relative_to(target) for p in target.rglob("*"))
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.spawn_agent") as mock_spawn:
        result = adopt_project(target, no_agent=False, dry_run=True)
    after = sorted(p.relative_to(target) for p in target.rglob("*"))
    assert before == after
    mock_spawn.assert_not_called()
    assert result["dry_run"] is True
    assert result["registry_id"] is None
    assert result["agent_created"] is False


def test_adopt_dry_run_reports_planned_registry_and_agent(host_env):
    _, target = host_env
    with _no_home():
        result = adopt_project(target, no_agent=False, dry_run=True)
    assert result["registry_file"] == "EXISTING-SITE_REGISTRY.json"
    assert "EXISTING-SITE_REGISTRY.json" in result["files"]
    assert result["agent_home"] == str(target / "src" / "existing_site" / "existing_site")
    assert any("resident agent" in f for f in result["files"])


def test_adopt_dry_run_no_agent_reports_no_home(host_env):
    _, target = host_env
    with _no_home():
        result = adopt_project(target, no_agent=True, dry_run=True)
    assert result["agent_home"] is None


def test_adopt_dry_run_still_reports_gitignore_action(host_env):
    _, target = host_env
    with _no_home():
        result = adopt_project(target, no_agent=True, dry_run=True)
    assert result["gitignore_action"] == "created"
    assert not (target / ".gitignore").exists()


# ---------------------------------------------------------------------------
# Module handle_command
# ---------------------------------------------------------------------------


def test_module_handles_not_mine():
    from aipass.aipass.apps.modules.adopt import handle_command

    assert handle_command("notmine", []) is False


def test_module_handles_help():
    from aipass.aipass.apps.modules.adopt import handle_command

    assert handle_command("adopt", ["--help"]) is True


def test_module_handles_no_args():
    from aipass.aipass.apps.modules.adopt import handle_command

    assert handle_command("adopt", []) is True


def test_module_rejects_unknown_option(host_env):
    from aipass.aipass.apps.modules.adopt import handle_command

    _, target = host_env
    with patch("aipass.aipass.apps.modules.adopt.error") as mock_error:
        handle_command("adopt", [str(target), "--bogus"])
    mock_error.assert_called_once()
    assert "Unknown option" in mock_error.call_args[0][0]


def test_module_adopt_by_absolute_path(host_env, monkeypatch):
    from aipass.aipass.apps.modules.adopt import handle_command

    host, target = host_env
    monkeypatch.chdir(host)
    with (
        _no_home(),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
        patch("aipass.aipass.apps.modules.adopt.console") as mock_con,
    ):
        handle_command("adopt", [str(target), "--no-agent"])
    printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
    assert "Registry:" in printed
    assert "EXISTING-SITE_REGISTRY.json" in printed


def test_module_adopt_by_bare_name(host_env, monkeypatch):
    from aipass.aipass.apps.modules.adopt import handle_command

    host, target = host_env
    monkeypatch.chdir(host)
    with (
        _no_home(),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
        patch("aipass.aipass.apps.modules.adopt.console") as mock_con,
    ):
        handle_command("adopt", ["existing-site", "--no-agent"])
    printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
    assert "Registry:" in printed
    assert "EXISTING-SITE_REGISTRY.json" in printed


def test_module_adopt_dry_run_reports_would_adopt(host_env, monkeypatch, capsys):
    from aipass.aipass.apps.modules.adopt import handle_command

    host, target = host_env
    monkeypatch.chdir(host)
    with _no_home():
        handle_command("adopt", ["existing-site", "--no-agent", "--dry-run"])
    out = capsys.readouterr().out
    assert "Would adopt" in out
    assert not (target / "EXISTING-SITE_REGISTRY.json").exists()


def test_module_adopt_missing_target_no_host(tmp_path, monkeypatch):
    from aipass.aipass.apps.modules.adopt import handle_command

    monkeypatch.chdir(tmp_path)
    with (
        patch("aipass.aipass.apps.modules.adopt.error") as mock_error,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_command("adopt", ["nope"])
    mock_error.assert_called_once()
    assert "Not inside an AIPass installation" in mock_error.call_args[0][0]
    assert exc_info.value.code == 1


def test_module_adopt_reports_refusal(host_env, monkeypatch):
    from aipass.aipass.apps.modules.adopt import handle_command

    host, target = host_env
    monkeypatch.chdir(host)
    (target / "EXISTING-SITE_REGISTRY.json").write_text("{}")
    with (
        patch("aipass.aipass.apps.modules.adopt.error") as mock_error,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_command("adopt", ["existing-site", "--no-agent"])
    mock_error.assert_called_once()
    assert "already adopted" in mock_error.call_args[0][0]
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# aipass.py wiring
# ---------------------------------------------------------------------------


def test_aipass_public_commands_includes_adopt():
    from aipass.aipass.apps.aipass import _PUBLIC_COMMANDS

    assert "adopt" in _PUBLIC_COMMANDS
