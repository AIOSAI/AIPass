# =================== AIPass ====================
# Name: test_coverage_arch_checklist.py
# Description: Line-coverage tests for architecture_check.py and checklist.py
# Version: 1.1.1
# Created: 2026-04-26
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/architecture_check.py and apps/modules/checklist.py."""

# Written to close the coverage gaps the two modules' own test files left.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — citizen_class resolution through spawn; tests/test_citizen_class_resolution.py
# seedgo: no-test-needed(documentation) — the text print_help and print_introspection show

import json
from pathlib import Path, PureWindowsPath
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import architecture_check
from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
    check_domain_organization,
    check_file_size,
    check_handler_independence,
    check_module,
    is_bypassed,
)
from aipass.seedgo.apps.handlers.audit_tests import refusal
from aipass.seedgo.apps.handlers.bypass import bypass_handler
from aipass.seedgo.apps.modules import CommandRefused, checklist
from aipass.seedgo.apps.modules.checklist import (
    _is_applicable,
    _is_entry_point,
)


def _lines(text: str) -> List[str]:
    """Split text into lines, widening LiteralString to str for pyright."""
    return text.split("\n")


def _windows_form(tmp_path: Path, *parts: str) -> str:
    """The tmp_path-rebuilt path as Windows spells it: a drive letter and backslashes."""
    return str(PureWindowsPath("C:/", *tmp_path.parts[1:], *parts))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Patch architecture_check's and checklist's own seams, at the edge.

    Both modules bind their dependencies with ``from X import Y`` at their own
    import time, so the seam a test controls is the NAME on the consuming
    module (``architecture_check.get_template_ignore_patterns``,
    ``checklist.discover_checkers``, ...) -- patching the origin module after
    import would never reach a name the consumer already copied in.
    ``json_handler.log_operation`` is the one exception: every consumer reads
    it live off the shared module object, and conftest's AIPASS_TEST_LOG_DIR
    seam already keeps that call safe for real, so it is left untouched here.
    """
    monkeypatch.setattr(checklist, "error", MagicMock())
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack_path: {})
    monkeypatch.setattr(checklist, "get_branch_from_path", lambda file_path: None)
    monkeypatch.setattr(checklist, "load_bypass_rules", lambda branch_path: [])

    monkeypatch.setattr(architecture_check, "get_template_ignore_patterns", lambda: [])


def _pin_checklist_gates(checklist, monkeypatch, sandbox: Path, pin_branch: bool = True):
    """Pin run_checklist's early-return gates so results never depend on test order.

    ``is_throwaway_path`` matches pytest's own tmp_path, so the test's sandbox is
    carved out of it and every other path keeps the real answer.
    ``is_prototype_file`` stays real: it reads only the first lines of the file
    the test wrote, which carries no marker. ``_resolve_branch_path`` hits the
    real branch registry (which then feeds ``is_seedgo_ignored``) and resolves
    differently depending on what a neighbouring test happened to import first,
    so it is pinned unless the test drives the branch lookup itself.
    """
    real_throwaway = checklist.is_throwaway_path
    root = sandbox.resolve()
    monkeypatch.setattr(
        checklist, "is_throwaway_path", lambda path: real_throwaway(path) and not Path(path).is_relative_to(root)
    )
    if pin_branch:
        monkeypatch.setattr(checklist, "_resolve_branch_path", lambda _path: None)


def _run_one(tmp_path, monkeypatch, returned: dict, pin_branch: bool = True):
    """run_checklist over one sample file with one all_files checker answering ``returned``."""
    _pin_checklist_gates(checklist, monkeypatch, tmp_path, pin_branch=pin_branch)
    probe = MagicMock()
    probe.AUDIT_SCOPE = "all_files"
    probe.check_module = MagicMock(return_value=returned)
    monkeypatch.setattr(checklist, "discover_checkers", lambda pack_path: {"probe": probe})
    f = tmp_path / "sample.py"
    f.write_text("x = 1\n", encoding="utf-8")
    return checklist.run_checklist(str(f)), probe


def _baseline(tmp_path, monkeypatch, template: dict, branch_name: str = "mybranch", passport=None):
    """check_template_baseline over a planted templates/citizen/; ``template`` maps path to text, None for a dir.

    ``passport`` is the passport.json text; the default is a specialist, and
    False plants no passport at all.
    """
    citizen = tmp_path / "templates" / "citizen"
    citizen.mkdir(parents=True)
    for relative, text in template.items():
        target = citizen / relative
        if text is None:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(architecture_check, "SPAWN_TEMPLATES_DIR", tmp_path / "templates")
    branch = tmp_path / branch_name
    (branch / "apps").mkdir(parents=True)
    entry = branch / "apps" / "entry_under_test.py"
    entry.write_text("# entry\n", encoding="utf-8")
    if passport is not False:
        (branch / ".trinity").mkdir()
        text = passport if passport is not None else json.dumps({"identity": {"citizen_class": "specialist"}})
        (branch / ".trinity" / "passport.json").write_text(text, encoding="utf-8")
    return architecture_check.check_template_baseline(str(entry))


def _rows(result) -> set:
    """The names of the template rows a baseline scored."""
    return {c["name"] for c in result}


# ===========================================================================
# 1. architecture_check — is_bypassed
# ===========================================================================


