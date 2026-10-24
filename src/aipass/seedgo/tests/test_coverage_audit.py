# =================== AIPass ====================
# Name: test_coverage_audit.py
# Description: Unit tests for branch_audit.py: checker discovery, the corpus, the file lane, diagnostics
# Version: 1.4.1
# Created: 2026-04-26
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/audit/branch_audit.py."""

# The audit's first phases: checker discovery, the corpus walk, branch-level
# extraction, the all_files lane and the diagnostics loader. The render phase
# (audit_display.py) and audit_branch's orchestration live in the
# test_coverage_audit_*.py siblings (split 2026-10-08 under oversize_test_file).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that branch_audit.py parses and imports

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
from aipass.seedgo.apps.handlers.audit import branch_audit
from aipass.seedgo.apps.handlers.bypass.ignore_handler import audit_ignore_match as real_audit_ignore_match

pytestmark = pytest.mark.usefixtures("coverage_audit_seams")


# ===========================================================================
# BRANCH_AUDIT TESTS
# ===========================================================================


class TestDiscoverCheckers:
    """Tests for discover_checkers."""

    def test_discover_from_path(self, tmp_path):
        """Discovers *_check.py modules with check_module."""
        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "naming_check.py"
        checker_file.write_text(
            "def check_module(path, bypass_rules=None):\n"
            "    return {\n"
            "        'passed': True, 'score': 100, 'checks': []\n"
            "    }\n",
            encoding="utf-8",
        )
        result = branch_audit.discover_checkers(standards_dir)
        assert "naming" in result

    def test_skip_without_check_functions(self, tmp_path):
        """Skips modules without check_module or check_branch."""
        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "bad_check.py"
        checker_file.write_text("x = 42\n", encoding="utf-8")
        result = branch_audit.discover_checkers(standards_dir)
        assert "bad" not in result

    def test_skip_failing_load(self, tmp_path):
        """Skips modules that raise during exec_module."""
        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "broken_check.py"
        checker_file.write_text("raise RuntimeError('broken')\n", encoding="utf-8")
        result = branch_audit.discover_checkers(standards_dir)
        assert "broken" not in result

    def test_empty_directory(self, tmp_path):
        """Empty standards dir returns empty dict."""
        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        result = branch_audit.discover_checkers(standards_dir)
        assert result == {}

    def test_spec_none_skipped(self, tmp_path):
        """Files where spec_from_file_location returns None skipped."""
        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "valid_check.py"
        checker_file.write_text(
            "def check_module(path, bypass_rules=None):\n"
            "    return {\n"
            "        'passed': True, 'score': 100, 'checks': []\n"
            "    }\n",
            encoding="utf-8",
        )
        with patch(
            "importlib.util.spec_from_file_location",
            return_value=None,
        ):
            result = branch_audit.discover_checkers(standards_dir)
        assert "valid" not in result

    def test_check_branch_function_discovered(self, tmp_path):
        """Modules with check_branch are discovered."""
        standards_dir = tmp_path / "standards"
        standards_dir.mkdir()
        checker_file = standards_dir / "branch_check.py"
        checker_file.write_text(
            "def check_branch(path, bypass_rules=None):\n"
            "    return {\n"
            "        'passed': True, 'score': 100, 'checks': []\n"
            "    }\n",
            encoding="utf-8",
        )
        result = branch_audit.discover_checkers(standards_dir)
        assert "branch" in result


def _recording_checker(answer=None, scope: str = "all_files", include_init: bool = False) -> types.SimpleNamespace:
    """A per-file checker that records the NAME of every file it is handed.

    *answer* maps a file name to the result dict; the default passes everything
    at 100. ``seen`` is the record the corpus tests read.
    """
    seen: list = []

    def check_module(module_path, bypass_rules=None):
        name = Path(module_path).name
        seen.append(name)
        if answer is not None:
            return answer(name)
        return {"passed": True, "score": 100, "checks": [{"passed": True, "message": "OK"}]}

    return types.SimpleNamespace(
        AUDIT_SCOPE=scope, INCLUDE_INIT_FILES=include_init, check_module=check_module, seen=seen
    )


def _audit_corpus(monkeypatch, root: Path, checkers: dict, files=()) -> dict:
    """audit_branch over a branch at *root* holding *files*, judged by *checkers*.

    The entry file is ``entry.py`` at the branch root, never written and outside
    apps/, so a file under apps/ reaches a checker only through the corpus.
    tmp_path lies under the system temp root, which is_throwaway_path drops
    wholesale; emptying the root list lets the real predicate judge each file.
    The diagnostics loader would run pyright over the branch; it is silenced
    here, and its own lane is pinned by test_diagnostics_checker_added.
    """
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(branch_audit, "discover_checkers", lambda pack_path=None: checkers)
    monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("pass", encoding="utf-8")
    branch = {"name": "corpus", "entry_file": str(root / "entry.py"), "path": str(root)}
    return branch_audit.audit_branch(branch, [])


def _checked(checker: types.SimpleNamespace) -> set:
    """The corpus file names a recording checker was handed, the entry file left out."""
    return set(checker.seen) - {"entry.py"}


class TestCollectPyFiles:
    """The corpus audit_branch walks: what reaches an all_files checker."""

    def test_no_apps_dir(self, tmp_path, monkeypatch):
        """No apps/ means an empty corpus, whatever sits at the root. Mutant: apps_dir read as the branch root in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker()
        result = _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=("setup.py",))
        assert result["files_checked"] == 0
        assert _checked(checker) == set()

    def test_collects_py_files(self, tmp_path, monkeypatch):
        """Collects .py from apps/, excluding __init__.py. Mutant: __init__.py always collected in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker()
        files = ("apps/__init__.py", "apps/module.py", "apps/handlers/handler.py")
        _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=files)
        names = _checked(checker)
        assert "module.py" in names
        assert "handler.py" in names
        assert "__init__.py" not in names

    def test_collects_init_files_when_requested(self, tmp_path, monkeypatch):
        """INCLUDE_INIT_FILES keeps __init__.py, for import checkers that must not miss them.

        Mutant: the init walk asked for no inits in apps/handlers/audit/branch_audit.py — killed.
        """
        checker = _recording_checker(include_init=True)
        _audit_corpus(monkeypatch, tmp_path, {"handlers": checker}, files=("apps/__init__.py", "apps/module.py"))
        names = _checked(checker)
        assert "module.py" in names
        assert "__init__.py" in names

    def test_respects_ignore_patterns(self, tmp_path, monkeypatch):
        """Files matching ignore patterns are excluded. Mutant: the ignore match discarded in apps/handlers/audit/branch_audit.py — killed."""
        # The real matcher over branch-relative paths: the tmp_path name cannot collide.
        monkeypatch.setattr(branch_audit.ignore_handler, "audit_ignore_match", real_audit_ignore_match)
        checker = _recording_checker()
        files = ("apps/module.py", "apps/integrations/google/driver.py", "apps/handlers/integrations/call.py")
        _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=files)
        assert sorted(_checked(checker)) == ["call.py", "module.py"]

    def test_excludes_disabled_files(self, tmp_path, monkeypatch):
        """Files with (disabled) in the name are excluded. Mutant: the disabled-name test dropped in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker()
        files = ("apps/module.py", "apps/dashboard_sync(disabled).py")
        _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=files)
        names = _checked(checker)
        assert "module.py" in names
        assert "dashboard_sync(disabled).py" not in names

    def test_respects_seedgo_ignore_tools_dir(self, tmp_path, monkeypatch):
        """Files under apps/tools/ are excluded via the global .seedgoignore default. Mutant: .seedgoignore not consulted in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker()
        _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=("apps/module.py", "apps/tools/scratch.py"))
        names = _checked(checker)
        assert "module.py" in names
        assert "scratch.py" not in names


def _branch_level(result: dict) -> types.SimpleNamespace:
    """A branch-level checker whose whole-branch answer is *result*."""
    return types.SimpleNamespace(AUDIT_SCOPE="branch_level", check_branch=lambda branch_path, bypass_rules=None: result)


class TestExtractBranchLevelViolations:
    """A branch-level result's per-file findings, as audit_branch reports them."""

    def test_empty_result(self, tmp_path, monkeypatch):
        """Empty result reports no violations and no crash. Mutant: checks read without a default in apps/handlers/audit/branch_audit.py — killed."""
        result = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level({})})
        assert result["dead_code_violations"] == []
        assert "error" not in result["results"]["dead_code"]

    def test_extracts_violations(self, tmp_path, monkeypatch):
        """Extracts violations from checks with list-type keys. Mutant: each file keeps only its last finding in apps/handlers/audit/branch_audit.py — killed."""
        found = {
            "checks": [
                {
                    "name": "unused_check",
                    "passed": False,
                    "message": "Found unused",
                    "unused": [
                        {
                            "file": "/foo.py",
                            "name": "bar",
                            "line": 10,
                        },
                        {
                            "file": "/foo.py",
                            "name": "baz",
                            "line": 20,
                        },
                    ],
                },
            ]
        }
        violations = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level(found)})["dead_code_violations"]
        assert len(violations) == 1
        assert violations[0]["file"] == "/foo.py"
        assert len(violations[0]["issues"]) == 2

    def test_skips_non_list_keys(self, tmp_path, monkeypatch):
        """Skips standard keys (name, passed, message, score). Mutant: no key skipped in apps/handlers/audit/branch_audit.py — killed."""
        found = {
            "checks": [
                {
                    "name": "check",
                    "passed": True,
                    "message": "ok",
                    "score": 100,
                },
            ]
        }
        result = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level(found)})
        assert result["dead_code_violations"] == []
        assert "error" not in result["results"]["dead_code"]

    def test_skips_items_without_file_key(self, tmp_path, monkeypatch):
        """Skips list items without a file key. Mutant: the file-key guard dropped in apps/handlers/audit/branch_audit.py — killed."""
        found = {
            "checks": [
                {
                    "name": "check",
                    "passed": False,
                    "message": "err",
                    "items": [{"name": "orphan"}],
                },
            ]
        }
        result = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level(found)})
        assert result["dead_code_violations"] == []
        assert "error" not in result["results"]["dead_code"]

    def test_multiple_files(self, tmp_path, monkeypatch):
        """Groups violations by file path. Mutant: every finding grouped under one file in apps/handlers/audit/branch_audit.py — killed."""
        found = {
            "checks": [
                {
                    "name": "dead",
                    "passed": False,
                    "message": "found dead",
                    "dead_functions": [
                        {
                            "file": "/a.py",
                            "name": "f_a",
                            "line": 1,
                        },
                        {
                            "file": "/b.py",
                            "name": "f_b",
                            "line": 2,
                        },
                    ],
                },
            ]
        }
        violations = _audit_corpus(monkeypatch, tmp_path, {"dead_code": _branch_level(found)})["dead_code_violations"]
        assert len(violations) == 2
        files = {v["file"] for v in violations}
        assert "/a.py" in files
        assert "/b.py" in files


