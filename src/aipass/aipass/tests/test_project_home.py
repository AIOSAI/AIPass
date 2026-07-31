# =================== AIPass ====================
# Name: test_project_home.py
# Description: Tests for shared/project_home.py — CLAUDE.md ancestor fence helpers
# Version: 1.0.0
# Created: 2026-07-31
# Modified: 2026-07-31
# =============================================

"""Tests for the CLAUDE.md ancestor-fence helpers in shared/project_home.py.

Covers _claude_md_excludes(), _claude_local_settings(nested=...),
_merge_local_settings() (retrofit-safe union merge — the critical
idempotency function, exercised directly here rather than only through
callers), and find_fenceless_projects() (doctor's nested-project scan).

All file operations use tmp_path to stay fully isolated from the live
filesystem.
"""

import json
from pathlib import Path

from aipass.aipass.shared.project_home import (
    _claude_local_settings,
    _claude_md_excludes,
    _merge_local_settings,
    find_fenceless_projects,
)


# ---------------------------------------------------------------------------
# _claude_md_excludes
# ---------------------------------------------------------------------------


def test_claude_md_excludes_returns_host_and_dot_claude_paths():
    """Returns the two absolute paths a nested project must fence out."""
    excludes = _claude_md_excludes("/home/x/AIPass")
    assert excludes == [
        "/home/x/AIPass/CLAUDE.md",
        "/home/x/AIPass/.claude/CLAUDE.md",
    ]


# ---------------------------------------------------------------------------
# _claude_local_settings
# ---------------------------------------------------------------------------


def test_claude_local_settings_default_omits_excludes():
    """nested=False (the default) — no claudeMdExcludes key at all."""
    data = json.loads(_claude_local_settings("/home/x/AIPass"))
    assert data == {"env": {"AIPASS_HOME": "/home/x/AIPass"}}
    assert "claudeMdExcludes" not in data


def test_claude_local_settings_nested_adds_excludes():
    """nested=True adds claudeMdExcludes alongside env.AIPASS_HOME."""
    data = json.loads(_claude_local_settings("/home/x/AIPass", nested=True))
    assert data["env"] == {"AIPASS_HOME": "/home/x/AIPass"}
    assert data["claudeMdExcludes"] == [
        "/home/x/AIPass/CLAUDE.md",
        "/home/x/AIPass/.claude/CLAUDE.md",
    ]


# ---------------------------------------------------------------------------
# _merge_local_settings — retrofit-safe union merge
# ---------------------------------------------------------------------------


def test_merge_local_settings_adds_excludes_to_env_only_existing():
    """Existing file has only env.AIPASS_HOME (pre-fence era) — merge adds the fence."""
    existing = {"env": {"AIPASS_HOME": "/home/x/AIPass"}}
    generated = json.loads(_claude_local_settings("/home/x/AIPass", nested=True))

    merged = _merge_local_settings(existing, generated)

    assert merged["env"] == {"AIPASS_HOME": "/home/x/AIPass"}
    assert merged["claudeMdExcludes"] == [
        "/home/x/AIPass/CLAUDE.md",
        "/home/x/AIPass/.claude/CLAUDE.md",
    ]


def test_merge_local_settings_is_idempotent():
    """Merging the already-merged result against the same generated content is a no-op."""
    existing = {"env": {"AIPASS_HOME": "/home/x/AIPass"}}
    generated = json.loads(_claude_local_settings("/home/x/AIPass", nested=True))

    once = _merge_local_settings(existing, generated)
    twice = _merge_local_settings(once, generated)

    assert once == twice


def test_merge_local_settings_preserves_custom_excludes_entries():
    """A user's hand-added claudeMdExcludes entry survives the merge alongside the official ones."""
    existing = {
        "env": {"AIPASS_HOME": "/home/x/AIPass"},
        "claudeMdExcludes": ["/custom/extra/CLAUDE.md"],
    }
    generated = json.loads(_claude_local_settings("/home/x/AIPass", nested=True))

    merged = _merge_local_settings(existing, generated)

    assert merged["claudeMdExcludes"] == [
        "/custom/extra/CLAUDE.md",
        "/home/x/AIPass/CLAUDE.md",
        "/home/x/AIPass/.claude/CLAUDE.md",
    ]


