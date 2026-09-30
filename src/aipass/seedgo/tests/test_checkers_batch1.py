# =================== META ====================
# Name: test_checkers_batch1.py
# Description: Unit tests for 8 aipass_standards checkers
# Version: 1.0.2
# Created: 2026-03-29
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/architecture_check.py and seven batch-1 sibling checkers."""

# Covers architecture, cli, cli_flags, commented_logger, debug_print, deep_nesting,
# documentation and encapsulation. Each checker gets 3 tests: clean pass, violation
# caught, bypass respected.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the eight checker modules under test parse and import
# seedgo: no-test-needed(constant) — each checker's STANDARD name string, not asserted by any test here

from unittest.mock import MagicMock

import pytest

from aipass.seedgo.apps.handlers.bypass import utils as _bypass_utils
from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
    check_module as check_architecture,
)
from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
    check_module as check_cli,
)
from aipass.seedgo.apps.handlers.aipass_standards.cli_flags_check import (
    check_module as check_cli_flags,
)
from aipass.seedgo.apps.handlers.aipass_standards.commented_logger_check import (
    check_module as check_commented_logger,
)
from aipass.seedgo.apps.handlers.aipass_standards.debug_print_check import (
    check_module as check_debug_print,
)
from aipass.seedgo.apps.handlers.aipass_standards.deep_nesting_check import (
    check_module as check_deep_nesting,
)
from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
    check_module as check_documentation,
)
from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
    check_module as check_encapsulation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pin_bypass_log(monkeypatch):
    """Point is_bypassed's json_handler at a mock for every test here.

    The bypass tests call the real is_bypassed, which appends to the
    repo-tracked seedgo_json/utils_log.json via the json_handler global in
    its OWN module — xdist workers racing on that shared file corrupt it
    (JSONDecodeError: Extra data). sys.modules patching never reaches a
    function's globals, so the pin must land on the utils module object.
    """
    mock_handler = MagicMock()
    mock_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(_bypass_utils, "json_handler", mock_handler)


# ===========================================================================
# 1. architecture_check
# ===========================================================================


def test_architecture_check_clean_passes(tmp_path):
    """A small file in apps/modules/ passes architecture checks."""
    # Build a realistic path structure: branch/apps/modules/clean.py
    modules_dir = tmp_path / "mybranch" / "apps" / "modules"
    modules_dir.mkdir(parents=True)
    clean_file = modules_dir / "clean.py"
    clean_file.write_text(
        '"""Clean module."""\n\ndef do_work():\n    return True\n',
        encoding="utf-8",
    )
    result = check_architecture(str(clean_file))
    assert isinstance(result, dict)
    assert "passed" in result and "score" in result and "checks" in result
    assert result["score"] >= 75, f"Clean module code should pass: {result}"


def test_architecture_check_violation_caught(tmp_path):
    """A 750-line file outside the 3-layer structure should lose points."""
    # File NOT in apps/, modules/, or handlers/ — violates 3-layer pattern
    bad_file = tmp_path / "random_dir" / "big.py"
    bad_file.parent.mkdir(parents=True)
    lines = ['"""Big module."""\n'] + ["x = 1\n"] * 750
    bad_file.write_text("".join(lines), encoding="utf-8")
    result = check_architecture(str(bad_file))
    assert result["score"] < 100, f"Over-sized file outside 3-layer should lose points: {result}"


def test_architecture_check_bypass_respected(tmp_path):
    """Bypass rules should grant score 100."""
    f = tmp_path / "bypassed.py"
    f.write_text("x = 1\n", encoding="utf-8")
    bypass_rules = [{"standard": "architecture", "file": "bypassed.py"}]
    result = check_architecture(str(f), bypass_rules=bypass_rules)
    assert result["score"] == 100, f"Bypass should yield 100: {result}"


# ===========================================================================
# 2. cli_check
# ===========================================================================


def test_cli_check_clean_passes(tmp_path):
    """A module file using console.print and no bare print() should pass."""
    modules_dir = tmp_path / "mybranch" / "apps" / "modules"
    modules_dir.mkdir(parents=True)
    clean_file = modules_dir / "display.py"
    clean_file.write_text(
        '"""Display module."""\n\n'
        "from aipass.cli.apps.modules.display import console\n\n"
        "def show():\n"
        '    """Show output."""\n'
        '    console.print("hello")\n',
        encoding="utf-8",
    )
    result = check_cli(str(clean_file))
    assert result["score"] >= 75, f"Clean CLI code should pass: {result}"


def test_cli_check_violation_caught(tmp_path):
    """A module file with bare print() should fail the print usage check."""
    modules_dir = tmp_path / "mybranch" / "apps" / "modules"
    modules_dir.mkdir(parents=True)
    bad_file = modules_dir / "noisy.py"
    bad_file.write_text(
        '"""Noisy module."""\n\ndef run():\n    """Run it."""\n    print("raw output")\n    print("more raw output")\n',
        encoding="utf-8",
    )
    result = check_cli(str(bad_file))
    assert result["score"] < 100, f"Bare print() should lose points: {result}"


def test_cli_check_bypass_respected(tmp_path):
    """Bypass rules should grant score 100."""
    f = tmp_path / "bypassed.py"
    f.write_text('print("hello")\n', encoding="utf-8")
    bypass_rules = [{"standard": "cli", "file": "bypassed.py"}]
    result = check_cli(str(f), bypass_rules=bypass_rules)
    assert result["score"] == 100, f"Bypass should yield 100: {result}"


# ===========================================================================
# 3. cli_flags_check
# ===========================================================================


def test_cli_flags_check_clean_passes(tmp_path):
    """An entry point file with --version flag support should pass."""
    apps_dir = tmp_path / "mybranch" / "apps"
    apps_dir.mkdir(parents=True)
    entry_file = apps_dir / "mybranch.py"
    entry_file.write_text(
        '"""Entry point."""\n\n'
        "import sys\n\n"
        "def main():\n"
        '    """Main entry."""\n'
        '    if "--version" in sys.argv or "-V" in sys.argv:\n'
        '        print("mybranch 1.0.0")\n'
        "        return\n",
        encoding="utf-8",
    )
    result = check_cli_flags(str(entry_file))
    assert result["score"] >= 75, f"Entry point with --version should pass: {result}"


def test_cli_flags_check_violation_caught(tmp_path):
    """An entry point without --version flag should fail."""
    apps_dir = tmp_path / "mybranch" / "apps"
    apps_dir.mkdir(parents=True)
    entry_file = apps_dir / "mybranch.py"
    entry_file.write_text(
        '"""Entry point."""\n\ndef main():\n    """Main entry."""\n    pass\n',
        encoding="utf-8",
    )
    result = check_cli_flags(str(entry_file))
    assert result["score"] < 100, f"Entry point without --version should lose points: {result}"


def test_cli_flags_check_bypass_respected(tmp_path):
    """Bypass rules should grant score 100."""
    apps_dir = tmp_path / "mybranch" / "apps"
    apps_dir.mkdir(parents=True)
    f = apps_dir / "mybranch.py"
    f.write_text('"""No flags."""\ndef main():\n    pass\n', encoding="utf-8")
    bypass_rules = [{"standard": "cli_flags", "file": "mybranch.py"}]
    result = check_cli_flags(str(f), bypass_rules=bypass_rules)
    assert result["score"] == 100, f"Bypass should yield 100: {result}"


# ===========================================================================
# 4. commented_logger_check
# ===========================================================================


def test_commented_logger_check_clean_passes(tmp_path):
    """A file with no commented-out logger calls should pass."""
    clean_file = tmp_path / "clean.py"
    clean_file.write_text(
        '"""Clean module."""\n\n'
        "from aipass.prax import logger\n\n"
        "def do_work():\n"
        '    """Do work."""\n'
        '    logger.info("Working")\n'
        "    return True\n",
        encoding="utf-8",
    )
    result = check_commented_logger(str(clean_file))
    assert result["score"] == 100, f"Clean code should score 100: {result}"


def test_commented_logger_check_violation_caught(tmp_path):
    """A file with commented-out logger calls should fail."""
    bad_file = tmp_path / "messy.py"
    bad_file.write_text(
        '"""Messy module."""\n\n'
        '# logger.info("old debug line")\n'
        '# logger.error("disabled error")\n'
        "def do_work():\n"
        '    """Do work."""\n'
        '    # logger.warning("stale warning")\n'
        "    return True\n",
        encoding="utf-8",
    )
    result = check_commented_logger(str(bad_file))
    assert result["score"] < 100, f"Commented-out loggers should lose points: {result}"


def test_commented_logger_check_bypass_respected(tmp_path):
    """Bypass rules should grant score 100."""
    f = tmp_path / "bypassed.py"
    f.write_text('# logger.info("disabled")\n', encoding="utf-8")
    bypass_rules = [{"standard": "commented_logger", "file": "bypassed.py"}]
    result = check_commented_logger(str(f), bypass_rules=bypass_rules)
    assert result["score"] == 100, f"Bypass should yield 100: {result}"


# ===========================================================================
# 5. debug_print_check
# ===========================================================================


def test_debug_print_check_clean_passes(tmp_path):
    """A file with no bare print() calls should pass."""
    clean_file = tmp_path / "clean.py"
    clean_file.write_text(
        '"""Clean module."""\n\n'
        "from aipass.prax import logger\n\n"
        "def do_work():\n"
        '    """Do work."""\n'
        '    logger.info("Working")\n'
        "    return True\n",
        encoding="utf-8",
    )
    result = check_debug_print(str(clean_file))
    assert result["score"] == 100, f"Clean code should score 100: {result}"


def test_debug_print_check_violation_caught(tmp_path):
    """A file with bare print() calls should fail."""
    bad_file = tmp_path / "debug_leftovers.py"
    bad_file.write_text(
        '"""Debug leftover module."""\n\n'
        "def do_work():\n"
        '    """Do work."""\n'
        '    print("DEBUG: got here")\n'
        '    print("DEBUG: value is", 42)\n'
        "    return True\n",
        encoding="utf-8",
    )
    result = check_debug_print(str(bad_file))
    assert result["score"] < 100, f"Bare print() calls should lose points: {result}"


def test_debug_print_check_bypass_respected(tmp_path):
    """Bypass rules should grant score 100."""
    f = tmp_path / "bypassed.py"
    f.write_text(
        '"""Bypassed."""\nprint("allowed")\n',
        encoding="utf-8",
    )
    bypass_rules = [{"standard": "debug_print", "file": "bypassed.py"}]
    result = check_debug_print(str(f), bypass_rules=bypass_rules)
    assert result["score"] == 100, f"Bypass should yield 100: {result}"


def test_debug_print_string_literal_not_flagged(tmp_path):
    """print() mentioned inside string literals must not trigger false positives."""
    f = tmp_path / "messages.py"
    f.write_text(
        '"""Module with print() in docstring."""\n\n'
        "def check():\n"
        '    msg = "use console.print() not bare print()"\n'
        "    return msg\n",
        encoding="utf-8",
    )
    result = check_debug_print(str(f))
    assert result["score"] == 100, f"print() inside strings should not flag: {result}"


# ===========================================================================
# 6. deep_nesting_check
# ===========================================================================


def test_deep_nesting_check_clean_passes(tmp_path):
    """A file with shallow nesting (depth <= 4) should pass."""
    clean_file = tmp_path / "shallow.py"
    clean_file.write_text(
        '"""Shallow module."""\n\n'
        "def process(items):\n"
        '    """Process items."""\n'
        "    for item in items:\n"
        "        if item > 0:\n"
        "            return item\n"
        "    return None\n",
        encoding="utf-8",
    )
    result = check_deep_nesting(str(clean_file))
    assert result["score"] == 100, f"Shallow nesting should score 100: {result}"


def test_deep_nesting_check_violation_caught(tmp_path):
    """A file with deeply nested functions (depth > 4) should fail."""
    bad_file = tmp_path / "deep.py"
    bad_file.write_text(
        '"""Deep nesting module."""\n\n'
        "def deeply_nested(data):\n"
        '    """Too deep."""\n'
        "    if data:\n"
        "        for item in data:\n"
        "            if item:\n"
        "                for sub in item:\n"
        "                    if sub:\n"
        "                        return sub\n"
        "    return None\n",
        encoding="utf-8",
    )
    result = check_deep_nesting(str(bad_file))
    assert result["score"] < 100, f"Deep nesting should lose points: {result}"


def test_deep_nesting_check_bypass_respected(tmp_path):
    """Bypass rules should grant score 100."""
    f = tmp_path / "bypassed.py"
    # Write deeply nested code that would normally fail
    f.write_text(
        '"""Bypassed."""\n'
        "def deep(x):\n"
        "    if x:\n"
        "        for i in x:\n"
        "            if i:\n"
        "                for j in i:\n"
        "                    if j:\n"
        "                        return j\n",
        encoding="utf-8",
    )
    bypass_rules = [{"standard": "deep_nesting", "file": "bypassed.py"}]
    result = check_deep_nesting(str(f), bypass_rules=bypass_rules)
    assert result["score"] == 100, f"Bypass should yield 100: {result}"


# ===========================================================================
# 7. documentation_check
# ===========================================================================


def test_documentation_check_clean_passes(tmp_path):
    """A file with module docstring and function docstrings should pass."""
    clean_file = tmp_path / "documented.py"
    clean_file.write_text(
        '"""Well documented module."""\n\n'
        "def public_func():\n"
        '    """This function does things."""\n'
        "    return True\n\n"
        "def another_public():\n"
        '    """Another documented function."""\n'
        "    return False\n",
        encoding="utf-8",
    )
    result = check_documentation(str(clean_file))
    assert result["score"] == 100, f"Documented code should score 100: {result}"


def test_documentation_check_violation_caught(tmp_path):
    """A file missing docstrings should fail."""
    bad_file = tmp_path / "undocumented.py"
    bad_file.write_text(
        "import os\n\ndef public_func():\n    return True\n\ndef another_public():\n    return False\n",
        encoding="utf-8",
    )
    result = check_documentation(str(bad_file))
    assert result["score"] < 100, f"Missing docstrings should lose points: {result}"


def test_documentation_check_bypass_respected(tmp_path):
    """Bypass rules should grant score 100."""
    f = tmp_path / "bypassed.py"
    f.write_text("x = 1\n", encoding="utf-8")
    bypass_rules = [{"standard": "documentation", "file": "bypassed.py"}]
    result = check_documentation(str(f), bypass_rules=bypass_rules)
    assert result["score"] == 100, f"Bypass should yield 100: {result}"


# ===========================================================================
# 8. encapsulation_check
# ===========================================================================


def test_encapsulation_check_clean_passes(tmp_path):
    """A file with no cross-branch handler imports should pass."""
    clean_file = tmp_path / "clean.py"
    clean_file.write_text(
        '"""Clean module."""\n\nfrom pathlib import Path\n\ndef do_work():\n    """Do work."""\n    return True\n',
        encoding="utf-8",
    )
    result = check_encapsulation(str(clean_file))
    assert result["score"] >= 75, f"Clean encapsulation should pass: {result}"


def test_encapsulation_check_violation_caught(tmp_path):
    """A file importing another branch's handlers should fail."""
    bad_file = tmp_path / "leaky.py"
    bad_file.write_text(
        '"""Leaky module."""\n\n'
        "from flow.apps.handlers.plan.validator import validate\n"
        "from api.apps.handlers.openrouter.client import get_response\n\n"
        "def do_work():\n"
        '    """Do work."""\n'
        "    return validate()\n",
        encoding="utf-8",
    )
    result = check_encapsulation(str(bad_file))
    # The cross-branch check should flag at least one violation
    failed_checks = [c for c in result["checks"] if not c["passed"]]
    assert len(failed_checks) > 0, f"Cross-branch handler imports should be flagged: {result}"


def test_encapsulation_check_bypass_respected(tmp_path):
    """Bypass rules should grant score 100."""
    f = tmp_path / "bypassed.py"
    f.write_text(
        '"""Bypassed."""\nfrom flow.apps.handlers.plan.validator import validate\n',
        encoding="utf-8",
    )
    bypass_rules = [{"standard": "encapsulation", "file": "bypassed.py"}]
    result = check_encapsulation(str(f), bypass_rules=bypass_rules)
    assert result["score"] == 100, f"Bypass should yield 100: {result}"
