# =================== META ====================
# Name: test_handler_import.py
# Description: Unit tests for handler_import_check checker handler
# Version: 2.0.1
# Created: 2026-04-26
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/handler_import_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the checker and its content module import

from pathlib import Path

from aipass.seedgo.apps.handlers.aipass_standards import handler_import_content
from aipass.seedgo.apps.handlers.aipass_standards.handler_import_check import check_branch


def _write_file(path: Path, content: str) -> None:
    """Write content to a file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestHandlerImportCheck:
    """Tests for the handler_import_check checker."""

    def test_branch_with_handler_import_passes(self, tmp_path: Path) -> None:
        """apps/__init__.py containing 'from . import handlers' scores 100."""
        _write_file(tmp_path / "apps" / "__init__.py", "from . import handlers\n")

        result = check_branch(str(tmp_path))
        assert result["passed"] is True
        assert result["score"] == 100
        assert result["standard"] == "HANDLER_IMPORT"

    def test_branch_missing_handler_import_fails(self, tmp_path: Path) -> None:
        """apps/__init__.py without the handler import scores 0."""
        _write_file(tmp_path / "apps" / "__init__.py", "from . import modules\n")

        result = check_branch(str(tmp_path))
        assert result["passed"] is False
        assert result["score"] == 0
        assert result["standard"] == "HANDLER_IMPORT"
        failed = [c for c in result["checks"] if not c["passed"]]
        assert len(failed) == 1
        assert "missing" in failed[0]["message"]

    def test_branch_no_apps_init_fails(self, tmp_path: Path) -> None:
        """Branch with apps/ but no apps/__init__.py scores 0."""
        (tmp_path / "apps").mkdir(parents=True)

        result = check_branch(str(tmp_path))
        assert result["passed"] is False
        assert result["score"] == 0
        assert "not found" in result["checks"][0]["message"]

    def test_branch_bypassed(self, tmp_path: Path) -> None:
        """A bypass rule for the standard scores 100 even with no apps/ at all."""
        result = check_branch(str(tmp_path), bypass_rules=[{"file": str(tmp_path), "standard": "handler_import"}])
        assert result["passed"] is True
        assert result["score"] == 100
        assert result["checks"][0]["name"] == "Bypassed"

    def test_branch_no_apps_dir(self, tmp_path: Path) -> None:
        """Branch with no apps/ directory at all scores 0."""
        result = check_branch(str(tmp_path))
        assert result["passed"] is False
        assert result["score"] == 0
        assert "not found" in result["checks"][0]["message"]

    def test_content_names_the_standard(self) -> None:
        """get_handler_import_standards() returns the HANDLER IMPORT standard text."""
        assert "HANDLER IMPORT" in handler_import_content.get_handler_import_standards()
