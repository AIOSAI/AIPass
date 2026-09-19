"""Tests for readme_check.py — Check 7 (test count accuracy), Check 8 (markdown link
validity) and the advisory docs-index / rot-bait lane (check_branch_info) — and for
docs_page_check.py, the docs/*.md page shape one layer down (DPLAN-0351)."""

# =================== META ====================
# Name: test_readme_content_checks.py
# Description: Unit tests for readme content accuracy checks and the docs page standard
# Version: 1.2.0
# Created: 2026-05-15
# Modified: 2026-09-19
# =============================================

import pytest
from pathlib import Path
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


# ===========================================================================
# Advisory lane: docs index, named paths, rot bait (check_branch_info)
# ===========================================================================


def _advisory_branch(tmp_path, readme_text: str, docs: dict | None = None, name: str = "mybranch"):
    """A branch root with an entry point, a README and optional docs/*.md."""
    branch_root = tmp_path / name
    apps_dir = branch_root / "apps"
    apps_dir.mkdir(parents=True)
    (apps_dir / f"{name}.py").write_text("# entry\n", encoding="utf-8")
    (branch_root / "README.md").write_text(readme_text, encoding="utf-8")
    for doc_name, body in (docs or {}).items():
        docs_dir = branch_root / "docs"
        docs_dir.mkdir(exist_ok=True)
        (docs_dir / doc_name).write_text(body, encoding="utf-8")
    return branch_root


_PLAIN_README = (
    "# MYBRANCH\n\nA face for strangers.\n\n"
    "## Quick Start\n\n## What It Does\n\n## Live Inventory\n\n## How To Reach Me\n\n"
    "## Commands\n\n## Architecture\n\n## Documentation\n\n## Integration Points\n\n"
    "*Last Updated: 2099-01-01*\n"
)


