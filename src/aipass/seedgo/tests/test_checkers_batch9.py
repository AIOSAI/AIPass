"""Tests for seedgo checker handlers — batch 9 (readme_check, trigger_check)."""

# =================== META ====================
# Name: test_checkers_batch9.py
# Description: Unit tests for readme_check and trigger_check
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

import pytest
from typing import List
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lines(text: str) -> List[str]:
    """Split text into lines, widening LiteralString to str for pyright."""
    return text.split("\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for standards checkers."""
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

    # -- bypass handler -----------------------------------------------------
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed as real_is_bypassed

    bypass_pkg = MagicMock()
    bypass_utils = MagicMock()
    bypass_utils.is_bypassed = real_is_bypassed
    bypass_pkg.utils = bypass_utils
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    bypass_pkg.ignore_handler = bypass_ignore
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.utils", bypass_utils)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        bypass_ignore,
    )

    # Force re-imports so checkers pick up fresh mocks
    for mod_name in [
        "aipass.seedgo.apps.handlers.aipass_standards.readme_check",
        "aipass.seedgo.apps.handlers.aipass_standards.trigger_check",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ===========================================================================
# 1. readme_check -- check_readme_exists
# ===========================================================================


def test_readme_exists_present(tmp_path):
    """README.md exists passes."""
    readme = tmp_path / "README.md"
    readme.write_text("# Branch\n", encoding="utf-8")

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_readme_exists,
    )

    result = check_readme_exists(readme)
    assert result["passed"] is True


def test_readme_exists_missing(tmp_path):
    """README.md missing fails."""
    readme = tmp_path / "README.md"

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_readme_exists,
    )

    result = check_readme_exists(readme)
    assert result["passed"] is False


# ===========================================================================
# 2. readme_check -- check_required_sections
# ===========================================================================


def test_required_sections_all_present():
    """README with all required section groups passes."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Architecture",
        "Some content here.",
        "",
        "## Commands",
        "- cmd1",
        "",
        "## Integration Points",
        "Details here.",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_required_sections,
    )

    result = check_required_sections(lines, "/fake/apps/entry.py")
    assert result["passed"] is True


def test_required_sections_missing_commands():
    """README missing Commands/Usage section fails."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Architecture",
        "Some content.",
        "",
        "## Depends On",
        "Details.",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_required_sections,
    )

    result = check_required_sections(lines, "/fake/apps/entry.py")
    assert result["passed"] is False
    assert "Commands/Usage" in result["message"]