class TestRunAllFiles:
    """The all_files lane of audit_branch: every corpus file through one checker."""

    def test_basic_run(self, tmp_path, monkeypatch):
        """Basic run collects scores from passing checks. Mutant: each file's score recorded as 0 in apps/handlers/audit/branch_audit.py — killed."""
        checker = _recording_checker(
            lambda name: {"passed": True, "score": 90, "checks": [{"passed": True, "message": "OK"}]}
        )
        result = _audit_corpus(monkeypatch, tmp_path, {"naming": checker}, files=("apps/foo.py",))
        assert "foo.py" in _checked(checker)
        assert result["scores"]["naming"] == 90

    def test_checker_raises_exception(self, tmp_path, monkeypatch):
        """A crash is a failing file named in the violations, never a silently dropped one."""

        def answer(name):
            if name == "foo.py":
                raise RuntimeError("boom")
            return {"passed": True, "score": 100, "checks": [{"passed": True, "message": "OK"}]}

        result = _audit_corpus(
            monkeypatch, tmp_path, {"naming": _recording_checker(answer)}, files=("apps/foo.py", "apps/bar.py")
        )
        (violation,) = result["naming_violations"]
        assert (violation["file"], violation["score"]) == ("foo.py", 0)
        assert "RuntimeError: boom" in violation["message"]
        # Dropped, the crash averaged to 100 on bar.py alone; counted, it pulls the row to 50.
        assert result["scores"]["naming"] == 50

    def test_a_declined_check_is_excluded_and_named(self, tmp_path, monkeypatch):
        """A file stands down on the declined field, never on its message's words. Mutant: declined files averaged in apps/handlers/audit/branch_audit.py — killed."""

        def answer(name):
            if name == "foo.py":
                return {
                    "passed": True,
                    "score": 100,
                    "checks": [{"passed": True, "declined": True, "message": "Not a naming target"}],
                }
            return {"passed": True, "score": 40, "checks": [{"passed": True, "message": "fine"}]}

        result = _audit_corpus(
            monkeypatch, tmp_path, {"naming": _recording_checker(answer)}, files=("apps/foo.py", "apps/bar.py")
        )
        assert result["scores"]["naming"] == 40
        assert result["declined"] == {"naming": ["apps/foo.py"]}

    def test_failing_checks_collected(self, tmp_path, monkeypatch):
        """Failing checks collected as violations. Mutant: failures kept only above score 50 in apps/handlers/audit/branch_audit.py — killed."""

        def answer(name):
            return {
                "passed": False,
                "score": 40,
                "checks": [
                    {"passed": False, "message": "Bad naming"},
                    {"passed": True, "message": "OK"},
                ],
            }

        result = _audit_corpus(monkeypatch, tmp_path, {"naming": _recording_checker(answer)}, files=("apps/bad.py",))
        violations = [v for v in result["naming_violations"] if v["file"] == "bad.py"]
        assert len(violations) == 1
        assert violations[0]["score"] == 40
        assert "Bad naming" in violations[0]["issues"]


