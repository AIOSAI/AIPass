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


_BYPASS_AWARE_CHECKER_TEMPLATE = """
CALL_LOG = "__CALL_LOG__"
AUDIT_SCOPE = "all_files"


def check_module(path, bypass_rules=None):
    with open(CALL_LOG, "a", encoding="utf-8") as f:
        f.write(path + "\\n")
    if bypass_rules:
        return {"passed": True, "score": 100, "checks": []}
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    score = 40 if "BAD" in content else 100
    passed = score >= 75
    checks = [] if passed else [{"passed": False, "message": "Contains BAD marker"}]
    return {"passed": passed, "score": score, "checks": checks}
"""


def _write_bypass_aware_checker(pack_dir: Path, call_log: Path) -> None:
    """Write an all_files checker whose verdict depends on the bypass rules.

    Any rule at all makes the BAD marker vanish -- the one-line stand-in for
    what a real .seedgo/bypass.json rule does to a violation. Same filename as
    _write_checker's so it replaces it in the pack.
    """
    pack_dir.mkdir(parents=True, exist_ok=True)
    escaped = str(call_log).replace("\\", "\\\\")
    (pack_dir / "naming_check.py").write_text(
        _BYPASS_AWARE_CHECKER_TEMPLATE.replace("__CALL_LOG__", escaped), encoding="utf-8"
    )


def _write_post_check_checker(pack_dir: Path, call_log: Path) -> None:
    """Write an all_files checker that also implements check_branch_post()."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    escaped = str(call_log).replace("\\", "\\\\")
    (pack_dir / "postcheck_check.py").write_text(
        _POST_CHECK_CHECKER_TEMPLATE.replace("__CALL_LOG__", escaped), encoding="utf-8"
    )


_OBSERVE_CHECKER_TEMPLATE = """
CALL_LOG = "__CALL_LOG__"
AUDIT_SCOPE = "all_files"


def check_module(path, bypass_rules=None):
    return {"passed": True, "score": 100, "checks": []}


def check_branch_observe(branch_path, bypass_rules=None):
    import pathlib

    log = pathlib.Path(CALL_LOG)
    taken = len([ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]) if log.exists() else 0
    with open(CALL_LOG, "a", encoding="utf-8") as f:
        f.write("reading\\n")
    return [{"standard": "observing", "branch": pathlib.Path(branch_path).name, "reading": taken + 1}]
