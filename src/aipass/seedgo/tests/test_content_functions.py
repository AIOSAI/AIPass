"""Tests for all 37 content functions (standards + proof).

One test per content function. Each asserts the function's own subject matter
AND, through ``_assert_content_str``, that the answer is a non-empty multi-line
string.

Was 74 tests in 37 pairs until 2026-09-07 (FPLAN-0491). Every pair was a
``_returns_str`` row and a ``_has_expected_content`` row calling the SAME
function and asserting over the SAME value; the substring assertion already
fails on None (TypeError) and on an empty string, so the only claim unique to
the first row was "contains a newline". The pairs are merged, not dropped:
``_assert_content_str`` now runs inside the surviving row, on the same result.
Mutation-checked at the merge: a content function returning a single line
reds its test.

29 of the 37 rows carried an ``or``-joined substring assertion until 2026-09-07
(FPLAN-0509, assertion_shape OR-ESCAPE): ``assert "X" in result or "y" in
result.lower()`` passes on either clause, so it pinned neither. Each was
replaced by the substrings the function ACTUALLY returns, measured by calling
it and reading the string, one assert per claim. Two of the discarded clauses
were already dead and the ``or`` had been hiding it: ``"meta" in result.lower()``
is FALSE for get_introspection_standards, and ``"snake_case" in result.lower()``
is FALSE for get_naming_standards. All 66 replacement substrings were
mutation-checked one at a time against their own content module.
"""

# =================== META ====================
# Name: test_content_functions.py
# Description: Unit tests for all 37 content handler functions
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for content handlers."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # Force re-imports so content modules pick up fresh mocks
    standards_prefix = "aipass.seedgo.apps.handlers.aipass_standards"
    proof_prefix = "aipass.seedgo.apps.handlers.aipass_proof"
    content_modules = [
        f"{standards_prefix}.architecture_content",
        f"{standards_prefix}.cli_content",
        f"{standards_prefix}.cli_flags_content",
        f"{standards_prefix}.commented_logger_content",
        f"{standards_prefix}.dead_code_content",
        f"{standards_prefix}.debug_print_content",
        f"{standards_prefix}.deep_nesting_content",
        f"{standards_prefix}.documentation_content",
        f"{standards_prefix}.encapsulation_content",
        f"{standards_prefix}.error_handling_content",
        f"{standards_prefix}.handlers_content",
        f"{standards_prefix}.hardcoded_key_content",
        f"{standards_prefix}.help_text_content",
        f"{standards_prefix}.imports_content",
        f"{standards_prefix}.introspection_content",
        f"{standards_prefix}.json_structure_content",
        f"{standards_prefix}.log_handler_content",
        f"{standards_prefix}.log_level_content",
        f"{standards_prefix}.log_structure_content",
        f"{standards_prefix}.log_visibility_content",
        f"{standards_prefix}.meta_content",
        f"{standards_prefix}.modules_content",
        f"{standards_prefix}.naming_content",
        f"{standards_prefix}.permission_flags_content",
        f"{standards_prefix}.readme_content",
        f"{standards_prefix}.ruff_check_content",
        f"{standards_prefix}.shebang_content",
        f"{standards_prefix}.silent_catch_content",
        f"{standards_prefix}.stderr_routing_content",
        f"{standards_prefix}.todo_content",
        f"{standards_prefix}.trigger_content",
        f"{standards_prefix}.unused_function_content",
        f"{proof_prefix}.content_naming_content",
        f"{proof_prefix}.interface_content",
        f"{proof_prefix}.plugin_integrity_content",
        f"{proof_prefix}.readme_currency_content",
        f"{proof_prefix}.triplet_content",
    ]
    for mod_name in content_modules:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ===========================================================================
# Helper
# ===========================================================================


def _assert_content_str(result: str, label: str) -> None:
    """Validate that a content function returned a non-empty string."""
    assert isinstance(result, str), f"{label} should return str, got {type(result)}"
    assert len(result) > 0, f"{label} should return non-empty string"
    assert "\n" in result, f"{label} should be multi-line content"