def test_merge_local_settings_does_not_duplicate_existing_official_entries():
    """Re-running the merge when the official entries are already present adds nothing twice."""
    existing = {
        "env": {"AIPASS_HOME": "/home/x/AIPass"},
        "claudeMdExcludes": [
            "/home/x/AIPass/CLAUDE.md",
            "/home/x/AIPass/.claude/CLAUDE.md",
        ],
    }
    generated = json.loads(_claude_local_settings("/home/x/AIPass", nested=True))

    merged = _merge_local_settings(existing, generated)

    assert merged["claudeMdExcludes"] == [
        "/home/x/AIPass/CLAUDE.md",
        "/home/x/AIPass/.claude/CLAUDE.md",
    ]


def test_merge_local_settings_generated_env_wins_on_conflict():
    """A stale env value (e.g. AIPASS_HOME pointed at an old location) is refreshed by generated."""
    existing = {"env": {"AIPASS_HOME": "/old/stale/home"}}
    generated = {"env": {"AIPASS_HOME": "/new/current/home"}}

    merged = _merge_local_settings(existing, generated)

    assert merged["env"]["AIPASS_HOME"] == "/new/current/home"


def test_merge_local_settings_unions_extra_env_keys():
    """A user's hand-added env key survives; generated only ever contributes AIPASS_HOME."""
    existing = {"env": {"AIPASS_HOME": "/home/x/AIPass", "SOME_CUSTOM_VAR": "1"}}
    generated = {"env": {"AIPASS_HOME": "/home/x/AIPass"}}

    merged = _merge_local_settings(existing, generated)

    assert merged["env"] == {"AIPASS_HOME": "/home/x/AIPass", "SOME_CUSTOM_VAR": "1"}


def test_merge_local_settings_preserves_unrelated_top_level_keys():
    """Keys outside env/claudeMdExcludes (e.g. a user's own settings) are never touched."""
    existing = {"env": {"AIPASS_HOME": "/home/x/AIPass"}, "somethingElse": {"foo": "bar"}}
    generated = json.loads(_claude_local_settings("/home/x/AIPass", nested=True))

    merged = _merge_local_settings(existing, generated)

    assert merged["somethingElse"] == {"foo": "bar"}


def test_merge_local_settings_no_excludes_key_when_neither_side_has_any():
    """Non-nested merge (no claudeMdExcludes on either side) never introduces the key."""
    existing = {"env": {"AIPASS_HOME": "/home/x/AIPass"}}
    generated = json.loads(_claude_local_settings("/home/x/AIPass", nested=False))

    merged = _merge_local_settings(existing, generated)

    assert "claudeMdExcludes" not in merged


def test_merge_local_settings_empty_existing():
    """An empty existing dict (e.g. unparseable file rebuilt to {}) is filled entirely from generated."""
    generated = json.loads(_claude_local_settings("/home/x/AIPass", nested=True))

    merged = _merge_local_settings({}, generated)

    assert merged == generated


# ---------------------------------------------------------------------------
# find_fenceless_projects
# ---------------------------------------------------------------------------


def _make_nested(projects_dir: Path, name: str, registry: bool = True) -> Path:
    proj = projects_dir / name
    proj.mkdir(parents=True)
    if registry:
        (proj / f"{name.upper()}_REGISTRY.json").write_text("{}", encoding="utf-8")
    return proj


def test_find_fenceless_projects_no_projects_dir(tmp_path):
    """Returns [] when <home>/projects doesn't even exist."""
    assert find_fenceless_projects(str(tmp_path)) == []


