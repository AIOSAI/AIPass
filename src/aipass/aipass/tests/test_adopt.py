# =================== AIPass ====================
# Name: test_adopt.py
# Description: Tests for aipass adopt — project adoption handler
# Version: 1.3.0
# Created: 2026-07-20
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/new_project/adopt.py and apps/modules/adopt.py."""

# All file operations use tmp_path to stay fully isolated from the live
# filesystem. dry_run tests assert zero filesystem mutation.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — spawn_agent's own behavior; @spawn's function, mocked here

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.aipass import print_introspection
from aipass.aipass.apps.handlers.new_project.adopt import (
    GITIGNORE_MARKER,
    adopt_project,
)
from aipass.aipass.apps.modules import adopt as adopt_module
from aipass.aipass.apps.modules.adopt import handle_command
from aipass.aipass.shared import scaffold_content as sc
from aipass.aipass.shared.registry_discovery import registries_in


@pytest.fixture()
def host_env(tmp_path):
    """Minimal AIPass host installation with an existing (pre-populated) project dir."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text(
        json.dumps({"metadata": {"id": "host-id"}, "branches": []}), encoding="utf-8"
    )
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
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "elsewhere" / "myapp"
    outside.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="not <host>/projects/<name>"):
        adopt_project(outside)


def test_adopt_rejects_already_adopted(host_env):
    _, target = host_env
    (target / "EXISTING_SITE_REGISTRY.json").write_text("{}", encoding="utf-8")
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
    subprocess.run(["git", "init"], cwd=target, capture_output=True, text=True, encoding="utf-8", check=True)

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
        encoding="utf-8",
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
    reg = json.loads((target / "EXISTING-SITE_REGISTRY.json").read_text(encoding="utf-8"))
    assert reg["metadata"]["name"] == "EXISTING-SITE"
    assert (target / ".claude" / "settings.json").exists()
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "env" not in settings


def test_adopt_writes_claude_md_excludes_fence(host_env, tmp_path):
    """adopt only ever targets <host>/projects/<name>, so settings.local.json must
    always carry the claudeMdExcludes fence when AIPASS_HOME is detected — never
    just the bare env.AIPASS_HOME that `nested=False` would produce."""
    _, target = host_env
    # The home is built from tmp_path, so adopt.py's is_throwaway_path() would call it
    # throwaway and skip the very write under test: it answers False here, as it does for
    # a real home. Nothing else on this path asks it (fleet green leg 4).
    fake_home = str(tmp_path / "aipass_home")
    with (
        patch(
            "aipass.aipass.apps.handlers.new_project.adopt._detect_aipass_home",
            return_value=fake_home,
        ),
        patch("aipass.aipass.apps.handlers.new_project.adopt.is_throwaway_path", return_value=False),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
    ):
        adopt_project(target, no_agent=True)

    local_settings = target / ".claude" / "settings.local.json"
    assert local_settings.is_file()
    settings = json.loads(local_settings.read_text(encoding="utf-8"))
    assert settings["env"]["AIPASS_HOME"] == fake_home
    assert settings.get("claudeMdExcludes") == [
        (Path(fake_home) / "CLAUDE.md").as_posix(),
        (Path(fake_home) / ".claude" / "CLAUDE.md").as_posix(),
        (Path(fake_home) / "AGENTS.md").as_posix(),
        (Path(fake_home) / ".claude" / "AGENTS.md").as_posix(),
    ]


def test_adopt_mints_agents_md_from_the_host_template_and_no_claude_md(host_env):
    host, target = host_env
    (host / ".aipass").mkdir()
    (host / ".aipass" / "project_AGENTS.md").write_text("# {name}\ntemplate\n", encoding="utf-8")
    (host / ".aipass" / "project_CLAUDE.md").write_text("# {name}\nclaude\n", encoding="utf-8")
    (host / "CLAUDE.md").write_text("host claude\n", encoding="utf-8")
    with (
        patch("aipass.aipass.apps.handlers.new_project.adopt._detect_aipass_home", return_value=str(host)),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
    ):
        adopt_project(target, no_agent=True)

    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# EXISTING-SITE\ntemplate\n"
    assert not (target / "CLAUDE.md").exists()


def test_adopt_mints_the_host_root_agents_md_when_no_template(host_env):
    host, target = host_env
    (host / "AGENTS.md").write_text("host agents {name}\n", encoding="utf-8")
    with (
        patch("aipass.aipass.apps.handlers.new_project.adopt._detect_aipass_home", return_value=str(host)),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
    ):
        adopt_project(target, no_agent=True)

    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "host agents {name}\n"
    assert not (target / "CLAUDE.md").exists()


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