# ===========================================================================
# PROOF CONTENT FUNCTIONS (5)
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. content_naming_proof
# ---------------------------------------------------------------------------


def test_get_content_naming_proof_has_expected_content():
    """get_content_naming_proof states the {name}_content.py -> get_{name}_standards() convention."""
    from aipass.seedgo.apps.handlers.aipass_proof.content_naming_content import (
        get_content_naming_proof,
    )

    result = get_content_naming_proof()
    _assert_content_str(result, "content_naming_proof")
    assert "CONTENT NAMING PROOF" in result
    assert "get_{name}_standards()" in result


# ---------------------------------------------------------------------------
# 2. interface_proof
# ---------------------------------------------------------------------------


def test_get_interface_proof_has_expected_content():
    """get_interface_proof states the AUDIT_SCOPE rule and the check_branch signature."""
    from aipass.seedgo.apps.handlers.aipass_proof.interface_content import (
        get_interface_proof,
    )

    result = get_interface_proof()
    _assert_content_str(result, "interface_proof")
    assert "INTERFACE PROOF" in result
    assert "AUDIT_SCOPE variable is declared at module level" in result
    assert "def check_branch(branch_path, module_name)" in result


# ---------------------------------------------------------------------------
# 3. plugin_integrity_proof
# ---------------------------------------------------------------------------


def test_get_plugin_integrity_proof_has_expected_content():
    """get_plugin_integrity_proof demands dynamic discovery and names standards_audit.py."""
    from aipass.seedgo.apps.handlers.aipass_proof.plugin_integrity_content import (
        get_plugin_integrity_proof,
    )

    result = get_plugin_integrity_proof()
    _assert_content_str(result, "plugin_integrity_proof")
    assert "PLUGIN INTEGRITY PROOF" in result
    assert "dynamic discovery (glob + importlib)" in result
    assert "standards_audit.py" in result


# ---------------------------------------------------------------------------
# 4. readme_currency_proof
# ---------------------------------------------------------------------------


def test_get_readme_currency_proof_has_expected_content():
    """get_readme_currency_proof states that the README checker count must match reality."""
    from aipass.seedgo.apps.handlers.aipass_proof.readme_currency_content import (
        get_readme_currency_proof,
    )

    result = get_readme_currency_proof()
    _assert_content_str(result, "readme_currency_proof")
    assert "README CURRENCY PROOF" in result
    assert "Checker count in README matches actual" in result


# ---------------------------------------------------------------------------
# 5. triplet_proof
# ---------------------------------------------------------------------------


def test_get_triplet_proof_has_expected_content():
    """get_triplet_proof names all three files of the triplet."""
    from aipass.seedgo.apps.handlers.aipass_proof.triplet_content import (
        get_triplet_proof,
    )

    result = get_triplet_proof()
    _assert_content_str(result, "triplet_proof")
    assert "TRIPLET PROOF" in result
    assert "{name}_check.py" in result
    assert "{name}_content.py" in result
    assert "{name}.md" in result


# ===========================================================================
# STANDARDS CONTENT FUNCTIONS (28)
# ===========================================================================


# ---------------------------------------------------------------------------
# 6. architecture_standards
# ---------------------------------------------------------------------------


def test_get_architecture_standards_has_expected_content():
    """get_architecture_standards states the 3-layer pattern and the handler import ban."""
    from aipass.seedgo.apps.handlers.aipass_standards.architecture_content import (
        get_architecture_standards,
    )

    result = get_architecture_standards()
    _assert_content_str(result, "architecture_standards")
    assert "THE 3-LAYER PATTERN:" in result
    assert "Handlers CANNOT import modules" in result


# ---------------------------------------------------------------------------
# 7. cli_standards
# ---------------------------------------------------------------------------