class TestIsBypassed:
    """Tests for is_bypassed helper."""

    def test_no_bypass_rules_returns_false(self, tmp_path):

        assert is_bypassed(str(tmp_path / "file.py"), "architecture", bypass_rules=None) is False

    def test_empty_bypass_rules_returns_false(self, tmp_path):

        assert is_bypassed(str(tmp_path / "file.py"), "architecture", bypass_rules=[]) is False

    def test_matching_standard_and_file(self, tmp_path):

        rules = [{"standard": "architecture", "file": "file.py"}]
        assert is_bypassed(str(tmp_path / "file.py"), "architecture", bypass_rules=rules) is True

    def test_non_matching_standard(self, tmp_path):

        rules = [{"standard": "cli", "file": "file.py"}]
        assert is_bypassed(str(tmp_path / "file.py"), "architecture", bypass_rules=rules) is False

    def test_non_matching_file(self, tmp_path):

        rules = [{"standard": "architecture", "file": "other.py"}]
        assert is_bypassed(str(tmp_path / "file.py"), "architecture", bypass_rules=rules) is False

    def test_line_specific_bypass_match(self, tmp_path):

        rules = [{"standard": "architecture", "file": "file.py", "lines": [10, 20]}]
        assert is_bypassed(str(tmp_path / "file.py"), "architecture", line=10, bypass_rules=rules) is True

    def test_line_specific_bypass_no_match(self, tmp_path):

        rules = [{"standard": "architecture", "file": "file.py", "lines": [10, 20]}]
        assert is_bypassed(str(tmp_path / "file.py"), "architecture", line=15, bypass_rules=rules) is False

    def test_rule_without_standard_matches_nothing(self, tmp_path):
        """A rule with no 'standard' is a blank and silences nothing (owner, 2026-09-25 18:55)."""

        rules = [{"file": "file.py"}]
        assert is_bypassed(str(tmp_path / "file.py"), "architecture", bypass_rules=rules) is False

    def test_rule_without_file_matches_nothing(self, tmp_path):
        """A rule with no 'file' is a blank and silences nothing (owner, 2026-09-25 18:55)."""

        rules = [{"standard": "architecture"}]
        assert is_bypassed(str(tmp_path / "file.py"), "architecture", bypass_rules=rules) is False


# ===========================================================================
# 2. architecture_check — check_module (integration)
# ===========================================================================


class TestCheckModule:
    """Tests for check_module orchestration function."""

    def test_bypassed_file(self, tmp_path):
        """File with full architecture bypass returns passed with score 100."""

        f = tmp_path / "thing.py"
        f.write_text("x = 1\n", encoding="utf-8")
        rules = [{"standard": "architecture", "file": "thing.py"}]
        result = check_module(str(f), bypass_rules=rules)
        assert result["passed"] is True
        assert result["score"] == 100
        assert result["checks"][0]["name"] == "Bypassed"

    def test_nonexistent_file(self, tmp_path):
        """Missing file returns passed=False and score=0."""

        result = check_module(str(tmp_path / "nonexistent" / "path" / "file.py"))
        assert result["passed"] is False
        assert result["score"] == 0
        assert "not found" in result["checks"][0]["message"].lower()

    def test_unreadable_file(self, tmp_path):
        """File that raises on read returns error result."""

        # Create a directory with the same name to cause read error
        bad = tmp_path / "bad.py"
        bad.mkdir()
        result = check_module(str(bad))
        assert result["passed"] is False
        assert result["score"] == 0

    def test_handler_file_runs_independence_and_domain_checks(self, tmp_path):
        """Handler file runs handler independence and domain organization checks."""

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

        d = tmp_path / "branch" / "apps" / "modules"
        d.mkdir(parents=True)
        f = d / "__init__.py"
        f.write_text("# init\n", encoding="utf-8")
        result = check_module(str(f))
        check_names = [c["name"] for c in result["checks"]]
        assert "3-layer pattern" not in check_names

    def test_entry_point_primary_triggers_template_baseline(self, tmp_path):
        """Primary entry point with passport triggers template baseline."""

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

        lines = ["x"] * 300
        result = check_file_size(lines, "f.py")
        assert result["passed"] is True
        assert "good" in result["message"]

    def test_exactly_500_lines(self):

        lines = ["x"] * 500
        result = check_file_size(lines, "f.py")
        assert result["passed"] is True
        assert "getting heavy" in result["message"]

    def test_exactly_700_lines_advisory(self):

        lines = ["x"] * 700
        result = check_file_size(lines, "f.py")
        assert result["passed"] is True
        assert "advisory" in result["message"]

    def test_exactly_1500_lines_fails(self):

        lines = ["x"] * 1500
        result = check_file_size(lines, "f.py")
        assert result["passed"] is False
        assert "must split" in result["message"]

    def test_empty_file(self):

        result = check_file_size([], "f.py")
        assert result["passed"] is True
        assert "perfect" in result["message"]


# ===========================================================================
# 4. architecture_check — check_handler_independence edge cases
# ===========================================================================


