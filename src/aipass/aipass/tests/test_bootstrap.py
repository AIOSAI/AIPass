# =================== AIPass ====================
# Name: test_bootstrap.py
# Description: Tests for init bootstrap handler (DPLAN-0164)
# Version: 1.3.0
# Created: 2026-05-04
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/init/bootstrap.py and the init/update flows it drives."""

# update_project lives in test_bootstrap_update.py; hooks.json and tier files in test_bootstrap_hooks.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports

import json
import uuid
from datetime import date
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.init.bootstrap import (
    is_throwaway_path,
    init_project,
    update_project,
)
from aipass.aipass.apps.handlers.init import bootstrap
from aipass.aipass.shared import scaffold_content as sc
from aipass.aipass.shared.registry_discovery import registries_in
from aipass.aipass.tests.support_bootstrap import _expected_aipass_home


# _sanitize_name is read through init_project, its one caller; an empty name means the directory's.


@pytest.mark.parametrize(
    "raw,registry_name,package",
    [
        ("my_project", "MY_PROJECT", "my_project"),  # lowercase is uppercased
        ("my-project", "MY-PROJECT", "my_project"),  # hyphens are kept
        ("my project!v2", "MY_PROJECT_V2", "my_project_v2"),  # other characters become underscores
        ("foo.bar/baz", "FOO_BAR_BAZ", "foo_bar_baz"),  # dots and slashes too
        ("...name...", "NAME", "name"),  # leading and trailing underscores are stripped
        ("hello world", "HELLO_WORLD", "hello_world"),  # spaces become underscores
        ("ALPHA", "ALPHA", "alpha"),  # uppercase passes through
    ],
)
def test_project_name_is_sanitized_into_the_registry_name(tmp_path, raw: str, registry_name: str, package: str):
    """The registry file and the src/ package carry the sanitized name, and no other registry lands.

    Mutant: _sanitize_name's .upper() dropped -> red. Mutant: package_name read off the
    raw name again -> the punctuated cases red (a trailing-dot directory crashed on Windows).
    """
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name=raw)
    assert [p.name for p in registries_in(target)] == [f"{registry_name}_REGISTRY.json"]
    packages = sorted(p.parent.relative_to(target / "src").as_posix() for p in (target / "src").rglob("__init__.py"))
    assert packages == [package]
    assert package.isidentifier()


@pytest.mark.parametrize("raw", ["!!!", "___"])
def test_a_name_that_sanitizes_to_nothing_is_refused(tmp_path, raw: str):
    """A name with nothing left after sanitizing is refused, and no registry is written.

    Mutant: _sanitize_name's .strip("_") dropped -> "___" survives as a name -> red.
    """
    target = tmp_path / "proj"
    target.mkdir()
    with pytest.raises(ValueError, match="Cannot derive project name"):
        init_project(target, project_name=raw)
    assert registries_in(target) == []


def test_init_project_creates_all_expected_files(tmp_path):
    """init_project produces all expected files and directories."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="demo")

    expected_files = [
        target / "DEMO_REGISTRY.json",
        target / "AGENTS.md",
        target / "README.md",
        target / ".gitignore",
        target / ".claude" / "settings.json",
        target / ".claude" / "commands" / "prep.md",
        target / "src" / "demo" / "__init__.py",
    ]
    if result["aipass_home"]:
        expected_files.append(target / ".aipass" / "tier0_kernel.md")
        expected_files.append(target / ".aipass" / "tier1_navmap.md")
    for f in expected_files:
        assert f.exists(), f"Expected file not created: {f}"
    assert not (target / ".aipass" / "aipass_global_prompt.md").exists(), "Retired global prompt should NOT be seeded"
    assert not (target / "CLAUDE.md").exists(), "AGENTS.md is the one instruction file"

    assert (target / "src" / "demo").is_dir(), "Expected src/demo/ package directory"

    # No .trinity/ should be created (projects are not citizens)
    assert not (target / ".trinity").exists(), ".trinity/ should NOT be created"

    assert not (target / ".aipass" / "aipass_local_prompt.md").exists()

    assert not (target / ".ai_mail.local").exists(), ".ai_mail.local/ should NOT be at project level"

    created_basenames = [Path(f).name for f in result["created_files"]]
    # created_files and the disk are asserted separately: never `or`, the report is under test.
    for f in expected_files:
        assert f.name in created_basenames, f"Expected {f.name} in created_files"
        assert f.exists(), f"Expected {f.name} on disk"
    assert len(result["created_files"]) >= 10