def test_adopt_spawn_failure_leaves_no_registry_and_rerun_proceeds(host_env):
    _, target = host_env
    with (
        _no_home(),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
        patch(
            "aipass.aipass.apps.handlers.new_project.spawn_agent",
            return_value={"success": False, "error": "boom"},
        ),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            adopt_project(target, no_agent=False)
    assert not registries_in(target)
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        result = adopt_project(target, no_agent=True)
    assert (target / result["registry_file"]).is_file()


def test_adopt_manifest_omits_pre_existing_scaffold_files(host_env):
    """A file the project already had is the project's: init update must never treat it as ours."""
    _, target = host_env
    (target / ".agents" / "skills" / "prep").mkdir(parents=True)
    (target / ".agents" / "skills" / "prep" / "SKILL.md").write_text("my own prep\n", encoding="utf-8")
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        adopt_project(target, no_agent=True)
    recorded = json.loads((target / ".aipass" / "scaffold_manifest.json").read_text(encoding="utf-8"))["files"]
    assert ".agents/skills/prep/SKILL.md" not in recorded
    assert ".claude/settings.json" in recorded


def test_adopt_replaces_dangling_venv_symlink(host_env, tmp_path):
    _, target = host_env
    aipass_home = tmp_path / "fake_aipass_home"
    (aipass_home / ".venv").mkdir(parents=True)
    (target / ".venv").symlink_to(tmp_path / "gone")
    with (
        patch(
            "aipass.aipass.apps.handlers.new_project.adopt._detect_aipass_home",
            return_value=str(aipass_home),
        ),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
    ):
        adopt_project(target, no_agent=True)
    assert (target / ".venv").resolve() == (aipass_home / ".venv").resolve()


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
    assert handle_command("notmine", []) is False


def test_module_handles_help(capsys: pytest.CaptureFixture[str]):
    """Mutant: print_help() dropped from the --help branch -> red."""
    assert handle_command("adopt", ["--help"]) is True
    out, err = capsys.readouterr()
    assert "USAGE:" in out
    assert "--dry-run" in out


def test_module_handles_no_args(capsys: pytest.CaptureFixture[str]):
    """Mutant: print_introspection() dropped from the bare branch -> red."""
    assert handle_command("adopt", []) is True
    out, err = capsys.readouterr()
    assert "Usage: aipass adopt" in out


def test_module_rejects_unknown_option(host_env):
    """An unknown flag is refused by name.

    Mutant: `error(f"Unknown option: {unknown[0]}")` -> `error("Unknown option")` -> red.
    """
    _, target = host_env
    with patch("aipass.aipass.apps.modules.adopt.error") as mock_error:
        handle_command("adopt", [str(target), "--bogus"])
    mock_error.assert_called_once_with("Unknown option: --bogus")
    assert "Unknown option" in mock_error.call_args[0][0]


def test_module_adopt_by_absolute_path(host_env, monkeypatch, capsys: pytest.CaptureFixture[str]):
    """Mutant: Registry line not printed -> red."""
    host, target = host_env
    monkeypatch.chdir(host)
    with (
        _no_home(),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
    ):
        handle_command("adopt", [str(target), "--no-agent"])
    out, _err = capsys.readouterr()
    printed = " ".join(out.split())
    assert "Registry:" in printed
    assert "EXISTING-SITE_REGISTRY.json" in printed


def test_module_adopt_by_bare_name(host_env, monkeypatch, capsys: pytest.CaptureFixture[str]):
    """Mutant: Registry line not printed -> red."""
    host, target = host_env
    monkeypatch.chdir(host)
    with (
        _no_home(),
        patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"),
    ):
        handle_command("adopt", ["existing-site", "--no-agent"])
    out, _err = capsys.readouterr()
    printed = " ".join(out.split())
    assert "Registry:" in printed
    assert "EXISTING-SITE_REGISTRY.json" in printed


def test_module_adopt_dry_run_reports_would_adopt(host_env, monkeypatch, capsys):
    host, target = host_env
    monkeypatch.chdir(host)
    with _no_home():
        handle_command("adopt", ["existing-site", "--no-agent", "--dry-run"])
    out = capsys.readouterr().out
    assert "Would adopt" in out
    assert not (target / "EXISTING-SITE_REGISTRY.json").exists()


def test_module_adopt_missing_target_no_host(tmp_path, monkeypatch):
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
    host, target = host_env
    monkeypatch.chdir(host)
    (target / "EXISTING-SITE_REGISTRY.json").write_text("{}", encoding="utf-8")
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


def test_aipass_public_commands_includes_adopt(capsys: pytest.CaptureFixture[str]):
    """The bare `aipass` listing names adopt, read through print_introspection.

    Mutant: the "adopt" key dropped from _PUBLIC_COMMANDS -> red.
    """
    print_introspection([adopt_module])
    out = capsys.readouterr().out
    assert "Turn an existing projects/ directory into a full project" in out


def test_adopt_writes_the_prep_skill_and_links_claude_skills_to_it(host_env):
    _, target = host_env
    with _no_home(), patch("aipass.aipass.apps.handlers.new_project.adopt._enroll_project"):
        result = adopt_project(target, no_agent=True)

    skill = target / ".agents" / "skills" / "prep" / "SKILL.md"
    assert skill.read_text(encoding="utf-8") == sc.prep_skill_md()
    assert (target / ".claude" / "skills").resolve() == (target / ".agents" / "skills").resolve()
    assert str(target / ".claude" / "skills") in result["files"]
    assert not (target / ".claude" / "commands").exists()
    assert result["notes"] == []


def test_an_adopt_dry_run_plans_the_skill_link_and_makes_neither(host_env):
    _, target = host_env
    with _no_home():
        result = adopt_project(target, no_agent=True, dry_run=True)

    assert str(target / ".agents" / "skills" / "prep" / "SKILL.md") in result["files"]
    assert str(target / ".claude" / "skills") in result["files"]
    assert not (target / ".claude" / "skills").exists()
    assert not (target / ".agents").exists()
