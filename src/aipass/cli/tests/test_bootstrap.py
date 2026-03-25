"""Tests for the CLI init bootstrap handler.

Covers _sanitize_name() and init_project() — all file operations
use tmp_path to stay fully isolated from the live filesystem.
"""

import json
import re
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


def test_init_project_creates_all_six_files(tmp_path):
    """init_project produces exactly the six expected files."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="demo")

    expected_files = [
        target / "DEMO_REGISTRY.json",
        target / ".trinity" / "passport.json",
        target / ".trinity" / "local.json",
        target / ".trinity" / "observations.json",
        target / ".aipass" / "aipass_local_prompt.md",
        target / "AIPASS.md",
    ]
    for f in expected_files:
        assert f.exists(), f"Expected file not created: {f}"

    assert len(result["created_files"]) == 6


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


def test_init_project_passport_json_contents(tmp_path):
    """passport.json has correct identity and citizenship fields."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="gamma")

    passport_path = target / ".trinity" / "passport.json"
    data = json.loads(passport_path.read_text(encoding="utf-8"))

    assert data["document_metadata"]["document_type"] == "project_identity"
    assert data["document_metadata"]["document_name"] == "GAMMA.PASSPORT"
    assert data["document_metadata"]["version"] == "1.0.0"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["document_metadata"]["created"])
    assert data["identity"]["project_name"] == "GAMMA"
    assert data["identity"]["role"] == "project_root"
    assert data["citizenship"]["registered"] is True
    assert data["citizenship"]["registry_id"] == result["registry_id"]
    assert data["citizenship"]["registry_name"] == "GAMMA"


def test_init_project_local_and_observations_are_empty_objects(tmp_path):
    """local.json and observations.json are written as empty JSON objects."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="delta")

    for filename in ("local.json", "observations.json"):
        path = target / ".trinity" / filename
        content = path.read_text(encoding="utf-8")
        assert content == "{}\n"


def test_init_project_local_prompt_content(tmp_path):
    """aipass_local_prompt.md contains the project name heading."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="epsilon")

    prompt_path = target / ".aipass" / "aipass_local_prompt.md"
    content = prompt_path.read_text(encoding="utf-8")
    assert content.startswith("# EPSILON")
    assert "Local Prompt" in content


def test_init_project_aipass_md_content(tmp_path):
    """AIPASS.md contains the standard project prompt boilerplate."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="zeta")

    md_path = target / "AIPASS.md"
    content = md_path.read_text(encoding="utf-8")
    assert "# AIPass" in content
    assert "## Startup" in content
    assert "## Memories" in content
    assert ".trinity/passport.json" in content


def test_init_project_raises_on_existing_passport(tmp_path):
    """FileExistsError when .trinity/passport.json already exists."""
    target = tmp_path / "proj"
    target.mkdir()
    trinity = target / ".trinity"
    trinity.mkdir()
    (trinity / "passport.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Passport already exists"):
        init_project(target, project_name="dup")


def test_init_project_raises_on_existing_registry(tmp_path):
    """FileExistsError when the REGISTRY.json file already exists."""
    target = tmp_path / "proj"
    target.mkdir()
    (target / "DUP_REGISTRY.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Registry already exists"):
        init_project(target, project_name="dup")


def test_init_project_raises_on_empty_name(tmp_path):
    """ValueError when the name is empty after sanitization."""
    target = tmp_path / "proj"
    target.mkdir()

    with pytest.raises(ValueError, match="Cannot derive project name"):
        init_project(target, project_name="!!!")


def test_init_project_auto_creates_target_dir(tmp_path):
    """Target directory is created (including parents) if it doesn't exist."""
    target = tmp_path / "deep" / "nested" / "proj"
    assert not target.exists()

    result = init_project(target, project_name="nested")

    assert target.is_dir()
    assert result["project_name"] == "NESTED"
    assert len(result["created_files"]) == 6


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
    """local.json, observations.json, prompt, and AIPASS.md are not
    overwritten if they already exist (only passport and registry guard
    with errors)."""
    target = tmp_path / "proj"
    target.mkdir()

    # Pre-create the optional files
    trinity = target / ".trinity"
    trinity.mkdir()
    (trinity / "local.json").write_text('{"existing": true}\n', encoding="utf-8")
    (trinity / "observations.json").write_text(
        '{"existing": true}\n', encoding="utf-8"
    )

    aipass_dir = target / ".aipass"
    aipass_dir.mkdir()
    (aipass_dir / "aipass_local_prompt.md").write_text(
        "# Custom prompt\n", encoding="utf-8"
    )

    (target / "AIPASS.md").write_text("# Custom AIPASS\n", encoding="utf-8")

    result = init_project(target, project_name="eta")

    # Only registry and passport should be in created_files
    assert len(result["created_files"]) == 2

    # Verify pre-existing files were NOT overwritten
    local_content = (trinity / "local.json").read_text(encoding="utf-8")
    assert '"existing": true' in local_content

    obs_content = (trinity / "observations.json").read_text(encoding="utf-8")
    assert '"existing": true' in obs_content

    prompt_content = (aipass_dir / "aipass_local_prompt.md").read_text(
        encoding="utf-8"
    )
    assert prompt_content == "# Custom prompt\n"

    md_content = (target / "AIPASS.md").read_text(encoding="utf-8")
    assert md_content == "# Custom AIPASS\n"


def test_init_project_returns_dict(tmp_path):
    """init_project return value is a dict."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="rtype")

    assert isinstance(result, dict)
