# ===================AIPASS====================
# META DATA HEADER
# Name: test_memory_health.py - Memory Health Handler Tests
# Date: 2026-03-24
# Version: 1.0.0
# Category: daemon/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-24): Initial creation - memory health tests
#
# CODE STANDARDS:
#   - Pytest conventions
#   - Temp dir isolation via tmp_path
# =============================================

"""Tests for the memory health handler."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.daemon.apps.handlers.monitoring import memory_health as mh


# =============================================
# HELPERS
# =============================================

def _write_json(path: Path, data: dict) -> None:
    """Write a dict to a JSON file, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def _valid_memory_json() -> dict:
    """Return a valid memory file structure with metadata and limits."""
    return {
        "document_metadata": {
            "document_type": "session_history",
            "version": "1.0.0",
            "limits": {"max_lines": 600},
        },
        "sessions": [],
    }


def _setup_full_branch(tmp_path: Path) -> Path:
    """Create a fully populated branch directory with all memory files."""
    branch = tmp_path / "TESTBRANCH"
    trinity = branch / ".trinity"
    trinity.mkdir(parents=True)

    _write_json(trinity / "local.json", _valid_memory_json())
    _write_json(trinity / "observations.json", _valid_memory_json())
    (branch / "README.md").write_text("# Test", encoding="utf-8")
    _write_json(branch / "DASHBOARD.local.json", {"status": "ok"})

    return branch


# =============================================
# FILE EXISTENCE TESTS
# =============================================

class TestCheckMemoryFilesExist:
    """Tests for check_memory_files_exist()."""

    def test_all_files_present(self, tmp_path: Path) -> None:
        """All required and optional files present returns clean result."""
        branch = _setup_full_branch(tmp_path)
        result = mh.check_memory_files_exist(str(branch), "TESTBRANCH")

        assert result["all_required_present"] is True
        assert result["missing_required"] == []
        assert result["missing_optional"] == []
        assert result["required"][".trinity/local.json"] is True
        assert result["required"]["README.md"] is True

    def test_missing_all_files(self, tmp_path: Path) -> None:
        """Empty directory has all files missing."""
        branch = tmp_path / "EMPTY"
        branch.mkdir()
        result = mh.check_memory_files_exist(str(branch), "EMPTY")

        assert result["all_required_present"] is False
        assert ".trinity/local.json" in result["missing_required"]
        assert "README.md" in result["missing_required"]
        assert ".trinity/observations.json" in result["missing_optional"]
        assert "DASHBOARD.local.json" in result["missing_optional"]

    def test_missing_local_json_only(self, tmp_path: Path) -> None:
        """Missing .trinity/local.json flags required missing."""
        branch = tmp_path / "PARTIAL"
        branch.mkdir()
        (branch / "README.md").write_text("# Readme", encoding="utf-8")

        result = mh.check_memory_files_exist(str(branch), "PARTIAL")

        assert result["all_required_present"] is False
        assert ".trinity/local.json" in result["missing_required"]
        assert "README.md" not in result["missing_required"]

    def test_missing_readme_only(self, tmp_path: Path) -> None:
        """Missing README.md flags required missing."""
        branch = tmp_path / "NO_README"
        trinity = branch / ".trinity"
        trinity.mkdir(parents=True)
        _write_json(trinity / "local.json", {})

        result = mh.check_memory_files_exist(str(branch), "NO_README")

        assert result["all_required_present"] is False
        assert "README.md" in result["missing_required"]
        assert ".trinity/local.json" not in result["missing_required"]

    def test_optional_observations_present(self, tmp_path: Path) -> None:
        """observations.json present removes it from missing_optional."""
        branch = tmp_path / "WITH_OBS"
        trinity = branch / ".trinity"
        trinity.mkdir(parents=True)
        _write_json(trinity / "observations.json", {})

        result = mh.check_memory_files_exist(str(branch), "WITH_OBS")

        assert result["optional"][".trinity/observations.json"] is True
        assert ".trinity/observations.json" not in result["missing_optional"]

    def test_optional_dashboard_present(self, tmp_path: Path) -> None:
        """DASHBOARD.local.json present removes it from missing_optional."""
        branch = tmp_path / "WITH_DASH"
        branch.mkdir()
        _write_json(branch / "DASHBOARD.local.json", {})

        result = mh.check_memory_files_exist(str(branch), "WITH_DASH")

        assert result["optional"]["DASHBOARD.local.json"] is True
        assert "DASHBOARD.local.json" not in result["missing_optional"]

    def test_directory_not_counted_as_file(self, tmp_path: Path) -> None:
        """A directory named README.md should not count as the file."""
        branch = tmp_path / "DIR_TRICK"
        branch.mkdir()
        (branch / "README.md").mkdir()  # directory, not file

        result = mh.check_memory_files_exist(str(branch), "DIR_TRICK")

        assert result["required"]["README.md"] is False
        assert "README.md" in result["missing_required"]


