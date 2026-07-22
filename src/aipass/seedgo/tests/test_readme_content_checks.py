"""Tests for readme_check.py — Check 7 (test count accuracy) and Check 8 (markdown link validity)."""

# =================== META ====================
# Name: test_readme_content_checks.py
# Description: Unit tests for readme content accuracy checks
# Version: 1.0.0
# Created: 2026-05-15
# Modified: 2026-05-15
# =============================================

import pytest
from typing import List
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lines(text: str) -> List[str]:
    return text.split("\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for readme_check."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed as real_is_bypassed
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import (
        is_seedgo_ignored as real_is_seedgo_ignored,
        load_ignore_entries as real_load_ignore_entries,
    )

    bypass_pkg = MagicMock()
    bypass_utils = MagicMock()
    bypass_utils.is_bypassed = real_is_bypassed
    bypass_pkg.utils = bypass_utils
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    bypass_ignore.is_seedgo_ignored = real_is_seedgo_ignored
    bypass_ignore.load_ignore_entries = real_load_ignore_entries
    bypass_pkg.ignore_handler = bypass_ignore
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.utils", bypass_utils)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        bypass_ignore,
    )

    monkeypatch.delitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.aipass_standards.readme_check",
        raising=False,
    )


# ===========================================================================
# 7. check_test_count_accuracy
# ===========================================================================


def test_test_count_no_claims():
    """No test count claims in README passes (skipped)."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_test_count_accuracy,
    )
    from pathlib import Path

    lines = _lines("# Branch\n\nSome content without test counts.\n")
    result = check_test_count_accuracy(lines, Path("/nonexistent"), "fake.py")
    assert result["passed"] is True
    assert "skipped" in result["message"].lower()


def test_test_count_no_tests_dir(tmp_path):
    """Test count claim with no tests/ directory passes (skipped)."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_test_count_accuracy,
    )

    lines = _lines("├── tests/    # 50 tests\n")
    result = check_test_count_accuracy(lines, tmp_path, "fake.py")
    assert result["passed"] is True
    assert "skipped" in result["message"].lower()


def test_test_count_accurate(tmp_path):
    """Claimed count within 10% of actual passes."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_test_count_accuracy,
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_one.py").write_text(
        "def test_a(): pass\ndef test_b(): pass\ndef test_c(): pass\n"
        "def test_d(): pass\ndef test_e(): pass\ndef test_f(): pass\n"
        "def test_g(): pass\ndef test_h(): pass\ndef test_i(): pass\n"
        "def test_j(): pass\n",
        encoding="utf-8",
    )

    lines = _lines("├── tests/    # 10 tests\n")
    result = check_test_count_accuracy(lines, tmp_path, "fake.py")
    assert result["passed"] is True
    assert "within 10%" in result["message"]


def test_test_count_drift_over_10_pct(tmp_path):
    """Claimed count drifting >10% from actual fails."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_test_count_accuracy,
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_one.py").write_text(
        "def test_a(): pass\ndef test_b(): pass\ndef test_c(): pass\n"
        "def test_d(): pass\ndef test_e(): pass\ndef test_f(): pass\n"
        "def test_g(): pass\ndef test_h(): pass\ndef test_i(): pass\n"
        "def test_j(): pass\n",
        encoding="utf-8",
    )

    lines = _lines("├── tests/    # 50 tests\n")
    result = check_test_count_accuracy(lines, tmp_path, "fake.py")
    assert result["passed"] is False
    assert "drift" in result["message"].lower()


def test_test_count_claims_zero_actual_nonzero(tmp_path):
    """README claims tests but 0 actual functions found fails."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_test_count_accuracy,
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_empty.py").write_text("# no test functions\n", encoding="utf-8")

    lines = _lines("├── tests/    # 30 tests\n")
    result = check_test_count_accuracy(lines, tmp_path, "fake.py")
    assert result["passed"] is False


def test_test_count_uses_max_claimed(tmp_path):
    """When multiple counts claimed, uses the highest for comparison."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_test_count_accuracy,
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    funcs = "\n".join(f"def test_{i}(): pass" for i in range(100))
    (tests_dir / "test_one.py").write_text(funcs, encoding="utf-8")

    lines = _lines("├── tests/    # 100 tests across 5 files\n│   ├── test_a.py  # 20 tests\n")
    result = check_test_count_accuracy(lines, tmp_path, "fake.py")
    assert result["passed"] is True