class TestHandlerIndependenceEdgeCases:
    """Edge cases for handler independence."""

    def test_import_with_comment(self, tmp_path):
        """Import followed by a comment is still checked."""

        lines = [
            "from seedgo.apps.modules.audit import run  # inline comment",
        ]
        result = check_handler_independence(lines, str(tmp_path / "seedgo" / "apps" / "handlers" / "json" / "j.py"))
        assert result is not None
        assert result["passed"] is False

    def test_no_parent_branch_detected_generic_fail(self, tmp_path):
        """When parent branch cannot be determined, generic fail message is used."""

        lines = [
            "from something.apps.modules.stuff import thing",
        ]
        # Path with no 'apps' segment means parent_branch stays None
        result = check_handler_independence(lines, str(tmp_path / "random" / "path" / "handler.py"))
        assert result is not None
        assert result["passed"] is False
        assert "branch module" in result["message"]

    def test_single_line_docstring_skipped(self, tmp_path):
        """Single-line docstring with import text is skipped."""

        lines = [
            '"""from seedgo.apps.modules.audit import run"""',
            "def work():",
            "    pass",
        ]
        result = check_handler_independence(lines, str(tmp_path / "seedgo" / "apps" / "handlers" / "json" / "j.py"))
        assert result is not None
        assert result["passed"] is True

    def test_single_quote_docstring(self, tmp_path):
        """Single-quote triple-quoted docstrings are handled correctly."""

        lines = [
            "'''",
            "from seedgo.apps.modules.audit import run",
            "'''",
            "def work():",
            "    pass",
        ]
        result = check_handler_independence(lines, str(tmp_path / "seedgo" / "apps" / "handlers" / "json" / "j.py"))
        assert result is not None
        assert result["passed"] is True

    def test_empty_module_path(self):
        """Empty module path does not crash."""

        lines = ["import os"]
        result = check_handler_independence(lines, "")
        assert result is not None
        assert result["passed"] is True

    def test_comment_line_skipped(self, tmp_path):
        """Comment lines are skipped."""

        lines = [
            "# from seedgo.apps.modules.audit import run",
        ]
        result = check_handler_independence(lines, str(tmp_path / "seedgo" / "apps" / "handlers" / "json" / "j.py"))
        assert result is not None
        assert result["passed"] is True


# ===========================================================================
# 5. architecture_check — check_domain_organization edge cases
# ===========================================================================


class TestDomainOrganizationEdgeCases:
    """Additional domain organization tests."""

    def test_common_technical_name_fails(self, tmp_path):

        result = check_domain_organization(str(tmp_path / "branch" / "apps" / "handlers" / "common" / "file.py"))
        assert result is not None
        assert result["passed"] is False

    def test_shared_technical_name_fails(self, tmp_path):

        result = check_domain_organization(str(tmp_path / "branch" / "apps" / "handlers" / "shared" / "file.py"))
        assert result is not None
        assert result["passed"] is False

    def test_lib_technical_name_fails(self, tmp_path):

        result = check_domain_organization(str(tmp_path / "branch" / "apps" / "handlers" / "lib" / "file.py"))
        assert result is not None
        assert result["passed"] is False

    def test_operations_technical_name_fails(self, tmp_path):

        result = check_domain_organization(str(tmp_path / "branch" / "apps" / "handlers" / "operations" / "file.py"))
        assert result is not None
        assert result["passed"] is False

    def test_handler_domain_is_file(self, tmp_path):
        """When handler path has file directly in handlers/, domain is the filename."""

        result = check_domain_organization(str(tmp_path / "branch" / "apps" / "handlers" / "my_handler.py"))
        assert result is not None
        # my_handler.py is the "domain" — not a technical name, so it passes
        assert result["passed"] is True


# ===========================================================================
# 6. architecture_check — template baseline helpers
# ===========================================================================


class TestLoadIgnorePatterns:
    """.spawn/.registry_ignore.json, read through check_template_baseline's rows."""

    def test_no_ignore_file(self, tmp_path, monkeypatch):
        """Mutant: ignore list invented, no file in apps/handlers/aipass_standards/architecture_check.py — killed."""

        result = _baseline(tmp_path, monkeypatch, {"README.md": "# readme\n"})
        assert "File: README.md" in _rows(result)

    def test_valid_ignore_file(self, tmp_path, monkeypatch):
        """Mutant: the file's ignore_files dropped in apps/handlers/aipass_standards/architecture_check.py — killed."""

        ignore = json.dumps({"ignore_files": ["README.md"], "ignore_patterns": ["*.tmp"]})
        template = {".spawn/.registry_ignore.json": ignore, "README.md": "# readme\n", "data.tmp": "x\n"}
        rows = _rows(_baseline(tmp_path, monkeypatch, template))
        assert "File: README.md" not in rows
        assert "File: data.tmp" not in rows

    def test_malformed_ignore_file(self, tmp_path, monkeypatch):
        """Mutant: bad file yields an ignore list in apps/handlers/aipass_standards/architecture_check.py — killed."""

        template = {".spawn/.registry_ignore.json": "not json", "README.md": "# readme\n"}
        assert "File: README.md" in _rows(_baseline(tmp_path, monkeypatch, template))


def _ignoring(tmp_path, monkeypatch, files: list, patterns: list, template: dict) -> set:
    """The rows of a baseline whose template carries this ignore config."""
    ignore = json.dumps({"ignore_files": files, "ignore_patterns": patterns})
    return _rows(_baseline(tmp_path, monkeypatch, {".spawn/.registry_ignore.json": ignore, **template}))


class TestShouldIgnore:
    """Each ignore rule, read through the rows check_template_baseline scores."""

    def test_exact_filename_match(self, tmp_path, monkeypatch):
        """Mutant: ignore_files' first name skipped in apps/handlers/aipass_standards/architecture_check.py — killed."""

        rows = _ignoring(tmp_path, monkeypatch, ["README.md"], [], {"README.md": "x\n"})
        assert "File: README.md" not in rows

    def test_star_suffix_pattern(self, tmp_path, monkeypatch):
        """Mutant: the * kept in a suffix pattern in apps/handlers/aipass_standards/architecture_check.py — killed."""

        rows = _ignoring(tmp_path, monkeypatch, [], ["*.tmp"], {"data.tmp": "x\n"})
        assert "File: data.tmp" not in rows

    def test_dot_star_prefix_pattern(self, tmp_path, monkeypatch):
        """Mutant: * kept in .prefix* pattern in apps/handlers/aipass_standards/architecture_check.py — killed."""

        rows = _ignoring(tmp_path, monkeypatch, [], [".hidden*"], {".hidden_file": "x\n"})
        assert "File: .hidden_file" not in rows

    def test_exact_pattern_match(self, tmp_path, monkeypatch):
        """Mutant: pattern matched in parents only in apps/handlers/aipass_standards/architecture_check.py — killed."""

        rows = _ignoring(tmp_path, monkeypatch, [], ["__pycache__"], {"__pycache__": None})
        assert "Dir: __pycache__/" not in rows

    def test_pattern_in_parts(self, tmp_path, monkeypatch):
        """Mutant: pattern matched on name only in apps/handlers/aipass_standards/architecture_check.py — killed."""

        rows = _ignoring(tmp_path, monkeypatch, [], ["__pycache__"], {"__pycache__/something.pyc": "x\n"})
        assert "File: __pycache__/something.pyc" not in rows

    def test_no_match(self, tmp_path, monkeypatch):
        """Mutant: every item ignored in apps/handlers/aipass_standards/architecture_check.py — killed."""

        rows = _ignoring(tmp_path, monkeypatch, ["bad.py"], ["*.tmp"], {"good_file.py": "x\n"})
        assert "File: good_file.py" in rows