# =============================================
# STRUCTURE VALIDATION TESTS
# =============================================

class TestValidateMemoryStructure:
    """Tests for validate_memory_structure()."""

    def test_valid_structure_with_document_metadata(self, tmp_path: Path) -> None:
        """Valid file with document_metadata and limits passes."""
        f = tmp_path / "valid.json"
        _write_json(f, _valid_memory_json())

        result = mh.validate_memory_structure(str(f))

        assert result["valid"] is True
        assert result["has_metadata"] is True
        assert result["has_limits"] is True
        assert result["issues"] == []
        assert "document_type" in result["metadata_fields"]
        assert "limits" in result["metadata_fields"]

    def test_valid_structure_with_metadata_key(self, tmp_path: Path) -> None:
        """File using 'metadata' key (instead of 'document_metadata') is valid."""
        f = tmp_path / "alt_meta.json"
        _write_json(f, {
            "metadata": {
                "version": "1.0.0",
                "limits": {"max_entries": 100},
            },
        })

        result = mh.validate_memory_structure(str(f))

        assert result["valid"] is True
        assert result["has_metadata"] is True
        assert result["has_limits"] is True

    def test_missing_limits_field(self, tmp_path: Path) -> None:
        """Metadata present but no limits field should report issue."""
        f = tmp_path / "no_limits.json"
        _write_json(f, {
            "document_metadata": {
                "document_type": "session_history",
                "version": "1.0.0",
            },
        })

        result = mh.validate_memory_structure(str(f))

        assert result["valid"] is False
        assert result["has_metadata"] is True
        assert result["has_limits"] is False
        assert any("limits" in issue for issue in result["issues"])

    def test_no_metadata_section(self, tmp_path: Path) -> None:
        """File with no metadata section at all."""
        f = tmp_path / "bare.json"
        _write_json(f, {"sessions": [], "data": "hello"})

        result = mh.validate_memory_structure(str(f))

        assert result["valid"] is False
        assert result["has_metadata"] is False
        assert result["has_limits"] is False
        assert any("metadata" in issue.lower() for issue in result["issues"])

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Malformed JSON returns invalid with error."""
        f = tmp_path / "broken.json"
        f.write_text("{not valid json", encoding="utf-8")

        result = mh.validate_memory_structure(str(f))

        assert result["valid"] is False
        assert result["has_metadata"] is False
        assert any("Invalid JSON" in issue for issue in result["issues"])

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Nonexistent file path returns invalid."""
        result = mh.validate_memory_structure(str(tmp_path / "ghost.json"))

        assert result["valid"] is False
        assert result["issues"] == ["File does not exist"]
        assert result["metadata_fields"] == []

    def test_empty_json_object(self, tmp_path: Path) -> None:
        """Empty JSON object {} has no metadata."""
        f = tmp_path / "empty.json"
        _write_json(f, {})

        result = mh.validate_memory_structure(str(f))

        assert result["valid"] is False
        assert result["has_metadata"] is False


# =============================================
# FRESHNESS TESTS
# =============================================

