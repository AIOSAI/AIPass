"""Tests for architecture_check and checklist coverage gaps."""

# =================== AIPass ====================
# Name: test_coverage_arch_checklist.py
# Description: Line-coverage tests for architecture_check.py and checklist.py
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-04-26
# =============================================

import json
from pathlib import Path
from typing import List

import pytest
from unittest.mock import MagicMock


def _lines(text: str) -> List[str]:
    """Split text into lines, widening LiteralString to str for pyright."""
    return text.split("\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for architecture_check and checklist."""
    import sys

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_error = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    cli_apps = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)

    cli_modules = MagicMock()
    cli_modules.error = mock_error
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.json.json_handler",
        json_mod,
    )

    # -- bypass handler (used by architecture_check) ------------------------
    bypass_pkg = MagicMock()
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    bypass_pkg.ignore_handler = bypass_ignore

    # Use real is_bypassed — it only does string matching and calls
    # json_handler.log_operation. That call resolves json_handler from the real
    # utils module globals, which sys.modules patching does not reach, so point
    # it at the mock explicitly — otherwise these tests write to the shared
    # seedgo_json/utils_log.json that xdist workers would race on.
    from aipass.seedgo.apps.handlers.bypass import utils as real_bypass_utils

    monkeypatch.setattr(real_bypass_utils, "json_handler", json_mod)

    bypass_utils = MagicMock()
    bypass_utils.is_bypassed = real_bypass_utils.is_bypassed
    bypass_pkg.utils = bypass_utils
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        bypass_ignore,
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.utils",
        bypass_utils,
    )

    # -- bypass handler (used by checklist) ---------------------------------
    bypass_handler_mod = MagicMock()
    bypass_handler_mod.get_branch_from_path = MagicMock(return_value=None)
    bypass_handler_mod.load_bypass_rules = MagicMock(return_value=[])
    bypass_handler_mod._find_registry = MagicMock(return_value=Path("/fake/registry"))
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.bypass_handler",
        bypass_handler_mod,
    )

    # -- branch_audit (discover_checkers) ------------------------------------
    audit_pkg = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit", audit_pkg)
    branch_audit_mod = MagicMock()
    branch_audit_mod.discover_checkers = MagicMock(return_value={})
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.audit.branch_audit",
        branch_audit_mod,
    )

    # Force genuine re-imports so modules pick up fresh mocks.
    # Dropping the sys.modules entry alone is NOT enough: ``from pkg import mod``
    # short-circuits on the parent package attribute, handing back a stale module
    # object still bound to whatever mocks a neighbouring test file installed.
    # Drop the attribute too — monkeypatch restores both on teardown.
    from aipass.seedgo.apps import modules as seedgo_modules_pkg
    from aipass.seedgo.apps.handlers import aipass_standards as standards_pkg

    for pkg, mod_name in (
        (standards_pkg, "aipass.seedgo.apps.handlers.aipass_standards.architecture_check"),
        (seedgo_modules_pkg, "aipass.seedgo.apps.modules.checklist"),
    ):
        monkeypatch.delitem(sys.modules, mod_name, raising=False)
        monkeypatch.delattr(pkg, mod_name.rsplit(".", 1)[1], raising=False)


def _pin_checklist_gates(checklist, monkeypatch):
    """Pin run_checklist's early-return gates so results never depend on test order.

    ``is_throwaway_path`` matches pytest's own tmp_path, ``is_prototype_file``
    reads the filesystem and ``_resolve_branch_path`` hits the real branch
    registry (which then feeds ``is_seedgo_ignored``). Each resolves differently
    depending on what a neighbouring test happened to import first, so every test
    that drives run_checklist has to pin them explicitly.
    """
    monkeypatch.setattr(checklist, "is_throwaway_path", lambda _path: False)
    monkeypatch.setattr(checklist, "is_prototype_file", lambda _path: False)
    monkeypatch.setattr(checklist, "_resolve_branch_path", lambda _path: None)


# ===========================================================================
# 1. architecture_check — is_bypassed
# ===========================================================================


class TestIsBypassed:
    """Tests for is_bypassed helper."""

    def test_no_bypass_rules_returns_false(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            is_bypassed,
        )

        assert is_bypassed("/some/file.py", "architecture", bypass_rules=None) is False

    def test_empty_bypass_rules_returns_false(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            is_bypassed,
        )

        assert is_bypassed("/some/file.py", "architecture", bypass_rules=[]) is False

    def test_matching_standard_and_file(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            is_bypassed,
        )

        rules = [{"standard": "architecture", "file": "file.py"}]
        assert is_bypassed("/some/file.py", "architecture", bypass_rules=rules) is True

    def test_non_matching_standard(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            is_bypassed,
        )

        rules = [{"standard": "cli", "file": "file.py"}]
        assert is_bypassed("/some/file.py", "architecture", bypass_rules=rules) is False

    def test_non_matching_file(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            is_bypassed,
        )

        rules = [{"standard": "architecture", "file": "other.py"}]
        assert is_bypassed("/some/file.py", "architecture", bypass_rules=rules) is False

    def test_line_specific_bypass_match(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            is_bypassed,
        )

        rules = [{"standard": "architecture", "file": "file.py", "lines": [10, 20]}]
        assert is_bypassed("/some/file.py", "architecture", line=10, bypass_rules=rules) is True

    def test_line_specific_bypass_no_match(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            is_bypassed,
        )

        rules = [{"standard": "architecture", "file": "file.py", "lines": [10, 20]}]
        assert is_bypassed("/some/file.py", "architecture", line=15, bypass_rules=rules) is False

    def test_rule_without_standard_matches(self):
        """Rule with no 'standard' key matches any standard."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            is_bypassed,
        )

        rules = [{"file": "file.py"}]
        assert is_bypassed("/some/file.py", "architecture", bypass_rules=rules) is True

    def test_rule_without_file_matches(self):
        """Rule with no 'file' key matches any file."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            is_bypassed,
        )

        rules = [{"standard": "architecture"}]
        assert is_bypassed("/some/file.py", "architecture", bypass_rules=rules) is True


