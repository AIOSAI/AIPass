"""Equivalence tests for the incremental audit cache (DPLAN-0275).

Proves audit_branch_incremental() output is byte-equivalent to audit_branch()
across the full re-run matrix: cold cache, unchanged branch (cache hit),
mutated/added/deleted files, checker-pack edits, and bypass/ignore rule
edits. This is the hard acceptance bar from Compass #136/#147 — incremental
must never mean approximate.
"""

# =================== META ====================
# Name: test_incremental_audit.py
# Description: Equivalence + unit tests for incremental_cache.py / audit_branch_incremental
# Version: 1.0.0
# Created: 2026-07-31
# Modified: 2026-07-31
# =============================================

# seedgo:bypass standard=architecture reason="test files live in tests/, not apps/"
# seedgo:bypass standard=encapsulation reason="tests import handlers directly for unit testing"

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for branch_audit + incremental_cache."""
    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    from aipass.seedgo.apps.handlers.bypass.ignore_handler import (
        is_seedgo_ignored as real_is_seedgo_ignored,
        load_ignore_entries as real_load_ignore_entries,
    )

    mock_ignore_handler = MagicMock()
    mock_ignore_handler.get_audit_ignore_patterns = MagicMock(return_value=[])
    mock_ignore_handler.is_seedgo_ignored = real_is_seedgo_ignored
    mock_ignore_handler.load_ignore_entries = real_load_ignore_entries
    mock_scan_branch = MagicMock(return_value=None)

    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    cli_mod = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    bypass_pkg = MagicMock()
    bypass_pkg.ignore_handler = mock_ignore_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.ignore_handler", mock_ignore_handler)

    test_map_pkg = MagicMock()
    test_map_pkg.scan_branch = mock_scan_branch
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.test_map", test_map_pkg)
    scanner_mod = MagicMock()
    scanner_mod.scan_branch = mock_scan_branch
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.test_map.function_scanner", scanner_mod)

    # audit package (must be a real module with __path__ pointing at the real
    # directory so submodule imports like audit.incremental_cache work)
    audit_pkg = types.ModuleType("aipass.seedgo.apps.handlers.audit")
    audit_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "apps" / "handlers" / "audit")]
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit", audit_pkg)

    for mod_name in [
        "aipass.seedgo.apps.handlers.audit.audit_display",
        "aipass.seedgo.apps.handlers.audit.branch_audit",
        "aipass.seedgo.apps.handlers.audit.incremental_cache",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHECKER_TEMPLATE = """
CALL_LOG = "__CALL_LOG__"


def check_module(path, bypass_rules=None):
    with open(CALL_LOG, "a", encoding="utf-8") as f:
        f.write(path + "\\n")
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    score = 40 if "BAD" in content else 100
    passed = score >= 75
    checks = [] if passed else [{"passed": False, "message": "Contains BAD marker"}]
    return {"passed": passed, "score": score, "checks": checks}


AUDIT_SCOPE = "all_files"
"""


def _write_checker(pack_dir: Path, call_log: Path) -> None:
    """Write a real all_files checker that logs every check_module() call."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    escaped = str(call_log).replace("\\", "\\\\")
    (pack_dir / "naming_check.py").write_text(_CHECKER_TEMPLATE.replace("__CALL_LOG__", escaped), encoding="utf-8")


def _read_calls(call_log: Path) -> list:
    if not call_log.exists():
        return []
    return [line for line in call_log.read_text(encoding="utf-8").splitlines() if line]


def _setup_branch(tmp_path: Path, files: dict) -> tuple:
    """Create a minimal branch with apps/main.py plus the given extra files."""
    branch_path = tmp_path / "mybranch"
    apps_dir = branch_path / "apps"
    apps_dir.mkdir(parents=True)
    entry = apps_dir / "main.py"
    entry.write_text("pass\n", encoding="utf-8")
    for name, content in files.items():
        (apps_dir / name).write_text(content, encoding="utf-8")
    branch = {"name": "mybranch", "entry_file": str(entry), "path": str(branch_path)}
    return branch, branch_path


def _prepare(tmp_path, monkeypatch, files: dict) -> tuple:
    """Wire up an isolated branch_audit/incremental_cache pair for one test."""
    from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
    from aipass.seedgo.apps.handlers.audit import branch_audit, incremental_cache

    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(incremental_cache, "CACHE_FILE", tmp_path / "seedgo_json" / "audit_cache.json")
    monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
    monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)

    pack_dir = tmp_path / "pack"
    call_log = tmp_path / "calls.log"
    _write_checker(pack_dir, call_log)

    branch, branch_path = _setup_branch(tmp_path, files)
    return branch_audit, incremental_cache, branch, branch_path, pack_dir, call_log


