# =================== AIPass ====================
# Name: test_bootstrap_hooks.py
# Description: Tests for the hooks.json and tier files init and update scaffold into a project
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/init/bootstrap.py: hooks.json, its union merge, and the tier files."""
# The hooks lane of `aipass init` and `aipass init update`, split out of
# test_bootstrap.py on 2026-10-08 (fleet green, oversize_test_file). All file
# operations use tmp_path; the templates are read from the detected AIPASS_HOME.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports

import json
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.init.bootstrap import (
    init_project,
    update_project,
)


# ---------------------------------------------------------------------------
# DPLAN-0190: hooks.json + /memo tests
# ---------------------------------------------------------------------------


def test_init_project_no_memo_md(tmp_path):
    """init_project does NOT create memo.md — it belongs at provider level."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="memo")

    memo_path = target / ".claude" / "commands" / "memo.md"
    assert not memo_path.exists()


def test_init_project_creates_hooks_json(tmp_path):
    """init_project creates .aipass/hooks.json from project_hooks.json template."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="hooks")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    hooks_json = target / ".aipass" / "hooks.json"
    assert hooks_json.exists(), ".aipass/hooks.json should be created"
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    assert data.get("hooks_enabled") is True
    assert "UserPromptSubmit" in data


def test_init_project_hooks_json_matches_template(tmp_path):
    """hooks.json content matches the project_hooks.json template."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="tmpl")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    hooks_json = target / ".aipass" / "hooks.json"
    template = Path(result["aipass_home"]) / ".aipass" / "project_hooks.json"
    if not template.exists():
        pytest.skip("project_hooks.json template not found")

    assert hooks_json.read_bytes() == template.read_bytes()


def test_init_project_hooks_json_in_created_files(tmp_path):
    """hooks.json path appears in created_files list."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="created")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    assert any("hooks.json" in f for f in result["created_files"])


def test_init_project_no_hooks_json_without_aipass_home(tmp_path, monkeypatch):
    """When AIPASS_HOME is not detectable, hooks.json is not created."""
    target = tmp_path / "proj"
    target.mkdir()

    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap._detect_aipass_home",
        lambda: None,
    )

    init_project(target, project_name="nohooks")

    assert not (target / ".aipass" / "hooks.json").exists()


def test_init_project_no_hook_scripts_shipped(tmp_path):
    """No hook scripts are shipped to .claude/hooks/ (engine runs from $AIPASS_HOME)."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="noscripts")

    # THE GUARD BECAME AN EXPRESSION (v5 unentered_assert, 2026-09-08). The
    # `if hooks_dir.exists():` arm had no else, so the case this test is named
    # for - no hooks directory at all - passed having checked nothing, and so
    # did the case where the directory was never created because init crashed
    # earlier. An absent directory ships no scripts, which is the same verdict
    # said out loud.
    hooks_dir = target / ".claude" / "hooks"
    shipped = sorted(f.name for f in hooks_dir.iterdir()) if hooks_dir.exists() else []
    assert shipped == [], f"No hook scripts should be shipped: {shipped}"


def test_init_project_settings_has_no_hook_events(tmp_path):
    """settings.json contains no hooks — provider handles all events."""
    target = tmp_path / "proj"
    target.mkdir()

    init_project(target, project_name="events")

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "hooks" not in settings


def test_update_project_creates_hooks_json_if_missing(tmp_path):
    """update_project creates hooks.json from template when missing."""
    target = tmp_path / "proj"
    target.mkdir()

    registry_data = {
        "metadata": {
            "id": "test-id",
            "name": "MISS",
            "version": "1.0.0",
            "created": "2026-01-01",
            "last_updated": "2026-01-01",
            "total_branches": 0,
        },
        "branches": [],
    }
    (target / "MISS_REGISTRY.json").write_text(json.dumps(registry_data), encoding="utf-8")

    hooks_json = target / ".aipass" / "hooks.json"
    assert not hooks_json.exists()

    result = update_project(target)

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    assert hooks_json.exists()
    assert any("hooks.json" in f for f in result["updated_files"])
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    assert data.get("hooks_enabled") is True


