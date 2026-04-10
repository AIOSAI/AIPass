"""Tests for the CLI init bootstrap handler.

Covers _sanitize_name() and init_project() — all file operations
use tmp_path to stay fully isolated from the live filesystem.
"""

import json
import uuid
from datetime import date
from pathlib import Path

import pytest

from aipass.cli.apps.handlers.init.bootstrap import _sanitize_name, init_project


# ---------------------------------------------------------------------------
# _sanitize_name tests
# ---------------------------------------------------------------------------


def test_sanitize_name_normal_input():
    """Normal lowercase string is uppercased."""
    assert _sanitize_name("my_project") == "MY_PROJECT"


def test_sanitize_name_preserves_hyphens():
    """Hyphens are kept as-is (valid filename chars)."""
    assert _sanitize_name("my-project") == "MY-PROJECT"


def test_sanitize_name_replaces_special_chars():
    """Non-alphanumeric characters (except _ and -) become underscores."""
    assert _sanitize_name("my project!v2") == "MY_PROJECT_V2"


def test_sanitize_name_replaces_dots_and_slashes():
    """Dots and slashes are replaced with underscores."""
    assert _sanitize_name("foo.bar/baz") == "FOO_BAR_BAZ"


def test_sanitize_name_strips_leading_trailing_underscores():
    """Leading/trailing underscores from replacement are stripped."""
    assert _sanitize_name("...name...") == "NAME"


def test_sanitize_name_spaces_become_underscores():
    """Spaces are not alphanumeric, so they become underscores."""
    assert _sanitize_name("hello world") == "HELLO_WORLD"


def test_sanitize_name_empty_after_sanitize():
    """All-special-character input collapses to empty string."""
    assert _sanitize_name("!!!") == ""


def test_sanitize_name_already_upper():
    """Already-uppercase names pass through unchanged."""
    assert _sanitize_name("ALPHA") == "ALPHA"


def test_sanitize_name_empty_string():
    """Empty input returns empty string."""
    assert _sanitize_name("") == ""


def test_sanitize_name_only_underscores():
    """All-underscore input is stripped to empty string."""
    assert _sanitize_name("___") == ""


# ---------------------------------------------------------------------------
# init_project tests
# ---------------------------------------------------------------------------


def test_init_project_creates_all_expected_files(tmp_path):
    """init_project produces all expected files and directories."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="demo")

    expected_files = [
        target / "DEMO_REGISTRY.json",
        target / ".aipass" / "aipass_global_prompt.md",
        target / "CLAUDE.md",
        target / "AGENTS.md",
        target / "GEMINI.md",
        target / "README.md",
        target / "STATUS.local.md",
        target / ".gitignore",
        target / ".claude" / "settings.json",
    ]
    for f in expected_files:
        assert f.exists(), f"Expected file not created: {f}"

    # hooks/ and src/ are directories, not files
    assert (target / "hooks").is_dir(), "Expected hooks/ directory"
    assert (target / "src").is_dir(), "Expected src/ directory"

    # No .trinity/ should be created (projects are not citizens)
    assert not (target / ".trinity").exists(), ".trinity/ should NOT be created"

    # No local prompt at project level (belongs in agent dirs only)
    assert not (target / ".aipass" / "aipass_local_prompt.md").exists()

    # 9 files + 2 directories = 11 created_files entries
    assert len(result["created_files"]) == 11


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


def test_init_project_claude_md_content(tmp_path):
    """CLAUDE.md contains real AIPass project content."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="zeta")

    md_path = target / "CLAUDE.md"
    content = md_path.read_text(encoding="utf-8")
    assert "# ZETA" in content
    assert "## What is AIPass" in content
    assert "## Getting Started" in content
    assert "## Available Commands" in content
    assert "## Startup Protocol" in content
    # Startup protocol reads registry, not .trinity/
    startup_idx = content.index("## Startup Protocol")
    startup_section = content[startup_idx:]
    assert ".trinity/" not in startup_section
    assert "aipass init agent" in content
    assert "ZETA_REGISTRY.json" in content


def test_init_project_rerunnable_skips_existing_registry(tmp_path):
    """Running init twice skips the existing registry and reuses its ID."""
    target = tmp_path / "proj"
    target.mkdir()

    result1 = init_project(target, project_name="dup")
    result2 = init_project(target, project_name="dup")

    # Same registry ID reused
    assert result1["registry_id"] == result2["registry_id"]
    # Second run creates no new files (all already exist)
    assert len(result2["created_files"]) == 0


def test_init_project_raises_on_empty_name(tmp_path):
    """ValueError when the name is empty after sanitization."""
    target = tmp_path / "proj"
    target.mkdir()

    with pytest.raises(ValueError, match="Cannot derive project name"):
        init_project(target, project_name="!!!")


def test_init_project_agents_md_content(tmp_path):
    """AGENTS.md contains Codex-equivalent content."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    content = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "# ALPHA" in content
    assert "ALPHA_REGISTRY.json" in content
    assert "aipass init agent" in content


def test_init_project_gemini_md_content(tmp_path):
    """GEMINI.md contains Gemini-equivalent content."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    content = (target / "GEMINI.md").read_text(encoding="utf-8")
    assert "# ALPHA" in content
    assert "ALPHA_REGISTRY.json" in content


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
    """.claude/settings.json has valid hook configuration."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    settings_path = target / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "hooks" in data
    assert "UserPromptSubmit" in data["hooks"]


def test_init_project_global_prompt_content(tmp_path):
    """Global prompt contains project name and AIPass terminology."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    content = (target / ".aipass" / "aipass_global_prompt.md").read_text(encoding="utf-8")
    assert "# ALPHA" in content
    assert "ALPHA_REGISTRY.json" in content
    assert "## Commands" in content


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
    assert len(result["created_files"]) == 11


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

    # Pre-create optional files
    aipass_dir = target / ".aipass"
    aipass_dir.mkdir()
    (aipass_dir / "aipass_global_prompt.md").write_text(
        "# Custom global\n", encoding="utf-8"
    )
    (target / "CLAUDE.md").write_text("# Custom CLAUDE\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("# Custom AGENTS\n", encoding="utf-8")
    (target / "GEMINI.md").write_text("# Custom GEMINI\n", encoding="utf-8")
    (target / "README.md").write_text("# Custom README\n", encoding="utf-8")
    (target / "STATUS.local.md").write_text("# Custom status\n", encoding="utf-8")
    (target / ".gitignore").write_text("# Custom\n", encoding="utf-8")

    claude_dir = target / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("{}\n", encoding="utf-8")

    hooks_dir = target / "hooks"
    hooks_dir.mkdir()

    src_dir = target / "src"
    src_dir.mkdir()

    result = init_project(target, project_name="eta")

    # Only registry should be in created_files (everything else pre-existed)
    assert len(result["created_files"]) == 1

    # Verify pre-existing files were NOT overwritten
    md_content = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert md_content == "# Custom CLAUDE\n"


def test_init_project_returns_dict(tmp_path):
    """init_project return value is a dict."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="rtype")

    assert isinstance(result, dict)


def test_init_project_agents_md_no_trinity(tmp_path):
    """AGENTS.md startup protocol references registry, not .trinity/."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="keep")

    content = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert ".trinity/" not in content
    assert "KEEP_REGISTRY.json" in content