_ENTRY_POINT_CHECKER_TEMPLATE = """
CALL_LOG = "__CALL_LOG__"


def check_module(path, bypass_rules=None):
    with open(CALL_LOG, "a", encoding="utf-8") as f:
        f.write(path + "\\n")
    return {"passed": True, "score": 100, "checks": []}


AUDIT_SCOPE = "entry_point"
"""


def _write_entry_point_checker(pack_dir: Path, call_log: Path) -> None:
    """Write a real entry_point-scope checker that logs every check_module() call."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    escaped = str(call_log).replace("\\", "\\\\")
    (pack_dir / "cliux_check.py").write_text(
        _ENTRY_POINT_CHECKER_TEMPLATE.replace("__CALL_LOG__", escaped), encoding="utf-8"
    )


_FILTER_CHECKER_TEMPLATE = """
CALL_LOG = "__CALL_LOG__"
FILE_FILTER = "special"
AUDIT_SCOPE = "all_files"


def check_module(path, bypass_rules=None):
    with open(CALL_LOG, "a", encoding="utf-8") as f:
        f.write(path + "\\n")
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    if "SKIP_ME" in content:
        return {"passed": True, "score": 0, "checks": [{"passed": True, "message": "skipped: not applicable"}]}
    score = 40 if "BAD" in content else 100
    passed = score >= 75
    checks = [] if passed else [{"passed": False, "message": "Contains BAD marker"}]
    return {"passed": passed, "score": score, "checks": checks}
"""


def _write_filter_checker(pack_dir: Path, call_log: Path) -> None:
    """Write an all_files checker with a FILE_FILTER and a 'skipped' result path."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    escaped = str(call_log).replace("\\", "\\\\")
    (pack_dir / "filterthing_check.py").write_text(
        _FILTER_CHECKER_TEMPLATE.replace("__CALL_LOG__", escaped), encoding="utf-8"
    )


_POST_CHECK_CHECKER_TEMPLATE = """
CALL_LOG = "__CALL_LOG__"
AUDIT_SCOPE = "all_files"


def check_module(path, bypass_rules=None):
    with open(CALL_LOG, "a", encoding="utf-8") as f:
        f.write(path + "\\n")
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    score = 40 if "BAD" in content else 100
    passed = score >= 75
    checks = [] if passed else [{"passed": False, "message": "Contains BAD marker"}]
    return {"passed": passed, "score": score, "checks": checks}


def check_branch_post(branch_path, bypass_rules=None):
    import pathlib

    apps_dir = pathlib.Path(branch_path) / "apps"
    bad_files = sorted(f.name for f in apps_dir.glob("*.py") if "BAD" in f.read_text(encoding="utf-8"))
    violations = [
        {"file": n, "path": n, "score": 0, "issues": ["post-check found BAD"], "message": "post-check found BAD"}
        for n in bad_files
    ]
    scores = [20] * len(bad_files) if bad_files else [90]
    return violations, scores
"""