def test_get_cli_standards_has_expected_content():
    """get_cli_standards names Rich console.print() as the only approved output path."""
    from aipass.seedgo.apps.handlers.aipass_standards.cli_content import (
        get_cli_standards,
    )

    result = get_cli_standards()
    _assert_content_str(result, "cli_standards")
    assert "OUTPUT STANDARD: Rich console.print() ONLY" in result
    assert "from aipass.cli.apps.modules import console" in result


# ---------------------------------------------------------------------------
# 8. cli_flags_standards
# ---------------------------------------------------------------------------


def test_get_cli_flags_standards_has_expected_content():
    """get_cli_flags_standards lists the tier 1 required flags, --help and --version among them."""
    from aipass.seedgo.apps.handlers.aipass_standards.cli_flags_content import (
        get_cli_flags_standards,
    )

    result = get_cli_flags_standards()
    _assert_content_str(result, "cli_flags_standards")
    assert "CLI FLAGS STANDARD" in result
    assert "TIER 1 - REQUIRED FLAGS:" in result
    assert "--help" in result
    assert "--version" in result


# ---------------------------------------------------------------------------
# 9. commented_logger_standards
# ---------------------------------------------------------------------------


def test_get_commented_logger_standards_has_expected_content():
    """get_commented_logger_standards calls commented-out logger calls dead logging and lists the detected levels."""
    from aipass.seedgo.apps.handlers.aipass_standards.commented_logger_content import (
        get_commented_logger_standards,
    )

    result = get_commented_logger_standards()
    _assert_content_str(result, "commented_logger_standards")
    assert "Commented-out logger calls are dead logging" in result
    assert "error, warning, warn, info, exception, critical, debug." in result


# ---------------------------------------------------------------------------
# 10. dead_code_standards
# ---------------------------------------------------------------------------


def test_get_dead_code_standards_has_expected_content():
    """get_dead_code_standards calls unreferenced files dead weight and declares branch_level scope."""
    from aipass.seedgo.apps.handlers.aipass_standards.dead_code_content import (
        get_dead_code_standards,
    )

    result = get_dead_code_standards()
    _assert_content_str(result, "dead_code_standards")
    assert "Unreferenced files are dead weight" in result
    assert "branch_level" in result


# ---------------------------------------------------------------------------
# 11. debug_print_standards
# ---------------------------------------------------------------------------


def test_get_debug_print_standards_has_expected_content():
    """get_debug_print_standards bans bare print() and points at the Prax logger instead."""
    from aipass.seedgo.apps.handlers.aipass_standards.debug_print_content import (
        get_debug_print_standards,
    )

    result = get_debug_print_standards()
    _assert_content_str(result, "debug_print_standards")
    assert "have no place in production code" in result
    assert "Use structured logging (Prax logger)" in result


# ---------------------------------------------------------------------------
# 12. deep_nesting_standards
# ---------------------------------------------------------------------------


def test_get_deep_nesting_standards_has_expected_content():
    """get_deep_nesting_standards states the depth > 4 threshold and the counted node types."""
    from aipass.seedgo.apps.handlers.aipass_standards.deep_nesting_content import (
        get_deep_nesting_standards,
    )

    result = get_deep_nesting_standards()
    _assert_content_str(result, "deep_nesting_standards")
    assert "Threshold: depth > 4 is a violation" in result
    assert "If, For, While, Try, With, ExceptHandler" in result


# ---------------------------------------------------------------------------
# 13. documentation_standards
# ---------------------------------------------------------------------------


def test_get_documentation_standards_has_expected_content():
    """get_documentation_standards requires a module docstring and Google-style function docstrings."""
    from aipass.seedgo.apps.handlers.aipass_standards.documentation_content import (
        get_documentation_standards,
    )

    result = get_documentation_standards()
    _assert_content_str(result, "documentation_standards")
    assert "REQUIRED: MODULE DOCSTRING" in result
    assert "FUNCTION DOCSTRINGS (Google-style)" in result


# ---------------------------------------------------------------------------
# 14. encapsulation_standards
# ---------------------------------------------------------------------------