class TestGetCitizenClass:
    """The passport's citizen_class, read through check_template_baseline."""

    def test_no_passport(self, tmp_path, monkeypatch):
        """Mutant: no passport scored as failure in apps/handlers/aipass_standards/architecture_check.py — killed."""

        assert _baseline(tmp_path, monkeypatch, {}, passport=False) == []

    def test_valid_passport(self, tmp_path, monkeypatch):
        """Mutant: class read from wrong key in apps/handlers/aipass_standards/architecture_check.py — killed."""

        passport = json.dumps({"identity": {"citizen_class": "builder"}})
        result = _baseline(tmp_path, monkeypatch, {}, passport=passport)
        assert '"builder"' in result[0]["message"]

    def test_malformed_passport(self, tmp_path, monkeypatch):
        """Mutant: bad passport yields a class in apps/handlers/aipass_standards/architecture_check.py — killed."""

        result = _baseline(tmp_path, monkeypatch, {}, passport="not json")
        assert result[0]["message"] == "No citizen_class in mybranch/.trinity/passport.json"

    def test_passport_missing_citizen_class(self, tmp_path, monkeypatch):
        """Mutant: missing class defaulted in apps/handlers/aipass_standards/architecture_check.py — killed."""

        result = _baseline(tmp_path, monkeypatch, {}, passport=json.dumps({"identity": {}}))
        assert result[0]["message"] == "No citizen_class in mybranch/.trinity/passport.json"


class TestTransformPath:
    """Template paths as a branch reads them, through check_template_baseline's row names."""

    def test_basic_placeholder_replacement(self, tmp_path, monkeypatch):
        """Mutant: {{BRANCH}} left unreplaced in apps/handlers/aipass_standards/architecture_check.py — killed."""

        rows = _rows(_baseline(tmp_path, monkeypatch, {"{{BRANCH}}/apps/{{BRANCH}}.py": "x\n"}))
        assert "File: mybranch/apps/mybranch.py" in rows

    def test_hyphenated_branch_name(self, tmp_path, monkeypatch):
        """Hyphenated branch: placeholder replaced, then the entry-point rename applied.

        Mutant: entry named from my_branch in apps/handlers/aipass_standards/architecture_check.py — killed.
        """

        rows = _rows(_baseline(tmp_path, monkeypatch, {"apps/{{BRANCH}}.py": "x\n"}, branch_name="my-branch"))
        # branch_lower="my_branch" replaces placeholder -> "apps/my_branch.py"
        # FILE_RENAMES maps "my_branch.py" -> "my-branch.py" (entry_point_name)
        assert "File: apps/my-branch.py" in rows

    def test_dotted_branch_name(self, tmp_path, monkeypatch):
        """A leading dot is stripped for the entry-point name.

        Mutant: the entry-point rename skipped in apps/handlers/aipass_standards/architecture_check.py — killed.
        """

        rows = _rows(_baseline(tmp_path, monkeypatch, {"apps/{{BRANCH}}.py": "x\n"}, branch_name=".hidden"))
        # The placeholder replacement gives ".hidden.py"; FILE_RENAMES maps it to "hidden.py"
        assert "File: apps/hidden.py" in rows

    def test_no_placeholder(self, tmp_path, monkeypatch):
        """Mutant: rename keyed on any file in apps/handlers/aipass_standards/architecture_check.py — killed."""

        rows = _rows(_baseline(tmp_path, monkeypatch, {"apps/modules/helper.py": "x\n"}))
        assert "File: apps/modules/helper.py" in rows


class TestScanTemplate:
    """The template scan, through check_template_baseline's rows."""

    def test_scan_template_basic(self, tmp_path, monkeypatch):
        """Mutant: template dirs unlisted in apps/handlers/aipass_standards/architecture_check.py — killed."""

        # Create a minimal template structure
        template = {"apps/modules": None, "apps/entry.py": "# entry\n", "apps/modules/helper.py": "# helper\n"}
        rows = _rows(_baseline(tmp_path, monkeypatch, template))
        assert "Dir: apps/" in rows
        assert "File: apps/entry.py" in rows

    def test_scan_template_with_ignore(self, tmp_path, monkeypatch):
        """Mutant: ignore config unread in apps/handlers/aipass_standards/architecture_check.py — killed."""

        # Create template with an ignoreable file
        rows = _ignoring(tmp_path, monkeypatch, ["README.md"], [], {"README.md": "# r\n", "apps/entry.py": "# e\n"})
        # README.md should be ignored
        assert "File: README.md" not in rows
        assert "File: apps/entry.py" in rows

    def test_scan_template_excludes_test_scaffold(self, tmp_path, monkeypatch):
        """Mutant: template-only files kept in apps/handlers/aipass_standards/architecture_check.py — killed."""
        monkeypatch.setattr(
            architecture_check, "get_template_ignore_patterns", MagicMock(return_value=["test_scaffold.py"])
        )

        template = {"tests/conftest.py": "# conf\n", "tests/test_scaffold.py": "# scaffold\n"}
        rows = _rows(_baseline(tmp_path, monkeypatch, template))
        assert "File: tests/test_scaffold.py" not in rows
        assert "File: tests/conftest.py" in rows