def test_required_sections_alternate_names():
    """README with alternate section names (Usage, Directory Structure, Provides To) passes."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Directory Structure",
        "Tree here.",
        "",
        "## Usage",
        "- usage1",
        "",
        "## Provides To",
        "Other branches.",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_required_sections,
    )

    result = check_required_sections(lines, "/fake/apps/entry.py")
    assert result["passed"] is True


# ===========================================================================
# 3. readme_check -- check_last_updated_freshness
# ===========================================================================


def test_last_updated_freshness_date_present(tmp_path):
    """Well-formed Last Updated date passes."""
    lines: List[str] = [
        "# Branch",
        "*Last Updated: 2026-06-01*",
        "",
    ]
    branch_root = tmp_path / "mybranch"
    branch_root.mkdir()
    (branch_root / "apps").mkdir()

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_last_updated_freshness,
    )

    result = check_last_updated_freshness(lines, branch_root, "/fake/apps/entry.py")
    assert result["passed"] is True
    assert "present" in result["message"]


def test_last_updated_freshness_bold_format(tmp_path):
    """Bold markdown format for Last Updated date passes."""
    lines: List[str] = [
        "# Branch",
        "**Last Updated:** 2026-05-18",
        "",
    ]
    branch_root = tmp_path / "mybranch"
    branch_root.mkdir()
    (branch_root / "apps").mkdir()

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_last_updated_freshness,
    )

    result = check_last_updated_freshness(lines, branch_root, "/fake/apps/entry.py")
    assert result["passed"] is True
    assert "2026-05-18" in result["message"]


def test_last_updated_freshness_malformed_date(tmp_path):
    """Malformed date (regex matches but strptime fails) fails."""
    lines: List[str] = [
        "# Branch",
        "*Last Updated: 2026-13-45*",
        "",
    ]
    branch_root = tmp_path / "mybranch"
    branch_root.mkdir()
    (branch_root / "apps").mkdir()

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_last_updated_freshness,
    )

    result = check_last_updated_freshness(lines, branch_root, "/fake/apps/entry.py")
    assert result["passed"] is False
    assert "Malformed" in result["message"]


def test_last_updated_freshness_missing():
    """README without Last Updated date fails."""
    lines: List[str] = [
        "# Branch",
        "No date here.",
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_last_updated_freshness,
    )

    from pathlib import Path

    result = check_last_updated_freshness(lines, Path("/nonexistent"), "/fake/apps/entry.py")
    assert result["passed"] is False
    assert "Last Updated" in result["message"]


def test_last_updated_freshness_bypassed(tmp_path):
    """Bypassed freshness check passes immediately."""
    lines: List[str] = ["# Branch", "No date.", ""]
    branch_root = tmp_path / "mybranch"
    branch_root.mkdir()

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_last_updated_freshness,
    )

    bypass = [{"file": "/fake/apps/entry.py", "standard": "readme"}]
    result = check_last_updated_freshness(lines, branch_root, "/fake/apps/entry.py", bypass)
    assert result["passed"] is True


# ===========================================================================
# 4. readme_check -- check_directory_tree
# ===========================================================================


def test_directory_tree_accurate(tmp_path):
    """Directory tree listing valid directories passes."""
    branch_root = tmp_path / "mybranch"
    apps_dir = branch_root / "apps"
    modules_dir = apps_dir / "modules"
    modules_dir.mkdir(parents=True)

    lines: List[str] = [
        "# Branch",
        "",
        "## Architecture",
        "",
        "```",
        "mybranch/",
        "  apps/",
        "    modules/",
        "```",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_directory_tree,
    )

    result = check_directory_tree(lines, branch_root, "/fake/apps/entry.py")
    assert result["passed"] is True


def test_directory_tree_no_tree_section():
    """README without a tree block passes (optional)."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Other Section",
        "Some content.",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_directory_tree,
    )

    from pathlib import Path

    result = check_directory_tree(lines, Path("/nonexistent"), "/fake/apps/entry.py")
    assert result["passed"] is True
    assert result["message"] == "No directory tree block found (optional check)"


# ===========================================================================
# 5. readme_check -- check_module_list
# ===========================================================================


def test_module_list_all_mentioned(tmp_path):
    """All modules in apps/modules/ mentioned in README passes."""
    branch_root = tmp_path / "mybranch"
    modules_dir = branch_root / "apps" / "modules"
    modules_dir.mkdir(parents=True)
    (modules_dir / "audit.py").write_text("pass", encoding="utf-8")
    (modules_dir / "report.py").write_text("pass", encoding="utf-8")
    (modules_dir / "__init__.py").write_text("", encoding="utf-8")

    lines: List[str] = [
        "# Branch",
        "This branch has audit and report modules.",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_module_list,
    )

    result = check_module_list(lines, branch_root, "/fake/apps/entry.py")
    assert result["passed"] is True


def test_module_list_missing_module(tmp_path):
    """Module not mentioned in README fails."""
    branch_root = tmp_path / "mybranch"
    modules_dir = branch_root / "apps" / "modules"
    modules_dir.mkdir(parents=True)
    (modules_dir / "secret_module.py").write_text("pass", encoding="utf-8")

    lines: List[str] = [
        "# Branch",
        "No modules mentioned here.",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_module_list,
    )

    result = check_module_list(lines, branch_root, "/fake/apps/entry.py")
    assert result["passed"] is False
    assert "secret_module" in result["message"]


def test_module_list_no_modules_dir(tmp_path):
    """No apps/modules/ directory passes (skipped)."""
    branch_root = tmp_path / "mybranch"
    branch_root.mkdir()

    lines: List[str] = ["# Branch"]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_module_list,
    )

    result = check_module_list(lines, branch_root, "/fake/apps/entry.py")
    assert result["passed"] is True


# ===========================================================================
# 6. readme_check -- check_command_list
# ===========================================================================