def test_get_encapsulation_standards_has_expected_content():
    """get_encapsulation_standards states rule 1, no cross-branch handler imports."""
    from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_content import (
        get_encapsulation_standards,
    )

    result = get_encapsulation_standards()
    _assert_content_str(result, "encapsulation_standards")
    assert "ENCAPSULATION STANDARDS" in result
    assert "RULE 1: No Cross-Branch Handler Imports" in result


# ---------------------------------------------------------------------------
# 15. error_handling_standards
# ---------------------------------------------------------------------------


def test_get_error_handling_standards_has_expected_content():
    """get_error_handling_standards demands truthful errors and names the except: pass failure."""
    from aipass.seedgo.apps.handlers.aipass_standards.error_handling_content import (
        get_error_handling_standards,
    )

    result = get_error_handling_standards()
    _assert_content_str(result, "error_handling_standards")
    assert "Errors must tell the truth." in result
    assert "except: pass" in result


# ---------------------------------------------------------------------------
# 16. handlers_standards
# ---------------------------------------------------------------------------


def test_get_handlers_standards_has_expected_content():
    """get_handlers_standards mentions handler concepts."""
    from aipass.seedgo.apps.handlers.aipass_standards.handlers_content import (
        get_handlers_standards,
    )

    result = get_handlers_standards()
    _assert_content_str(result, "handlers_standards")
    assert "handler" in result.lower()


# ---------------------------------------------------------------------------
# 17. hardcoded_key_standards
# ---------------------------------------------------------------------------


def test_get_hardcoded_key_standards_has_expected_content():
    """get_hardcoded_key_standards bans literal API keys and lists the detected provider prefixes."""
    from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_key_content import (
        get_hardcoded_key_standards,
    )

    result = get_hardcoded_key_standards()
    _assert_content_str(result, "hardcoded_key_standards")
    assert "API keys and secrets must" in result
    assert "Provider prefixes:" in result


# ---------------------------------------------------------------------------
# 18. help_text_standards
# ---------------------------------------------------------------------------


def test_get_help_text_standards_has_expected_content():
    """get_help_text_standards mentions help text concepts."""
    from aipass.seedgo.apps.handlers.aipass_standards.help_text_content import (
        get_help_text_standards,
    )

    result = get_help_text_standards()
    _assert_content_str(result, "help_text_standards")
    assert "help" in result.lower()


# ---------------------------------------------------------------------------
# 19. imports_standards
# ---------------------------------------------------------------------------


def test_get_imports_standards_has_expected_content():
    """get_imports_standards mentions import concepts."""
    from aipass.seedgo.apps.handlers.aipass_standards.imports_content import (
        get_imports_standards,
    )

    result = get_imports_standards()
    _assert_content_str(result, "imports_standards")
    assert "import" in result.lower()


# ---------------------------------------------------------------------------
# 20. introspection_standards
# ---------------------------------------------------------------------------


def test_get_introspection_standards_has_expected_content():
    """get_introspection_standards states the two-level auto-discovery pattern and its function name."""
    from aipass.seedgo.apps.handlers.aipass_standards.introspection_content import (
        get_introspection_standards,
    )

    result = get_introspection_standards()
    _assert_content_str(result, "introspection_standards")
    assert "TWO-LEVEL AUTO-DISCOVERY PATTERN" in result
    assert "print_introspection()" in result


# ---------------------------------------------------------------------------
# 21. json_structure_standards
# ---------------------------------------------------------------------------