# ===========================================================================
# 7. architecture_check — check_template_baseline with mocked templates
# ===========================================================================


class TestCheckTemplateBaselineFull:
    """Full template baseline tests with mocked spawn template dirs."""

    def test_a_template_entry_is_spelled_in_posix_on_every_platform(self):
        """The CI red of 2026-09-08, cured at the producer instead of at the pin.

        `_scan_template` rendered each entry with `str()`, which follows the
        host, so the Windows leg produced "apps\\something.py" where Linux
        produced "apps/something.py". Two things broke there and only one of them
        was visible: the check NAME a branch reads, and the bypass match, which
        is done against this same text while bypass rules are written with
        forward slashes - so a deliberate exception silently stopped being
        honoured on one platform. `_transform_path` already returned posix on its
        rename branch, so the module disagreed with itself.

        Asserted through `PureWindowsPath`, which behaves the same on every host,
        because a pin for a platform defect must not itself ask the platform.
        Mutation caught: `item.relative_to(root).as_posix()` becoming
        `str(item.relative_to(root))`, which answers "apps\\something.py" here.
        """
        spelled = architecture_check._relative_spelling(
            PureWindowsPath(r"C:\templates\citizen\apps\something.py"),
            PureWindowsPath(r"C:\templates\citizen"),
        )

        assert spelled == "apps/something.py"

    def test_spawn_templates_dir_missing(self, tmp_path, monkeypatch):
        """When SPAWN_TEMPLATES_DIR does not exist, returns failure."""
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
        # The missing file should be bypassed. Selected rather than guarded inside
        # a loop: if the check ever stops being emitted, the count fails here
        # instead of the test passing with nothing looked at.
        file_checks = [c for c in result if c["name"].startswith("File:")]
        bypassed = [c for c in file_checks if "something.py" in c["name"]]
        assert len(bypassed) == 1, f"expected one check for something.py, got {[c['name'] for c in result]}"
        assert bypassed[0]["name"] == "File: apps/something.py"
        assert bypassed[0]["passed"] is True
        assert bypassed[0]["message"] == "Template file missing (bypassed)"

    def test_template_baseline_missing_dir_bypassed(self, tmp_path, monkeypatch):
        """Bypassed missing template directory is marked as passed."""
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
        assert len(dir_checks) == 1, f"expected one handlers dir check, got {[c['name'] for c in result]}"
        assert dir_checks[0]["name"] == "Dir: apps/handlers/"
        assert dir_checks[0]["passed"] is True
        assert dir_checks[0]["message"] == "Template directory missing (bypassed)"


# ===========================================================================
# 8. checklist — _is_applicable
# ===========================================================================


class TestIsApplicable:
    """Tests for _is_applicable."""

    def test_branch_level_with_check_module(self, tmp_path):

        checker = MagicMock()
        checker.AUDIT_SCOPE = "branch_level"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, str(tmp_path / "file.py")) is True

    def test_branch_level_without_check_module(self, tmp_path):

        checker = MagicMock(spec=[])
        checker.AUDIT_SCOPE = "branch_level"
        assert _is_applicable(checker, str(tmp_path / "file.py")) is False

    def test_branch_level_non_python(self, tmp_path):

        checker = MagicMock()
        checker.AUDIT_SCOPE = "branch_level"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, str(tmp_path / "file.txt")) is False

    def test_all_files_scope_python(self, tmp_path):

        checker = MagicMock()
        checker.AUDIT_SCOPE = "all_files"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, str(tmp_path / "file.py")) is True

    def test_all_files_scope_non_python(self, tmp_path):

        checker = MagicMock()
        checker.AUDIT_SCOPE = "all_files"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, str(tmp_path / "file.txt")) is False

    def test_entry_point_scope_matches_entry(self, tmp_path):

        checker = MagicMock()
        checker.AUDIT_SCOPE = "entry_point"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, str(tmp_path / "branch" / "apps" / "branch.py")) is True

    def test_entry_point_scope_matches_entry_on_a_windows_path(self, tmp_path, monkeypatch):
        """A drive letter and backslashes still name an entry point (compass 458).

        Mutant: _is_entry_point's `file_path.replace("\\", "/")` back to `file_path` — killed.
        """
        # checklist's Path is WindowsPath on Windows; PureWindowsPath stands in for it on this host.
        monkeypatch.setattr(checklist, "Path", PureWindowsPath)
        checker = MagicMock()
        checker.AUDIT_SCOPE = "entry_point"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, _windows_form(tmp_path, "branch", "apps", "branch.py")) is True
        assert _is_applicable(checker, _windows_form(tmp_path, "branch", "apps", "modules", "helper.py")) is False

    def test_entry_point_scope_non_entry(self, tmp_path):

        checker = MagicMock()
        checker.AUDIT_SCOPE = "entry_point"
        checker.check_module = MagicMock()
        assert _is_applicable(checker, str(tmp_path / "branch" / "apps" / "modules" / "helper.py")) is False

    def test_no_check_module_returns_false(self, tmp_path):

        checker = MagicMock(spec=[])
        checker.AUDIT_SCOPE = "all_files"
        assert _is_applicable(checker, str(tmp_path / "file.py")) is False

    def test_default_scope_is_entry_point(self, tmp_path):
        """Checker with no AUDIT_SCOPE defaults to entry_point."""

        checker = MagicMock(spec=["check_module"])
        checker.check_module = MagicMock()
        # No AUDIT_SCOPE attribute -> defaults to "entry_point"
        assert _is_applicable(checker, str(tmp_path / "branch" / "apps" / "branch.py")) is True
        assert _is_applicable(checker, str(tmp_path / "branch" / "apps" / "modules" / "helper.py")) is False