def test_test_count_bypassed():
    """Bypassed standard passes immediately."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_test_count_accuracy,
    )
    from pathlib import Path

    bypass_rules = [{"file": "fake.py", "standard": "readme", "reason": "test"}]
    lines = _lines("├── tests/    # 999 tests\n")
    result = check_test_count_accuracy(lines, Path("/tmp"), "fake.py", bypass_rules)
    assert result["passed"] is True


def test_test_count_rglob_nested(tmp_path):
    """Counts test functions in nested test subdirectories."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_test_count_accuracy,
    )

    tests_dir = tmp_path / "tests"
    sub_dir = tests_dir / "subdir"
    sub_dir.mkdir(parents=True)
    (tests_dir / "test_top.py").write_text("def test_a(): pass\n", encoding="utf-8")
    (sub_dir / "test_nested.py").write_text("def test_b(): pass\n", encoding="utf-8")

    lines = _lines("├── tests/    # 2 tests\n")
    result = check_test_count_accuracy(lines, tmp_path, "fake.py")
    assert result["passed"] is True


# ===========================================================================
# _extract_test_counts
# ===========================================================================


def test_extract_test_counts_various_patterns():
    """Extracts counts from various README patterns."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _extract_test_counts,
    )

    content = "├── tests/    # 219 tests (watchdog + feedback)\n**Tests:** 219 tests passing\n"
    counts = _extract_test_counts(content)
    assert 219 in counts
    assert len(counts) == 2


def test_extract_test_counts_singular():
    """Matches singular 'test' as well as plural."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _extract_test_counts,
    )

    counts = _extract_test_counts("1 test passing")
    assert counts == [1]


def test_extract_test_counts_empty():
    """Returns empty list when no patterns match."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _extract_test_counts,
    )

    assert _extract_test_counts("No numbers here.") == []


# ===========================================================================
# _count_test_functions
# ===========================================================================


def test_count_test_functions_basic(tmp_path):
    """Counts def test_ functions across files."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _count_test_functions,
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_a.py").write_text("def test_one(): pass\ndef test_two(): pass\n", encoding="utf-8")
    (tests_dir / "test_b.py").write_text("def test_three(): pass\n", encoding="utf-8")

    assert _count_test_functions(tests_dir) == 3


def test_count_test_functions_skips_non_test_files(tmp_path):
    """Only counts from test_*.py files, not conftest or helpers."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _count_test_functions,
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_real.py").write_text("def test_one(): pass\n", encoding="utf-8")
    (tests_dir / "conftest.py").write_text("def test_fixture(): pass\n", encoding="utf-8")
    (tests_dir / "helpers.py").write_text("def test_helper(): pass\n", encoding="utf-8")

    assert _count_test_functions(tests_dir) == 1


def test_count_test_functions_empty_dir(tmp_path):
    """Empty tests dir returns 0."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _count_test_functions,
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    assert _count_test_functions(tests_dir) == 0


# ===========================================================================
# 8. check_markdown_links
# ===========================================================================


def test_markdown_links_no_links():
    """README with no relative links passes (skipped)."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_markdown_links,
    )
    from pathlib import Path

    lines = _lines("# Branch\n\nNo links here.\n")
    result = check_markdown_links(lines, Path("/tmp"), "fake.py")
    assert result["passed"] is True
    assert "skipped" in result["message"].lower()


def test_markdown_links_external_only():
    """README with only external links passes (skipped)."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_markdown_links,
    )
    from pathlib import Path

    lines = _lines("[Google](https://google.com)\n[Mail](mailto:a@b.com)\n[Section](#heading)\n")
    result = check_markdown_links(lines, Path("/tmp"), "fake.py")
    assert result["passed"] is True
    assert "skipped" in result["message"].lower()