def test_update_project_union_merge_preserves_user_enabled(tmp_path):
    """update preserves user's enabled=false for existing hooks."""
    target = tmp_path / "proj"
    target.mkdir()
    result = init_project(target, project_name="merge")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    hooks_json = target / ".aipass" / "hooks.json"
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    data["PreToolUse"]["git_gate"]["enabled"] = False
    hooks_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    update_project(target)

    updated = json.loads(hooks_json.read_text(encoding="utf-8"))
    assert updated["PreToolUse"]["git_gate"]["enabled"] is False


def _init_hooks_project(tmp_path: Path) -> tuple[Path, dict]:
    """A project made by init_project, and the hooks template update merges from.

    The template is read from disk, never restated, so these pins follow the
    shipped project_hooks.json. Reached through init_project and update_project
    (fleet green leg 7): the merge has no other door, and both write only
    under tmp_path.
    """
    target = tmp_path / "proj"
    target.mkdir()
    result = init_project(target, project_name="merge")
    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")
    template_path = Path(result["aipass_home"]) / ".aipass" / "project_hooks.json"
    return target / ".aipass" / "hooks.json", json.loads(template_path.read_text(encoding="utf-8"))


def test_update_project_union_merge_adds_new_hooks(tmp_path):
    """update adds back an event and a handler the project does not have.

    Mutant: the template loop of _merge_hooks_json adds nothing -> red.
    """
    hooks_json, template = _init_hooks_project(tmp_path)
    events = [key for key in template if key not in ("_comment", "hooks_enabled")]
    gone_event, thinned_event = events[0], events[1]
    gone_handler = next(iter(template[thinned_event]))
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    del data[gone_event]
    del data[thinned_event][gone_handler]
    hooks_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    update_project(target=hooks_json.parent.parent)

    updated = json.loads(hooks_json.read_text(encoding="utf-8"))
    assert updated.get(gone_event) == template[gone_event]
    assert updated.get(thinned_event, {}).get(gone_handler) == template[thinned_event][gone_handler]


def test_update_project_union_merge_preserves_user_hooks(tmp_path):
    """A custom hook the template does not carry is kept beside the template's.

    Mutant: the existing-hooks loop of _merge_hooks_json copies nothing -> red.
    """
    hooks_json, template = _init_hooks_project(tmp_path)
    event = next(key for key in template if key not in ("_comment", "hooks_enabled"))
    custom = {"enabled": True, "handler": "custom.handler", "matcher": ""}
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    data[event]["my_custom_hook"] = custom
    hooks_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    update_project(target=hooks_json.parent.parent)

    updated = json.loads(hooks_json.read_text(encoding="utf-8"))
    assert updated.get(event, {}).get("my_custom_hook") == custom
    assert set(template[event]) <= set(updated[event])


def test_merge_hooks_json_preserves_hooks_enabled_false(tmp_path):
    """The project's hooks_enabled false outlives the template's true.

    Mutant: hooks_enabled read from the template first -> red.
    """
    hooks_json, template = _init_hooks_project(tmp_path)
    assert template["hooks_enabled"] is True  # the pin needs a template that disagrees
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    data["hooks_enabled"] = False
    hooks_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    update_project(target=hooks_json.parent.parent)

    assert json.loads(hooks_json.read_text(encoding="utf-8"))["hooks_enabled"] is False


def test_update_project_hooks_json_already_current(tmp_path):
    """update reports hooks.json as already_current when unchanged."""
    target = tmp_path / "proj"
    target.mkdir()
    result = init_project(target, project_name="curr")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    result = update_project(target)

    assert not any("hooks.json" in f for f in result["updated_files"])
    assert any("hooks.json" in f for f in result["already_current"])


# ---------------------------------------------------------------------------
# Tiered prompt injection tests (FPLAN-0284)
# ---------------------------------------------------------------------------