# ===========================================================================
# 9. checklist — handle_command directory mode
# ===========================================================================


class TestHandleCommandDirectoryMode:
    """Tests for handle_command in directory mode."""

    def test_directory_with_py_files(self, tmp_path, monkeypatch):
        """Directory mode runs checklist on all .py files."""
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "first.py").write_text("x = 1\n", encoding="utf-8")
        (d / "second.py").write_text("y = 2\n", encoding="utf-8")
        (d / "_private.py").write_text("z = 3\n", encoding="utf-8")
        (d / "readme.txt").write_text("not python\n", encoding="utf-8")

        with patch.object(checklist, "run_checklist", return_value=[]) as ran:
            assert checklist.handle_command("checklist", [str(d)]) is True

        checked = sorted(Path(call.args[0]).name for call in ran.call_args_list)
        assert checked == ["first.py", "second.py"], "directory mode must skip _private.py and readme.txt"

    def test_directory_with_no_py_files(self, tmp_path, monkeypatch):
        """Directory with no .py files shows error."""

        d = tmp_path / "emptydir"
        d.mkdir()
        (d / "readme.txt").write_text("not python\n", encoding="utf-8")

        # Refuses since 2026-09-07: it printed ❌ and returned True, which
        # seedgo.py turned into exit 0 - a caller could not tell "nothing to
        # check here" from "checked, all clean".
        with pytest.raises(CommandRefused) as refused:
            checklist.handle_command("checklist", [str(d)])
        assert refused.value.code == refusal.EXIT_NO_UNITS

    def test_directory_filters_underscore_files(self, tmp_path, monkeypatch):
        """Directory mode filters files starting with underscore."""

        d = tmp_path / "onlypriv"
        d.mkdir()
        (d / "_init.py").write_text("x = 1\n", encoding="utf-8")

        # Filtered down to nothing is the same answer as empty, and it refuses
        # for the same reason.
        with pytest.raises(CommandRefused) as refused:
            checklist.handle_command("checklist", [str(d)])
        assert refused.value.code == refusal.EXIT_NO_UNITS


# ===========================================================================
# 10. checklist — handle_command with --pack flag
# ===========================================================================


class TestHandleCommandPackFlag:
    """Tests for handle_command with --pack flag."""

    def test_pack_flag(self, tmp_path, monkeypatch):
        """--pack flag passes pack_name to run_checklist."""
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        with patch.object(checklist, "run_checklist", return_value=[]) as ran:
            assert checklist.handle_command("checklist", ["--pack", "custom", str(f)]) is True

        ran.assert_called_once_with(str(f.resolve()), pack_name="custom", prototype=False)

    def test_short_pack_flag(self, tmp_path, monkeypatch):
        """-p flag is equivalent to --pack."""
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        with patch.object(checklist, "run_checklist", return_value=[]) as ran:
            assert checklist.handle_command("checklist", ["-p", "custom", str(f)]) is True

        ran.assert_called_once_with(str(f.resolve()), pack_name="custom", prototype=False)

    def test_no_file_after_pack_shows_error(self, monkeypatch):
        """--pack with no file specified shows error."""

        with pytest.raises(CommandRefused) as refused:
            checklist.handle_command("checklist", ["--pack", "custom"])
        assert refused.value.code == refusal.EXIT_UNKNOWN_ARGUMENT

    def test_unknown_flag_skipped(self, tmp_path, monkeypatch):
        """Unknown flags are skipped during argument parsing."""
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        with patch.object(checklist, "run_checklist", return_value=[]) as ran:
            assert checklist.handle_command("checklist", ["--unknown", str(f)]) is True

        # Skipped, not adopted as the file and not adopted as the pack.
        ran.assert_called_once_with(str(f.resolve()), pack_name="aipass", prototype=False)


# ===========================================================================
# 11. checklist — _resolve_pack_path
# ===========================================================================