def test_docs_index_reports_unlinked_doc(tmp_path):
    """A docs/*.md the README never names is reported, by name."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    branch_root = _advisory_branch(tmp_path, _PLAIN_README, docs={"audit.md": "# Audit\n"})

    lines = [line for line in check_branch_info(str(branch_root)) if "docs index" in line]
    assert len(lines) == 1
    assert "not linked" in lines[0]
    assert "docs/audit.md" in lines[0]
    assert "advisory" in lines[0]


def test_docs_index_linked_doc_not_reported(tmp_path):
    """A docs/*.md reached by a relative link is not reported as unlinked."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\nDepth: [audit](docs/audit.md)\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme, docs={"audit.md": "# Audit\n"})

    lines = [line for line in check_branch_info(str(branch_root)) if "docs index" in line]
    assert lines == ["readme docs index (advisory): all 1 docs/*.md linked from README"]


def test_docs_index_link_is_resolved_not_string_matched(tmp_path):
    """A link that reaches the file by a path the README never spells out
    ("docs/./audit.md") still indexes it: link targets are RESOLVED against the
    branch root, not string-matched against the text. Without resolution the
    lane would only ever see paths written the one canonical way."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\nDepth: [audit](docs/./audit.md)\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme, docs={"audit.md": "# Audit\n"})
    assert "docs/audit.md" not in readme

    lines = [line for line in check_branch_info(str(branch_root)) if "docs index" in line]
    assert lines == ["readme docs index (advisory): all 1 docs/*.md linked from README"]


def test_docs_index_plain_path_mention_counts_as_linked(tmp_path):
    """The literal path docs/<name> indexes the file even without link syntax."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\nDepth lives in `docs/audit.md`.\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme, docs={"audit.md": "# Audit\n"})

    lines = [line for line in check_branch_info(str(branch_root)) if "docs index" in line]
    assert "not linked" not in lines[0]


def test_docs_index_dir_link_covers_docs_readme(tmp_path):
    """A link to docs/ indexes docs/README.md — that is how a directory index renders."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\nDepth: [docs](docs/)\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme, docs={"README.md": "# Docs\n"})

    lines = [line for line in check_branch_info(str(branch_root)) if "docs index" in line]
    assert "not linked" not in lines[0]


def test_docs_index_absent_docs_dir_is_silence(tmp_path):
    """No docs/ directory reports NOTHING — silence, not a finding."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    branch_root = _advisory_branch(tmp_path, _PLAIN_README)

    assert check_branch_info(str(branch_root)) == []


def test_docs_index_empty_docs_dir_is_silence(tmp_path):
    """A docs/ directory with no *.md in it reports nothing either."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    branch_root = _advisory_branch(tmp_path, _PLAIN_README)
    (branch_root / "docs").mkdir()

    assert check_branch_info(str(branch_root)) == []


def test_missing_readme_is_silence(tmp_path):
    """No README at all: the advisory lane says nothing (check 1 owns that)."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    branch_root = _advisory_branch(tmp_path, _PLAIN_README, docs={"audit.md": "# Audit\n"})
    (branch_root / "README.md").unlink()

    assert check_branch_info(str(branch_root)) == []


def test_broken_readme_link_reported_by_scored_check_only(tmp_path):
    """A dead relative link is reported — by check 8, and NOT duplicated in the
    advisory lane. The target is branch-rooted on purpose: the advisory lane
    would pick it up if it stopped skipping link targets, and then one dead
    link would be told twice."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_branch_info,
        check_markdown_links,
    )

    readme = "# MyBranch\n\nThe gate: [gate](apps/handlers/gone.py)\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme)

    scored = check_markdown_links(_lines(readme), branch_root, str(branch_root / "apps" / "mybranch.py"))
    assert scored["passed"] is False
    assert "apps/handlers/gone.py" in scored["message"]

    assert not [line for line in check_branch_info(str(branch_root)) if "apps/handlers/gone.py" in line]


def test_named_path_absent_is_reported(tmp_path):
    """A branch-rooted path the README names but that is not there is reported."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\nThe gate is `apps/handlers/gone.py`.\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme)

    lines = [line for line in check_branch_info(str(branch_root)) if "readme paths" in line]
    assert len(lines) == 1
    assert "apps/handlers/gone.py" in lines[0]


def test_named_path_present_is_silent(tmp_path):
    """A named path that exists produces no line."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\nThe entry is `apps/mybranch.py`.\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme)

    assert not [line for line in check_branch_info(str(branch_root)) if "readme paths" in line]


def test_named_path_outside_branch_root_ignored(tmp_path):
    """A path rooted somewhere else (a neighbour branch, an illustration) is out
    of scope: this audit reads ONE branch and cannot tell stale from foreign."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\nSee `lifecycle/auto_fix.py` and `/path/to/registry.json`.\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme)

    assert not [line for line in check_branch_info(str(branch_root)) if "readme paths" in line]


def test_rot_bait_stale_count_reported(tmp_path):
    """A count claim in the README is rot bait, quoted back with its noun."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\nThis branch ships 46 standards today.\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme)

    lines = [line for line in check_branch_info(str(branch_root)) if "count claim" in line]
    assert len(lines) == 1
    assert "46 standards" in lines[0]


def test_rot_bait_dated_status_heading_reported(tmp_path):
    """A dated heading and a Status heading are both snapshots."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\n## Status (2026-09-07)\n\nGreen.\n\n## Latest Audit\n\n100.\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme)

    lines = [line for line in check_branch_info(str(branch_root)) if "dated/status" in line]
    assert len(lines) == 1
    assert "2 dated/status heading(s)" in lines[0]
    assert "## Status (2026-09-07)" in lines[0]


def test_rot_bait_last_updated_is_never_rot_bait(tmp_path):
    """Last Updated carries a date and is REQUIRED by check 3 — never flagged,
    not even when a branch writes it as a dated HEADING, which is the only
    shape where the exemption is load-bearing."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\n## Last Updated (2026-09-15)\n\nA face.\n\n**Last Updated:** 2026-09-15\n"
    branch_root = _advisory_branch(tmp_path, readme)

    assert not [line for line in check_branch_info(str(branch_root)) if "dated/status" in line]


def test_rot_bait_command_list_reported(tmp_path):
    """A Commands section that re-types --help is reported with its count."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = (
        "# MyBranch\n\n## Commands\n\n"
        "- `drone @mybranch audit`\n"
        "- `drone @mybranch check`\n"
        "- `drone @mybranch report`\n\n"
        "## Depends On\n\ndrone\n\n*Last Updated: 2099-01-01*\n"
    )
    branch_root = _advisory_branch(tmp_path, readme)

    lines = [line for line in check_branch_info(str(branch_root)) if "Commands section" in line]
    assert len(lines) == 1
    assert "3 invocation(s)" in lines[0]
    assert "drone @mybranch --help" in lines[0]


def test_rot_bait_short_command_pointer_is_silent(tmp_path):
    """A pointer (under the threshold) is the contract, not rot bait."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = (
        "# MyBranch\n\n## Commands\n\nEvery command: `drone @mybranch --help`\n\n"
        "## Depends On\n\ndrone\n\n*Last Updated: 2099-01-01*\n"
    )
    branch_root = _advisory_branch(tmp_path, readme)

    assert not [line for line in check_branch_info(str(branch_root)) if "Commands section" in line]


def test_command_count_survives_fenced_comments(tmp_path):
    """A bash comment inside a fence is not a markdown heading: counting must
    not stop at '# Audit' three invocations in."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = (
        "# MyBranch\n\n## Commands\n\n```bash\n"
        "drone @mybranch one\n"
        "drone @mybranch two\n\n"
        "# Audit\n"
        "drone @mybranch three\n"
        "drone @mybranch four\n"
        "```\n\n## Depends On\n\ndrone\n\n*Last Updated: 2099-01-01*\n"
    )
    branch_root = _advisory_branch(tmp_path, readme)

    lines = [line for line in check_branch_info(str(branch_root)) if "Commands section" in line]
    assert "4 invocation(s)" in lines[0]


def test_advisory_samples_are_rich_safe(tmp_path):
    """Square brackets in quoted README text would be eaten as Rich markup."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    readme = "# MyBranch\n\n## Status [2026-09-07]\n\nGreen.\n\n*Last Updated: 2099-01-01*\n"
    branch_root = _advisory_branch(tmp_path, readme)

    lines = [line for line in check_branch_info(str(branch_root)) if "dated/status" in line]
    assert "[" not in lines[0] and "]" not in lines[0]
    assert "(2026-09-07)" in lines[0]


def test_branch_inputs_declares_docs_for_the_audit_cache(tmp_path):
    """docs/*.md is declared, or a new docs file is invisible until something
    else in the branch changes and the index line is served stale."""
    from aipass.seedgo.apps.handlers.aipass_standards import readme_check

    assert "docs/*.md" in readme_check.BRANCH_INPUTS


def test_advisory_lane_does_not_move_the_readme_score(tmp_path):
    """LOAD-BEARING: a branch that trips every advisory line still scores
    exactly what it scored before the lane existed — 8 checks, no advisory
    finding anywhere in checks[]. CI gates every branch at 100."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info, check_module

    readme = (
        "# MyBranch\n\n## Architecture\n\n```\nmybranch/\n```\n\n"
        "## Commands\n\n"
        "- `drone @mybranch one`\n- `drone @mybranch two`\n- `drone @mybranch three`\n\n"
        "## Depends On\n\ndrone\n\n"
        "## Status (2026-09-07)\n\nShips 46 standards. See `apps/handlers/gone.py`.\n\n"
        "*Last Updated: 2099-01-01*\n"
    )
    branch_root = _advisory_branch(tmp_path, readme, docs={"audit.md": "# Audit\n"})
    entry = branch_root / "apps" / "mybranch.py"

    result = check_module(str(entry))
    advisory = check_branch_info(str(branch_root))

    assert len(advisory) >= 4, "the branch must actually trip the advisory lane"
    assert any(line.startswith("readme sections (advisory)") for line in advisory)
    assert result["score"] == 100
    assert len(result["checks"]) == 8
    assert all(c["passed"] for c in result["checks"])
    blob = " ".join(f"{c['name']} {c['message']}" for c in result["checks"]).lower()
    for word in ("docs index", "rot bait", "branch-rooted path", "dated/status", "not linked from readme"):
        assert word not in blob


# The README face is eight ## sections, names exact, order fixed (DPLAN-0351
# phase 3): the fleet's de facto order, advisory before it scores.

_EIGHT = (
    "Quick Start",
    "What It Does",
    "Live Inventory",
    "How To Reach Me",
    "Commands",
    "Architecture",
    "Documentation",
    "Integration Points",
)


def _sections_line(branch_root):
    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import check_branch_info

    return [line for line in check_branch_info(str(branch_root)) if line.startswith("readme sections")]


def test_readme_sections_the_eight_in_order_are_silent(tmp_path):
    """A README with the eight in order says nothing: an H3, an H1 and a fenced heading are not sections."""
    body = "".join(f"## {name}\n\nBody.\n\n" for name in _EIGHT)
    fenced = "## Architecture\n\n### A detail\n\n```md\n## Quick Start\n```\n\n"
    body = body.replace("## Architecture\n\nBody.\n\n", fenced)
    branch_root = _advisory_branch(tmp_path, f"# MYBRANCH\n\nA face.\n\n{body}")

    assert _sections_line(branch_root) == []


def test_readme_sections_names_what_is_missing_renamed_out_of_order_and_extra(tmp_path):
    """One advisory line carries the whole diff a hand wave needs: missing, renames, order, strangers."""
    readme = (
        "# MYBRANCH\n\n## What It Does\n\n## Quick Start\n\n## How to reach me\n\n## Commands\n\n"
        "## Architecture\n\n## Status [live]\n\n## Integration\n\n*Last Updated: 2099-01-01*\n"
    )
    branch_root = _advisory_branch(tmp_path, readme)

    (line,) = _sections_line(branch_root)

    assert "(advisory)" in line
    assert "missing Live Inventory, Documentation" in line
    assert "'How to reach me' to 'How To Reach Me'" in line and "'Integration' to 'Integration Points'" in line
    assert "order: What It Does before Quick Start" in line and "Commands before" not in line
    assert "not one of the eight: Status (live)" in line


def test_readme_sections_the_standard_prints_the_order_the_check_reads():
    """readme.md's Canonical Section Order and the query text carry the checker's eight, in its order."""
    import re
    from aipass.seedgo.apps.handlers.aipass_standards import readme_check
    from aipass.seedgo.apps.handlers.aipass_standards.readme_content import get_readme_standards

    standard = (Path(readme_check.__file__).parent / "readme.md").read_text(encoding="utf-8")
    block = standard.split("## Canonical Section Order", 1)[1].split("\n## ", 1)[0]
    listed = tuple(re.findall(r"^\d+\. \*\*(.+?)\*\*", block, re.MULTILINE))
    rendered = get_readme_standards()

    assert readme_check.README_SECTIONS == _EIGHT == listed
    assert [rendered.index(name) for name in _EIGHT] == sorted(rendered.index(name) for name in _EIGHT)


def test_readme_sections_seedgo_own_readme_is_one_of_the_six_in_order():
    """An oracle outside the checker: the README this branch ships reads clean."""
    assert _sections_line(Path(__file__).resolve().parents[1]) == []


# ===========================================================================
# docs_page_check -- the docs/*.md page shape (DPLAN-0351)
# ===========================================================================
#
# The README's depth lives in docs/, and every page there has one shape: a
# back-link, one H1, a purpose paragraph, topic sections no deeper than ###,
# links that resolve, a size under the context pack's cap, and a name that is
# not a retired defect register. Six checks score; story and defect prose
# only nominate.

_GOOD_PAGE = (
    "[<- Back to the README](../README.md)\n\n"
    "# The page\n\n"
    "What this page is for, in one present-tense sentence.\n\n"
    "## A topic\n\nBody, and [the other page](other.md).\n\n"
    "### A detail\n\nMore body.\n\n"
    "```bash\n# a shell comment is not a second H1\n```\n"
)
_OTHER_PAGE = "[<- Back](../README.md)\n\n# Other\n\nThe second page, in one sentence.\n"


def _docs():
    from aipass.seedgo.apps.handlers.aipass_standards import docs_page_check

    return docs_page_check


def _docs_branch(root, pages, other=True):
    """A branch with an entry point, a README and docs/<name> for each page."""
    (root / "apps").mkdir(parents=True, exist_ok=True)
    entry = root / "apps" / f"{root.name}.py"
    entry.write_text("", encoding="utf-8")
    (root / "README.md").write_text("# Branch\n", encoding="utf-8")
    (root / "docs").mkdir(exist_ok=True)
    for name, text in ({"other.md": _OTHER_PAGE} if other else {}).items() | pages.items():
        (root / "docs" / name).write_text(text, encoding="utf-8")
    return entry


def _failed(result):
    """{check name: message} for every failing check."""
    return {c["name"]: c["message"] for c in result["checks"] if not c["passed"]}


_OPENING = "Back-link and one H1"


def test_docs_page_a_page_in_the_template_shape_passes_all_six(tmp_path):
    """The template itself is the zero point: six checks, all green, score 100."""
    entry = _docs_branch(tmp_path / "b", {"page.md": _GOOD_PAGE})

    result = _docs().check_module(str(entry))

    assert [c["name"] for c in result["checks"]] == list(_docs().CHECK_NAMES)
    assert len(result["checks"]) == 6 and result["checks"][0]["name"] == _OPENING
    assert _failed(result) == {}
    assert result["score"] == 100


@pytest.mark.parametrize(
    "text, why",
    [
        ("Intro line.\n\n# Page\n\nPurpose.\n", "line 1 comes before the H1"),
        ("# Page\n\nPurpose.\n\n# Second title\n\nMore.\n", "2 H1 headings"),
        ("## Only a section\n\nBody.\n", "no H1"),
        (
            "See the [README](../README.md) for the whole story of this branch and why.\n\n# Page\n\nPurpose.\n",
            "line 1 comes before the H1",
        ),
    ],
)
def test_docs_page_the_h1_is_one_and_first(tmp_path, text, why):
    """One title, at the top. Prose above it, or a second title, is a page with two faces."""
    entry = _docs_branch(tmp_path / "b", {"bad.md": text})

    failed = _failed(_docs().check_module(str(entry)))

    assert "docs/bad.md" in failed[_OPENING] and why in failed[_OPENING]


def test_docs_page_a_comment_and_a_back_link_may_sit_above_the_h1(tmp_path):
    """The bare back-link belongs at the top; an HTML comment is invisible to a reader."""
    text = "<!-- generated header -->\n[<- Back to the README](../README.md)\n\n# Page\n\nPurpose.\n"
    entry = _docs_branch(tmp_path / "b", {"page.md": text})

    assert _OPENING not in _failed(_docs().check_module(str(entry)))


def test_docs_page_a_missing_or_low_back_link_is_red_under_the_opening_check(tmp_path):
    """Scored since wave 0 put the back-link on every page: above the purpose paragraph, or the page is red.

    The DPLAN-0347 move stamp's link sits below the purpose, which is not the slot.
    """
    stamp = "# Stamped\n\nPurpose.\n\nMoved out of README.md. Back to the [README](../README.md)\n"
    entry = _docs_branch(tmp_path / "b", {"page.md": _GOOD_PAGE, "bare.md": "# Bare\n\nPurpose.\n", "stamp.md": stamp})

    result = _docs().check_module(str(entry))
    message = _failed(result)[_OPENING]

    assert "2 of 4" in message and "no README back-link" in message
    assert "docs/bare.md" in message and "docs/stamp.md" in message and "page.md" not in message
    assert set(_failed(result)) == {_OPENING}
    assert not [line for line in _docs().check_branch_info(str(tmp_path / "b")) if "back-link" in line]


@pytest.mark.parametrize(
    "under",
    [
        "## Bug\n\nBody.",
        "- a list item",
        "| a | table |",
        "> a quote",
        "```\ncode\n```",
        "---",
        "[a lone link](other.md)",
    ],
)
def test_docs_page_the_line_under_the_h1_must_be_prose(tmp_path, under):
    """A reader arriving at the page is told what it is for before anything else.

    The three red pages in the fleet on landing day opened on a section
    heading, a section heading and a code fence.
    """
    entry = _docs_branch(tmp_path / "b", {"bad.md": f"# Page\n\n{under}\n\nLater prose.\n"})

    failed = _failed(_docs().check_module(str(entry)))

    assert "docs/bad.md" in failed["Purpose paragraph"]


def test_docs_page_a_back_link_under_the_h1_is_skipped_on_the_way_to_the_purpose(tmp_path):
    """Title, back-link, purpose is a legal ordering too -- the survey found both."""
    text = "# Page\n\n[<- Back to the README](../README.md)\n\nPurpose.\n"
    entry = _docs_branch(tmp_path / "b", {"page.md": text})

    assert _failed(_docs().check_module(str(entry))) == {}


def test_docs_page_a_heading_deeper_than_three_is_red_but_not_inside_a_fence(tmp_path):
    """Depth 3 is the ceiling; a '####' inside a code sample is not a heading."""
    fenced = "# Page\n\nPurpose.\n\n```md\n#### sample\n```\n"
    deep = "# Page\n\nPurpose.\n\n## A\n\n### B\n\n#### C\n\nBody.\n"
    entry = _docs_branch(tmp_path / "b", {"fenced.md": fenced, "deep.md": deep})

    message = _failed(_docs().check_module(str(entry)))["Heading depth"]

    assert "docs/deep.md" in message and "depth-4" in message
    assert "fenced.md" not in message


def test_docs_page_a_dead_relative_link_is_red_and_named(tmp_path):
    """Links are read from the page's own directory -- the way GitHub renders them."""
    text = (
        "# Page\n\nPurpose, [live](other.md), [up](../README.md), [web](https://example.com), [anchor](#a).\n\n"
        "![missing image](img/none.png) and [gone](gone.md#part)\n\n"
        "`[not a link](nowhere.md)`\n\n```\n[also not](nowhere.md)\n```\n"
    )
    entry = _docs_branch(tmp_path / "b", {"page.md": text})

    message = _failed(_docs().check_module(str(entry)))["Links resolve"]

    assert "img/none.png" in message and "gone.md#part" in message
    assert "nowhere.md" not in message and "other.md" not in message
    assert "#a" not in message.replace("gone.md#part", ""), "an in-page anchor is not a file"
    assert "example.com" not in message and "README" not in message


def test_docs_page_size_reads_the_context_packs_cap_and_at_the_cap_passes(monkeypatch, tmp_path):
    """The number lives in config once; the checker asks for it on every call."""
    d = _docs()
    at = "# P\n\nPurpose.\n"
    monkeypatch.setattr(d.budget, "docs_page_cap", lambda: (len(at), ""))
    entry = _docs_branch(tmp_path / "b", {"at.md": at, "over.md": at + "x"}, other=False)

    message = _failed(d.check_module(str(entry)))["Size"]

    assert "docs/over.md" in message and "over by 1" in message
    assert "at.md" not in message


def test_docs_page_an_unreadable_cap_fails_the_size_check_and_says_why(monkeypatch, tmp_path):
    """No remembered 20,000: a cap nobody can read is a failing check, never a guess."""
    d = _docs()
    monkeypatch.setattr(d.budget, "docs_page_cap", lambda: (None, "seedgo: pack.json has no caps['docs/*.md']"))
    entry = _docs_branch(tmp_path / "b", {"page.md": _GOOD_PAGE})

    result = d.check_module(str(entry))

    assert "caps['docs/*.md']" in _failed(result)["Size"]
    assert [c["name"] for c in result["checks"]] == list(d.CHECK_NAMES), "the cap verdict replaced another check"


def test_docs_page_the_shipped_cap_is_the_context_pack_key():
    """The pack.json key exists and reads; the checker holds no copy of the number."""
    import ast
    from aipass.seedgo.apps.handlers.context_standards import startup_budget_check as budget

    cap, reason = budget.docs_page_cap()
    tree = ast.parse(open(_docs().__file__, encoding="utf-8").read())
    numbers = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, int)}

    assert reason == "" and cap
    assert cap not in numbers, "a copy of the cap was written into the checker"


def test_docs_page_a_defect_register_under_docs_is_red_by_name(tmp_path):
    """The owner retired the registers on 2026-09-19; one coming back under docs/ is red, however spelt.

    A register in the template shape is still red: the name is the defect, not the layout.
    """
    pages = {
        "known_issues.md": _GOOD_PAGE,
        "Tech-Debt.md": _GOOD_PAGE,
        "old known issues.md": _GOOD_PAGE,
        "issues_known.md": _GOOD_PAGE,
    }
    entry = _docs_branch(tmp_path / "b", pages)

    result = _docs().check_module(str(entry))
    message = _failed(result)["Not a register"]

    assert set(_failed(result)) == {"Not a register"}
    assert "3 of 5" in message and "retired 2026-09-19" in message and "docs.local" in message
    assert "known_issues.md" in message and "Tech-Debt.md" in message and "old known issues.md" in message
    assert "issues_known.md" not in message and "other.md" not in message
    assert result["checks"][-1]["name"] == "Not a register" and result["score"] == 83


def test_docs_page_reads_one_level_and_nothing_at_all_is_a_skip(tmp_path):
    """docs/*.md only -- the same reach as the README's docs index. No pages, no red."""
    entry = _docs_branch(tmp_path / "b", {}, other=False)
    (tmp_path / "b" / "docs" / "nested").mkdir()
    (tmp_path / "b" / "docs" / "nested" / "deep.md").write_text("no shape at all\n", encoding="utf-8")

    result = _docs().check_module(str(entry))

    assert result["score"] == 100
    assert all("skipped" in c["message"] for c in result["checks"])


def test_docs_page_an_undecodable_page_fails_every_check(tmp_path):
    """A page the checker cannot read is a page it did not check."""
    entry = _docs_branch(tmp_path / "b", {}, other=False)
    (tmp_path / "b" / "docs" / "binary.md").write_bytes(b"\xff\xfe not utf-8 \xff")

    result = _docs().check_module(str(entry))

    assert result["score"] == 0
    assert all("cannot be read" in c["message"] for c in result["checks"])


def test_docs_page_a_bypass_on_one_page_takes_only_that_page_out(tmp_path):
    """Bypass is per page, by path, like every other standard's per-file rule."""
    entry = _docs_branch(tmp_path / "b", {"odd.md": "no title\n", "bad.md": "no title either\n"})
    rules = [{"file": "docs/odd.md", "standard": "docs_page", "reason": "test"}]

    message = _failed(_docs().check_module(str(entry), rules))[_OPENING]

    assert "docs/bad.md" in message and "odd.md" not in message


def test_docs_page_advisory_nominates_story_lines_by_the_high_precision_arms(tmp_path):
    """History belongs in the CHANGELOG. Only the arms that hand-sampled at 7/8 or better nominate."""
    text = (
        "# Page\n\nPurpose.\n\n"
        "The gate used to read the old key.\n"  # 5
        "It previously lived in apps/.\n"  # 6
        "Cured 2026-09-01 by the owner.\n"  # 7
        "The loader was fixed.\n"  # 8: no date -- not an arm
        "| used to | a table cell |\n"  # 9: table -- not prose
        "```\npreviously in a sample\n```\n"
    )
    entry = _docs_branch(tmp_path / "b", {"story.md": text}, other=False)

    story = next(
        line for line in _docs().check_branch_info(str(entry.parent.parent)) if line.startswith("docs_page story")
    )

    assert "3 line(s)" in story
    assert "docs/story.md:5" in story and "docs/story.md:6" in story and "docs/story.md:7" in story


def test_docs_page_advisory_nominates_defect_prose_but_not_a_pointer_to_the_register(tmp_path):
    """An open defect goes to the owner's pad. A line that links to the register only points at it."""
    text = (
        "# Page\n\nPurpose.\n\n"
        "**Known gap:** the ceiling does not clean up a filled store.\n"  # 5
        "- [known_issues.md](known_issues.md) -- what is still open\n"
        "See [still open](other.md) for the list.\n"
    )
    entry = _docs_branch(tmp_path / "b", {"page.md": text})

    defect = next(
        line
        for line in _docs().check_branch_info(str(entry.parent.parent))
        if line.startswith("docs_page defect prose")
    )

    assert "1 line(s)" in defect and "docs/page.md:5" in defect


def test_docs_page_advisory_lines_never_move_the_score(tmp_path):
    """A page that trips every advisory arm still scores 100: nominations are not findings."""
    text = "[<- Back](../README.md)\n\n# Page\n\nPurpose.\n\nIt used to break. Known gap: still open.\n"
    entry = _docs_branch(tmp_path / "b", {"page.md": text})

    result = _docs().check_module(str(entry))
    advisory = _docs().check_branch_info(str(entry.parent.parent))

    assert len(advisory) == 2 and all("(advisory)" in line for line in advisory)
    assert result["score"] == 100
