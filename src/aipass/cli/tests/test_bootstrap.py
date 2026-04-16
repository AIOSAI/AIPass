"""Tests for the CLI init bootstrap handler.

Covers _sanitize_name() and init_project() — all file operations
use tmp_path to stay fully isolated from the live filesystem.
"""

import json
import uuid
from datetime import date

import pytest

from aipass.cli.apps.handlers.init.bootstrap import _sanitize_name, init_project, update_project


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
        target / ".ai_mail.local" / "inbox.json",
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

    # 10 files + 2 directories = 12 created_files entries
    assert len(result["created_files"]) == 12


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


def test_init_project_settings_has_two_hooks(tmp_path):
    """.claude/settings.json has both global and local prompt hooks."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="alpha")

    settings_path = target / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = data["hooks"]["UserPromptSubmit"]
    assert len(hooks) == 2, f"Expected 2 UserPromptSubmit hooks, got {len(hooks)}"

    # First hook: global prompt
    global_cmd = hooks[0]["hooks"][0]["command"]
    assert "aipass_global_prompt.md" in global_cmd

    # Second hook: local prompt walk-up
    local_cmd = hooks[1]["hooks"][0]["command"]
    assert "aipass_local_prompt.md" in local_cmd
    assert "python3" in local_cmd, "Local prompt hook should use python3 for cross-platform support"
    assert "parents" in local_cmd, "Local prompt hook should use pathlib.Path.parents for traversal"


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
    assert len(result["created_files"]) == 12


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
    (aipass_dir / "aipass_global_prompt.md").write_text("# Custom global\n", encoding="utf-8")
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

    mail_dir = target / ".ai_mail.local"
    mail_dir.mkdir()
    (mail_dir / "inbox.json").write_text("{}\n", encoding="utf-8")

    result = init_project(target, project_name="eta")

    # Only registry should be in created_files (everything else pre-existed)
    assert len(result["created_files"]) == 1

    # Verify pre-existing files were NOT overwritten
    md_content = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert md_content == "# Custom CLAUDE\n"


def test_init_project_no_overwrite(tmp_path):
    """Init does not overwrite existing files — re-runnable safety."""
    target = tmp_path / "proj"
    target.mkdir()

    # First run creates files
    result1 = init_project(target, project_name="safe")
    assert len(result1["created_files"]) > 0

    # Second run creates nothing — all files skipped
    result2 = init_project(target, project_name="safe")
    assert len(result2["created_files"]) == 0

    # Content from first run is preserved
    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "SAFE" in claude_md


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


# ---------------------------------------------------------------------------
# update_project tests
# ---------------------------------------------------------------------------


def test_update_project_raises_if_no_registry(tmp_path):
    """ValueError when target has no *_REGISTRY.json (not an AIPass project)."""
    target = tmp_path / "bare"
    target.mkdir()

    with pytest.raises(ValueError, match="No AIPass project found"):
        update_project(target)


def test_update_project_return_dict_structure(tmp_path):
    """Return dict contains all required keys."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="upd")

    result = update_project(target)

    assert set(result.keys()) == {
        "project_name",
        "target",
        "updated_files",
        "already_current",
        "skipped_files",
        "aipass_home",
    }
    assert result["project_name"] == "UPD"
    assert result["target"] == str(target.resolve())
    assert isinstance(result["updated_files"], list)
    assert isinstance(result["already_current"], list)
    assert isinstance(result["skipped_files"], list)


def test_update_project_already_current_after_init(tmp_path):
    """Running update immediately after init reports all managed files as already current."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="fresh")

    result = update_project(target)

    assert len(result["updated_files"]) == 0
    assert len(result["already_current"]) == 5


def test_update_project_idempotent(tmp_path):
    """Running update twice in a row produces no changes on second run."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="idem")

    result1 = update_project(target)
    result2 = update_project(target)

    # Both runs should be identical
    assert result1["updated_files"] == result2["updated_files"]
    assert result1["already_current"] == result2["already_current"]


def test_update_project_updates_modified_managed_file(tmp_path):
    """A managed file with altered content is re-written on update."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="mod")

    # Corrupt a managed file
    claude_md = target / "CLAUDE.md"
    claude_md.write_text("# Corrupted\n", encoding="utf-8")

    result = update_project(target)

    # CLAUDE.md must appear in updated, not already_current
    assert str(claude_md.resolve()) in result["updated_files"]
    assert str(claude_md.resolve()) not in result["already_current"]

    # Content is restored
    restored = claude_md.read_text(encoding="utf-8")
    assert "MOD" in restored
    assert "## What is AIPass" in restored


def test_update_project_never_touches_user_owned_files(tmp_path):
    """Registry, README, STATUS, .gitignore are always in skipped_files."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="skip")

    # Modify user-owned files
    (target / "README.md").write_text("# My custom README\n", encoding="utf-8")
    (target / "STATUS.local.md").write_text("# Custom status\n", encoding="utf-8")
    (target / ".gitignore").write_text("# custom\n", encoding="utf-8")

    result = update_project(target)

    skipped = result["skipped_files"]
    assert any("REGISTRY" in s for s in skipped)
    assert any("README.md" in s for s in skipped)
    assert any("STATUS.local.md" in s for s in skipped)
    assert any(".gitignore" in s for s in skipped)

    # User customisations are preserved
    assert (target / "README.md").read_text(encoding="utf-8") == "# My custom README\n"
    assert (target / "STATUS.local.md").read_text(encoding="utf-8") == "# Custom status\n"


