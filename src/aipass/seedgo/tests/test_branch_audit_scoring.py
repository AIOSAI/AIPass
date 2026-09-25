# =================== META ====================
# Name: test_branch_audit_scoring.py
# Description: audit_branch's all_files row — which files the average counts
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/audit/branch_audit.py, the all_files row's average."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — the cache serving or re-running a row; tests/test_incremental_audit.py
# seedgo: no-test-needed(shared) — os.walk convictions themselves; tests/test_os_walk_onerror_check.py

import types
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import os_walk_onerror_check, skip_dirs
from aipass.seedgo.apps.handlers.audit import branch_audit

WALKER = "import os\n\n\ndef files(root):\n    return [d for d, _, _ in os.walk(root)]\n"


def _checker(verdicts):
    """An all_files checker whose result for a file is looked up by its name."""
    return types.SimpleNamespace(
        AUDIT_SCOPE="all_files",
        check_module=lambda path, bypass_rules=None: verdicts.get(Path(path).name, PASS),
    )


PASS = {"passed": True, "score": 100, "checks": [{"passed": True, "message": "OK"}]}


@pytest.fixture
def audit(tmp_path, monkeypatch):
    """Audit a branch under tmp_path with only the given checkers."""
    # tmp_path sits under the system temp root, which the corpus drops as throwaway.
    monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])
    monkeypatch.setattr(branch_audit, "_load_diagnostics_checker", lambda: None)
    monkeypatch.setattr(branch_audit, "scan_branch", lambda path: None)

    def run(checkers, files):
        apps = tmp_path / "mybranch" / "apps"
        apps.mkdir(parents=True)
        (apps / "main.py").write_text("pass\n", encoding="utf-8")
        for name, body in files.items():
            (apps / name).write_text(body, encoding="utf-8")
        monkeypatch.setattr(branch_audit, "discover_checkers", lambda _pack=None: checkers)
        branch = {"name": "mybranch", "entry_file": str(apps / "main.py"), "path": str(apps.parent)}
        return branch_audit.audit_branch(branch, [])

    return run


class TestAFailingFileIsAlwaysAveraged:
    def test_a_failure_whose_message_says_skipped_scores_the_row_down(self, audit):
        """The shipped defect: os_walk_onerror's "is skipped in silence" read as not applicable."""
        out = audit({"os_walk_onerror": os_walk_onerror_check}, {"walker.py": WALKER})
        assert out["scores"]["os_walk_onerror"] == 50
        assert [v["file"] for v in out["os_walk_onerror_violations"]] == ["walker.py"]

    def test_a_failure_beside_a_passing_skipped_check_is_averaged(self, audit):
        mixed = {
            "passed": False,
            "score": 0,
            "checks": [
                {"passed": True, "message": "Bypassed - thin orchestration check skipped"},
                {"passed": False, "message": "Business logic in a module"},
            ],
        }
        out = audit({"modules": _checker({"bad.py": mixed})}, {"bad.py": "pass\n"})
        assert out["scores"]["modules"] == 50


class TestAPassingNotApplicableFileStaysOut:
    @pytest.mark.parametrize("message", ["Not an entry point (skipped)", "No try/except blocks (not applicable)"])
    def test_its_score_does_not_reach_the_average(self, audit, message):
        standing_down = {"passed": True, "score": 0, "checks": [{"passed": True, "message": message}]}
        out = audit({"cli": _checker({"other.py": standing_down})}, {"other.py": "pass\n"})
        assert out["scores"]["cli"] == 100