def test_init_project_return_dict_structure(tmp_path):
    """Return dict contains all required keys with correct types."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="alpha")

    assert set(result.keys()) == {
        "registry_id",
        "registry_file",
        "project_name",
        "target",
        "created_files",
        "aipass_home",
    }
    assert result["project_name"] == "ALPHA"
    assert result["registry_file"] == "ALPHA_REGISTRY.json"
    assert result["target"] == str(target.resolve())
    assert isinstance(result["created_files"], list)


def test_init_project_registry_id_is_valid_uuid(tmp_path):
    """registry_id must be a valid UUID4 string."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="test")

    parsed = uuid.UUID(result["registry_id"], version=4)
    assert str(parsed) == result["registry_id"]


def test_init_project_registry_json_contents(tmp_path):
    """REGISTRY.json has correct metadata structure and values."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="beta")

    registry_path = target / "BETA_REGISTRY.json"
    data = json.loads(registry_path.read_text(encoding="utf-8"))

    assert data["metadata"]["id"] == result["registry_id"]
    assert data["metadata"]["name"] == "BETA"
    assert data["metadata"]["version"] == "1.0.0"
    assert data["metadata"]["created"] == date.today().isoformat()
    assert data["metadata"]["last_updated"] == date.today().isoformat()
    assert data["metadata"]["total_branches"] == 0
    assert data["branches"] == []


def test_init_project_no_trinity_created(tmp_path):
    """Projects are not citizens — no .trinity/ directory created."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="gamma")

    assert not (target / ".trinity").exists()


def test_init_project_no_local_prompt(tmp_path):
    """Project init does NOT create aipass_local_prompt.md (agent-only file)."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="epsilon")

    assert not (target / ".aipass" / "aipass_local_prompt.md").exists()


def _host(tmp_path: Path, files: dict) -> Path:
    host = tmp_path / "host"
    for rel, text in files.items():
        (host / rel).parent.mkdir(parents=True, exist_ok=True)
        (host / rel).write_text(text, encoding="utf-8")
    return host


_ALL_SOURCES = {
    ".aipass/project_AGENTS.md": "# {name}\ntemplate\n",
    ".aipass/project_CLAUDE.md": "# {name}\nclaude template\n",
    "AGENTS.md": "host agents {name}\n",
    "CLAUDE.md": "host claude\n",
}


def test_init_mints_agents_md_from_the_host_template_and_no_claude_md(tmp_path, monkeypatch):
    host = _host(tmp_path, _ALL_SOURCES)
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(host))
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="zeta")

    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# ZETA\ntemplate\n"
    assert not (target / "CLAUDE.md").exists()


def test_init_mints_the_host_root_agents_md_as_is_when_no_template(tmp_path, monkeypatch):
    sources = {rel: text for rel, text in _ALL_SOURCES.items() if rel != ".aipass/project_AGENTS.md"}
    host = _host(tmp_path, sources)
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(host))
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="zeta")

    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "host agents {name}\n"
    assert not (target / "CLAUDE.md").exists()


def test_init_mints_the_generated_agents_md_when_the_host_has_neither(tmp_path, monkeypatch):
    host = _host(tmp_path, {"CLAUDE.md": "host claude\n"})
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(host))
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="zeta")

    assert (target / "AGENTS.md").read_text(encoding="utf-8") == sc.agents_md("ZETA")
    assert not (target / "CLAUDE.md").exists()


def test_init_project_rerunnable_blocked_by_guard(tmp_path):
    """Running init twice raises RuntimeError due to _guard_init."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="dup")

    with pytest.raises(RuntimeError, match="already an AIPass project"):
        init_project(target, project_name="dup")


def test_init_project_raises_on_empty_name(tmp_path):
    """ValueError when the name is empty after sanitization."""
    target = tmp_path / "proj"
    target.mkdir()

    with pytest.raises(ValueError, match="Cannot derive project name"):
        init_project(target, project_name="!!!")