def test_update_project_creates_missing_managed_dirs(tmp_path):
    """update_project recreates .aipass/ and .claude/ if they were deleted."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="recover")

    # Delete only the managed subdirectories (not root files like CLAUDE.md)
    import shutil

    shutil.rmtree(target / ".aipass")
    shutil.rmtree(target / ".claude")

    result = update_project(target)

    assert (target / ".aipass" / "aipass_global_prompt.md").exists()
    assert (target / ".claude" / "settings.json").exists()
    # The 2 files inside deleted dirs are re-written; root files still match
    assert len(result["updated_files"]) == 2
    assert len(result["already_current"]) == 3


def test_update_project_skipped_files_count(tmp_path):
    """update_project skips 4 user-owned files + existing mailbox = 5 total."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="count")

    result = update_project(target)

    # 4 user-owned (registry, README, STATUS, .gitignore) + inbox.json = 5
    assert len(result["skipped_files"]) == 5


# ---------------------------------------------------------------------------
# DPLAN-0121: AIPASS_HOME + mailbox tests
# ---------------------------------------------------------------------------


def test_init_project_creates_mailbox(tmp_path):
    """init_project creates .ai_mail.local/inbox.json."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="mail")

    assert (target / ".ai_mail.local" / "inbox.json").exists()


def test_init_project_mailbox_json_contents(tmp_path):
    """inbox.json has valid empty mailbox structure."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="mail")

    data = json.loads((target / ".ai_mail.local" / "inbox.json").read_text(encoding="utf-8"))
    assert data["mailbox"] == "inbox"
    assert data["total_messages"] == 0
    assert data["unread_count"] == 0
    assert data["messages"] == []


def test_init_project_mailbox_not_overwritten_on_rerun(tmp_path):
    """Re-running init skips existing inbox.json."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="mail")

    inbox = target / ".ai_mail.local" / "inbox.json"
    inbox.write_text('{"custom": true}\n', encoding="utf-8")

    init_project(target, project_name="mail")

    assert json.loads(inbox.read_text(encoding="utf-8")) == {"custom": True}


def test_init_project_returns_aipass_home(tmp_path):
    """init_project return dict includes aipass_home key."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="home")

    assert "aipass_home" in result
    assert result["aipass_home"] is None or isinstance(result["aipass_home"], str)


def test_init_project_settings_has_aipass_home_when_detected(tmp_path):
    """When AIPASS_HOME is detected, settings.json includes env.AIPASS_HOME."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="env")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "env" in settings
    assert settings["env"]["AIPASS_HOME"] == result["aipass_home"]


def test_update_project_creates_mailbox_if_missing(tmp_path):
    """update_project creates inbox.json if it does not exist."""
    import shutil

    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="newmail")

    # Remove the entire mailbox directory to simulate missing mailbox
    shutil.rmtree(target / ".ai_mail.local")

    result = update_project(target)

    inbox = target / ".ai_mail.local" / "inbox.json"
    assert inbox.exists()
    assert str(inbox) in result["updated_files"]


def test_update_project_skips_existing_mailbox(tmp_path):
    """update_project never overwrites an existing inbox.json."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="keepmail")

    inbox = target / ".ai_mail.local" / "inbox.json"
    inbox.write_text(
        '{"mailbox":"inbox","total_messages":5,"unread_count":2,"messages":["x"]}\n',
        encoding="utf-8",
    )

    result = update_project(target)

    assert str(inbox) in result["skipped_files"]
    assert json.loads(inbox.read_text(encoding="utf-8"))["total_messages"] == 5


def test_update_project_returns_aipass_home(tmp_path):
    """update_project return dict includes aipass_home key."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="uhome")

    result = update_project(target)

    assert "aipass_home" in result
    assert result["aipass_home"] is None or isinstance(result["aipass_home"], str)


def test_update_project_adds_aipass_home_if_missing(tmp_path):
    """update_project injects AIPASS_HOME into settings.json if env section is absent."""
    target = tmp_path / "proj"
    target.mkdir()
    init_project(target, project_name="addenv")

    settings_path = target / ".claude" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    data.pop("env", None)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    result = update_project(target)

    if result["aipass_home"] is not None:
        new_data = json.loads(settings_path.read_text(encoding="utf-8"))
        assert new_data.get("env", {}).get("AIPASS_HOME") == result["aipass_home"]
        assert str(settings_path) in result["updated_files"]