class TestResolvePackPath:
    """A pack name resolved to its directory, through the command and run_checklist."""

    def test_nonexistent_pack(self, tmp_path, monkeypatch, capsys):
        """Mutant: every pack name resolved to a directory in apps/modules/checklist.py — killed."""
        _pin_checklist_gates(checklist, monkeypatch, tmp_path)
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        # The real handlers dir exists but holds no matching pack.
        assert checklist.handle_command(
            "checklist", ["--pack", "totally_bogus_pack_name_that_will_never_exist", str(f)]
        )
        out = capsys.readouterr().out
        assert "[FAIL] — (error): Pack 'totally_bogus_pack_name_that_will_never_exist' not found" in out

    def test_pack_not_found_in_run_checklist(self, tmp_path, monkeypatch):
        """run_checklist returns error when pack is not found."""
        _pin_checklist_gates(checklist, monkeypatch, tmp_path)

        # No bogus_standards/ exists, so the real pack lookup answers None.
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
    """The bypass rules a checker is handed, through run_checklist."""

    def test_no_branch_detected(self, tmp_path, monkeypatch):
        """Mutant: rules invented for a file in no branch in apps/modules/checklist.py — killed."""
        _results, probe = _run_one(tmp_path, monkeypatch, {"passed": True, "checks": []}, pin_branch=False)
        assert probe.check_module.call_args.kwargs["bypass_rules"] == []

    def test_branch_with_empty_path(self, tmp_path, monkeypatch):
        """Mutant: an empty branch path loaded as a branch in apps/modules/checklist.py — killed."""
        monkeypatch.setattr(
            checklist,
            "get_branch_from_path",
            MagicMock(return_value={"name": "mybranch", "path": ""}),
        )
        # Loading anything at all would hand these over; an empty path must load nothing.
        monkeypatch.setattr(checklist, "load_bypass_rules", MagicMock(return_value=[{"standard": "loaded"}]))

        _results, probe = _run_one(tmp_path, monkeypatch, {"passed": True, "checks": []}, pin_branch=False)
        assert probe.check_module.call_args.kwargs["bypass_rules"] == []

    def test_branch_with_absolute_path(self, tmp_path, monkeypatch):
        """Mutant: the loaded rules dropped before the checker in apps/modules/checklist.py — killed."""
        mock_load = MagicMock(return_value=[{"standard": "arch"}])
        monkeypatch.setattr(
            checklist,
            "get_branch_from_path",
            MagicMock(return_value={"name": "mybranch", "path": str(tmp_path / "absolute" / "path" / "mybranch")}),
        )
        monkeypatch.setattr(checklist, "load_bypass_rules", mock_load)

        _results, probe = _run_one(tmp_path, monkeypatch, {"passed": True, "checks": []}, pin_branch=False)
        assert probe.check_module.call_args.kwargs["bypass_rules"] == [{"standard": "arch"}]

    def test_branch_with_relative_path(self, tmp_path, monkeypatch):
        """Mutant: relative branch path resolved on CWD in apps/modules/checklist.py — killed."""
        mock_load = MagicMock(return_value=[])
        monkeypatch.setattr(
            checklist,
            "get_branch_from_path",
            MagicMock(return_value={"name": "mybranch", "path": "relative/path/mybranch"}),
        )
        monkeypatch.setattr(checklist, "load_bypass_rules", mock_load)
        monkeypatch.setattr(
            bypass_handler,
            "_find_registry",
            MagicMock(return_value=tmp_path / "repo_root" / "registry.json"),
        )

        _results, probe = _run_one(tmp_path, monkeypatch, {"passed": True, "checks": []}, pin_branch=False)
        mock_load.assert_called_once_with(str((tmp_path / "repo_root" / "relative" / "path" / "mybranch").resolve()))
        assert probe.check_module.call_args.kwargs["bypass_rules"] == []


# ===========================================================================
# 13. checklist — _format_failure
# ===========================================================================


class TestFormatFailureEdgeCases:
    """A failed checker's one-line detail, through run_checklist."""

    def test_format_failure_no_checks_key(self, tmp_path, monkeypatch):
        """A failed result with no 'checks' key gets the fallback.

        Mutant: the no-details fallback emptied in apps/modules/checklist.py — killed.
        """

        results, _probe = _run_one(tmp_path, monkeypatch, {"passed": False})
        assert "no details" in results[0]["detail"].lower()

    def test_format_failure_all_passed(self, tmp_path, monkeypatch):
        """A failed result whose checks all passed gets the fallback.

        Mutant: the no-details fallback emptied in apps/modules/checklist.py — killed.
        """

        results, _probe = _run_one(
            tmp_path, monkeypatch, {"passed": False, "checks": [{"passed": True, "message": "OK"}]}
        )
        assert "no details" in results[0]["detail"].lower()

    def test_format_failure_three_failures(self, tmp_path, monkeypatch):
        """Mutant: the +N more count off by one in apps/modules/checklist.py — killed."""

        returned = {
            "passed": False,
            "checks": [
                {"passed": False, "message": "First issue"},
                {"passed": False, "message": "Second issue"},
                {"passed": False, "message": "Third issue"},
            ],
        }
        results, _probe = _run_one(tmp_path, monkeypatch, returned)
        assert "First issue" in results[0]["detail"]
        assert "+2 more" in results[0]["detail"]

    def test_format_failure_missing_message(self, tmp_path, monkeypatch):
        """Mutant: the Unknown issue default blanked in apps/modules/checklist.py — killed."""

        results, _probe = _run_one(tmp_path, monkeypatch, {"passed": False, "checks": [{"passed": False}]})
        assert "Unknown issue" in results[0]["detail"]


# ===========================================================================
# 14. checklist — run_checklist with checker that raises exception
# ===========================================================================