# ===========================================================================
# 2. architecture_check — check_module (integration)
# ===========================================================================


class TestCheckModule:
    """Tests for check_module orchestration function."""

    def test_bypassed_file(self, tmp_path):
        """File with full architecture bypass returns passed with score 100."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_module,
        )

        f = tmp_path / "thing.py"
        f.write_text("x = 1\n", encoding="utf-8")
        rules = [{"standard": "architecture", "file": "thing.py"}]
        result = check_module(str(f), bypass_rules=rules)
        assert result["passed"] is True
        assert result["score"] == 100
        assert result["checks"][0]["name"] == "Bypassed"

    def test_nonexistent_file(self):
        """Missing file returns passed=False and score=0."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_module,
        )

        result = check_module("/nonexistent/path/file.py")
        assert result["passed"] is False
        assert result["score"] == 0
        assert "not found" in result["checks"][0]["message"].lower()

    def test_unreadable_file(self, tmp_path):
        """File that raises on read returns error result."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_module,
        )

        # Create a directory with the same name to cause read error
        bad = tmp_path / "bad.py"
        bad.mkdir()
        result = check_module(str(bad))
        assert result["passed"] is False
        assert result["score"] == 0

    def test_handler_file_runs_independence_and_domain_checks(self, tmp_path):
        """Handler file runs handler independence and domain organization checks."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_module,
        )

        handler_dir = tmp_path / "branch" / "apps" / "handlers" / "json"
        handler_dir.mkdir(parents=True)
        f = handler_dir / "json_handler.py"
        f.write_text("# handler\ndef do_work():\n    return True\n", encoding="utf-8")
        result = check_module(str(f))
        check_names = [c["name"] for c in result["checks"]]
        assert "Handler independence" in check_names
        assert "Domain organization" in check_names

    def test_init_file_skips_layer_check(self, tmp_path):
        """__init__.py files skip the layer location check."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_module,
        )

        d = tmp_path / "branch" / "apps" / "modules"
        d.mkdir(parents=True)
        f = d / "__init__.py"
        f.write_text("# init\n", encoding="utf-8")
        result = check_module(str(f))
        check_names = [c["name"] for c in result["checks"]]
        assert "3-layer pattern" not in check_names

    def test_entry_point_primary_triggers_template_baseline(self, tmp_path):
        """Primary entry point with passport triggers template baseline."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_module,
        )

        branch = tmp_path / "mybranch"
        apps = branch / "apps"
        apps.mkdir(parents=True)
        entry = apps / "mybranch.py"
        entry.write_text("# entry\n", encoding="utf-8")
        trinity = branch / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text('{"identity": {}}', encoding="utf-8")
        result = check_module(str(entry))
        check_names = [c["name"] for c in result["checks"]]
        assert any("Template baseline" in n or "citizen_class" in str(c) for n, c in zip(check_names, result["checks"]))

    def test_secondary_entry_point_skips_template_baseline(self, tmp_path):
        """Secondary entry point (name != branch dir) does NOT trigger template baseline."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_module,
        )

        branch = tmp_path / "mybranch"
        apps = branch / "apps"
        apps.mkdir(parents=True)
        entry = apps / "daemon_wakeup.py"
        entry.write_text("# daemon\n", encoding="utf-8")
        result = check_module(str(entry))
        check_names = [c["name"] for c in result["checks"]]
        assert not any("Template baseline" in n for n in check_names)

    def test_score_calculation_75_threshold(self, tmp_path):
        """Score >= 75 passes, score < 75 fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_module,
        )

        # File outside 3-layer pattern, but under size limit -> 1 pass, 1 fail = 50%
        d = tmp_path / "random"
        d.mkdir()
        f = d / "thing.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = check_module(str(f))
        assert result["score"] == 50
        assert result["passed"] is False


# ===========================================================================
# 3. architecture_check — check_file_size edge cases
# ===========================================================================