def test_get_json_structure_standards_has_expected_content():
    """get_json_structure_standards mentions JSON structure concepts."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_content import (
        get_json_structure_standards,
    )

    result = get_json_structure_standards()
    _assert_content_str(result, "json_structure_standards")
    assert "json" in result.lower()


# ---------------------------------------------------------------------------
# 22. log_handler_standards
# ---------------------------------------------------------------------------


def test_get_log_handler_standards_has_expected_content():
    """get_log_handler_standards requires RotatingFileHandler via prax."""
    from aipass.seedgo.apps.handlers.aipass_standards.log_handler_content import (
        get_log_handler_standards,
    )

    result = get_log_handler_standards()
    _assert_content_str(result, "log_handler_standards")
    assert "LOG HANDLER ROTATION STANDARD" in result
    assert "RotatingFileHandler" in result


# ---------------------------------------------------------------------------
# 23. log_level_standards
# ---------------------------------------------------------------------------


def test_get_log_level_standards_has_expected_content():
    """get_log_level_standards reserves ERROR for real system failures."""
    from aipass.seedgo.apps.handlers.aipass_standards.log_level_content import (
        get_log_level_standards,
    )

    result = get_log_level_standards()
    _assert_content_str(result, "log_level_standards")
    assert "LOG LEVEL HYGIENE STANDARD" in result
    assert "Ensure ERROR level is reserved for real system failures." in result


# ---------------------------------------------------------------------------
# 24. log_structure_standards
# ---------------------------------------------------------------------------


def test_get_log_structure_standards_has_expected_content():
    """get_log_structure_standards states the two-tier model with system_logs/ at repo root."""
    from aipass.seedgo.apps.handlers.aipass_standards.log_structure_content import (
        get_log_structure_standards,
    )

    result = get_log_structure_standards()
    _assert_content_str(result, "log_structure_standards")
    assert "TWO-TIER LOG STRUCTURE" in result
    assert "system_logs/" in result


# ---------------------------------------------------------------------------
# 25. log_visibility_standards
# ---------------------------------------------------------------------------


def test_get_log_visibility_standards_has_expected_content():
    """get_log_visibility_standards ties logging.getLogger() to a required prax system_logger import."""
    from aipass.seedgo.apps.handlers.aipass_standards.log_visibility_content import (
        get_log_visibility_standards,
    )

    result = get_log_visibility_standards()
    _assert_content_str(result, "log_visibility_standards")
    assert "LOG VISIBILITY STANDARD" in result
    assert "logging.getLogger()" in result
    assert "prax system_logger" in result


# ---------------------------------------------------------------------------
# 26. meta_standards
# ---------------------------------------------------------------------------


def test_get_meta_standards_has_expected_content():
    """get_meta_standards requires a META block on line 1 of every Python file."""
    from aipass.seedgo.apps.handlers.aipass_standards.meta_content import (
        get_meta_standards,
    )

    result = get_meta_standards()
    _assert_content_str(result, "meta_standards")
    assert "META BLOCK STANDARD" in result
    assert "Every Python file starts with a META block on line 1" in result


# ---------------------------------------------------------------------------
# 27. modules_standards
# ---------------------------------------------------------------------------


def test_get_modules_standards_has_expected_content():
    """get_modules_standards mentions module concepts."""
    from aipass.seedgo.apps.handlers.aipass_standards.modules_content import (
        get_modules_standards,
    )

    result = get_modules_standards()
    _assert_content_str(result, "modules_standards")
    assert "module" in result.lower()


# ---------------------------------------------------------------------------
# 28. naming_standards
# ---------------------------------------------------------------------------


def test_get_naming_standards_has_expected_content():
    """get_naming_standards states path = context, name = action, and lists the standard verbs."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_content import (
        get_naming_standards,
    )

    result = get_naming_standards()
    _assert_content_str(result, "naming_standards")
    assert "Path = Context, Name = Action" in result
    assert "STANDARD VERBS:" in result


# ---------------------------------------------------------------------------
# 29. permission_flags_standards
# ---------------------------------------------------------------------------


def test_get_permission_flags_standards_has_expected_content():
    """get_permission_flags_standards names the one approved permission bypass flag."""
    from aipass.seedgo.apps.handlers.aipass_standards.permission_flags_content import (
        get_permission_flags_standards,
    )

    result = get_permission_flags_standards()
    _assert_content_str(result, "permission_flags_standards")
    assert "PERMISSION FLAGS STANDARD" in result
    assert "--permission-mode bypassPermissions" in result


# ---------------------------------------------------------------------------
# 30. readme_standards
# ---------------------------------------------------------------------------