def test_init_project_agents_md_content(tmp_path):
    """AGENTS.md contains project-specific content from generator."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    content = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "# ALPHA" in content
    assert "AIPass" in content


def test_init_project_gitignore_content(tmp_path):
    """.gitignore contains standard AIPass patterns."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    content = (target / ".gitignore").read_text(encoding="utf-8")
    assert ".trinity/" in content
    assert ".ai_mail.local/" in content
    assert "__pycache__/" in content
    assert "logs/" in content


def test_init_project_claude_settings_content(tmp_path):
    """.claude/settings.json has env and permissions, no hooks."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    settings_path = target / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "hooks" not in data, "Hooks should not be in project settings — provider handles them"
    assert "permissions" in data
    assert "deny" in data["permissions"]


def test_init_project_settings_no_hooks(tmp_path, monkeypatch):
    """.claude/settings.json has no hooks — all hooks fire from provider level."""
    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
        lambda home: home != _expected_aipass_home(),
    )
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    settings_path = target / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))

    assert "hooks" not in data, "Project settings should not contain hooks"
    assert "env" not in data, "AIPASS_HOME is machine-local — belongs in settings.local.json"
    assert "permissions" in data


def test_init_project_readme_md_content(tmp_path):
    """README.md contains getting started guide with project name."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    content = (target / "README.md").read_text(encoding="utf-8")
    assert "# ALPHA" in content
    assert "## Quick Start" in content
    assert "aipass init agent" in content
    assert "src/" in content


def test_init_project_auto_creates_target_dir(tmp_path):
    """Target directory is created (including parents) if it doesn't exist."""
    target = tmp_path / "deep" / "nested" / "proj"
    assert not target.exists()

    result = init_project(target, project_name="nested")

    assert target.is_dir()
    assert result["project_name"] == "NESTED"
    assert len(result["created_files"]) >= 10


def test_init_project_defaults_name_from_directory(tmp_path):
    """When project_name is None, name is derived from the directory name."""
    target = tmp_path / "my_cool_project"
    target.mkdir()

    result = init_project(target)

    assert result["project_name"] == "MY_COOL_PROJECT"
    assert result["registry_file"] == "MY_COOL_PROJECT_REGISTRY.json"
    assert (target / "MY_COOL_PROJECT_REGISTRY.json").exists()


def test_init_project_custom_name_overrides_directory(tmp_path):
    """Explicit project_name takes precedence over the directory name."""
    target = tmp_path / "dir_name"
    target.mkdir()

    result = init_project(target, project_name="custom")

    assert result["project_name"] == "CUSTOM"
    assert result["registry_file"] == "CUSTOM_REGISTRY.json"