class TestRunChecklistCheckerException:
    """Tests for run_checklist when a checker raises an exception."""

    def test_checker_exception_captured(self, tmp_path, monkeypatch):
        """Checker that raises exception is captured as a failed result."""
        _pin_checklist_gates(checklist, monkeypatch, tmp_path)

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
        monkeypatch.setattr(checklist, "_resolve_pack_path", lambda name: tmp_path / "fake_pack")

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
        _pin_checklist_gates(checklist, monkeypatch, tmp_path)

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
        monkeypatch.setattr(checklist, "_resolve_pack_path", lambda name: tmp_path / "fake_pack")

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        results = checklist.run_checklist(str(f))
        assert len(results) == 1
        assert results[0]["passed"] is False
        assert "Something is wrong" in results[0]["detail"]

    def test_no_applicable_checkers_returns_skip(self, tmp_path, monkeypatch):
        """When no checkers are applicable, returns skip result."""
        _pin_checklist_gates(checklist, monkeypatch, tmp_path)

        entry_only_checker = MagicMock()
        entry_only_checker.AUDIT_SCOPE = "entry_point"
        entry_only_checker.check_module = MagicMock()

        monkeypatch.setattr(
            checklist,
            "discover_checkers",
            lambda pack_path: {"entry_check": entry_only_checker},
        )
        monkeypatch.setattr(checklist, "_resolve_pack_path", lambda name: tmp_path / "fake_pack")

        # Create a file that is NOT an entry point
        f = tmp_path / "helper.py"
        f.write_text("x = 1\n", encoding="utf-8")

        results = checklist.run_checklist(str(f))
        assert len(results) == 1
        assert results[0]["passed"] is True
        assert "No applicable" in results[0]["detail"]

    def test_no_checkers_discovered(self, tmp_path, monkeypatch):
        """When discover_checkers returns empty dict, returns error."""
        _pin_checklist_gates(checklist, monkeypatch, tmp_path)

        monkeypatch.setattr(
            checklist,
            "discover_checkers",
            lambda pack_path: {},
        )
        monkeypatch.setattr(checklist, "_resolve_pack_path", lambda name: tmp_path / "fake_pack")

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
    """The checklist's printed verdicts, through the command, read off stdout."""

    @staticmethod
    def _printed(tmp_path, capsys, results) -> str:
        """`checklist <file>` with run_checklist answering ``results``; what the user reads."""
        capsys.readouterr()
        with patch.object(checklist, "run_checklist", return_value=results):
            assert checklist.handle_command("checklist", [str(tmp_path / "file.py")]) is True
        return capsys.readouterr().out

    def test_print_all_passed(self, tmp_path, capsys):
        """All-passed results show a checkmark per standard and the summary.

        Mutant: the summary line's markup unclosed in apps/modules/checklist.py — killed.
        """

        results = [
            {"standard": "architecture", "passed": True, "detail": None},
            {"standard": "documentation", "passed": True, "detail": None},
        ]
        out = self._printed(tmp_path, capsys, results)
        assert "✓ architecture" in out and "✓ documentation" in out
        assert "All 2 standards passed" in out

    def test_print_failed_with_detail(self, tmp_path, capsys):
        """Mutant: the detail dropped from a finding in apps/modules/checklist.py — killed."""

        results = [{"standard": "architecture", "passed": False, "detail": "Missing docstring"}]
        assert "[FAIL] — architecture: Missing docstring" in self._printed(tmp_path, capsys, results)

    def test_print_failed_without_detail(self, tmp_path, capsys):
        """Mutant: the marker dropped from a detail-less finding in apps/modules/checklist.py — killed."""

        results = [{"standard": "architecture", "passed": False, "detail": ""}]
        out = self._printed(tmp_path, capsys, results)
        assert "[FAIL] — architecture\n" in out

    def test_print_mixed_results(self, tmp_path, capsys):
        """Mixed results do not print the 'All passed' summary.

        Mutant: the summary printed unconditionally in apps/modules/checklist.py — killed.
        """

        results = [
            {"standard": "architecture", "passed": True, "detail": None},
            {"standard": "documentation", "passed": False, "detail": "Issues found"},
        ]
        # Check that "All X standards passed" was NOT printed
        assert "standards passed" not in self._printed(tmp_path, capsys, results)


# ===========================================================================
# 16. checklist — handle_command path resolution
# ===========================================================================


class TestHandleCommandPathResolution:
    """Tests for handle_command path resolution logic."""

    def test_absolute_path(self, tmp_path, monkeypatch):
        """Absolute file path is resolved directly."""
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        with patch.object(checklist, "run_checklist", return_value=[]) as ran:
            assert checklist.handle_command("checklist", [str(f)]) is True

        ran.assert_called_once_with(str(f.resolve()), pack_name="aipass", prototype=False)

    def test_relative_path_fallback_cwd(self, tmp_path, monkeypatch):
        """Mutant: the repo root never tried before CWD in apps/modules/checklist.py — killed."""
        # No git repo: the repo root is asked first and answers None.
        asked = []
        monkeypatch.setattr(checklist, "_get_repo_root", lambda: asked.append("repo root"))
        monkeypatch.chdir(tmp_path)

        f = tmp_path / "sample.py"
        f.write_text("x = 1\n", encoding="utf-8")

        with patch.object(checklist, "run_checklist", return_value=[]) as ran:
            assert checklist.handle_command("checklist", ["sample.py"]) is True

        # No repo root, so the bare name resolves against CWD — which is tmp_path.
        ran.assert_called_once_with(str((tmp_path / "sample.py").resolve()), pack_name="aipass", prototype=False)
        assert asked == ["repo root"]


# ===========================================================================
# 17. checklist — _is_entry_point edge cases
# ===========================================================================


class TestIsEntryPointEdgeCases:
    """Additional _is_entry_point edge cases."""

    def test_non_py_file(self, tmp_path):

        assert _is_entry_point(str(tmp_path / "branch" / "apps" / "config.json")) is False

    def test_nested_under_apps(self, tmp_path):

        assert _is_entry_point(str(tmp_path / "branch" / "apps" / "handlers" / "thing.py")) is False

    def test_no_apps_in_path(self, tmp_path):

        assert _is_entry_point(str(tmp_path / "branch" / "src" / "thing.py")) is False

    def test_valid_entry_point(self, tmp_path):

        assert _is_entry_point(str(tmp_path / "branch" / "apps" / "branch.py")) is True

    def test_valid_entry_point_on_a_windows_path(self, tmp_path, monkeypatch):
        """A drive letter and backslashes still name an entry point (compass 458).

        Mutant: _is_entry_point's `file_path.replace("\\", "/")` back to `file_path` — killed.
        """
        # checklist's Path is WindowsPath on Windows; PureWindowsPath stands in for it on this host.
        monkeypatch.setattr(checklist, "Path", PureWindowsPath)
        assert _is_entry_point(_windows_form(tmp_path, "branch", "apps", "branch.py")) is True
        assert _is_entry_point(_windows_form(tmp_path, "branch", "apps", "handlers", "thing.py")) is False
