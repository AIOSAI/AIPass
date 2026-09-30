# =================== META ====================
# Name: test_audit.py
# Description: Unit tests for handlers/audit/
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/audit/audit_display.py, discovery.py and branch_audit.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module in handlers/audit/ parses and imports

import json
from pathlib import Path

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
from aipass.seedgo.apps.handlers.audit import audit_display, branch_audit, discovery


def _branch_summary(capsys, standard: str, **fields) -> list[str]:
    """The lines print_branch_summary writes for one branch scoring *standard* at 50."""
    audit_result = {"branch": {"name": "b"}, "scores": {standard: 50}, "average": 50, "files_checked": 0, **fields}
    capsys.readouterr()
    audit_display.print_branch_summary(audit_result)
    return capsys.readouterr().out.splitlines()


def _failed_branch_check(standard: str) -> dict:
    """A branch-level result for *standard* with one failed check, so its issues heading prints."""
    return {"results": {standard: {"checks": [{"passed": False, "message": "m"}]}}}


def _registry(tmp_path: Path, branches: list[dict], monkeypatch) -> None:
    """Point discovery at a registry under tmp_path holding *branches*, and at no caller registry."""
    reg_file = tmp_path / "TEST_REGISTRY.json"
    reg_file.write_text(json.dumps({"branches": branches}), encoding="utf-8")
    monkeypatch.setattr(discovery, "_find_registry", lambda: reg_file)
    monkeypatch.setattr(discovery, "_find_caller_registries", lambda: [])


# ---------------------------------------------------------------------------
# Tests -- a standard's display name, through print_branch_summary
# ---------------------------------------------------------------------------


def test_format_standard_name_snake_case(capsys):
    """DEEP_NESTING's issues heading reads 'Deep Nesting'.

    Mutant: the heading prints the raw name in apps/handlers/audit/audit_display.py — killed.
    """
    lines = _branch_summary(capsys, "DEEP_NESTING", **_failed_branch_check("DEEP_NESTING"))
    assert "    └─ Deep Nesting issues:" in lines


def test_format_standard_name_lower_snake(capsys):
    """lower_snake reads as title case. Mutant: the underscore kept in apps/handlers/audit/audit_display.py — killed."""
    lines = _branch_summary(capsys, "error_handling", **_failed_branch_check("error_handling"))
    assert "    └─ Error Handling issues:" in lines


def test_format_standard_name_single_word(capsys):
    """A single word is title-cased.

    Mutant: the heading prints the raw name in apps/handlers/audit/audit_display.py — killed.
    """
    lines = _branch_summary(capsys, "naming", **_failed_branch_check("naming"))
    assert "    └─ Naming issues:" in lines


def test_format_standard_name_empty(capsys):
    """An empty name stays empty.

    Mutant: an empty name replaced by a placeholder in apps/handlers/audit/audit_display.py — killed.
    """
    lines = _branch_summary(capsys, "", **_failed_branch_check(""))
    assert "    └─  issues:" in lines


# ---------------------------------------------------------------------------
# Tests -- a standard's violation list, through print_branch_summary
# ---------------------------------------------------------------------------


def test_render_violations_shows_file_paths(capsys):
    """Each violation prints its file and its issues.

    Mutant: the file line dropped in apps/handlers/audit/audit_display.py — killed.
    """
    violations = [
        {"path": "/some/file.py", "score": 60, "issues": ["bad naming"]},
    ]
    lines = _branch_summary(capsys, "naming", naming_violations=violations)
    assert "    ✗ /some/file.py (score: 60%)" in lines
    assert "      • bad naming" in lines


def test_render_violations_truncates_at_five(capsys):
    """At most 5 violations print, then 'and N more'.

    Mutant: six shown in apps/handlers/audit/audit_display.py — killed.
    """
    violations = [{"path": f"/file_{i}.py", "score": 50, "issues": ["issue"]} for i in range(8)]
    lines = _branch_summary(capsys, "test", test_violations=violations)
    printed = "\n".join(lines)
    assert "    ... and 3 more" in lines
    assert [i for i in range(8) if f"/file_{i}.py" in printed] == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Tests -- discovery helpers
# ---------------------------------------------------------------------------


def test_discover_branches_returns_list(tmp_path, monkeypatch):
    """discover_branches returns a list -- of the registry's branches, name-sorted."""
    for name in ("zulu", "alpha"):
        apps_dir = tmp_path / name / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / f"{name}.py").write_text("def main(): pass\n", encoding="utf-8")
    _registry(
        tmp_path,
        [
            {"name": "zulu", "path": str(tmp_path / "zulu")},
            {"name": "alpha", "path": str(tmp_path / "alpha")},
        ],
        monkeypatch,
    )

    result = discovery.discover_branches()
    assert isinstance(result, list)
    # Registry order is zulu-then-alpha; discover_branches sorts by name.
    assert [b["name"] for b in result] == ["alpha", "zulu"]
    assert result[0]["entry_file"] == str(tmp_path / "alpha" / "apps" / "alpha.py")