def test_find_fenceless_projects_ignores_non_project_dirs(tmp_path):
    """A directory under projects/ without a *_REGISTRY.json is not a nested project."""
    projects = tmp_path / "projects"
    _make_nested(projects, "not-a-project", registry=False)
    assert find_fenceless_projects(str(tmp_path)) == []


def test_find_fenceless_projects_ignores_stray_files(tmp_path):
    """A stray file directly under projects/ (not a directory) is skipped without error."""
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "README.md").write_text("not a project", encoding="utf-8")
    assert find_fenceless_projects(str(tmp_path)) == []


def test_find_fenceless_projects_missing_settings_local(tmp_path):
    """Nested project with no .claude/settings.local.json at all is fenceless."""
    projects = tmp_path / "projects"
    proj = _make_nested(projects, "myapp")
    assert find_fenceless_projects(str(tmp_path)) == [proj]


def test_find_fenceless_projects_unparseable_settings_local(tmp_path):
    """Nested project whose settings.local.json is corrupt JSON is fenceless."""
    projects = tmp_path / "projects"
    proj = _make_nested(projects, "myapp")
    claude_dir = proj / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text("not json{{{", encoding="utf-8")
    assert find_fenceless_projects(str(tmp_path)) == [proj]


def test_find_fenceless_projects_missing_excludes_key(tmp_path):
    """Nested project with settings.local.json but no claudeMdExcludes key is fenceless."""
    projects = tmp_path / "projects"
    proj = _make_nested(projects, "myapp")
    claude_dir = proj / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(
        json.dumps({"env": {"AIPASS_HOME": str(tmp_path)}}), encoding="utf-8"
    )
    assert find_fenceless_projects(str(tmp_path)) == [proj]


def test_find_fenceless_projects_partial_excludes(tmp_path):
    """claudeMdExcludes present but missing one of the two expected entries is still fenceless."""
    projects = tmp_path / "projects"
    proj = _make_nested(projects, "myapp")
    claude_dir = proj / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "env": {"AIPASS_HOME": str(tmp_path)},
                "claudeMdExcludes": [str(tmp_path / "CLAUDE.md")],
            }
        ),
        encoding="utf-8",
    )
    assert find_fenceless_projects(str(tmp_path)) == [proj]


def test_find_fenceless_projects_correctly_fenced_is_excluded(tmp_path):
    """A project with both expected claudeMdExcludes entries is not reported."""
    projects = tmp_path / "projects"
    proj = _make_nested(projects, "myapp")
    claude_dir = proj / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "env": {"AIPASS_HOME": str(tmp_path)},
                "claudeMdExcludes": _claude_md_excludes(str(tmp_path)),
            }
        ),
        encoding="utf-8",
    )
    assert find_fenceless_projects(str(tmp_path)) == []


def test_find_fenceless_projects_extra_custom_excludes_still_passes(tmp_path):
    """Extra hand-added exclude entries beyond the required two don't make a project fenceless."""
    projects = tmp_path / "projects"
    proj = _make_nested(projects, "myapp")
    claude_dir = proj / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "env": {"AIPASS_HOME": str(tmp_path)},
                "claudeMdExcludes": ["/custom/extra/CLAUDE.md", *_claude_md_excludes(str(tmp_path))],
            }
        ),
        encoding="utf-8",
    )
    assert find_fenceless_projects(str(tmp_path)) == []


def test_find_fenceless_projects_mixed_results_sorted_by_name(tmp_path):
    """Multiple nested projects — only the fenceless ones are returned, in sorted order."""
    projects = tmp_path / "projects"
    fenced = _make_nested(projects, "zzz-fenced")
    claude_dir = fenced / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(
        json.dumps({"claudeMdExcludes": _claude_md_excludes(str(tmp_path))}), encoding="utf-8"
    )
    unfenced_a = _make_nested(projects, "aaa-unfenced")
    unfenced_b = _make_nested(projects, "bbb-unfenced")
    _make_nested(projects, "not-a-project", registry=False)

    result = find_fenceless_projects(str(tmp_path))

    assert result == [unfenced_a, unfenced_b]
