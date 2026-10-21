# =================== AIPass ====================
# Name: test_project_home.py
# Description: Tests for shared/project_home.py — instruction-file ancestor fence helpers
# Version: 1.3.0
# Created: 2026-07-31
# Modified: 2026-10-21
# =============================================

"""Tests for shared/project_home.py and the instruction-file ancestor-fence helpers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports
# seedgo: no-test-needed(covered_elsewhere) — is_throwaway_path, _detect_aipass_home, _claude_settings;
# seedgo: no-test-needed(covered_elsewhere) — _enroll_project; see tests/test_trust.py, tests/test_doctor.py
# seedgo: no-test-needed(covered_elsewhere) — and tests/test_bootstrap.py, which also covers agents_md_seed

import json
import os
import sys
from pathlib import Path

import pytest

from aipass.aipass.shared.project_home import (
    claude_local_settings,
    claude_md_excludes,
    find_fenceless_projects,
    is_projects_child,
    merge_local_settings,
)


def _fence(home: str) -> list[str]:
    return [f"{home}/CLAUDE.md", f"{home}/.claude/CLAUDE.md", f"{home}/AGENTS.md", f"{home}/.claude/AGENTS.md"]


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX mode bits; root reads any directory")
def test_is_projects_child_raises_naming_the_host_it_could_not_read(tmp_path):
    """A host whose listing is denied (mode 0o300: enter, never list) cannot say
    whether the target is its projects/ child. The error names the host, where a
    False sent init and adopt down the not-a-child path with the wrong reason.

    Mutant: the OSError arm returns False again -> red.
    """
    host = tmp_path / "host"
    target = host / "projects" / "child"
    target.mkdir(parents=True)
    host.chmod(0o300)
    try:
        with pytest.raises(RuntimeError, match=str(host)):
            is_projects_child(target)
    finally:
        host.chmod(0o755)


def test_claude_md_excludes_returns_the_host_claude_md_and_agents_md_pairs(tmp_path):
    """Returns the four absolute paths a nested project must fence out.

    The product answers in POSIX form on every platform (settings files carry
    forward slashes), so home is built with as_posix() to match on Windows.
    """
    home = (tmp_path / "AIPass").as_posix()
    excludes = claude_md_excludes(home)
    assert excludes == [
        f"{home}/CLAUDE.md",
        f"{home}/.claude/CLAUDE.md",
        f"{home}/AGENTS.md",
        f"{home}/.claude/AGENTS.md",
    ]


def test_claude_local_settings_default_omits_excludes(tmp_path):
    """nested=False (the default) — no claudeMdExcludes key at all."""
    home = str(tmp_path / "AIPass")
    data = json.loads(claude_local_settings(home))
    assert data == {"env": {"AIPASS_HOME": home}}
    assert "claudeMdExcludes" not in data


def test_claude_local_settings_nested_adds_excludes(tmp_path):
    """nested=True adds claudeMdExcludes alongside env.AIPASS_HOME (POSIX-form home, as the product answers)."""
    home = (tmp_path / "AIPass").as_posix()
    data = json.loads(claude_local_settings(home, nested=True))
    assert data["env"] == {"AIPASS_HOME": home}
    assert data["claudeMdExcludes"] == _fence(home)


def test_merge_local_settings_adds_excludes_to_env_only_existing(tmp_path):
    """Existing file has only env.AIPASS_HOME (pre-fence era) — merge adds the fence (POSIX-form home)."""
    home = (tmp_path / "AIPass").as_posix()
    existing = {"env": {"AIPASS_HOME": home}}
    generated = json.loads(claude_local_settings(home, nested=True))

    merged = merge_local_settings(existing, generated)

    assert merged["env"] == {"AIPASS_HOME": home}
    assert merged["claudeMdExcludes"] == _fence(home)


def test_merge_local_settings_is_idempotent(tmp_path):
    """Merging the already-merged result against the same generated content is a no-op."""
    home = str(tmp_path / "AIPass")
    existing = {"env": {"AIPASS_HOME": home}}
    generated = json.loads(claude_local_settings(home, nested=True))

    once = merge_local_settings(existing, generated)
    twice = merge_local_settings(once, generated)

    assert once == twice


def test_merge_local_settings_preserves_custom_excludes_entries(tmp_path):
    """A user's hand-added claudeMdExcludes entry survives the merge alongside the official ones (POSIX-form home)."""
    home = (tmp_path / "AIPass").as_posix()
    existing = {
        "env": {"AIPASS_HOME": home},
        "claudeMdExcludes": ["/custom/extra/CLAUDE.md"],
    }
    generated = json.loads(claude_local_settings(home, nested=True))

    merged = merge_local_settings(existing, generated)

    assert merged["claudeMdExcludes"] == ["/custom/extra/CLAUDE.md", *_fence(home)]