def test_discover_branches_no_registry_returns_empty(tmp_path, monkeypatch):
    """When no registry file exists, discover_branches returns empty list."""
    monkeypatch.setattr(discovery, "_find_registry", lambda: tmp_path / "missing" / "AIPASS_REGISTRY.json")
    monkeypatch.setattr(discovery, "_find_caller_registries", lambda: [])
    result = discovery.discover_branches()
    assert result == []


# ---------------------------------------------------------------------------
# Tests -- branch_audit.discover_checkers
# ---------------------------------------------------------------------------


def test_discover_checkers_returns_dict(tmp_path):
    """discover_checkers maps checker names to modules.

    Mutant: the check_module/check_branch filter dropped in apps/handlers/audit/branch_audit.py — killed.
    """
    # Empty directory => empty dict
    empty = tmp_path / "empty"
    empty.mkdir()
    result = branch_audit.discover_checkers(empty)
    assert isinstance(result, dict)
    assert len(result) == 0
    # A *_check.py with neither entry point is not a checker; one with check_module is.
    (tmp_path / "notes_check.py").write_text("NOTE = 1\n", encoding="utf-8")
    (tmp_path / "real_check.py").write_text(
        "def check_module(module_path, bypass_rules=None):\n    return {}\n", encoding="utf-8"
    )
    found = branch_audit.discover_checkers(tmp_path)
    assert list(found) == ["real"]
    assert found["real"].__name__ == "real_check"


def test_discover_checkers_finds_check_files(tmp_path):
    """discover_checkers finds *_check.py files with check_module or check_branch."""
    check_file = tmp_path / "example_check.py"
    check_file.write_text(
        'AUDIT_SCOPE = "all_files"\n'
        "def check_module(module_path, bypass_rules=None):\n"
        '    return {"passed": True, "checks": [], "score": 100}\n',
        encoding="utf-8",
    )
    result = branch_audit.discover_checkers(tmp_path)
    assert "example" in result


def test_collect_py_files_empty_branch(tmp_path, monkeypatch):
    """A branch with no apps/ dir audits no files.

    Mutant: the walk rooted at the branch, not apps/, in apps/handlers/audit/branch_audit.py — killed.
    """
    # tmp_path sits under the system temp root, which the corpus drops as throwaway.
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    (tmp_path / "stray.py").write_text("x = 1\n", encoding="utf-8")
    branch = {"name": "tmpb", "path": str(tmp_path), "entry_file": ""}
    result = branch_audit.audit_branch(branch, [], pack_path=tmp_path / "no_pack")
    assert result["files_checked"] == 0


# ---------------------------------------------------------------------------
# Tests -- uppercase registry name resolves to lowercase entry point
# ---------------------------------------------------------------------------


def test_uppercase_registry_name_resolves_to_lowercase_entry(tmp_path, monkeypatch):
    """Branches with uppercase registry names (BACKUP, HOOKS, etc.) must resolve to lowercase filesystem paths
    for entry_file.

    Mutants in apps/handlers/audit/discovery.py, both killed: the entry name not lower-cased;
    discover_branches skips the primary registry.
    """
    # Create a mock registry with uppercase branch name
    branch_dir = tmp_path / "backup"
    branch_dir.mkdir()
    apps_dir = branch_dir / "apps"
    apps_dir.mkdir()
    (apps_dir / "backup.py").write_text("def main(): pass\n", encoding="utf-8")

    _registry(tmp_path, [{"name": "BACKUP", "path": str(branch_dir)}], monkeypatch)

    result = discovery.discover_branches()
    assert len(result) == 1
    assert result[0]["name"] == "BACKUP"
    assert result[0]["entry_file"].endswith("backup.py")
    assert "BACKUP.py" not in result[0]["entry_file"]


def test_uppercase_registry_name_no_entry_when_only_uppercase_file(tmp_path, monkeypatch):
    """A branch with only an UPPERCASE.py entry is not found.

    Mutant: the entry name not lower-cased in apps/handlers/audit/discovery.py — killed.
    """
    branch_dir = tmp_path / "backup"
    branch_dir.mkdir()
    apps_dir = branch_dir / "apps"
    apps_dir.mkdir()
    (apps_dir / "BACKUP.py").write_text("def main(): pass\n", encoding="utf-8")

    _registry(tmp_path, [{"name": "BACKUP", "path": str(branch_dir)}], monkeypatch)

    result = discovery.discover_branches()
    # Case folding is a property of the filesystem, not of the OS name, so ask
    # the directory the test just wrote instead of guessing from platform.
    lowercase_resolves = (apps_dir / "backup.py").exists()

    if lowercase_resolves:
        # Case-insensitive filesystem (default macOS/Windows): BACKUP.py answers
        # to backup.py, so the branch IS found -- under the lowercase entry name.
        assert len(result) == 1
        assert result[0]["entry_file"].endswith("backup.py")
    else:
        # Case-sensitive filesystem (Linux): no lowercase entry file, no branch.
        assert result == []