def test_markdown_links_all_valid(tmp_path):
    """All relative links pointing to existing paths pass."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_markdown_links,
    )

    (tmp_path / "STATUS.local.md").write_text("# Status\n", encoding="utf-8")
    trinity_dir = tmp_path / ".trinity"
    trinity_dir.mkdir()

    lines = _lines("[Status](STATUS.local.md)\n[Identity](.trinity/)\n")
    result = check_markdown_links(lines, tmp_path, "fake.py")
    assert result["passed"] is True
    assert "2 relative links verified" in result["message"]


def test_markdown_links_dead_link(tmp_path):
    """Dead relative link fails."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_markdown_links,
    )

    lines = _lines("[Setup](SETUP.md)\n")
    result = check_markdown_links(lines, tmp_path, "fake.py")
    assert result["passed"] is False
    assert "SETUP.md" in result["message"]


def test_markdown_links_mixed_valid_and_dead(tmp_path):
    """Mix of valid and dead links fails, reporting only dead ones."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_markdown_links,
    )

    (tmp_path / "README.md").write_text("# exists\n", encoding="utf-8")

    lines = _lines("[Readme](README.md)\n[Gone](deleted_file.md)\n[Also Gone](utils/)\n")
    result = check_markdown_links(lines, tmp_path, "fake.py")
    assert result["passed"] is False
    assert "deleted_file.md" in result["message"]
    assert "utils/" in result["message"]


def test_markdown_links_parent_path(tmp_path):
    """Parent-relative links (../) are resolved correctly."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_markdown_links,
    )

    parent_file = tmp_path.parent / "parent_readme.md"
    parent_file.write_text("# parent\n", encoding="utf-8")

    lines = _lines("[Back](../parent_readme.md)\n")
    result = check_markdown_links(lines, tmp_path, "fake.py")
    assert result["passed"] is True


def test_markdown_links_bypassed():
    """Bypassed standard passes immediately."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_markdown_links,
    )
    from pathlib import Path

    bypass_rules = [{"file": "fake.py", "standard": "readme", "reason": "test"}]
    lines = _lines("[Dead](nonexistent.md)\n")
    result = check_markdown_links(lines, Path("/tmp"), "fake.py", bypass_rules)
    assert result["passed"] is True


# ===========================================================================
# _extract_relative_links
# ===========================================================================


def test_extract_relative_links_mixed():
    """Extracts only relative links, skipping external."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _extract_relative_links,
    )

    content = "[Ext](https://example.com)\n[Local](docs/setup.md)\n[Anchor](#top)\n[File](README.md)\n"
    links = _extract_relative_links(content)
    assert len(links) == 2
    assert ("Local", "docs/setup.md") in links
    assert ("File", "README.md") in links


def test_extract_relative_links_empty():
    """No links returns empty list."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _extract_relative_links,
    )

    assert _extract_relative_links("No links at all.") == []


def test_extract_relative_links_backtick_text():
    """Links with backtick text are extracted correctly."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _extract_relative_links,
    )

    content = "[`tools/`](tools/)\n"
    links = _extract_relative_links(content)
    assert len(links) == 1
    assert links[0] == ("`tools/`", "tools/")


# ===========================================================================
# Integration: check_module with new checks
# ===========================================================================


def test_check_module_includes_new_checks(tmp_path):
    """check_module result includes test count and link checks."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_module

    branch_root = tmp_path
    apps_dir = branch_root / "apps"
    apps_dir.mkdir()
    entry = apps_dir / "mybranch.py"
    entry.write_text("# entry\n", encoding="utf-8")

    readme = branch_root / "README.md"
    readme.write_text(
        "# MyBranch\n\n"
        "## Architecture\n\n```\nmybranch/\n```\n\n"
        "## Commands\n\n- `drone @mybranch test`\n\n"
        "## Depends On\n\ndrone\n\n"
        "*Last Updated: 2099-01-01*\n",
        encoding="utf-8",
    )

    result = check_module(str(entry))
    check_names = [c["name"] for c in result["checks"]]
    assert "Test count accuracy" in check_names
    assert "Markdown link validity" in check_names
    assert len(result["checks"]) == 8


def test_check_module_missing_readme_has_8_failures(tmp_path):
    """Missing README produces 8 failure checks (1 exists + 7 dependent)."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_module

    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    entry = apps_dir / "mybranch.py"
    entry.write_text("# entry\n", encoding="utf-8")

    result = check_module(str(entry))
    assert len(result["checks"]) == 8
    assert result["score"] == 0