class TestCheckFreshness:
    """Tests for check_freshness()."""

    def test_fresh_file_is_ok(self, tmp_path: Path) -> None:
        """A just-created file should be OK."""
        f = tmp_path / "fresh.json"
        f.write_text("{}", encoding="utf-8")

        result = mh.check_freshness(str(f))

        assert result["exists"] is True
        assert result["status"] == "OK"
        assert result["days_ago"] is not None
        assert result["days_ago"] < 1
        assert result["last_modified"] is not None

    def test_warning_threshold(self, tmp_path: Path) -> None:
        """File older than warning_days but under red_days gives WARNING."""
        f = tmp_path / "stale.json"
        f.write_text("{}", encoding="utf-8")
        # Set mtime to 10 days ago
        ten_days_ago = time.time() - (10 * 86400)
        os.utime(f, (ten_days_ago, ten_days_ago))

        result = mh.check_freshness(str(f), warning_days=7, red_days=30)

        assert result["status"] == "WARNING"
        assert result["days_ago"] is not None
        assert result["days_ago"] > 7

    def test_red_threshold(self, tmp_path: Path) -> None:
        """File older than red_days gives RED."""
        f = tmp_path / "ancient.json"
        f.write_text("{}", encoding="utf-8")
        # Set mtime to 45 days ago
        old_time = time.time() - (45 * 86400)
        os.utime(f, (old_time, old_time))

        result = mh.check_freshness(str(f), warning_days=7, red_days=30)

        assert result["status"] == "RED"
        assert result["days_ago"] is not None
        assert result["days_ago"] > 30

    def test_nonexistent_file_is_red(self, tmp_path: Path) -> None:
        """Nonexistent file returns RED status."""
        result = mh.check_freshness(str(tmp_path / "missing.json"))

        assert result["exists"] is False
        assert result["status"] == "RED"
        assert result["last_modified"] is None
        assert result["days_ago"] is None
        assert result["message"] == "File does not exist"

    def test_custom_thresholds(self, tmp_path: Path) -> None:
        """Custom warning/red thresholds are respected."""
        f = tmp_path / "custom.json"
        f.write_text("{}", encoding="utf-8")
        # Set mtime to 3 days ago
        three_days_ago = time.time() - (3 * 86400)
        os.utime(f, (three_days_ago, three_days_ago))

        # With tight thresholds: warning at 2 days, red at 5 days
        result = mh.check_freshness(str(f), warning_days=2, red_days=5)

        assert result["status"] == "WARNING"

    def test_exactly_at_boundary_uses_ok(self, tmp_path: Path) -> None:
        """File modified exactly now should be OK, not WARNING."""
        f = tmp_path / "now.json"
        f.write_text("{}", encoding="utf-8")

        result = mh.check_freshness(str(f), warning_days=7, red_days=30)

        # Setting mtime to "now" yields 0 days ago which is < warning_days
        assert result["exists"] is True
        assert result["status"] == "OK"

    def test_days_ago_is_rounded(self, tmp_path: Path) -> None:
        """days_ago value is a numeric type."""
        f = tmp_path / "rounded.json"
        f.write_text("{}", encoding="utf-8")

        result = mh.check_freshness(str(f))

        assert result["days_ago"] is not None
        assert isinstance(result["days_ago"], (int, float))


# =============================================
# OVERALL HEALTH STATUS TESTS
# =============================================