def test_get_readme_standards_has_expected_content():
    """get_readme_standards mentions README concepts."""
    from aipass.seedgo.apps.handlers.aipass_standards.readme_content import (
        get_readme_standards,
    )

    result = get_readme_standards()
    _assert_content_str(result, "readme_standards")
    assert "readme" in result.lower()


# ---------------------------------------------------------------------------
# 31. ruff_check_standards
# ---------------------------------------------------------------------------


def test_get_ruff_check_standards_has_expected_content():
    """get_ruff_check_standards names ruff as the primary linter and shows the JSON output flag."""
    from aipass.seedgo.apps.handlers.aipass_standards.ruff_check_content import (
        get_ruff_check_standards,
    )

    result = get_ruff_check_standards()
    _assert_content_str(result, "ruff_check_standards")
    assert "Ruff is the primary linter for AIPass code." in result
    assert "--output-format=json" in result


# ---------------------------------------------------------------------------
# 32. shebang_standards
# ---------------------------------------------------------------------------


def test_get_shebang_standards_has_expected_content():
    """get_shebang_standards bans shebangs in pip-installable packages."""
    from aipass.seedgo.apps.handlers.aipass_standards.shebang_content import (
        get_shebang_standards,
    )

    result = get_shebang_standards()
    _assert_content_str(result, "shebang_standards")
    assert "SHEBANG STANDARD" in result
    assert "No shebangs in pip-installable packages" in result


# ---------------------------------------------------------------------------
# 33. silent_catch_standards
# ---------------------------------------------------------------------------


def test_get_silent_catch_standards_has_expected_content():
    """get_silent_catch_standards bans silently swallowed exceptions and names the ExceptHandler walk."""
    from aipass.seedgo.apps.handlers.aipass_standards.silent_catch_content import (
        get_silent_catch_standards,
    )

    result = get_silent_catch_standards()
    _assert_content_str(result, "silent_catch_standards")
    assert "Never silently swallow exceptions." in result
    assert "ExceptHandler" in result


# ---------------------------------------------------------------------------
# 34. stderr_routing_standards
# ---------------------------------------------------------------------------


def test_get_stderr_routing_standards_has_expected_content():
    """get_stderr_routing_standards mentions stderr routing concepts."""
    from aipass.seedgo.apps.handlers.aipass_standards.stderr_routing_content import (
        get_stderr_routing_standards,
    )

    result = get_stderr_routing_standards()
    _assert_content_str(result, "stderr_routing_standards")
    assert "stderr" in result.lower()


# ---------------------------------------------------------------------------
# 35. todo_standards
# ---------------------------------------------------------------------------


def test_get_todo_standards_has_expected_content():
    """get_todo_standards names the TODO and FIXME tags it flags."""
    from aipass.seedgo.apps.handlers.aipass_standards.todo_content import (
        get_todo_standards,
    )

    result = get_todo_standards()
    _assert_content_str(result, "todo_standards")
    assert "Code should be complete." in result
    assert "TODO" in result
    assert "FIXME" in result


# ---------------------------------------------------------------------------
# 36. trigger_standards
# ---------------------------------------------------------------------------


def test_get_trigger_standards_has_expected_content():
    """get_trigger_standards mentions trigger concepts."""
    from aipass.seedgo.apps.handlers.aipass_standards.trigger_content import (
        get_trigger_standards,
    )

    result = get_trigger_standards()
    _assert_content_str(result, "trigger_standards")
    assert "trigger" in result.lower()


# ---------------------------------------------------------------------------
# 37. unused_function_standards
# ---------------------------------------------------------------------------


def test_get_unused_function_standards_has_expected_content():
    """get_unused_function_standards calls dead code a maintenance burden and names phase 1."""
    from aipass.seedgo.apps.handlers.aipass_standards.unused_function_content import (
        get_unused_function_standards,
    )

    result = get_unused_function_standards()
    _assert_content_str(result, "unused_function_standards")
    assert "Dead code is maintenance burden." in result
    assert "Phase 1 -- Collect files:" in result