def test_command_list_present():
    """Commands section with content passes."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Commands",
        "- `audit` - Run audit",
        "- `report` - Generate report",
        "",
        "## Other",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_command_list,
    )

    result = check_command_list(lines, "/fake/apps/entry.py")
    assert result["passed"] is True
    assert "2 content lines" in result["message"]


def test_command_list_empty():
    """Commands section with no content fails."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Commands",
        "",
        "## Other Section",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_command_list,
    )

    result = check_command_list(lines, "/fake/apps/entry.py")
    assert result["passed"] is False
    assert "empty" in result["message"].lower()


def test_command_list_missing():
    """No Commands section at all fails."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Architecture",
        "Content here.",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
        check_command_list,
    )

    result = check_command_list(lines, "/fake/apps/entry.py")
    assert result["passed"] is False
    assert "No Commands" in result["message"]


# ===========================================================================
# 7. trigger_check -- is_handler_layer
# ===========================================================================


def test_is_handler_layer_true():
    """File in handlers/ directory is handler layer."""
    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        is_handler_layer,
    )

    assert is_handler_layer("/src/aipass/seedgo/apps/handlers/audit/ops.py") is True


def test_is_handler_layer_false():
    """File in modules/ directory is not handler layer."""
    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        is_handler_layer,
    )

    assert is_handler_layer("/src/aipass/seedgo/apps/modules/audit.py") is False


# ===========================================================================
# 8. trigger_check -- is_trigger_handler
# ===========================================================================


def test_is_trigger_handler_true():
    """File in trigger handlers/events/ is a trigger handler."""
    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        is_trigger_handler,
    )

    assert is_trigger_handler("/apps/handlers/events/trigger_on_audit.py") is True


def test_is_trigger_handler_false():
    """File not in trigger handlers/events/ is not a trigger handler."""
    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        is_trigger_handler,
    )

    assert is_trigger_handler("/apps/modules/audit.py") is False


# ===========================================================================
# 9. trigger_check -- check_no_logger_imports
# ===========================================================================


def test_no_logger_imports_clean():
    """Handler without prax logger imports passes."""
    content = "def handle_event(**kwargs):\n    pass\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_no_logger_imports,
    )

    result = check_no_logger_imports(content, lines, "/fake/handler.py")
    assert result["passed"] is True


def test_no_logger_imports_violation():
    """Handler importing prax logger fails."""
    content = "from prax import logger\n\ndef handle_event(**kwargs):\n    pass\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_no_logger_imports,
    )

    result = check_no_logger_imports(content, lines, "/fake/handler.py")
    assert result["passed"] is False
    assert "recursion" in result["message"]


# ===========================================================================
# 10. trigger_check -- check_no_print_statements
# ===========================================================================


def test_no_print_statements_clean():
    """Handler without print statements passes."""
    content = "def handle_event(**kwargs):\n    return True\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_no_print_statements,
    )

    result = check_no_print_statements(content, lines, "/fake/handler.py")
    assert result["passed"] is True


def test_no_print_statements_violation():
    """Handler with print() fails."""
    content = 'def handle_event(**kwargs):\n    print("debug")\n'
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_no_print_statements,
    )

    result = check_no_print_statements(content, lines, "/fake/handler.py")
    assert result["passed"] is False
    assert "print()" in result["message"]


def test_no_print_in_main_block_ok():
    """print() inside __main__ block is allowed."""
    content = 'def handle_event(**kwargs):\n    return True\n\nif __name__ == "__main__":\n    print("testing")\n'
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_no_print_statements,
    )

    result = check_no_print_statements(content, lines, "/fake/handler.py")
    assert result["passed"] is True


# ===========================================================================
# 11. trigger_check -- check_trigger_import_pattern
# ===========================================================================


def test_trigger_import_pattern_correct():
    """Correct trigger import pattern passes."""
    content = 'from trigger import trigger\n\ndef do_work():\n    trigger.fire("event")\n'
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_trigger_import_pattern,
    )

    result = check_trigger_import_pattern(content, lines, "/fake/module.py")
    assert result is not None
    assert result["passed"] is True


def test_trigger_import_pattern_missing():
    """trigger.fire() without import fails."""
    content = 'def do_work():\n    trigger.fire("event")\n'
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_trigger_import_pattern,
    )

    result = check_trigger_import_pattern(content, lines, "/fake/module.py")
    assert result is not None
    assert result["passed"] is False
    assert "missing proper import" in result["message"]


def test_trigger_import_pattern_no_trigger():
    """File not using trigger returns None."""
    content = "def do_work():\n    return True\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_trigger_import_pattern,
    )

    result = check_trigger_import_pattern(content, lines, "/fake/module.py")
    assert result is None


def test_trigger_import_pattern_trigger_branch():
    """Trigger branch file is exempt (self-reference)."""
    content = 'def fire(event):\n    trigger.fire("event")\n'
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_trigger_import_pattern,
    )

    result = check_trigger_import_pattern(content, lines, "/src/aipass/trigger/apps/modules/core.py")
    assert result is not None
    assert result["passed"] is True


# ===========================================================================
# 12. trigger_check -- check_handler_naming
# ===========================================================================


def test_handler_naming_correct():
    """Handler function with handle_ prefix passes."""
    content = "def handle_audit_complete(**kwargs):\n    pass\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_handler_naming,
    )

    result = check_handler_naming(content, lines, "/fake/handler.py")
    assert result is not None
    assert result["passed"] is True


def test_handler_naming_bad():
    """Handler function without handle_ prefix fails."""
    content = "def onHandleEvent(**kwargs):\n    pass\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_handler_naming,
    )

    result = check_handler_naming(content, lines, "/fake/handler.py")
    assert result is not None
    assert result["passed"] is False


def test_handler_naming_no_handlers():
    """File with no handler functions returns None."""
    content = "def do_work():\n    pass\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_handler_naming,
    )

    result = check_handler_naming(content, lines, "/fake/handler.py")
    assert result is None


# ===========================================================================
# 13. trigger_check -- check_missing_trigger_events
# ===========================================================================


def test_missing_trigger_events_lifecycle():
    """Lifecycle function without trigger.fire() is flagged."""
    content = "def create_branch():\n    pass\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    result = check_missing_trigger_events(content, lines, "/fake/module.py")
    assert result is not None
    assert result["passed"] is False
    assert "create_" in result["message"]


def test_missing_trigger_events_with_fire():
    """Lifecycle function with trigger.fire() passes (returns None)."""
    content = 'def create_branch():\n    trigger.fire("branch_created")\n'
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    result = check_missing_trigger_events(content, lines, "/fake/module.py")
    assert result is None


def test_missing_trigger_events_no_patterns():
    """File with no event-like patterns returns None."""
    content = "def do_work():\n    return True\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    result = check_missing_trigger_events(content, lines, "/fake/module.py")
    assert result is None


# ===========================================================================
# 14. trigger_check -- find_pattern_lines (via check_missing_trigger_events)
# ===========================================================================


def test_find_pattern_lines_detects_unlink():
    """Inline .unlink() without trigger.fire() is flagged."""
    content = "def cleanup():\n    path.unlink()\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    result = check_missing_trigger_events(content, lines, "/fake/module.py")
    assert result is not None
    assert result["passed"] is False
    assert ".unlink()" in result["message"]


def test_find_pattern_lines_detects_rename():
    """Inline .rename() without trigger.fire() is flagged."""
    content = "def move_file():\n    path.rename(new_path)\n"
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    result = check_missing_trigger_events(content, lines, "/fake/module.py")
    assert result is not None
    assert result["passed"] is False
    assert ".rename()" in result["message"]


# ===========================================================================
# 15. trigger_check -- the exemption is PER FUNCTION BODY (DPLAN-0339)
# ===========================================================================
#
# The flag used to be file-level: one `trigger.fire(` anywhere exempted every
# pattern in the file. Prax's initialize_logging_system/shutdown_logging_system
# fired nothing for months and still passed, because an unrelated hot-path
# `trigger.fire("startup")` lived in the same module. These pins hold the two
# halves of that proof plus the scoping rules around it.

# The live precedent, reduced: src/aipass/prax/apps/modules/logger.py. Same
# function names, same event names, same unrelated hot-path fire in
# _ensure_watcher that used to carry the whole file.
_PRAX_LOGGER_SHAPE = '''
class SystemLogger:
    def _ensure_watcher(self):
        SystemLogger._watcher_started = True


def initialize_logging_system():
    """Initialize the complete logging system"""
    from aipass.trigger.apps.modules.core import trigger

    result = run_initialize(MODULE_NAME)
    trigger.fire("logging_system_initialized", modules_count=result["modules_count"])


def shutdown_logging_system():
    """Shutdown logging system cleanly"""
    from aipass.trigger.apps.modules.core import trigger

    run_shutdown(MODULE_NAME)
    trigger.fire("logging_system_shutdown")
'''

# The same file with both fires moved OUT of the lifecycle doors and one
# unrelated fire left behind — exactly the shape that passed for months.
_PRAX_LOGGER_SHAPE_BROKEN = '''
class SystemLogger:
    def _ensure_watcher(self):
        from aipass.trigger.apps.modules.core import trigger

        SystemLogger._watcher_started = True
        trigger.fire("startup")


def initialize_logging_system():
    """Initialize the complete logging system"""
    result = run_initialize(MODULE_NAME)


def shutdown_logging_system():
    """Shutdown logging system cleanly"""
    run_shutdown(MODULE_NAME)
'''


def test_per_function_prax_logger_shape_accepts():
    """Lifecycle doors that fire in their OWN bodies pass (live prax precedent)."""
    content = _PRAX_LOGGER_SHAPE
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    assert check_missing_trigger_events(content, lines, "/fake/prax/apps/modules/logger.py") is None


def test_per_function_prax_logger_shape_rejects_when_fires_move_out():
    """An unrelated fire elsewhere in the file no longer covers the lifecycle doors."""
    content = _PRAX_LOGGER_SHAPE_BROKEN
    lines = _lines(content)
    assert "trigger.fire(" in content  # the file still fires — file-level flag would pass it

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    result = check_missing_trigger_events(content, lines, "/fake/prax/apps/modules/logger.py")
    assert result is not None
    assert result["passed"] is False
    assert "initialize_*_system" in result["message"]
    assert "shutdown_*_system" in result["message"]


def test_fire_in_one_function_does_not_exempt_another():
    """A fire in function A is not an exemption for function B in the same file."""
    content = 'def create_thing():\n    trigger.fire("thing_created")\n\n\ndef delete_thing():\n    pass\n'
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    result = check_missing_trigger_events(content, lines, "/fake/module.py")
    assert result is not None
    assert "delete_*" in result["message"]
    assert "create_*" not in result["message"]


def test_one_hop_delegation_acquits():
    """Delegating the fire to a local helper is still firing (aipass install.py shape)."""
    content = (
        "def _fire_lock_removed(path, reason):\n"
        '    trigger.fire("file_deleted", path=str(path), reason=reason)\n'
        "\n\n"
        "def _release_install_lock(lock):\n"
        "    lock.unlink()\n"
        '    _fire_lock_removed(lock, "install_lock_released")\n'
    )
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    assert check_missing_trigger_events(content, lines, "/fake/module.py") is None


def test_pattern10_unlink_scoped_to_enclosing_function():
    """An .unlink() is answered by the function it sits in, not by the whole file."""
    content = 'def purge_cache(path):\n    trigger.fire("cache_purged")\n\n\ndef wipe_state(path):\n    path.unlink()\n'
    lines = _lines(content)

    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    result = check_missing_trigger_events(content, lines, "/fake/module.py")
    assert result is not None
    assert ".unlink() file deletion on lines [6]" in result["message"]


def test_pattern10_module_level_keeps_file_level_behaviour():
    """A call outside any function has no function body to ask, so the file answers."""
    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    exempt = 'trigger.fire("started")\nPath("a").unlink()\n'
    assert check_missing_trigger_events(exempt, _lines(exempt), "/fake/module.py") is None

    bare = 'Path("a").unlink()\n'
    result = check_missing_trigger_events(bare, _lines(bare), "/fake/module.py")
    assert result is not None
    assert ".unlink()" in result["message"]


def test_unparseable_file_falls_back_to_file_level():
    """A file that does not parse keeps the old behaviour instead of dropping the check."""
    from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
        check_missing_trigger_events,
    )

    broken_exempt = 'def create_thing(:\n    trigger.fire("thing_created")\n'
    assert check_missing_trigger_events(broken_exempt, _lines(broken_exempt), "/fake/module.py") is None

    broken_bare = "def create_thing(:\n    pass\n"
    result = check_missing_trigger_events(broken_bare, _lines(broken_bare), "/fake/module.py")
    assert result is not None
    assert "create_*" in result["message"]