class TestGetMemoryHealthStatus:
    """Tests for get_memory_health_status()."""

    @pytest.fixture(autouse=True)
    def _mock_log_operation(self):
        """Prevent json_handler.log_operation from touching real files."""
        with patch.object(mh.json_handler, "log_operation"):
            yield

    def test_healthy_branch_returns_ok(self, tmp_path: Path) -> None:
        """Branch with all files, valid structure, and fresh data returns OK."""
        branch = _setup_full_branch(tmp_path)

        result = mh.get_memory_health_status(str(branch), "TESTBRANCH")

        assert result["overall_status"] == "OK"
        assert result["branch_name"] == "TESTBRANCH"
        assert result["branch_path"] == str(branch)
        assert result["issues"] == []
        assert "check_time" in result

    def test_missing_required_file_returns_red(self, tmp_path: Path) -> None:
        """Missing a required file yields RED overall status."""
        branch = tmp_path / "NOREQUIRED"
        branch.mkdir()
        # Only create optional files, no required ones

        result = mh.get_memory_health_status(str(branch), "NOREQUIRED")

        assert result["overall_status"] == "RED"
        assert any("Missing required" in issue for issue in result["issues"])

    def test_missing_optional_file_returns_warning(self, tmp_path: Path) -> None:
        """Missing an optional file yields WARNING overall status."""
        branch = tmp_path / "NOOPT"
        trinity = branch / ".trinity"
        trinity.mkdir(parents=True)
        _write_json(trinity / "local.json", _valid_memory_json())
        (branch / "README.md").write_text("# Test", encoding="utf-8")
        # No observations.json, no DASHBOARD.local.json

        result = mh.get_memory_health_status(str(branch), "NOOPT")

        assert result["overall_status"] == "WARNING"
        assert any("Missing optional" in issue for issue in result["issues"])

    def test_stale_files_returns_warning(self, tmp_path: Path) -> None:
        """Files older than warning threshold yield WARNING."""
        branch = _setup_full_branch(tmp_path)

        # Make local.json 10 days old
        local_file = branch / ".trinity" / "local.json"
        ten_days_ago = time.time() - (10 * 86400)
        os.utime(local_file, (ten_days_ago, ten_days_ago))
        readme = branch / "README.md"
        os.utime(readme, (ten_days_ago, ten_days_ago))

        result = mh.get_memory_health_status(str(branch), "STALE")

        assert result["overall_status"] == "WARNING"

    def test_very_stale_files_returns_red(self, tmp_path: Path) -> None:
        """Files older than red threshold yield RED."""
        branch = _setup_full_branch(tmp_path)

        # Make local.json 45 days old
        local_file = branch / ".trinity" / "local.json"
        old_time = time.time() - (45 * 86400)
        os.utime(local_file, (old_time, old_time))

        result = mh.get_memory_health_status(str(branch), "ANCIENT")

        assert result["overall_status"] == "RED"

    def test_invalid_structure_promotes_to_warning(self, tmp_path: Path) -> None:
        """Invalid memory structure promotes OK to WARNING."""
        branch = tmp_path / "BADSTRUCT"
        trinity = branch / ".trinity"
        trinity.mkdir(parents=True)

        # Write local.json with no metadata (invalid structure)
        _write_json(trinity / "local.json", {"sessions": []})
        _write_json(trinity / "observations.json", _valid_memory_json())
        (branch / "README.md").write_text("# Test", encoding="utf-8")
        _write_json(branch / "DASHBOARD.local.json", {"status": "ok"})

        result = mh.get_memory_health_status(str(branch), "BADSTRUCT")

        assert result["overall_status"] == "WARNING"
        assert ".trinity/local.json" in result["structure_checks"]

    def test_structure_checks_only_for_existing_files(self, tmp_path: Path) -> None:
        """Structure checks are only performed on files that exist."""
        branch = tmp_path / "MINIMAL"
        trinity = branch / ".trinity"
        trinity.mkdir(parents=True)
        _write_json(trinity / "local.json", _valid_memory_json())
        (branch / "README.md").write_text("# Test", encoding="utf-8")

        result = mh.get_memory_health_status(str(branch), "MINIMAL")

        # local.json exists, so it should be checked
        assert ".trinity/local.json" in result["structure_checks"]
        # observations.json does not exist, so it should not be in structure_checks
        assert ".trinity/observations.json" not in result["structure_checks"]

    def test_freshness_checks_include_local_and_readme(self, tmp_path: Path) -> None:
        """Freshness checks cover .trinity/local.json and README.md."""
        branch = _setup_full_branch(tmp_path)

        result = mh.get_memory_health_status(str(branch), "FRESH")

        assert ".trinity/local.json" in result["freshness_checks"]
        assert "README.md" in result["freshness_checks"]

    def test_result_contains_all_expected_keys(self, tmp_path: Path) -> None:
        """Returned dict has all documented keys with correct value types."""
        branch = _setup_full_branch(tmp_path)

        result = mh.get_memory_health_status(str(branch), "KEYS")

        expected_keys = {
            "branch_name", "branch_path", "overall_status",
            "file_check", "structure_checks", "freshness_checks",
            "issues", "check_time",
        }
        assert expected_keys == set(result.keys())
        assert isinstance(result["overall_status"], str)
        assert result["overall_status"] in ("OK", "WARNING", "RED")
        assert isinstance(result["branch_name"], str)