def _write_post_check_checker(pack_dir: Path, call_log: Path) -> None:
    """Write an all_files checker that also implements check_branch_post()."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    escaped = str(call_log).replace("\\", "\\\\")
    (pack_dir / "postcheck_check.py").write_text(
        _POST_CHECK_CHECKER_TEMPLATE.replace("__CALL_LOG__", escaped), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Equivalence tests -- the DPLAN-0275 acceptance bar
# ---------------------------------------------------------------------------


class TestEquivalence:
    """audit_branch_incremental() output must equal audit_branch() output."""

    def test_cold_cache_matches_full_audit(self, tmp_path, monkeypatch):
        """No cache yet -- incremental falls back to a full audit, byte-equal."""
        branch_audit, _cache, branch, _path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n"}
        )

        incremental_result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")
        full_result = branch_audit.audit_branch(branch, [], pack_path=pack_dir)

        assert incremental_result.pop("_cache_hit") is False
        assert incremental_result == full_result

    def test_unchanged_branch_is_cache_hit_zero_executions(self, tmp_path, monkeypatch):
        """A clean second run reuses cached output with zero checker calls."""
        branch_audit, _cache, branch, _path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n", "other.py": "print('GOOD')\n"}
        )

        first = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        calls_after_first = len(_read_calls(call_log))
        assert calls_after_first > 0

        second = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        assert len(_read_calls(call_log)) == calls_after_first

        assert first.pop("_cache_hit") is False
        assert second.pop("_cache_hit") is True
        assert first == second

    def test_mutate_file_reruns_only_that_file(self, tmp_path, monkeypatch):
        """Editing one file re-checks only that file; others reuse cached results."""
        branch_audit, _cache, branch, branch_path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n", "other.py": "print('GOOD')\n"}
        )
        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")

        (branch_path / "apps" / "good.py").write_text("print('BAD')\n", encoding="utf-8")

        incremental_result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        touched = {Path(p).name for p in _read_calls(call_log)}
        assert touched == {"good.py"}

        call_log.write_text("", encoding="utf-8")
        full_result = branch_audit.audit_branch(branch, [], pack_path=pack_dir)

        assert incremental_result.pop("_cache_hit") is False
        assert incremental_result == full_result

    def test_add_file_runs_only_new_file(self, tmp_path, monkeypatch):
        """Adding a file re-checks only the new file."""
        branch_audit, _cache, branch, branch_path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n"}
        )
        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")

        (branch_path / "apps" / "new_module.py").write_text("print('GOOD')\n", encoding="utf-8")

        incremental_result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        touched = {Path(p).name for p in _read_calls(call_log)}
        assert touched == {"new_module.py"}

        call_log.write_text("", encoding="utf-8")
        full_result = branch_audit.audit_branch(branch, [], pack_path=pack_dir)

        assert incremental_result.pop("_cache_hit") is False
        assert incremental_result == full_result
        assert incremental_result["files_checked"] == 3

    def test_delete_file_drops_from_cache_and_output(self, tmp_path, monkeypatch):
        """Deleting a file drops it from both the cache and the output."""
        branch_audit, cache, branch, branch_path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n", "doomed.py": "print('GOOD')\n"}
        )
        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)

        (branch_path / "apps" / "doomed.py").unlink()

        incremental_result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")
        full_result = branch_audit.audit_branch(branch, [], pack_path=pack_dir)

        assert incremental_result.pop("_cache_hit") is False
        assert incremental_result == full_result
        assert incremental_result["files_checked"] == 2  # main.py + good.py

        doc = cache.load_cache()
        cached_files = doc["branches"]["mybranch"]["files"]
        assert "apps/doomed.py" not in cached_files

    def test_checker_pack_edit_busts_full_rescan(self, tmp_path, monkeypatch):
        """Editing a checker file busts the whole-branch cache to a full re-scan."""
        branch_audit, _cache, branch, _path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n", "other.py": "print('GOOD')\n"}
        )
        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")

        checker_file = pack_dir / "naming_check.py"
        checker_file.write_text(checker_file.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")

        result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        touched = {Path(p).name for p in _read_calls(call_log)}

        assert result["_cache_hit"] is False
        assert touched == {"good.py", "other.py", "main.py"}

    def test_bypass_edit_busts_full_rescan(self, tmp_path, monkeypatch):
        """Adding a bypass.json busts the whole-branch cache to a full re-scan."""
        branch_audit, _cache, branch, branch_path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n"}
        )
        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")

        seedgo_dir = branch_path / ".seedgo"
        seedgo_dir.mkdir()
        (seedgo_dir / "bypass.json").write_text("[]", encoding="utf-8")

        result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        touched = {Path(p).name for p in _read_calls(call_log)}

        assert result["_cache_hit"] is False
        assert touched == {"good.py", "main.py"}

    def test_force_full_ignores_clean_cache(self, tmp_path, monkeypatch):
        """--full (force_full=True) always re-scans, even with a clean cache."""
        branch_audit, _cache, branch, _path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n"}
        )
        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")

        result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir, force_full=True)
        touched = {Path(p).name for p in _read_calls(call_log)}

        assert result["_cache_hit"] is False
        assert touched == {"good.py", "main.py"}

    # -- Blocker-fix regressions (DPLAN-0275 second review) --------------

    def test_readme_only_edit_busts_cache_hit(self, tmp_path, monkeypatch):
        """Editing only README.md (no .py change) must not serve a stale
        cache-hit output -- readme_check/readme_quality_check read README.md
        even though it lives outside apps/ and outside the entry file
        (Blocker 1: the fingerprint set must be a superset of what checkers
        actually read, not just apps/**/*.py)."""
        branch_audit, _cache, branch, branch_path, pack_dir, _call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n"}
        )
        (branch_path / "README.md").write_text("# mybranch\n", encoding="utf-8")

        first = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        assert first.pop("_cache_hit") is False

        (branch_path / "README.md").write_text("# mybranch\n\nUpdated docs.\n", encoding="utf-8")

        second = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        assert second.pop("_cache_hit") is False  # dirty -- NOT a stale cache hit

        full_result = branch_audit.audit_branch(branch, [], pack_path=pack_dir)
        assert second == full_result

    def test_tests_dir_only_addition_busts_cache_hit(self, tmp_path, monkeypatch):
        """Adding a file under tests/ (no apps/ change) must not serve a
        stale cache-hit output -- test_map's scan_branch reads
        tests/**/test_*.py, a path outside apps/ and outside the
        fingerprinted .py set (Blocker 1)."""
        branch_audit, _cache, branch, branch_path, pack_dir, _call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n"}
        )
        tests_dir = branch_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_good.py").write_text("def test_x(): pass\n", encoding="utf-8")

        first = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        assert first.pop("_cache_hit") is False

        (tests_dir / "test_new.py").write_text("def test_y(): pass\n", encoding="utf-8")

        second = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        assert second.pop("_cache_hit") is False  # dirty -- NOT a stale cache hit

        full_result = branch_audit.audit_branch(branch, [], pack_path=pack_dir)
        assert second == full_result

    def test_bypass_content_edit_busts_full_rescan(self, tmp_path, monkeypatch):
        """Editing bypass.json's CONTENT (not just creating it) must also
        bust the whole-branch cache to a full re-scan -- compute_bypass_stamp()
        fingerprints the file's (mtime, size), so any edit changes the stamp,
        not just the file's initial appearance."""
        branch_audit, _cache, branch, branch_path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n"}
        )
        seedgo_dir = branch_path / ".seedgo"
        seedgo_dir.mkdir()
        bypass_file = seedgo_dir / "bypass.json"
        bypass_file.write_text("[]", encoding="utf-8")

        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")

        bypass_file.write_text('[{"standard": "naming", "reason": "test"}]', encoding="utf-8")

        result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        touched = {Path(p).name for p in _read_calls(call_log)}

        assert result["_cache_hit"] is False
        assert touched == {"good.py", "main.py"}

    def test_file_filter_skipped_denominator_matches_full_audit(self, tmp_path, monkeypatch):
        """A FILE_FILTER-scoped checker whose check_module() sometimes
        returns a 'skipped'/'not applicable' check (excluded from the
        score-averaging denominator by _run_all_files) must reproduce the
        exact same scores/average whether some files are cache-reused and
        others freshly recomputed."""
        branch_audit, _cache, branch, branch_path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"special_ok.py": "print('GOOD')\n", "special_skip.py": "SKIP_ME\n"}
        )
        _write_filter_checker(pack_dir, tmp_path / "filter_calls.log")

        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")

        (branch_path / "apps" / "special_ok.py").write_text("print('BAD')\n", encoding="utf-8")

        incremental_result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")
        full_result = branch_audit.audit_branch(branch, [], pack_path=pack_dir)

        assert incremental_result.pop("_cache_hit") is False
        assert incremental_result == full_result
        assert incremental_result["scores"]["filterthing"] == full_result["scores"]["filterthing"]

    def test_check_branch_post_blend_matches_full_audit(self, tmp_path, monkeypatch):
        """A checker implementing check_branch_post() blends its fresh
        post-scan scores with the (possibly cache-reused) per-file scores
        identically whether the per-file part came from cache or a fresh
        recompute."""
        branch_audit, _cache, branch, branch_path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n", "other.py": "print('GOOD')\n"}
        )
        _write_post_check_checker(pack_dir, tmp_path / "post_calls.log")

        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")

        (branch_path / "apps" / "good.py").write_text("print('BAD')\n", encoding="utf-8")

        incremental_result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        call_log.write_text("", encoding="utf-8")
        full_result = branch_audit.audit_branch(branch, [], pack_path=pack_dir)

        assert incremental_result.pop("_cache_hit") is False
        assert incremental_result == full_result
        assert incremental_result["scores"]["postcheck"] == full_result["scores"]["postcheck"]

    def test_entry_point_checker_reruns_when_other_file_changes(self, tmp_path, monkeypatch):
        """Blocker 2 regression: an entry_point-scope checker must re-run
        on the entry file whenever the branch is dirty, even if the entry
        file itself is unchanged -- AUDIT_SCOPE says where a result is
        REPORTED, not what the checker reads (e.g. readme_check reads
        README.md, not entry_file). Without the fix, the cached entry-file
        result would be served forever once entry_file itself stops
        changing, regardless of what else in the branch changed."""
        branch_audit, _cache, branch, branch_path, pack_dir, _call_log = _prepare(
            tmp_path, monkeypatch, {"other.py": "print('GOOD')\n"}
        )
        entry_log = tmp_path / "entry_calls.log"
        _write_entry_point_checker(pack_dir, entry_log)

        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        assert _read_calls(entry_log)  # ran on the cold-cache first pass

        entry_log.write_text("", encoding="utf-8")
        (branch_path / "apps" / "other.py").write_text("print('CHANGED')\n", encoding="utf-8")

        incremental_result = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        touched = {Path(p).name for p in _read_calls(entry_log)}
        assert "main.py" in touched  # entry file re-ran though it didn't change itself

        full_result = branch_audit.audit_branch(branch, [], pack_path=pack_dir)
        assert incremental_result.pop("_cache_hit") is False
        assert incremental_result == full_result