def test_is_runtime_artifact_known_dirs():
    """_is_runtime_artifact recognizes known runtime dirs and suffixes."""
    from pathlib import Path

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _is_runtime_artifact,
    )

    assert _is_runtime_artifact(Path("/any/path/logs")) is True
    assert _is_runtime_artifact(Path("/any/path/artifacts")) is True
    assert _is_runtime_artifact(Path("/any/path/.trinity")) is True
    assert _is_runtime_artifact(Path("/any/path/cli_json")) is True
    assert _is_runtime_artifact(Path("/any/path/seedgo_json")) is True
    assert _is_runtime_artifact(Path("/any/path/STATUS.local.md")) is False
    assert _is_runtime_artifact(Path("/any/path/DASHBOARD.local.json")) is True
    assert _is_runtime_artifact(Path("/any/path/docs.local")) is True
    assert _is_runtime_artifact(Path("/any/path/dropbox")) is True
    assert _is_runtime_artifact(Path("/any/path/system_logs")) is True
    assert _is_runtime_artifact(Path("/any/path/tools")) is True
    assert _is_runtime_artifact(Path("/any/path/backups")) is True
    assert _is_runtime_artifact(Path("/any/path/src")) is False
    assert _is_runtime_artifact(Path("/any/path/apps")) is False
    assert _is_runtime_artifact(Path("/any/path/tests")) is False


def test_module_list_skips_disabled_file(tmp_path):
    """A (disabled) .py in apps/modules/ must not trigger a 'missing module' violation."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_module_list,
    )

    modules_dir = tmp_path / "apps" / "modules"
    modules_dir.mkdir(parents=True)
    (modules_dir / "__init__.py").write_text("", encoding="utf-8")
    (modules_dir / "real_module.py").write_text("# real\n", encoding="utf-8")
    (modules_dir / "old_module(disabled).py").write_text("# disabled\n", encoding="utf-8")

    readme_lines = _lines("# Branch\n\nreal_module is mentioned here.\n")
    result = check_module_list(readme_lines, tmp_path, "fake.py")
    assert result["passed"] is True
    assert "old_module" not in result["message"]


def test_count_test_functions_skips_disabled_file(tmp_path):
    """_count_test_functions must exclude test_*(disabled).py files."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        _count_test_functions,
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_active.py").write_text("def test_one(): pass\ndef test_two(): pass\n", encoding="utf-8")
    (tests_dir / "test_old(disabled).py").write_text(
        "def test_ghost(): pass\ndef test_phantom(): pass\ndef test_zombie(): pass\n",
        encoding="utf-8",
    )

    assert _count_test_functions(tests_dir) == 2


def test_directory_tree_passes_absent_runtime_dir(tmp_path):
    """Parity regression: README tree lists runtime dir (logs), dir absent on
    disk, no git available — tree check passes via _is_runtime_artifact."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_directory_tree,
    )

    branch_root = tmp_path / "mybranch"
    branch_root.mkdir()
    apps_dir = branch_root / "apps"
    apps_dir.mkdir()
    (apps_dir / "modules").mkdir()

    lines = [
        "## Architecture",
        "```",
        "mybranch/",
        "├── apps/",
        "│   └── modules/",
        "├── logs/",
        "├── cli_json/",
        "└── artifacts/",
        "```",
    ]

    result = check_directory_tree(lines, branch_root, str(apps_dir / "entry.py"))
    assert result["passed"] is True
    assert "verified" in result["message"]