def test_init_project_skips_existing_optional_files(tmp_path):
    """Optional files are not overwritten if they already exist.
    Init is re-runnable — existing files are skipped."""
    target = tmp_path / "proj"
    target.mkdir()

    aipass_dir = target / ".aipass"
    aipass_dir.mkdir()
    (target / "CLAUDE.md").write_text("# Custom CLAUDE\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("# Custom AGENTS\n", encoding="utf-8")
    (target / "README.md").write_text("# Custom README\n", encoding="utf-8")
    (target / ".gitignore").write_text("# Custom\n", encoding="utf-8")

    claude_dir = target / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("{}\n", encoding="utf-8")

    src_dir = target / "src"
    src_dir.mkdir()

    result = init_project(target, project_name="eta")

    assert len(result["created_files"]) >= 5

    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "# Custom CLAUDE\n"
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# Custom AGENTS\n"


def test_init_project_no_overwrite(tmp_path):
    """Init guard blocks re-init; update preserves content."""
    target = tmp_path / "proj"
    target.mkdir()

    result1 = init_project(target, project_name="safe")
    assert len(result1["created_files"]) > 0

    with pytest.raises(RuntimeError, match="already an AIPass project"):
        init_project(target, project_name="safe")

    agents_md = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "# SAFE" in agents_md


def test_init_project_returns_dict(tmp_path):
    """init_project return value is a dict."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="rtype")

    # Values pinned: a bare dict check passes on the empty dict a do-nothing init returns.
    assert isinstance(result, dict)
    assert result["created_files"], "init_project reported no created files"
    assert set(result) >= {"created_files", "aipass_home"}


def test_init_project_agents_md_no_trinity(tmp_path):
    """AGENTS.md references .trinity/ as part of startup protocol docs."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="keep")

    content = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "# KEEP" in content
    assert ".trinity/" in content


def test_init_project_returns_aipass_home(tmp_path):
    """init_project return dict includes aipass_home key."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="home")

    assert "aipass_home" in result
    # Expected value derived independently from the installed package location; None is
    # unreachable here, since the suite has already imported aipass.
    assert result["aipass_home"] == _expected_aipass_home()


def test_init_project_settings_has_aipass_home_when_detected(tmp_path, monkeypatch):
    """When AIPASS_HOME is detected, settings.local.json (not settings.json) includes env.AIPASS_HOME.

    Mutant: is_throwaway_path asked about str(target) instead of aipass_home -> red.
    """
    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
        lambda home: home != _expected_aipass_home(),
    )
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="env")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "env" not in settings

    local_settings = json.loads((target / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert local_settings["env"]["AIPASS_HOME"] == result["aipass_home"]


def test_update_project_returns_aipass_home(tmp_path):
    """update_project return dict includes aipass_home key."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="uhome")

    result = update_project(target)

    assert "aipass_home" in result
    assert result["aipass_home"] == _expected_aipass_home()


def test_update_project_adds_aipass_home_if_missing(tmp_path, monkeypatch):
    """update_project recreates settings.local.json with AIPASS_HOME if missing."""
    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
        lambda home: home != _expected_aipass_home(),
    )
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="addenv")

    local_settings_path = target / ".claude" / "settings.local.json"
    local_settings_path.unlink(missing_ok=True)

    result = update_project(target)

    # A floor, not an `if`: a detector returning None must fail, never pass silently.
    assert result["aipass_home"] == _expected_aipass_home()
    new_data = json.loads(local_settings_path.read_text(encoding="utf-8"))
    assert new_data.get("env", {}).get("AIPASS_HOME") == result["aipass_home"]
    assert str(local_settings_path) in result["updated_files"]


def test_global_prompt_md_returns_string():
    """Mutant: global_prompt_md returns a stub string -> red."""
    result = sc.global_prompt_md("TestProject")
    assert result.splitlines()[:3] == ["# TestProject — Project Context", "<!-- Injected every turn via hook. -->", ""]


def test_global_prompt_md_contains_project_name():
    """global_prompt_md() interpolates the project name."""
    result = sc.global_prompt_md("MyApp")
    assert "MyApp" in result


def test_global_prompt_md_contains_registry_reference():
    """global_prompt_md() references the registry with the project name."""
    result = sc.global_prompt_md("Demo")
    assert "Demo_REGISTRY.json" in result


def test_global_prompt_md_contains_aipass_context():
    """global_prompt_md() includes AIPass framework context."""
    result = sc.global_prompt_md("X")
    assert "AIPass" in result
    assert "drone" in result


def test_prep_md_returns_string():
    """Mutant: prep_md returns a stub string -> red."""
    result = sc.prep_md()
    assert result.splitlines()[:2] == ["# Session Wrap-Up", ""]


def test_prep_md_contains_session_wrap_up():
    """prep_md() contains the session wrap-up header."""
    result = sc.prep_md()
    assert "Session Wrap-Up" in result


def test_prep_md_contains_memory_instructions():
    """prep_md() names the memory directory AND the file inside it."""
    result = sc.prep_md()
    assert ".trinity/" in result
    assert "local.json" in result


def test_inbox_json_returns_valid_json():
    """inbox_json() parses, and its key set is exactly the mailbox contract.

    The key set is this unit's claim; the sibling below pins the values.
    """
    result = sc.inbox_json()
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    assert sorted(parsed) == ["mailbox", "messages", "total_messages", "unread_count"]


def test_inbox_json_has_mailbox_structure():
    """inbox_json() contains required mailbox fields."""
    parsed = json.loads(sc.inbox_json())
    assert parsed["mailbox"] == "inbox"
    assert parsed["total_messages"] == 0
    assert parsed["unread_count"] == 0
    assert parsed["messages"] == []