# ---------------------------------------------------------------------------
# Unit tests -- incremental_cache.py primitives
# ---------------------------------------------------------------------------


class TestFingerprintFile:
    def test_missing_file_returns_sentinel(self, tmp_path):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        assert incremental_cache.fingerprint_file(tmp_path / "nope.py") == [-1, -1]

    def test_existing_file_returns_mtime_and_size(self, tmp_path):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        f = tmp_path / "a.py"
        f.write_text("hello", encoding="utf-8")
        fp = incremental_cache.fingerprint_file(f)
        assert fp[1] == 5
        assert fp[0] > 0


class TestDiffFileset:
    def test_added_changed_deleted_unchanged(self):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        cached = {"a.py": [1, 10], "b.py": [1, 20], "c.py": [1, 30]}
        current = {"a.py": [1, 10], "b.py": [2, 20], "d.py": [1, 40]}
        added, changed, deleted, unchanged = incremental_cache.diff_fileset(cached, current)
        assert added == {"d.py"}
        assert changed == {"b.py"}
        assert deleted == {"c.py"}
        assert unchanged == {"a.py"}


class TestStamps:
    def test_pack_stamp_changes_when_checker_edited(self, tmp_path):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        checker = pack_dir / "naming_check.py"
        checker.write_text("def check_module(p): return {}\n", encoding="utf-8")
        stamp1 = incremental_cache.compute_pack_stamp(pack_dir)
        checker.write_text("def check_module(p): return {'x': 1}\n", encoding="utf-8")
        stamp2 = incremental_cache.compute_pack_stamp(pack_dir)
        assert stamp1 != stamp2

    def test_bypass_stamp_changes_when_seedgoignore_added(self, tmp_path):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        branch_path = tmp_path / "branch"
        branch_path.mkdir()
        stamp1 = incremental_cache.compute_bypass_stamp(branch_path)
        (branch_path / ".seedgoignore").write_text("tools/\n", encoding="utf-8")
        stamp2 = incremental_cache.compute_bypass_stamp(branch_path)
        assert stamp1 != stamp2

    def test_current_stamp_stable_when_nothing_changes(self, tmp_path):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        branch_path = tmp_path / "branch"
        branch_path.mkdir()
        stamp1 = incremental_cache.current_stamp(branch_path, pack_dir)
        stamp2 = incremental_cache.current_stamp(branch_path, pack_dir)
        assert stamp1 == stamp2