def test_merge_local_settings_adds_the_agents_md_pair_to_a_claude_md_fence_once(tmp_path):
    """A fence of the CLAUDE.md pair alone gains the AGENTS.md pair; a second merge adds nothing."""
    home = (tmp_path / "AIPass").as_posix()
    existing = {
        "env": {"AIPASS_HOME": home},
        "claudeMdExcludes": [
            f"{home}/CLAUDE.md",
            f"{home}/.claude/CLAUDE.md",
        ],
    }
    generated = json.loads(claude_local_settings(home, nested=True))

    merged = merge_local_settings(existing, generated)
    again = merge_local_settings(merged, generated)

    assert merged["claudeMdExcludes"] == _fence(home)
    assert again["claudeMdExcludes"] == _fence(home)


def test_merge_local_settings_generated_env_wins_on_conflict():
    """A stale env value (e.g. AIPASS_HOME pointed at an old location) is refreshed by generated."""
    existing = {"env": {"AIPASS_HOME": "/old/stale/home"}}
    generated = {"env": {"AIPASS_HOME": "/new/current/home"}}

    merged = merge_local_settings(existing, generated)

    assert merged["env"]["AIPASS_HOME"] == "/new/current/home"


def test_merge_local_settings_unions_extra_env_keys(tmp_path):
    """A user's hand-added env key survives; generated only ever contributes AIPASS_HOME."""
    home = str(tmp_path / "AIPass")
    existing = {"env": {"AIPASS_HOME": home, "SOME_CUSTOM_VAR": "1"}}
    generated = {"env": {"AIPASS_HOME": home}}

    merged = merge_local_settings(existing, generated)

    assert merged["env"] == {"AIPASS_HOME": home, "SOME_CUSTOM_VAR": "1"}


def test_merge_local_settings_preserves_unrelated_top_level_keys(tmp_path):
    """Keys outside env/claudeMdExcludes (e.g. a user's own settings) are never touched."""
    home = str(tmp_path / "AIPass")
    existing = {"env": {"AIPASS_HOME": home}, "somethingElse": {"foo": "bar"}}
    generated = json.loads(claude_local_settings(home, nested=True))

    merged = merge_local_settings(existing, generated)

    assert merged["somethingElse"] == {"foo": "bar"}


def test_merge_local_settings_no_excludes_key_when_neither_side_has_any(tmp_path):
    """Non-nested merge (no claudeMdExcludes on either side) never introduces the key."""
    home = str(tmp_path / "AIPass")
    existing = {"env": {"AIPASS_HOME": home}}
    generated = json.loads(claude_local_settings(home, nested=False))

    merged = merge_local_settings(existing, generated)

    assert "claudeMdExcludes" not in merged


def test_merge_local_settings_empty_existing(tmp_path):
    """An empty existing dict (e.g. unparseable file rebuilt to {}) is filled entirely from generated."""
    home = str(tmp_path / "AIPass")
    generated = json.loads(claude_local_settings(home, nested=True))

    merged = merge_local_settings({}, generated)

    assert merged == generated


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
    """claudeMdExcludes present but missing three of the four expected entries is still fenceless."""
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


def test_find_fenceless_projects_reports_a_project_fenced_against_claude_md_only(tmp_path):
    """The CLAUDE.md pair alone leaves the host AGENTS.md pair inherited, so the project is fenceless."""
    projects = tmp_path / "projects"
    proj = _make_nested(projects, "myapp")
    claude_dir = proj / ".claude"
    claude_dir.mkdir()
    home = tmp_path.as_posix()
    (claude_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "env": {"AIPASS_HOME": home},
                "claudeMdExcludes": [f"{home}/CLAUDE.md", f"{home}/.claude/CLAUDE.md"],
            }
        ),
        encoding="utf-8",
    )
    assert find_fenceless_projects(str(tmp_path)) == [proj]


def test_find_fenceless_projects_correctly_fenced_is_excluded(tmp_path):
    """A project with all four expected claudeMdExcludes entries is not reported."""
    projects = tmp_path / "projects"
    proj = _make_nested(projects, "myapp")
    claude_dir = proj / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "env": {"AIPASS_HOME": str(tmp_path)},
                "claudeMdExcludes": claude_md_excludes(str(tmp_path)),
            }
        ),
        encoding="utf-8",
    )
    assert find_fenceless_projects(str(tmp_path)) == []


def test_find_fenceless_projects_extra_custom_excludes_still_passes(tmp_path):
    """Extra hand-added exclude entries beyond the required four don't make a project fenceless."""
    projects = tmp_path / "projects"
    proj = _make_nested(projects, "myapp")
    claude_dir = proj / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "env": {"AIPASS_HOME": str(tmp_path)},
                "claudeMdExcludes": ["/custom/extra/CLAUDE.md", *claude_md_excludes(str(tmp_path))],
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
        json.dumps({"claudeMdExcludes": claude_md_excludes(str(tmp_path))}), encoding="utf-8"
    )
    unfenced_a = _make_nested(projects, "aaa-unfenced")
    unfenced_b = _make_nested(projects, "bbb-unfenced")
    _make_nested(projects, "not-a-project", registry=False)

    result = find_fenceless_projects(str(tmp_path))

    assert result == [unfenced_a, unfenced_b]