class TestCheckFileSizeEdgeCases:
    """Edge cases for file size boundaries."""

    def test_exactly_300_lines(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        lines = ["x"] * 300
        result = check_file_size(lines, "f.py")
        assert result["passed"] is True
        assert "good" in result["message"]

    def test_exactly_500_lines(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        lines = ["x"] * 500
        result = check_file_size(lines, "f.py")
        assert result["passed"] is True
        assert "getting heavy" in result["message"]

    def test_exactly_700_lines_advisory(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        lines = ["x"] * 700
        result = check_file_size(lines, "f.py")
        assert result["passed"] is True
        assert "advisory" in result["message"]

    def test_exactly_1500_lines_fails(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        lines = ["x"] * 1500
        result = check_file_size(lines, "f.py")
        assert result["passed"] is False
        assert "must split" in result["message"]

    def test_empty_file(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        result = check_file_size([], "f.py")
        assert result["passed"] is True
        assert "perfect" in result["message"]


# ===========================================================================
# 4. architecture_check — check_handler_independence edge cases
# ===========================================================================


class TestHandlerIndependenceEdgeCases:
    """Edge cases for handler independence."""

    def test_import_with_comment(self):
        """Import followed by a comment is still checked."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines = [
            "from seedgo.apps.modules.audit import run  # inline comment",
        ]
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/j.py")
        assert result is not None
        assert result["passed"] is False

    def test_no_parent_branch_detected_generic_fail(self):
        """When parent branch cannot be determined, generic fail message is used."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines = [
            "from something.apps.modules.stuff import thing",
        ]
        # Path with no 'apps' segment means parent_branch stays None
        result = check_handler_independence(lines, "/random/path/handler.py")
        assert result is not None
        assert result["passed"] is False
        assert "branch module" in result["message"]

    def test_single_line_docstring_skipped(self):
        """Single-line docstring with import text is skipped."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines = [
            '"""from seedgo.apps.modules.audit import run"""',
            "def work():",
            "    pass",
        ]
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/j.py")
        assert result is not None
        assert result["passed"] is True

    def test_single_quote_docstring(self):
        """Single-quote triple-quoted docstrings are handled correctly."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines = [
            "'''",
            "from seedgo.apps.modules.audit import run",
            "'''",
            "def work():",
            "    pass",
        ]
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/j.py")
        assert result is not None
        assert result["passed"] is True

    def test_empty_module_path(self):
        """Empty module path does not crash."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines = ["import os"]
        result = check_handler_independence(lines, "")
        assert result is not None
        assert result["passed"] is True

    def test_comment_line_skipped(self):
        """Comment lines are skipped."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines = [
            "# from seedgo.apps.modules.audit import run",
        ]
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/j.py")
        assert result is not None
        assert result["passed"] is True


# ===========================================================================
# 5. architecture_check — check_domain_organization edge cases
# ===========================================================================


class TestDomainOrganizationEdgeCases:
    """Additional domain organization tests."""

    def test_common_technical_name_fails(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_domain_organization,
        )

        result = check_domain_organization("/branch/apps/handlers/common/file.py")
        assert result is not None
        assert result["passed"] is False

    def test_shared_technical_name_fails(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_domain_organization,
        )

        result = check_domain_organization("/branch/apps/handlers/shared/file.py")
        assert result is not None
        assert result["passed"] is False

    def test_lib_technical_name_fails(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_domain_organization,
        )

        result = check_domain_organization("/branch/apps/handlers/lib/file.py")
        assert result is not None
        assert result["passed"] is False

    def test_operations_technical_name_fails(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_domain_organization,
        )

        result = check_domain_organization("/branch/apps/handlers/operations/file.py")
        assert result is not None
        assert result["passed"] is False

    def test_handler_domain_is_file(self):
        """When handler path has file directly in handlers/, domain is the filename."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_domain_organization,
        )

        result = check_domain_organization("/branch/apps/handlers/my_handler.py")
        assert result is not None
        # my_handler.py is the "domain" — not a technical name, so it passes
        assert result["passed"] is True


# ===========================================================================
# 6. architecture_check — template baseline helpers
# ===========================================================================


class TestLoadIgnorePatterns:
    """Tests for _load_ignore_patterns."""

    def test_no_ignore_file(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _load_ignore_patterns,
        )

        result = _load_ignore_patterns(tmp_path)
        assert result == {"ignore_files": [], "ignore_patterns": []}

    def test_valid_ignore_file(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _load_ignore_patterns,
        )

        spawn_dir = tmp_path / ".spawn"
        spawn_dir.mkdir()
        ignore = spawn_dir / ".registry_ignore.json"
        ignore.write_text(
            json.dumps({"ignore_files": ["README.md"], "ignore_patterns": ["*.tmp"]}),
            encoding="utf-8",
        )
        result = _load_ignore_patterns(tmp_path)
        assert result["ignore_files"] == ["README.md"]
        assert result["ignore_patterns"] == ["*.tmp"]

    def test_malformed_ignore_file(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _load_ignore_patterns,
        )

        spawn_dir = tmp_path / ".spawn"
        spawn_dir.mkdir()
        ignore = spawn_dir / ".registry_ignore.json"
        ignore.write_text("not json", encoding="utf-8")
        result = _load_ignore_patterns(tmp_path)
        assert result == {"ignore_files": [], "ignore_patterns": []}


class TestShouldIgnore:
    """Tests for _should_ignore."""

    def test_exact_filename_match(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _should_ignore,
        )

        item = tmp_path / "README.md"
        config = {"ignore_files": ["README.md"], "ignore_patterns": []}
        assert _should_ignore(item, config) is True

    def test_star_suffix_pattern(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _should_ignore,
        )

        item = tmp_path / "data.tmp"
        config = {"ignore_files": [], "ignore_patterns": ["*.tmp"]}
        assert _should_ignore(item, config) is True

    def test_dot_star_prefix_pattern(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _should_ignore,
        )

        item = tmp_path / ".hidden_file"
        config = {"ignore_files": [], "ignore_patterns": [".hidden*"]}
        assert _should_ignore(item, config) is True

    def test_exact_pattern_match(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _should_ignore,
        )

        item = tmp_path / "__pycache__"
        config = {"ignore_files": [], "ignore_patterns": ["__pycache__"]}
        assert _should_ignore(item, config) is True

    def test_pattern_in_parts(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _should_ignore,
        )

        item = tmp_path / "__pycache__" / "something.pyc"
        item.parent.mkdir(parents=True, exist_ok=True)
        config = {"ignore_files": [], "ignore_patterns": ["__pycache__"]}
        assert _should_ignore(item, config) is True

    def test_no_match(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _should_ignore,
        )

        item = tmp_path / "good_file.py"
        config = {"ignore_files": ["bad.py"], "ignore_patterns": ["*.tmp"]}
        assert _should_ignore(item, config) is False


class TestGetCitizenClass:
    """Tests for _get_citizen_class."""

    def test_no_passport(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _get_citizen_class,
        )

        assert _get_citizen_class(tmp_path) is None

    def test_valid_passport(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _get_citizen_class,
        )

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(
            json.dumps({"identity": {"citizen_class": "builder"}}),
            encoding="utf-8",
        )
        assert _get_citizen_class(tmp_path) == "builder"

    def test_malformed_passport(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _get_citizen_class,
        )

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text("not json", encoding="utf-8")
        assert _get_citizen_class(tmp_path) is None

    def test_passport_missing_citizen_class(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _get_citizen_class,
        )

        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"identity": {}}), encoding="utf-8")
        assert _get_citizen_class(tmp_path) is None


class TestTransformPath:
    """Tests for _transform_path."""

    def test_basic_placeholder_replacement(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _transform_path,
        )

        result = _transform_path("{{BRANCH}}/apps/{{BRANCH}}.py", "mybranch")
        assert result == "mybranch/apps/mybranch.py"

    def test_hyphenated_branch_name(self):
        """Hyphenated branch: placeholder replaced, then entry-point rename applied."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _transform_path,
        )

        result = _transform_path("apps/{{BRANCH}}.py", "my-branch")
        # branch_lower="my_branch" replaces placeholder -> "apps/my_branch.py"
        # FILE_RENAMES maps "my_branch.py" -> "my-branch.py" (entry_point_name)
        assert result == "apps/my-branch.py"

    def test_dotted_branch_name(self):
        """Leading dot is stripped for entry point name."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _transform_path,
        )

        result = _transform_path("apps/{{BRANCH}}.py", ".hidden")
        # branch_lower = ".hidden" -> ".hidden", entry_point_name = "hidden"
        # The placeholder replacement gives ".hidden.py"
        # But FILE_RENAMES maps ".hidden.py" -> "hidden.py"
        assert "hidden" in result

    def test_no_placeholder(self):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _transform_path,
        )

        result = _transform_path("apps/modules/helper.py", "mybranch")
        assert result == "apps/modules/helper.py"


class TestScanTemplate:
    """Tests for _scan_template."""

    def test_scan_template_basic(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _scan_template,
        )

        # Create a minimal template structure
        (tmp_path / "apps").mkdir()
        (tmp_path / "apps" / "modules").mkdir()
        (tmp_path / "apps" / "entry.py").write_text("# entry\n", encoding="utf-8")
        (tmp_path / "apps" / "modules" / "helper.py").write_text("# helper\n", encoding="utf-8")

        result = _scan_template(tmp_path)
        assert "apps" in result["directories"]
        assert any("entry.py" in f for f in result["files"])

    def test_scan_template_with_ignore(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _scan_template,
        )

        # Create template with an ignoreable file
        (tmp_path / ".spawn").mkdir()
        ignore = tmp_path / ".spawn" / ".registry_ignore.json"
        ignore.write_text(
            json.dumps({"ignore_files": ["README.md"], "ignore_patterns": []}),
            encoding="utf-8",
        )
        (tmp_path / "apps").mkdir()
        (tmp_path / "README.md").write_text("# readme\n", encoding="utf-8")
        (tmp_path / "apps" / "entry.py").write_text("# entry\n", encoding="utf-8")

        result = _scan_template(tmp_path)
        # README.md should be ignored
        assert not any("README.md" in f for f in result["files"])
        assert any("entry.py" in f for f in result["files"])

    def test_scan_template_excludes_test_scaffold(self, tmp_path, monkeypatch):
        import sys

        _arch = "aipass.seedgo.apps.handlers.aipass_standards.architecture_check"
        monkeypatch.delitem(sys.modules, _arch, raising=False)

        _ignore = sys.modules["aipass.seedgo.apps.handlers.bypass.ignore_handler"]
        monkeypatch.setattr(_ignore, "get_template_ignore_patterns", MagicMock(return_value=["test_scaffold.py"]))

        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            _scan_template,
        )

        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "conftest.py").write_text("# conf\n", encoding="utf-8")
        (tmp_path / "tests" / "test_scaffold.py").write_text("# scaffold\n", encoding="utf-8")

        result = _scan_template(tmp_path)
        assert not any("test_scaffold.py" in f for f in result["files"])
        assert any("conftest.py" in f for f in result["files"])


# ===========================================================================
# 7. architecture_check — check_template_baseline with mocked templates
# ===========================================================================


class TestCheckTemplateBaselineFull:
    """Full template baseline tests with mocked spawn template dirs."""

    def test_spawn_templates_dir_missing(self, tmp_path, monkeypatch):
        """When SPAWN_TEMPLATES_DIR does not exist, returns failure."""
        import sys

        _arch = "aipass.seedgo.apps.handlers.aipass_standards.architecture_check"
        monkeypatch.delitem(sys.modules, _arch, raising=False)
        from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

        monkeypatch.setattr(architecture_check, "SPAWN_TEMPLATES_DIR", tmp_path / "nonexistent")

        branch = tmp_path / "mybranch"
        apps = branch / "apps"
        apps.mkdir(parents=True)
        entry = apps / "mybranch.py"
        entry.write_text("# entry\n", encoding="utf-8")

        # Create passport
        trinity = branch / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"identity": {"citizen_class": "specialist"}}), encoding="utf-8")

        result = architecture_check.check_template_baseline(str(entry))
        assert len(result) >= 1
        assert result[0]["passed"] is False
        assert "not found" in result[0]["message"]

    def test_template_dir_absent_for_registered_class(self, tmp_path, monkeypatch):
        """A registered class whose template directory is not on disk fails by name.

        This is the environment failure (templates root present, the one template
        dir missing) — distinct from an unrecognised class, which never reaches
        the filesystem at all. Both are scored; only this one is about the disk.
        """
        import sys

        monkeypatch.delitem(
            sys.modules, "aipass.seedgo.apps.handlers.aipass_standards.architecture_check", raising=False
        )
        from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()  # root exists, templates/citizen/ deliberately does not
        monkeypatch.setattr(architecture_check, "SPAWN_TEMPLATES_DIR", templates_dir)

        branch = tmp_path / "mybranch"
        apps = branch / "apps"
        apps.mkdir(parents=True)
        entry = apps / "mybranch.py"
        entry.write_text("# entry\n", encoding="utf-8")

        trinity = branch / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"identity": {"citizen_class": "specialist"}}), encoding="utf-8")

        result = architecture_check.check_template_baseline(str(entry))
        assert len(result) == 1
        assert result[0]["passed"] is False
        assert "No template directory" in result[0]["message"]
        assert "citizen" in result[0]["message"]

    def test_template_baseline_full_match(self, tmp_path, monkeypatch):
        """All template items present in branch: full pass."""
        import sys

        monkeypatch.delitem(
            sys.modules, "aipass.seedgo.apps.handlers.aipass_standards.architecture_check", raising=False
        )
        from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

        # Create template dir
        templates_dir = tmp_path / "templates"
        citizen_template = templates_dir / "citizen"
        citizen_template.mkdir(parents=True)
        (citizen_template / "apps").mkdir()
        (citizen_template / "apps" / "modules").mkdir()
        (citizen_template / "apps" / "entry.py").write_text("# entry\n", encoding="utf-8")
        monkeypatch.setattr(architecture_check, "SPAWN_TEMPLATES_DIR", templates_dir)

        # Create branch that matches template
        branch = tmp_path / "mybranch"
        apps = branch / "apps"
        (apps / "modules").mkdir(parents=True)
        entry = apps / "mybranch.py"
        entry.write_text("# entry\n", encoding="utf-8")
        (apps / "entry.py").write_text("# entry\n", encoding="utf-8")

        trinity = branch / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"identity": {"citizen_class": "specialist"}}), encoding="utf-8")

        result = architecture_check.check_template_baseline(str(entry))
        # First check is the summary
        assert result[0]["name"].startswith("Template baseline")
        assert "0 missing" in result[0]["message"]

    def test_template_baseline_missing_dir(self, tmp_path, monkeypatch):
        """Missing template directory is flagged."""
        import sys

        monkeypatch.delitem(
            sys.modules, "aipass.seedgo.apps.handlers.aipass_standards.architecture_check", raising=False
        )
        from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

        templates_dir = tmp_path / "templates"
        citizen_template = templates_dir / "citizen"
        citizen_template.mkdir(parents=True)
        (citizen_template / "apps").mkdir()
        (citizen_template / "apps" / "modules").mkdir()
        monkeypatch.setattr(architecture_check, "SPAWN_TEMPLATES_DIR", templates_dir)

        branch = tmp_path / "mybranch"
        apps = branch / "apps"
        apps.mkdir(parents=True)
        entry = apps / "mybranch.py"
        entry.write_text("# entry\n", encoding="utf-8")
        # Note: apps/modules/ missing

        trinity = branch / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"identity": {"citizen_class": "specialist"}}), encoding="utf-8")

        result = architecture_check.check_template_baseline(str(entry))
        failed = [c for c in result if not c["passed"]]
        assert len(failed) >= 1

    def test_template_baseline_missing_file_bypassed(self, tmp_path, monkeypatch):
        """Bypassed missing template file is marked as passed."""
        import sys

        monkeypatch.delitem(
            sys.modules, "aipass.seedgo.apps.handlers.aipass_standards.architecture_check", raising=False
        )
        from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

        templates_dir = tmp_path / "templates"
        citizen_template = templates_dir / "citizen"
        citizen_template.mkdir(parents=True)
        (citizen_template / "apps").mkdir()
        (citizen_template / "apps" / "something.py").write_text("# x\n", encoding="utf-8")
        monkeypatch.setattr(architecture_check, "SPAWN_TEMPLATES_DIR", templates_dir)

        branch = tmp_path / "mybranch"
        apps = branch / "apps"
        apps.mkdir(parents=True)
        entry = apps / "mybranch.py"
        entry.write_text("# entry\n", encoding="utf-8")
        # something.py missing but bypassed

        trinity = branch / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"identity": {"citizen_class": "specialist"}}), encoding="utf-8")

        bypass = [{"standard": "architecture", "file": "something.py"}]
        result = architecture_check.check_template_baseline(str(entry), bypass_rules=bypass)
        # The missing file should be bypassed
        file_checks = [c for c in result if c["name"].startswith("File:")]
        for c in file_checks:
            if "something.py" in c["name"]:
                assert c["passed"] is True
                assert "bypassed" in c["message"]

    def test_template_baseline_missing_dir_bypassed(self, tmp_path, monkeypatch):
        """Bypassed missing template directory is marked as passed."""
        import sys

        monkeypatch.delitem(
            sys.modules, "aipass.seedgo.apps.handlers.aipass_standards.architecture_check", raising=False
        )
        from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

        templates_dir = tmp_path / "templates"
        citizen_template = templates_dir / "citizen"
        citizen_template.mkdir(parents=True)
        (citizen_template / "apps").mkdir()
        (citizen_template / "apps" / "handlers").mkdir()
        monkeypatch.setattr(architecture_check, "SPAWN_TEMPLATES_DIR", templates_dir)

        branch = tmp_path / "mybranch"
        apps = branch / "apps"
        apps.mkdir(parents=True)
        entry = apps / "mybranch.py"
        entry.write_text("# entry\n", encoding="utf-8")
        # apps/handlers/ missing but bypassed

        trinity = branch / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"identity": {"citizen_class": "specialist"}}), encoding="utf-8")

        bypass = [{"standard": "architecture", "file": "apps/handlers"}]
        result = architecture_check.check_template_baseline(str(entry), bypass_rules=bypass)
        dir_checks = [c for c in result if c["name"].startswith("Dir:") and "handlers" in c["name"]]
        for c in dir_checks:
            assert c["passed"] is True


# ===========================================================================
# 8. checklist — _is_applicable
# ===========================================================================


class TestIsApplicable:
    """Tests for _is_applicable."""

    def test_branch_level_with_check_module(self):
        from aipass.seedgo.apps.modules.checklist import _is_applicable

        checker = MagicMock()
        checker.AUDIT_SCOPE = "branch_level"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, "/some/file.py") is True

    def test_branch_level_without_check_module(self):
        from aipass.seedgo.apps.modules.checklist import _is_applicable

        checker = MagicMock(spec=[])
        checker.AUDIT_SCOPE = "branch_level"
        assert _is_applicable(checker, "/some/file.py") is False

    def test_branch_level_non_python(self):
        from aipass.seedgo.apps.modules.checklist import _is_applicable

        checker = MagicMock()
        checker.AUDIT_SCOPE = "branch_level"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, "/some/file.txt") is False

    def test_all_files_scope_python(self):
        from aipass.seedgo.apps.modules.checklist import _is_applicable

        checker = MagicMock()
        checker.AUDIT_SCOPE = "all_files"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, "/some/file.py") is True

    def test_all_files_scope_non_python(self):
        from aipass.seedgo.apps.modules.checklist import _is_applicable

        checker = MagicMock()
        checker.AUDIT_SCOPE = "all_files"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, "/some/file.txt") is False

    def test_entry_point_scope_matches_entry(self):
        from aipass.seedgo.apps.modules.checklist import _is_applicable

        checker = MagicMock()
        checker.AUDIT_SCOPE = "entry_point"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, "/branch/apps/branch.py") is True

    def test_entry_point_scope_non_entry(self):
        from aipass.seedgo.apps.modules.checklist import _is_applicable

        checker = MagicMock()
        checker.AUDIT_SCOPE = "entry_point"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, "/branch/apps/modules/helper.py") is False

    def test_no_check_module_returns_false(self):
        from aipass.seedgo.apps.modules.checklist import _is_applicable

        checker = MagicMock(spec=[])
        checker.AUDIT_SCOPE = "all_files"
        assert _is_applicable(checker, "/some/file.py") is False

    def test_default_scope_is_entry_point(self):
        """Checker with no AUDIT_SCOPE defaults to entry_point."""
        from aipass.seedgo.apps.modules.checklist import _is_applicable

        checker = MagicMock(spec=["check_module"])
        checker.check_module = MagicMock()
        # No AUDIT_SCOPE attribute -> defaults to "entry_point"
        assert _is_applicable(checker, "/branch/apps/branch.py") is True
        assert _is_applicable(checker, "/branch/apps/modules/helper.py") is False


# ===========================================================================
# 9. checklist — handle_command directory mode
# ===========================================================================


class TestHandleCommandDirectoryMode:
    """Tests for handle_command in directory mode."""

    def test_directory_with_py_files(self, tmp_path, monkeypatch):
        """Directory mode runs checklist on all .py files."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        d = tmp_path / "mydir"
        d.mkdir()
        (d / "first.py").write_text("x = 1\n", encoding="utf-8")
        (d / "second.py").write_text("y = 2\n", encoding="utf-8")
        (d / "_private.py").write_text("z = 3\n", encoding="utf-8")
        (d / "readme.txt").write_text("not python\n", encoding="utf-8")

        result = checklist.handle_command("checklist", [str(d)])
        assert result is True

    def test_directory_with_no_py_files(self, tmp_path, monkeypatch):
        """Directory with no .py files shows error."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        d = tmp_path / "emptydir"
        d.mkdir()
        (d / "readme.txt").write_text("not python\n", encoding="utf-8")

        result = checklist.handle_command("checklist", [str(d)])
        assert result is True

    def test_directory_filters_underscore_files(self, tmp_path, monkeypatch):
        """Directory mode filters files starting with underscore."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        d = tmp_path / "onlypriv"
        d.mkdir()
        (d / "_init.py").write_text("x = 1\n", encoding="utf-8")

        result = checklist.handle_command("checklist", [str(d)])
        assert result is True


# ===========================================================================
# 10. checklist — handle_command with --pack flag
# ===========================================================================


class TestHandleCommandPackFlag:
    """Tests for handle_command with --pack flag."""

    def test_pack_flag(self, tmp_path, monkeypatch):
        """--pack flag passes pack_name to run_checklist."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        result = checklist.handle_command("checklist", ["--pack", "custom", str(f)])
        assert result is True

    def test_short_pack_flag(self, tmp_path, monkeypatch):
        """-p flag is equivalent to --pack."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        result = checklist.handle_command("checklist", ["-p", "custom", str(f)])
        assert result is True

    def test_no_file_after_pack_shows_error(self, monkeypatch):
        """--pack with no file specified shows error."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        result = checklist.handle_command("checklist", ["--pack", "custom"])
        assert result is True  # Handled, but shows error

    def test_unknown_flag_skipped(self, tmp_path, monkeypatch):
        """Unknown flags are skipped during argument parsing."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        result = checklist.handle_command("checklist", ["--unknown", str(f)])
        assert result is True


# ===========================================================================
# 11. checklist — _resolve_pack_path
# ===========================================================================


class TestResolvePackPath:
    """Tests for _resolve_pack_path."""

    def test_nonexistent_pack(self, monkeypatch):
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules.checklist import _resolve_pack_path

        # Use monkeypatch to point handlers_dir to a tmp location
        result = _resolve_pack_path("totally_bogus_pack_name_that_will_never_exist")
        # If the real handlers dir exists but no matching pack, returns None
        assert result is None

    def test_pack_not_found_in_run_checklist(self, tmp_path, monkeypatch):
        """run_checklist returns error when pack is not found."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        _pin_checklist_gates(checklist, monkeypatch)

        # Make _resolve_pack_path return None
        monkeypatch.setattr(checklist, "_resolve_pack_path", lambda name: None)

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        results = checklist.run_checklist(str(f), pack_name="bogus")
        assert len(results) == 1
        assert results[0]["passed"] is False
        assert "not found" in results[0]["detail"]


# ===========================================================================
# 12. checklist — _load_bypass_for_file
# ===========================================================================


class TestLoadBypassForFile:
    """Tests for _load_bypass_for_file."""

    def test_no_branch_detected(self, monkeypatch):
        """When get_branch_from_path returns None, returns empty list."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules.checklist import _load_bypass_for_file

        result = _load_bypass_for_file("/some/file.py")
        assert result == []

    def test_branch_with_empty_path(self, monkeypatch):
        """When branch has empty path, returns empty list."""
        import sys

        monkeypatch.setattr(
            sys.modules["aipass.seedgo.apps.handlers.bypass.bypass_handler"],
            "get_branch_from_path",
            MagicMock(return_value={"name": "mybranch", "path": ""}),
        )

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules.checklist import _load_bypass_for_file

        result = _load_bypass_for_file("/some/file.py")
        assert result == []

    def test_branch_with_absolute_path(self, monkeypatch):
        """When branch has absolute path, passes it directly to load_bypass_rules."""
        import sys

        mock_load = MagicMock(return_value=[{"standard": "arch"}])
        monkeypatch.setattr(
            sys.modules["aipass.seedgo.apps.handlers.bypass.bypass_handler"],
            "get_branch_from_path",
            MagicMock(return_value={"name": "mybranch", "path": "/absolute/path/mybranch"}),
        )
        monkeypatch.setattr(
            sys.modules["aipass.seedgo.apps.handlers.bypass.bypass_handler"],
            "load_bypass_rules",
            mock_load,
        )

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules.checklist import _load_bypass_for_file

        result = _load_bypass_for_file("/some/file.py")
        assert result == [{"standard": "arch"}]

    def test_branch_with_relative_path(self, monkeypatch):
        """When branch has relative path, resolves relative to registry."""
        import sys

        mock_load = MagicMock(return_value=[])
        monkeypatch.setattr(
            sys.modules["aipass.seedgo.apps.handlers.bypass.bypass_handler"],
            "get_branch_from_path",
            MagicMock(return_value={"name": "mybranch", "path": "relative/path/mybranch"}),
        )
        monkeypatch.setattr(
            sys.modules["aipass.seedgo.apps.handlers.bypass.bypass_handler"],
            "load_bypass_rules",
            mock_load,
        )
        monkeypatch.setattr(
            sys.modules["aipass.seedgo.apps.handlers.bypass.bypass_handler"],
            "_find_registry",
            MagicMock(return_value=Path("/repo/root/registry.json")),
        )

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules.checklist import _load_bypass_for_file

        result = _load_bypass_for_file("/some/file.py")
        mock_load.assert_called_once()
        assert result == []


# ===========================================================================
# 13. checklist — _format_failure
# ===========================================================================


class TestFormatFailureEdgeCases:
    """Additional _format_failure tests for untested paths."""

    def test_format_failure_no_checks_key(self):
        """Result with no 'checks' key returns fallback."""
        from aipass.seedgo.apps.modules.checklist import _format_failure

        result = _format_failure({})
        assert "no details" in result.lower()

    def test_format_failure_all_passed(self):
        """Result where all checks passed returns fallback."""
        from aipass.seedgo.apps.modules.checklist import _format_failure

        result = _format_failure({"checks": [{"passed": True, "message": "OK"}]})
        assert "no details" in result.lower()

    def test_format_failure_three_failures(self):
        """Multiple failures shows '+N more' suffix."""
        from aipass.seedgo.apps.modules.checklist import _format_failure

        result = _format_failure(
            {
                "checks": [
                    {"passed": False, "message": "First issue"},
                    {"passed": False, "message": "Second issue"},
                    {"passed": False, "message": "Third issue"},
                ]
            }
        )
        assert "First issue" in result
        assert "+2 more" in result

    def test_format_failure_missing_message(self):
        """Failed check with no message uses 'Unknown issue'."""
        from aipass.seedgo.apps.modules.checklist import _format_failure

        result = _format_failure({"checks": [{"passed": False}]})
        assert "Unknown issue" in result


# ===========================================================================
# 14. checklist — run_checklist with checker that raises exception
# ===========================================================================


class TestRunChecklistCheckerException:
    """Tests for run_checklist when a checker raises an exception."""

    def test_checker_exception_captured(self, tmp_path, monkeypatch):
        """Checker that raises exception is captured as a failed result."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        _pin_checklist_gates(checklist, monkeypatch)

        # Create a mock checker that raises
        bad_checker = MagicMock()
        bad_checker.AUDIT_SCOPE = "all_files"
        bad_checker.check_module = MagicMock(side_effect=RuntimeError("boom"))

        good_checker = MagicMock()
        good_checker.AUDIT_SCOPE = "all_files"
        good_checker.check_module = MagicMock(return_value={"passed": True, "checks": []})

        # Patch discover_checkers on the checklist module (already bound at import)
        monkeypatch.setattr(
            checklist,
            "discover_checkers",
            lambda pack_path: {"bad_check": bad_checker, "good_check": good_checker},
        )
        monkeypatch.setattr(checklist, "_resolve_pack_path", lambda name: Path("/fake/pack"))

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        results = checklist.run_checklist(str(f))
        # Should have results for both checkers
        assert len(results) == 2
        bad_result = [r for r in results if r["standard"] == "bad_check"]
        assert len(bad_result) == 1
        assert bad_result[0]["passed"] is False
        assert "boom" in bad_result[0]["detail"]

    def test_checker_returns_failure_with_details(self, tmp_path, monkeypatch):
        """Checker returning passed=False has detail populated from _format_failure."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        _pin_checklist_gates(checklist, monkeypatch)

        fail_checker = MagicMock()
        fail_checker.AUDIT_SCOPE = "all_files"
        fail_checker.check_module = MagicMock(
            return_value={
                "passed": False,
                "checks": [{"passed": False, "message": "Something is wrong"}],
            }
        )

        monkeypatch.setattr(
            checklist,
            "discover_checkers",
            lambda pack_path: {"fail_check": fail_checker},
        )
        monkeypatch.setattr(checklist, "_resolve_pack_path", lambda name: Path("/fake/pack"))

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        results = checklist.run_checklist(str(f))
        assert len(results) == 1
        assert results[0]["passed"] is False
        assert "Something is wrong" in results[0]["detail"]

    def test_no_applicable_checkers_returns_skip(self, tmp_path, monkeypatch):
        """When no checkers are applicable, returns skip result."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        _pin_checklist_gates(checklist, monkeypatch)

        entry_only_checker = MagicMock()
        entry_only_checker.AUDIT_SCOPE = "entry_point"
        entry_only_checker.check_module = MagicMock()

        monkeypatch.setattr(
            checklist,
            "discover_checkers",
            lambda pack_path: {"entry_check": entry_only_checker},
        )
        monkeypatch.setattr(checklist, "_resolve_pack_path", lambda name: Path("/fake/pack"))

        # Create a file that is NOT an entry point
        f = tmp_path / "helper.py"
        f.write_text("x = 1\n", encoding="utf-8")

        results = checklist.run_checklist(str(f))
        assert len(results) == 1
        assert results[0]["passed"] is True
        assert "No applicable" in results[0]["detail"]

    def test_no_checkers_discovered(self, tmp_path, monkeypatch):
        """When discover_checkers returns empty dict, returns error."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        _pin_checklist_gates(checklist, monkeypatch)

        monkeypatch.setattr(
            checklist,
            "discover_checkers",
            lambda pack_path: {},
        )
        monkeypatch.setattr(checklist, "_resolve_pack_path", lambda name: Path("/fake/pack"))

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        results = checklist.run_checklist(str(f))
        assert len(results) == 1
        assert results[0]["passed"] is False
        assert "No checkers" in results[0]["detail"]


# ===========================================================================
# 15. checklist — _print_results
# ===========================================================================


class TestPrintResults:
    """Tests for _print_results output formatting."""

    def test_print_all_passed(self, monkeypatch):
        """All passed results show green checkmarks and summary."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules.checklist import _print_results

        mock_cli = sys.modules["aipass.cli"]
        mock_cli.console.reset_mock()

        results = [
            {"standard": "architecture", "passed": True, "detail": None},
            {"standard": "documentation", "passed": True, "detail": None},
        ]
        _print_results(results, "/some/file.py")
        assert mock_cli.console.print.called

    def test_print_failed_with_detail(self, monkeypatch):
        """Failed result with detail prints the detail message."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules.checklist import _print_results

        mock_cli = sys.modules["aipass.cli"]
        mock_cli.console.reset_mock()

        results = [{"standard": "architecture", "passed": False, "detail": "Missing docstring"}]
        _print_results(results, "/some/file.py")
        assert mock_cli.console.print.called

    def test_print_failed_without_detail(self, monkeypatch):
        """Failed result without detail still prints."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules.checklist import _print_results

        mock_cli = sys.modules["aipass.cli"]
        mock_cli.console.reset_mock()

        results = [{"standard": "architecture", "passed": False, "detail": ""}]
        _print_results(results, "/some/file.py")
        assert mock_cli.console.print.called

    def test_print_mixed_results(self, monkeypatch):
        """Mixed results do not print 'All passed' summary."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules.checklist import _print_results

        mock_cli = sys.modules["aipass.cli"]
        mock_cli.console.reset_mock()

        results = [
            {"standard": "architecture", "passed": True, "detail": None},
            {"standard": "documentation", "passed": False, "detail": "Issues found"},
        ]
        _print_results(results, "/some/file.py")
        # Check that "All X standards passed" was NOT printed
        calls = [str(c) for c in mock_cli.console.print.call_args_list]
        assert not any("All" in c and "passed" in c for c in calls)


# ===========================================================================
# 16. checklist — handle_command path resolution
# ===========================================================================


class TestHandleCommandPathResolution:
    """Tests for handle_command path resolution logic."""

    def test_absolute_path(self, tmp_path, monkeypatch):
        """Absolute file path is resolved directly."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        result = checklist.handle_command("checklist", [str(f)])
        assert result is True

    def test_relative_path_fallback_cwd(self, tmp_path, monkeypatch):
        """Relative path falls back to CWD resolution."""
        import sys

        monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)
        from aipass.seedgo.apps.modules import checklist

        # Monkeypatch _get_repo_root to return None (no git repo)
        monkeypatch.setattr(checklist, "_get_repo_root", lambda: None)
        monkeypatch.chdir(tmp_path)

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        result = checklist.handle_command("checklist", ["sample.py"])
        assert result is True


# ===========================================================================
# 17. checklist — _is_entry_point edge cases
# ===========================================================================


class TestIsEntryPointEdgeCases:
    """Additional _is_entry_point edge cases."""

    def test_non_py_file(self):
        from aipass.seedgo.apps.modules.checklist import _is_entry_point

        assert _is_entry_point("/branch/apps/config.json") is False

    def test_nested_under_apps(self):
        from aipass.seedgo.apps.modules.checklist import _is_entry_point

        assert _is_entry_point("/branch/apps/handlers/thing.py") is False

    def test_no_apps_in_path(self):
        from aipass.seedgo.apps.modules.checklist import _is_entry_point

        assert _is_entry_point("/branch/src/thing.py") is False

    def test_valid_entry_point(self):
        from aipass.seedgo.apps.modules.checklist import _is_entry_point

        assert _is_entry_point("/branch/apps/branch.py") is True