class TestLoadDiagnosticsChecker:
    """Tests for _load_diagnostics_checker.

    HELD (seedgo, fleet green leg 8): the loader is the unit. audit_branch shows
    its None arms only as a missing "diagnostics" result, and reaching them from
    there takes a seam for the module path (a product question), not the
    process-wide patches these tests carry today.
    """

    def test_path_not_exists(self):
        """Returns None when diagnostics file does not exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = branch_audit._load_diagnostics_checker()
        assert result is None

    def test_spec_none(self):
        """Returns None when spec_from_file_location is None."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "importlib.util.spec_from_file_location",
                return_value=None,
            ),
        ):
            result = branch_audit._load_diagnostics_checker()
        assert result is None

    def test_exec_module_raises(self):
        """A checker that fails while loading raises, never the None of an absent one (fleet green leg 14)."""
        mock_spec = MagicMock()
        mock_spec.loader.exec_module.side_effect = RuntimeError("fail")
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "importlib.util.spec_from_file_location",
                return_value=mock_spec,
            ),
            patch(
                "importlib.util.module_from_spec",
                return_value=MagicMock(),
            ),
            pytest.raises(RuntimeError, match="^fail$"),
        ):
            branch_audit._load_diagnostics_checker()

    def test_successful_load(self):
        """Returns module when loading succeeds."""
        mock_mod = MagicMock()
        mock_spec = MagicMock()
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "importlib.util.spec_from_file_location",
                return_value=mock_spec,
            ),
            patch(
                "importlib.util.module_from_spec",
                return_value=mock_mod,
            ),
        ):
            result = branch_audit._load_diagnostics_checker()
        assert result is mock_mod