class TestLoadSaveCache:
    def test_missing_file_returns_empty_dict(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        monkeypatch.setattr(incremental_cache, "CACHE_FILE", tmp_path / "audit_cache.json")
        assert incremental_cache.load_cache() == {}

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        monkeypatch.setattr(incremental_cache, "CACHE_FILE", tmp_path / "audit_cache.json")
        doc = {"branches": {"x": {"stamp": "abc", "files": {}, "output": {}}}}
        incremental_cache.save_cache(doc)
        loaded = incremental_cache.load_cache()
        assert loaded["branches"]["x"]["stamp"] == "abc"

    def test_corrupt_json_self_heals(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        cache_file = tmp_path / "audit_cache.json"
        cache_file.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(incremental_cache, "CACHE_FILE", cache_file)
        assert incremental_cache.load_cache() == {}
        assert cache_file.with_suffix(cache_file.suffix + ".corrupt").exists()

    def test_schema_version_mismatch_returns_empty(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        cache_file = tmp_path / "audit_cache.json"
        cache_file.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
        monkeypatch.setattr(incremental_cache, "CACHE_FILE", cache_file)
        assert incremental_cache.load_cache() == {}


class TestBranchEntry:
    def test_get_missing_branch_returns_empty(self):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        assert incremental_cache.get_branch_entry({}, "nope") == {}

    def test_set_then_get_roundtrip(self):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        cache: dict = {}
        incremental_cache.set_branch_entry(cache, "seedgo", {"stamp": "x"})
        assert incremental_cache.get_branch_entry(cache, "seedgo") == {"stamp": "x"}