def test_with_source_prepends_header(tmp_path):
    """with_source() prepends a source comment to content."""
    path = tmp_path / "foo" / "bar.md"
    result = sc.with_source("hello world", path)
    assert result.startswith(f"<!-- Source: {path.as_posix()} -->")
    assert "hello world" in result


def test_with_source_preserves_content(tmp_path):
    """with_source() does not alter the original content."""
    original = "line 1\nline 2\nline 3"
    result = sc.with_source(original, tmp_path / "a" / "b.md")
    assert result.endswith(original)


def test_with_source_header_is_first_line(tmp_path):
    """with_source() puts the source header on line 1, content on line 2+."""
    path = tmp_path / "test.md"
    result = sc.with_source("content", path)
    lines = result.split("\n")
    assert lines[0] == f"<!-- Source: {path.as_posix()} -->"
    assert lines[1] == "content"


def test_throwaway_path_detects_tmp(tmp_path):
    """Paths under the system temp dir are throwaway."""
    assert is_throwaway_path(str(tmp_path))


def test_throwaway_path_detects_scratchpad():
    """Paths containing 'scratchpad' are throwaway."""
    assert is_throwaway_path(str(Path.home() / ".claude" / "scratchpad" / "probe_1"))


def test_throwaway_path_allows_normal():
    """Normal home-directory paths are not throwaway."""
    assert not is_throwaway_path(str(Path.home() / "AIPass"))


def test_throwaway_path_allows_project():
    """A typical project path is not throwaway."""
    assert not is_throwaway_path(str(Path.home() / "Projects" / "myapp"))


def test_settings_omits_throwaway_aipass_home(tmp_path, monkeypatch):
    """init_project skips settings.local.json when detected AIPASS_HOME is a throwaway path."""
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(tmp_path))

    target = tmp_path / "proj"
    target.mkdir()
    bootstrap.init_project(target, project_name="alpha")

    assert not (target / ".claude" / "settings.local.json").exists()


# Directory/file-name fragments that .gitignore excludes from git tracking —
# mirrors scaffold_content.gitignore(). Tracked-file scans must skip these.
_GITIGNORED_PARTS = (".trinity", ".ai_mail.local", "logs", ".venv", "venv", ".git")


def test_minted_tracked_files_have_no_absolute_paths(tmp_path, monkeypatch):
    """No file init_project writes into a TRACKED path may contain the machine-local AIPASS_HOME.

    AIPASS_HOME is machine-local and may only land in gitignored *.local.json files.
    """
    fake_home = str(tmp_path / f"fake_aipass_home_{uuid.uuid4().hex}")
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: fake_home)
    monkeypatch.setattr(bootstrap, "is_throwaway_path", lambda home: home != fake_home)

    target = tmp_path / "proj"
    target.mkdir()
    bootstrap.init_project(target, project_name="pathcheck")

    # The scan's size is asserted first: an empty scan would make this guard a silent pass.
    tracked = [
        path
        for path in target.rglob("*")
        if path.is_file()
        and not any(part in _GITIGNORED_PARTS for part in path.relative_to(target).parts)
        and ".local." not in path.name
    ]
    assert len(tracked) >= 9, f"only {len(tracked)} tracked files minted - the scan below proves nothing"
    for path in tracked:
        rel = path.relative_to(target)
        content = path.read_text(encoding="utf-8")
        assert fake_home not in content, f"{rel} leaks machine-local AIPASS_HOME"


def test_init_repoints_a_venv_link_left_dangling_by_a_moved_home(tmp_path, monkeypatch):
    """A .venv symlink to a home that moved is repointed, not a FileExistsError."""
    host = _host(tmp_path, {".venv/pyvenv.cfg": ""})
    monkeypatch.setattr(bootstrap, "_detect_aipass_home", lambda: str(host))
    target = tmp_path / "proj"
    target.mkdir()
    (target / ".venv").symlink_to(tmp_path / "old_home" / ".venv")

    init_project(target, project_name="zeta")

    assert (target / ".venv").resolve() == (host / ".venv").resolve()