"""


def _write_observe_checker(pack_dir: Path, call_log: Path) -> None:
    """Write an all_files checker exposing an observe-only branch hook.

    Each reading is numbered, so a replayed one is distinguishable from a
    fresh one — the whole point of the lane is that it reads runtime state.
    """
    pack_dir.mkdir(parents=True, exist_ok=True)
    escaped = str(call_log).replace("\\", "\\\\")
    (pack_dir / "observing_check.py").write_text(
        _OBSERVE_CHECKER_TEMPLATE.replace("__CALL_LOG__", escaped), encoding="utf-8"
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

    def test_custom_config_addition_busts_cache_hit(self, tmp_path, monkeypatch):
        """Adding an operator file under {branch}_json/custom_config/ must not
        serve a stale cache-hit output -- the audit's custom_config info line
        names those files, so a cached run would keep reporting the old list."""
        branch_audit, _cache, branch, branch_path, pack_dir, _call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n"}
        )
        custom_config = branch_path / f"{branch_path.name}_json" / "custom_config"
        custom_config.mkdir(parents=True)

        first = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        assert first.pop("_cache_hit") is False

        (custom_config / "tuning_config.json").write_text('{"a": 1}', encoding="utf-8")

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

    def test_cache_hit_takes_a_fresh_observation(self, tmp_path, monkeypatch):
        """A cached audit still takes a FRESH observe reading, and still scores identically.

        Observe readings are of live runtime state — log files that appear and
        rotate with nothing edited — so a replayed one is a reading of a
        moment that has passed, presented as if current. Same reasoning that
        recomputes _deprecated_patterns on every cache hit. The scores, by
        contrast, must be exactly the cached ones: an observation is evidence,
        never a number.
        """
        branch_audit, _cache, branch, _path, pack_dir, _call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('GOOD')\n"}
        )
        observe_log = tmp_path / "observe_calls.log"
        _write_observe_checker(pack_dir, observe_log)
        logged: list = []
        monkeypatch.setattr(
            branch_audit.json_handler,
            "log_operation",
            lambda op, data=None, module_name=None: logged.append((op, data, module_name)) or True,
        )

        first = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)
        second = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir)

        assert second["_cache_hit"] is True, "the point of this test is the cached path"
        assert first["observations"][0]["reading"] == 1
        assert second["observations"][0]["reading"] == 2, "a cache hit must re-read, not replay"
        assert second["scores"] == first["scores"]
        assert second["average"] == first["average"]
        observed_writes = [entry for entry in logged if entry[0] == "branch_observation"]
        assert len(observed_writes) == 2, "every reading is persisted, including the one taken on a cache hit"
        assert {entry[2] for entry in observed_writes} == {"branch_observe"}, (
            "readings go to their own module log — audit traffic would evict them from a shared one"
        )

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


class TestNoBypassCacheIsolation:
    """A --no-bypass run and a normal run must never share a cached result.

    The cache stamp fingerprints the bypass.json FILE, not whether the rules
    in it were applied -- so both runs read the same tree, the same pack and
    the same (unmodified) bypass.json. Without the bypass STATE in the stamp,
    whichever runs second is served the other one's answer: the honest score
    published as the normal one, or the bypassed score published as honest.
    """

    RULES = [{"file": "apps/good.py", "standard": "naming", "reason": "test rule"}]

    def _prepare_bypass_aware(self, tmp_path, monkeypatch):
        branch_audit, cache, branch, branch_path, pack_dir, call_log = _prepare(
            tmp_path, monkeypatch, {"good.py": "print('BAD')\n"}
        )
        _write_bypass_aware_checker(pack_dir, call_log)
        return branch_audit, cache, branch, branch_path, pack_dir, call_log

    def test_no_bypass_run_is_not_served_the_bypassed_result(self, tmp_path, monkeypatch):
        """Normal run first, then --no-bypass: the honest score must be recomputed."""
        branch_audit, _cache, branch, _path, pack_dir, _log = self._prepare_bypass_aware(tmp_path, monkeypatch)

        bypassed = branch_audit.audit_branch_incremental(branch, self.RULES, pack_path=pack_dir)
        assert bypassed["average"] == 100  # the rule hides the BAD marker

        honest = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir, no_bypass=True)
        assert honest["_cache_hit"] is False
        assert honest["average"] < 100, "a --no-bypass run was served the bypassed cached score"

    def test_normal_run_is_not_served_the_no_bypass_result(self, tmp_path, monkeypatch):
        """--no-bypass first, then a normal run: the bypassed score must come back."""
        branch_audit, _cache, branch, _path, pack_dir, _log = self._prepare_bypass_aware(tmp_path, monkeypatch)

        honest = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir, no_bypass=True)
        assert honest["average"] < 100

        bypassed = branch_audit.audit_branch_incremental(branch, self.RULES, pack_path=pack_dir)
        assert bypassed["_cache_hit"] is False
        assert bypassed["average"] == 100, "a normal run was served the --no-bypass cached score"

    def test_no_bypass_ignores_rules_handed_to_it(self, tmp_path, monkeypatch):
        """no_bypass=True means no rules, whatever the caller passed alongside it.

        The flag and the rule list cannot disagree — otherwise the stamp says
        'no bypasses' while the audit under it applied them.
        """
        branch_audit, _cache, branch, _path, pack_dir, _log = self._prepare_bypass_aware(tmp_path, monkeypatch)

        result = branch_audit.audit_branch_incremental(branch, self.RULES, pack_path=pack_dir, no_bypass=True)
        assert result["average"] < 100

    def test_repeat_no_bypass_run_hits_its_own_cache(self, tmp_path, monkeypatch):
        """Two --no-bypass runs in a row: the second is a cache hit, zero checks."""
        branch_audit, _cache, branch, _path, pack_dir, call_log = self._prepare_bypass_aware(tmp_path, monkeypatch)

        first = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir, no_bypass=True)
        call_log.write_text("", encoding="utf-8")

        second = branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir, no_bypass=True)
        assert _read_calls(call_log) == []
        assert second.pop("_cache_hit") is True
        assert first.pop("_cache_hit") is False
        assert first == second

    def test_no_bypass_run_does_not_evict_the_normal_cache(self, tmp_path, monkeypatch):
        """A --no-bypass run must not cost the next normal run a full re-scan.

        Publishing both numbers is routine (every APLAN carries them), so the
        two runs keep separate cache entries rather than overwriting each
        other's — a shared key would mean a guaranteed full fleet re-scan
        every single time either number is refreshed.
        """
        branch_audit, _cache, branch, _path, pack_dir, call_log = self._prepare_bypass_aware(tmp_path, monkeypatch)

        branch_audit.audit_branch_incremental(branch, self.RULES, pack_path=pack_dir)
        branch_audit.audit_branch_incremental(branch, [], pack_path=pack_dir, no_bypass=True)
        call_log.write_text("", encoding="utf-8")

        again = branch_audit.audit_branch_incremental(branch, self.RULES, pack_path=pack_dir)
        assert _read_calls(call_log) == []
        assert again["_cache_hit"] is True
        assert again["average"] == 100


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

    def test_machinery_stamp_changes_when_bypass_package_edited(self, tmp_path, monkeypatch):
        """A bypass/ edit must re-scan every branch, not just seedgo's own tree.

        FPLAN-0382 changed is_bypassed's matching semantics and nothing in the
        stamp noticed: all 17 branches kept serving results computed under the
        old rules, reading 17/17 green while uncached CI showed 99%.
        """
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        machinery = tmp_path / "bypass"
        machinery.mkdir()
        utils = machinery / "utils.py"
        utils.write_text("def is_bypassed(): ...\n", encoding="utf-8")
        monkeypatch.setattr(incremental_cache, "MACHINERY_DIRS", (machinery,))

        stamp1 = incremental_cache.compute_machinery_stamp()
        utils.write_text("def is_bypassed(): ...  # comment only\n", encoding="utf-8")
        stamp2 = incremental_cache.compute_machinery_stamp()
        assert stamp1 != stamp2

    def test_current_stamp_includes_the_machinery_stamp(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        branch_path = tmp_path / "branch"
        branch_path.mkdir()
        machinery = tmp_path / "bypass"
        machinery.mkdir()
        (machinery / "utils.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(incremental_cache, "MACHINERY_DIRS", (machinery,))

        stamp1 = incremental_cache.current_stamp(branch_path, pack_dir)
        # Size must change, not just content: the fingerprint is (mtime_ns, size)
        # and two writes inside one filesystem timestamp tick are indistinguishable.
        (machinery / "utils.py").write_text("x = 1  # changed\n", encoding="utf-8")
        assert incremental_cache.current_stamp(branch_path, pack_dir) != stamp1

    def test_current_stamp_differs_when_bypasses_are_disabled(self, tmp_path):
        """Suppressing the rules is an input change, exactly like editing them.

        compute_bypass_stamp() fingerprints the bypass.json FILE, which is
        byte-identical across a normal and a --no-bypass run — so the stamp
        itself has to carry whether those rules were applied.
        """
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        branch_path = tmp_path / "branch"
        branch_path.mkdir()

        normal = incremental_cache.current_stamp(branch_path, pack_dir)
        no_bypass = incremental_cache.current_stamp(branch_path, pack_dir, no_bypass=True)
        assert normal != no_bypass

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


# ---------------------------------------------------------------------------
# Ruling 6 -- branch_level checkers whose inputs live OUTSIDE apps/
# ---------------------------------------------------------------------------


class TestBranchLevelCheckerInputsInvalidateTheCache:
    """The defect: the watch set covered apps/**/*.py, README.md, tests/**/*.py
    and {branch}_json/custom_config/ -- but NOT the inputs branch_level
    checkers actually score. trinity reads .trinity/; json_handler reads the
    {branch}_json/ triplets. Edit one and the branch never looks dirty, so a
    stale score is served until --full.

    Same species the module docstring already names for README-only edits, one
    lane over. The fix is declarative: a checker states BRANCH_INPUTS and the
    watch set resolves them, so the cache hardcodes no path.
    """

    @staticmethod
    def _watch_rels(branch_path, checkers):
        from aipass.seedgo.apps.handlers.audit import branch_audit

        return {f["rel"] for f in branch_audit._collect_watch_files(branch_path, checkers)}

    def test_a_declared_input_is_watched(self, tmp_path, monkeypatch):
        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        trinity_dir = branch_path / ".trinity"
        trinity_dir.mkdir()
        (trinity_dir / "local.json").write_text("{}\n", encoding="utf-8")

        checkers = {"trinity": types.SimpleNamespace(BRANCH_INPUTS=(".trinity/*",))}

        assert ".trinity/local.json" in self._watch_rels(branch_path, checkers)

    def test_the_branch_placeholder_is_substituted(self, tmp_path, monkeypatch):
        """json_handler's inputs are named after the branch, not a fixed dir."""
        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        json_dir = branch_path / "mybranch_json"
        json_dir.mkdir()
        (json_dir / "thing_config.json").write_text("{}\n", encoding="utf-8")

        checkers = {"json_handler": types.SimpleNamespace(BRANCH_INPUTS=("{branch}_json/*.json",))}

        assert "mybranch_json/thing_config.json" in self._watch_rels(branch_path, checkers)

    def test_a_checker_declaring_nothing_adds_nothing(self, tmp_path, monkeypatch):
        """Over-refusal guard: the watch set must not widen for every checker."""
        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        (branch_path / ".trinity").mkdir()
        (branch_path / ".trinity" / "local.json").write_text("{}\n", encoding="utf-8")

        bare = {"other": types.SimpleNamespace()}

        assert self._watch_rels(branch_path, bare) == self._watch_rels(branch_path, {})

    def test_an_undeclared_path_is_still_not_watched(self, tmp_path, monkeypatch):
        """The declaration is the whole allow-list -- no incidental widening."""
        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        (branch_path / "random").mkdir()
        (branch_path / "random" / "file.json").write_text("{}\n", encoding="utf-8")

        checkers = {"trinity": types.SimpleNamespace(BRANCH_INPUTS=(".trinity/*",))}

        assert "random/file.json" not in self._watch_rels(branch_path, checkers)

    def test_directories_matched_by_a_glob_are_watched(self, tmp_path, monkeypatch):
        """REVERSED 2026-08-27. This test previously asserted the opposite --
        that directories are skipped -- and that was the defect @daemon found
        hours later: the File set group scores stray DIRECTORIES, so excluding
        them made the one stray shape the ruling is about invisible to the
        cache. Reversed rather than deleted, so the history stays readable.
        Directories are watched by PRESENCE -- see
        TestTheCacheSeesStrayDirectories for why not by content.
        """
        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        (branch_path / ".trinity").mkdir()
        (branch_path / ".trinity" / "subdir").mkdir()

        checkers = {"trinity": types.SimpleNamespace(BRANCH_INPUTS=(".trinity/*",))}

        assert any(r.endswith("subdir") for r in self._watch_rels(branch_path, checkers))

    def test_a_missing_declared_directory_is_not_an_error(self, tmp_path, monkeypatch):
        """A branch with no .trinity/ must audit, not raise."""
        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})

        checkers = {"trinity": types.SimpleNamespace(BRANCH_INPUTS=(".trinity/*",))}

        assert self._watch_rels(branch_path, checkers)  # apps/main.py still there

    @pytest.mark.parametrize(
        ("module_name", "attribute", "expected"),
        [
            ("trinity_check", "BRANCH_INPUTS", ".trinity/*"),
            ("json_handler_check", "BRANCH_INPUT_NAMES", "{branch}_json/*.json"),
        ],
    )
    def test_the_two_real_checkers_declare_their_inputs(self, module_name, attribute, expected):
        """The shipped declarations, not a fixture: this is what closes ruling 6.

        Read from SOURCE rather than imported: this module's autouse fixture
        stubs the bypass package, so importing a real checker here fails for
        reasons that have nothing to do with the declaration.
        """
        import ast

        source = (
            Path(__file__).resolve().parent.parent / "apps" / "handlers" / "aipass_standards" / f"{module_name}.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        declared = [
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == attribute for t in node.targets)
        ]

        assert declared, f"{module_name} declares no {attribute}"
        assert expected in declared[0]

    def test_editing_a_trinity_file_makes_the_branch_dirty(self, tmp_path, monkeypatch):
        """End to end: the cache serves a hit, then must NOT after a .trinity edit."""
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        trinity_dir = branch_path / ".trinity"
        trinity_dir.mkdir()
        target = trinity_dir / "local.json"
        target.write_text("{}\n", encoding="utf-8")

        checkers = {"trinity": types.SimpleNamespace(BRANCH_INPUTS=(".trinity/*",))}
        before = incremental_cache.collect_fingerprints(
            __import__("aipass.seedgo.apps.handlers.audit.branch_audit", fromlist=["x"])._collect_watch_files(
                branch_path, checkers
            )
        )
        target.write_text('{"changed": true, "padding": "xxxxxxxxxxxxxxxxxxxx"}\n', encoding="utf-8")
        after = incremental_cache.collect_fingerprints(
            __import__("aipass.seedgo.apps.handlers.audit.branch_audit", fromlist=["x"])._collect_watch_files(
                branch_path, checkers
            )
        )

        _, changed, _, _ = incremental_cache.diff_fileset(before, after)
        assert ".trinity/local.json" in changed