def test_init_project_creates_tier_files(tmp_path):
    """init_project seeds tier0_kernel.md and tier1_navmap.md when AIPASS_HOME available."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="tiers")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    assert (target / ".aipass" / "tier0_kernel.md").exists()
    assert (target / ".aipass" / "tier1_navmap.md").exists()


def test_init_project_tier_files_match_canonical(tmp_path):
    """Tier files in new project match the canonical source exactly."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="canon")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    for tier_file in ("tier0_kernel.md", "tier1_navmap.md"):
        canonical = Path(result["aipass_home"]) / ".aipass" / tier_file
        if not canonical.exists():
            pytest.skip(f"{tier_file} not found in canonical .aipass/")
        assert (target / ".aipass" / tier_file).read_bytes() == canonical.read_bytes()


def test_init_project_tier_files_in_created_list(tmp_path):
    """Tier files appear in created_files list."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="listed")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    assert any("tier0_kernel.md" in f for f in result["created_files"])
    assert any("tier1_navmap.md" in f for f in result["created_files"])


def test_init_project_no_tier_files_without_aipass_home(tmp_path, monkeypatch):
    """Without AIPASS_HOME, tier files are not created."""
    target = tmp_path / "proj"
    target.mkdir()

    monkeypatch.setattr(
        "aipass.aipass.apps.handlers.init.bootstrap._detect_aipass_home",
        lambda: None,
    )

    init_project(target, project_name="notiers")

    assert not (target / ".aipass" / "tier0_kernel.md").exists()
    assert not (target / ".aipass" / "tier1_navmap.md").exists()


def test_init_project_hooks_json_has_tiers_enabled(tmp_path):
    """hooks.json from template has tier0_kernel and navmap enabled, no global_prompt."""
    target = tmp_path / "proj"
    target.mkdir()

    result = init_project(target, project_name="hookstier")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    hooks_json = target / ".aipass" / "hooks.json"
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    ups = data["UserPromptSubmit"]

    assert ups["tier0_kernel"]["enabled"] is True
    assert ups["navmap"]["enabled"] is True
    assert "global_prompt" not in ups


def test_update_project_adds_tier_files_to_existing(tmp_path):
    """update_project adds tier files to a project that lacks them."""
    target = tmp_path / "proj"
    target.mkdir()

    registry_data = {
        "metadata": {
            "id": "test-id",
            "name": "OLD",
            "version": "1.0.0",
            "created": "2026-01-01",
            "last_updated": "2026-01-01",
            "total_branches": 0,
        },
        "branches": [],
    }
    (target / "OLD_REGISTRY.json").write_text(json.dumps(registry_data), encoding="utf-8")
    (target / ".aipass").mkdir()

    result = update_project(target)

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    assert (target / ".aipass" / "tier0_kernel.md").exists()
    assert (target / ".aipass" / "tier1_navmap.md").exists()
    assert any("tier0_kernel.md" in f for f in result["updated_files"])
    assert any("tier1_navmap.md" in f for f in result["updated_files"])


def test_update_project_tier_files_already_current(tmp_path):
    """update reports tier files as already_current when unchanged."""
    target = tmp_path / "proj"
    target.mkdir()
    result = init_project(target, project_name="tiercurr")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    result = update_project(target)

    assert any("tier0_kernel.md" in f for f in result["already_current"])
    assert any("tier1_navmap.md" in f for f in result["already_current"])


def test_update_project_keeps_an_edited_tier_file(tmp_path):
    """A tier file the project rewrote is kept — this is literally the Vera navmap."""
    target = tmp_path / "proj"
    target.mkdir()
    result = init_project(target, project_name="stale")

    if result["aipass_home"] is None:
        pytest.skip("AIPASS_HOME not detectable in this environment")

    navmap = target / ".aipass" / "tier1_navmap.md"
    navmap.write_text("# The studio's own map\n", encoding="utf-8")

    result = update_project(target)

    assert str(navmap.resolve()) in result["kept_files"]
    assert navmap.read_text(encoding="utf-8") == "# The studio's own map\n"
    assert navmap.with_name("tier1_navmap.md.aipass-new").is_file()