class TestPresenceOnlyInputsDoNotChurnTheCache:
    """Found by running the real thing, not by a test: declaring
    ``{branch}_json/*.json`` as a CONTENT input made the branch dirty on every
    run, because the checkers write their own *_log.json files while the audit
    is running. The audit disturbs what it measures.

    json_handler scores triplet COMPLETENESS -- which filenames exist -- and
    never reads a byte of them. So presence is the whole signal: add or delete
    must bust the cache, a content write must not. Two channels, each named
    for what it means.
    """

    @staticmethod
    def _fps(branch_path, checkers):
        from aipass.seedgo.apps.handlers.audit import branch_audit, incremental_cache

        return incremental_cache.collect_fingerprints(branch_audit._collect_watch_files(branch_path, checkers))

    def _names_checker(self):
        return {"json_handler": types.SimpleNamespace(BRANCH_INPUT_NAMES=("{branch}_json/*.json",))}

    def test_a_content_write_does_not_make_the_branch_dirty(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        json_dir = branch_path / "mybranch_json"
        json_dir.mkdir()
        log = json_dir / "thing_log.json"
        log.write_text("{}\n", encoding="utf-8")

        before = self._fps(branch_path, self._names_checker())
        log.write_text('{"grew": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}\n', encoding="utf-8")
        after = self._fps(branch_path, self._names_checker())

        added, changed, deleted, _ = incremental_cache.diff_fileset(before, after)
        assert not (added or changed or deleted)

    def test_adding_a_file_still_makes_the_branch_dirty(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        json_dir = branch_path / "mybranch_json"
        json_dir.mkdir()
        (json_dir / "thing_config.json").write_text("{}\n", encoding="utf-8")

        before = self._fps(branch_path, self._names_checker())
        (json_dir / "thing_data.json").write_text("{}\n", encoding="utf-8")
        after = self._fps(branch_path, self._names_checker())

        added, _, _, _ = incremental_cache.diff_fileset(before, after)
        assert "mybranch_json/thing_data.json" in added

    def test_deleting_a_file_still_makes_the_branch_dirty(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        json_dir = branch_path / "mybranch_json"
        json_dir.mkdir()
        victim = json_dir / "thing_config.json"
        victim.write_text("{}\n", encoding="utf-8")

        before = self._fps(branch_path, self._names_checker())
        victim.unlink()
        after = self._fps(branch_path, self._names_checker())

        _, _, deleted, _ = incremental_cache.diff_fileset(before, after)
        assert "mybranch_json/thing_config.json" in deleted

    def test_content_inputs_still_react_to_content(self, tmp_path, monkeypatch):
        """The two channels must not collapse into one another."""
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        (branch_path / ".trinity").mkdir()
        target = branch_path / ".trinity" / "local.json"
        target.write_text("{}\n", encoding="utf-8")
        checkers = {"trinity": types.SimpleNamespace(BRANCH_INPUTS=(".trinity/*",))}

        before = self._fps(branch_path, checkers)
        target.write_text('{"changed": "yyyyyyyyyyyyyyyyyyyyyyyyyyyy"}\n', encoding="utf-8")
        after = self._fps(branch_path, checkers)

        _, changed, _, _ = incremental_cache.diff_fileset(before, after)
        assert ".trinity/local.json" in changed


class TestNotApplicableStandardsLeaveTheGatingAverage:
    """A standard that reports ``not_applicable`` measured nothing, so it must
    not appear in scores[] at all -- a 0 would blame the branch for the
    environment and a 100 would claim a measurement that never happened.

    This is what turned CI red: trinity refused every group on a fresh clone
    (memories are gitignored) and branch_audit converted that into 0/FAILED
    for all 18 branches.
    """

    @staticmethod
    def _run(tmp_path, monkeypatch, result):
        """One standard under test alongside a healthy one.

        The healthy peer is not decoration: in CI the other 44 standards still
        measure and score, so the realistic question is whether the average
        reflects THEM once trinity stands down.
        """
        from aipass.seedgo.apps.handlers.audit import branch_audit

        branch, branch_path = _setup_branch(tmp_path, {})
        checker = types.SimpleNamespace(
            AUDIT_SCOPE="branch_level",
            check_branch=lambda p, bypass_rules=None: result,
        )
        healthy = types.SimpleNamespace(
            AUDIT_SCOPE="branch_level",
            check_branch=lambda p, bypass_rules=None: {"standard": "OTHER", "score": 100, "passed": True, "checks": []},
        )
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda _p=None: {"trinity": checker, "other": healthy})
        monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
        monkeypatch.setattr(branch_audit, "scan_branch", lambda p: None)
        return branch_audit.audit_branch(branch, [])

    def test_a_not_applicable_standard_is_absent_from_scores(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            {
                "standard": "TRINITY",
                "score": None,
                "passed": None,
                "not_applicable": True,
                "checks": [],
            },
        )

        assert "trinity" not in out["scores"]

    def test_it_does_not_drag_the_average_to_zero(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            {
                "standard": "TRINITY",
                "score": None,
                "passed": None,
                "not_applicable": True,
                "checks": [],
            },
        )

        # 100, not 50: the healthy peer is the whole gating population once
        # trinity steps out. A 0 or a 50 would both be trinity still counting.
        assert out["average"] == 100

    def test_the_result_is_still_carried_for_display(self, tmp_path, monkeypatch):
        """Excluded from scoring is not the same as hidden."""
        out = self._run(
            tmp_path,
            monkeypatch,
            {
                "standard": "TRINITY",
                "score": None,
                "passed": None,
                "not_applicable": True,
                "checks": [],
            },
        )

        assert out["results"]["trinity"]["not_applicable"] is True

    def test_an_ordinary_failing_standard_still_scores_zero(self, tmp_path, monkeypatch):
        """Over-refusal guard: only not_applicable steps out, never a failure."""
        out = self._run(
            tmp_path,
            monkeypatch,
            {
                "standard": "TRINITY",
                "score": 0,
                "passed": False,
                "checks": [],
            },
        )

        assert out["scores"]["trinity"] == 0


class TestTheCacheSeesStrayDirectories:
    """@daemon's finding: _declared_input_files ended with ``if
    match.is_file()``, so the cache fingerprinted files only -- while the File
    set group scores stray DIRECTORIES (_stray_names appends a slash to them).
    The one stray shape the cache could not see was the exact shape the File
    set ruling is about.

    Their repro, both directions: after removing .trinity/.recovery the cached
    audit still said 98 naming the gone directory, and after creating a stray
    directory the cached audit said 100 in 0.3s. --full disagreed with both.

    A directory is watched by PRESENCE, never content: its mtime moves every
    time a child changes, so content-watching it would churn the cache for
    edits that are already tracked file by file. The cache and the checker
    must see the same world, and now they do.
    """

    @staticmethod
    def _fps(branch_path, checkers):
        from aipass.seedgo.apps.handlers.audit import branch_audit, incremental_cache

        return incremental_cache.collect_fingerprints(branch_audit._collect_watch_files(branch_path, checkers))

    def _checkers(self):
        return {"trinity": types.SimpleNamespace(BRANCH_INPUTS=(".trinity/*",))}

    def test_a_new_stray_directory_makes_the_branch_dirty(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        (branch_path / ".trinity").mkdir()

        before = self._fps(branch_path, self._checkers())
        (branch_path / ".trinity" / ".recovery").mkdir()
        added, _, _, _ = incremental_cache.diff_fileset(before, self._fps(branch_path, self._checkers()))

        assert ".trinity/.recovery" in added

    def test_a_removed_stray_directory_makes_the_branch_dirty(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        (branch_path / ".trinity").mkdir()
        (branch_path / ".trinity" / ".recovery").mkdir()

        before = self._fps(branch_path, self._checkers())
        (branch_path / ".trinity" / ".recovery").rmdir()
        _, _, deleted, _ = incremental_cache.diff_fileset(before, self._fps(branch_path, self._checkers()))

        assert ".trinity/.recovery" in deleted

    def test_a_directorys_own_churn_does_not_dirty_the_branch(self, tmp_path, monkeypatch):
        """Presence, not content: a child write already shows as its own file,
        and a directory mtime would double-report it.
        """
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        sub = branch_path / ".trinity" / "sub"
        sub.mkdir(parents=True)

        before = self._fps(branch_path, self._checkers())
        # A file created inside is reported as that file, never as the dir.
        (sub / "child.json").write_text("{}\n", encoding="utf-8")
        added, changed, _, _ = incremental_cache.diff_fileset(before, self._fps(branch_path, self._checkers()))

        assert ".trinity/sub" not in changed

    def test_files_are_still_watched_by_content(self, tmp_path, monkeypatch):
        """Over-refusal guard: adding directories must not blind the file lane."""
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        (branch_path / ".trinity").mkdir()
        target = branch_path / ".trinity" / "local.json"
        target.write_text("{}\n", encoding="utf-8")

        before = self._fps(branch_path, self._checkers())
        target.write_text('{"changed": "zzzzzzzzzzzzzzzzzzzzzzzzzzzz"}\n', encoding="utf-8")
        _, changed, _, _ = incremental_cache.diff_fileset(before, self._fps(branch_path, self._checkers()))

        assert ".trinity/local.json" in changed

    def test_the_cache_and_the_checker_see_the_same_strays(self, tmp_path, monkeypatch):
        """The invariant the defect broke, asserted directly."""
        from aipass.seedgo.apps.handlers.aipass_standards import trinity_check
        from aipass.seedgo.apps.handlers.audit import branch_audit

        _, _, _, branch_path, _, _ = _prepare(tmp_path, monkeypatch, {})
        trinity_dir = branch_path / ".trinity"
        trinity_dir.mkdir()
        (trinity_dir / ".recovery").mkdir()
        (trinity_dir / "STATUS.local.md").write_text("x\n", encoding="utf-8")
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}\n", encoding="utf-8")

        seen_by_checker = {
            line.rstrip("/").split("/")[-1] for line in trinity_check.check_branch_info(str(branch_path))
        }
        watched = {
            f["rel"].split("/")[-1]
            for f in branch_audit._collect_watch_files(branch_path, self._checkers())
            if f["rel"].startswith(".trinity/")
        }

        assert seen_by_checker <= watched, f"checker sees {seen_by_checker - watched} that the cache cannot"


# ===========================================================================
# A FAILED CACHE SAVE MUST NOT LEAVE ITS STAGING FILE BEHIND
# ===========================================================================


class TestAFailedSaveLeavesNoStagingFile:
    """save_cache stages through tempfile.mkstemp then os.replace. The cleanup
    lived in `except Exception`, which has a real hole: BaseException --
    KeyboardInterrupt, SystemExit, GeneratorExit -- passes straight through it
    and the staging file survives on disk. That is not theoretical; a 4.3MB
    truncated tmp2ay2d070.tmp has been sitting in seedgo_json/ since
    2026-08-14, ending mid-token, exactly the shape of a save interrupted
    between write and replace.

    try/finally closes the interpreter-level hole. Stated honestly and NOT
    claimed by these tests: it does not survive SIGKILL, nor default-disposition
    SIGTERM, because neither unwinds the stack. Those still orphan, and no
    finally clause can change that.
    """

    def test_a_keyboard_interrupt_mid_write_leaves_no_tmp(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        monkeypatch.setattr(incremental_cache, "CACHE_FILE", tmp_path / "audit_cache.json")

        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(incremental_cache.json, "dump", interrupted)

        with pytest.raises(KeyboardInterrupt):
            incremental_cache.save_cache({"branches": {}})

        assert list(tmp_path.glob("*.tmp")) == []

    def test_an_ordinary_failure_mid_write_leaves_no_tmp(self, tmp_path, monkeypatch):
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        monkeypatch.setattr(incremental_cache, "CACHE_FILE", tmp_path / "audit_cache.json")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(incremental_cache.json, "dump", boom)

        with pytest.raises(OSError):
            incremental_cache.save_cache({"branches": {}})

        assert list(tmp_path.glob("*.tmp")) == []

    def test_the_success_path_leaves_no_tmp_and_does_not_double_unlink(self, tmp_path, monkeypatch):
        """os.replace consumes the staging file, so the finally clause must
        tolerate its absence rather than raise over it.
        """
        from aipass.seedgo.apps.handlers.audit import incremental_cache

        cache_file = tmp_path / "audit_cache.json"
        monkeypatch.setattr(incremental_cache, "CACHE_FILE", cache_file)

        incremental_cache.save_cache({"branches": {"x": {"stamp": "abc"}}})

        assert cache_file.is_file()
        assert list(tmp_path.glob("*.tmp")) == []
