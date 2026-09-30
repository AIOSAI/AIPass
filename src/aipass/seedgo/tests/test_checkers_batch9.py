# =================== META ====================
# Name: test_checkers_batch9.py
# Description: Unit tests for readme_check and trigger_check
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/readme_check.py and apps/handlers/aipass_standards/trigger_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that readme_check.py and trigger_check.py parse and import
# seedgo: no-test-needed(documentation) — that the public check functions carry docstrings
# seedgo: no-test-needed(stdlib) — datetime.strptime's refusal of a date that does not exist

from typing import List

from aipass.seedgo.apps.handlers.aipass_standards.readme_check import (
    check_command_list,
    check_directory_tree,
    check_last_updated_freshness,
    check_module_list,
    check_readme_exists,
    check_required_sections,
)
from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
    check_handler_naming,
    check_missing_trigger_events,
    check_no_logger_imports,
    check_no_print_statements,
    check_trigger_import_pattern,
    is_handler_layer,
    is_trigger_handler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lines(text: str) -> List[str]:
    """Split text into lines, widening LiteralString to str for pyright."""
    return text.split("\n")


# ===========================================================================
# 1. readme_check -- check_readme_exists
# ===========================================================================


def test_readme_exists_present(tmp_path):
    """README.md exists passes."""
    readme = tmp_path / "README.md"
    readme.write_text("# Branch\n", encoding="utf-8")

    result = check_readme_exists(readme)
    assert result["passed"] is True


def test_readme_exists_missing(tmp_path):
    """README.md missing fails."""
    readme = tmp_path / "README.md"

    result = check_readme_exists(readme)
    assert result["passed"] is False


# ===========================================================================
# 2. readme_check -- check_required_sections
# ===========================================================================


def test_required_sections_all_present(tmp_path):
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

    result = check_required_sections(lines, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
    assert result["passed"] is True


def test_required_sections_missing_commands(tmp_path):
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

    result = check_required_sections(lines, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
    assert result["passed"] is False
    assert "Commands/Usage" in result["message"]


def test_required_sections_alternate_names(tmp_path):
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

    result = check_required_sections(lines, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
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

    result = check_last_updated_freshness(lines, branch_root, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
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

    result = check_last_updated_freshness(lines, branch_root, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
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

    result = check_last_updated_freshness(lines, branch_root, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
    assert result["passed"] is False
    assert "Malformed" in result["message"]


def test_last_updated_freshness_missing(tmp_path):
    """README without Last Updated date fails."""
    lines: List[str] = [
        "# Branch",
        "No date here.",
        "",
    ]

    result = check_last_updated_freshness(
        lines, tmp_path / "missing", (tmp_path / "fake" / "apps" / "entry.py").as_posix()
    )
    assert result["passed"] is False
    assert "Last Updated" in result["message"]


def test_last_updated_freshness_bypassed(tmp_path):
    """Bypassed freshness check passes immediately."""
    lines: List[str] = ["# Branch", "No date.", ""]
    branch_root = tmp_path / "mybranch"
    branch_root.mkdir()

    bypass = [{"file": (tmp_path / "fake" / "apps" / "entry.py").as_posix(), "standard": "readme"}]
    result = check_last_updated_freshness(
        lines, branch_root, (tmp_path / "fake" / "apps" / "entry.py").as_posix(), bypass
    )
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

    result = check_directory_tree(lines, branch_root, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
    assert result["passed"] is True


def test_directory_tree_no_tree_section(tmp_path):
    """README without a tree block passes (optional)."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Other Section",
        "Some content.",
    ]

    result = check_directory_tree(lines, tmp_path / "missing", (tmp_path / "fake" / "apps" / "entry.py").as_posix())
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

    result = check_module_list(lines, branch_root, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
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

    result = check_module_list(lines, branch_root, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
    assert result["passed"] is False
    assert "secret_module" in result["message"]


def test_module_list_no_modules_dir(tmp_path):
    """No apps/modules/ directory passes (skipped)."""
    branch_root = tmp_path / "mybranch"
    branch_root.mkdir()

    lines: List[str] = ["# Branch"]

    result = check_module_list(lines, branch_root, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
    assert result["passed"] is True


# ===========================================================================
# 6. readme_check -- check_command_list
# ===========================================================================


def test_command_list_present(tmp_path):
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

    result = check_command_list(lines, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
    assert result["passed"] is True
    assert "2 content lines" in result["message"]


def test_command_list_empty(tmp_path):
    """Commands section with no content fails."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Commands",
        "",
        "## Other Section",
    ]

    result = check_command_list(lines, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
    assert result["passed"] is False
    assert "empty" in result["message"].lower()


def test_command_list_missing(tmp_path):
    """No Commands section at all fails."""
    lines: List[str] = [
        "# Branch",
        "",
        "## Architecture",
        "Content here.",
    ]

    result = check_command_list(lines, (tmp_path / "fake" / "apps" / "entry.py").as_posix())
    assert result["passed"] is False
    assert "No Commands" in result["message"]


# ===========================================================================
# 7. trigger_check -- is_handler_layer
# ===========================================================================


def test_is_handler_layer_true(tmp_path):
    """File in handlers/ directory is handler layer."""
    assert (
        is_handler_layer((tmp_path / "src" / "aipass" / "seedgo" / "apps" / "handlers" / "audit" / "ops.py").as_posix())
        is True
    )


def test_is_handler_layer_false(tmp_path):
    """File in modules/ directory is not handler layer."""
    assert (
        is_handler_layer((tmp_path / "src" / "aipass" / "seedgo" / "apps" / "modules" / "audit.py").as_posix()) is False
    )


# ===========================================================================
# 8. trigger_check -- is_trigger_handler
# ===========================================================================


def test_is_trigger_handler_true(tmp_path):
    """File in trigger handlers/events/ is a trigger handler."""
    assert is_trigger_handler((tmp_path / "apps" / "handlers" / "events" / "trigger_on_audit.py").as_posix()) is True


def test_is_trigger_handler_false(tmp_path):
    """File not in trigger handlers/events/ is not a trigger handler."""
    assert is_trigger_handler((tmp_path / "apps" / "modules" / "audit.py").as_posix()) is False


# ===========================================================================
# 9. trigger_check -- check_no_logger_imports
# ===========================================================================


def test_no_logger_imports_clean(tmp_path):
    """Handler without prax logger imports passes."""
    content = "def handle_event(**kwargs):\n    pass\n"
    lines = _lines(content)

    result = check_no_logger_imports(content, lines, (tmp_path / "fake" / "handler.py").as_posix())
    assert result["passed"] is True


def test_no_logger_imports_violation(tmp_path):
    """Handler importing prax logger fails."""
    content = "from prax import logger\n\ndef handle_event(**kwargs):\n    pass\n"
    lines = _lines(content)

    result = check_no_logger_imports(content, lines, (tmp_path / "fake" / "handler.py").as_posix())
    assert result["passed"] is False
    assert "recursion" in result["message"]


# ===========================================================================
# 10. trigger_check -- check_no_print_statements
# ===========================================================================


def test_no_print_statements_clean(tmp_path):
    """Handler without print statements passes."""
    content = "def handle_event(**kwargs):\n    return True\n"
    lines = _lines(content)

    result = check_no_print_statements(content, lines, (tmp_path / "fake" / "handler.py").as_posix())
    assert result["passed"] is True


def test_no_print_statements_violation(tmp_path):
    """Handler with print() fails."""
    content = 'def handle_event(**kwargs):\n    print("debug")\n'
    lines = _lines(content)

    result = check_no_print_statements(content, lines, (tmp_path / "fake" / "handler.py").as_posix())
    assert result["passed"] is False
    assert "print()" in result["message"]


def test_no_print_in_main_block_ok(tmp_path):
    """print() inside __main__ block is allowed."""
    content = 'def handle_event(**kwargs):\n    return True\n\nif __name__ == "__main__":\n    print("testing")\n'
    lines = _lines(content)

    result = check_no_print_statements(content, lines, (tmp_path / "fake" / "handler.py").as_posix())
    assert result["passed"] is True


# ===========================================================================
# 11. trigger_check -- check_trigger_import_pattern
# ===========================================================================


def test_trigger_import_pattern_correct(tmp_path):
    """Correct trigger import pattern passes."""
    content = 'from trigger import trigger\n\ndef do_work():\n    trigger.fire("event")\n'
    lines = _lines(content)

    result = check_trigger_import_pattern(content, lines, (tmp_path / "fake" / "module.py").as_posix())
    assert result is not None
    assert result["passed"] is True


def test_trigger_import_pattern_missing(tmp_path):
    """trigger.fire() without import fails."""
    content = 'def do_work():\n    trigger.fire("event")\n'
    lines = _lines(content)

    result = check_trigger_import_pattern(content, lines, (tmp_path / "fake" / "module.py").as_posix())
    assert result is not None
    assert result["passed"] is False
    assert "missing proper import" in result["message"]


def test_trigger_import_pattern_no_trigger(tmp_path):
    """File not using trigger returns None."""
    content = "def do_work():\n    return True\n"
    lines = _lines(content)

    result = check_trigger_import_pattern(content, lines, (tmp_path / "fake" / "module.py").as_posix())
    assert result is None


def test_trigger_import_pattern_trigger_branch(tmp_path):
    """Trigger branch file is exempt (self-reference)."""
    content = 'def fire(event):\n    trigger.fire("event")\n'
    lines = _lines(content)

    result = check_trigger_import_pattern(
        content, lines, (tmp_path / "src" / "aipass" / "trigger" / "apps" / "modules" / "core.py").as_posix()
    )
    assert result is not None
    assert result["passed"] is True


# ===========================================================================
# 12. trigger_check -- check_handler_naming
# ===========================================================================


def test_handler_naming_correct(tmp_path):
    """Handler function with handle_ prefix passes."""
    content = "def handle_audit_complete(**kwargs):\n    pass\n"
    lines = _lines(content)

    result = check_handler_naming(content, lines, (tmp_path / "fake" / "handler.py").as_posix())
    assert result is not None
    assert result["passed"] is True


def test_handler_naming_bad(tmp_path):
    """Handler function without handle_ prefix fails."""
    content = "def onHandleEvent(**kwargs):\n    pass\n"
    lines = _lines(content)

    result = check_handler_naming(content, lines, (tmp_path / "fake" / "handler.py").as_posix())
    assert result is not None
    assert result["passed"] is False


def test_handler_naming_no_handlers(tmp_path):
    """File with no handler functions returns None."""
    content = "def do_work():\n    pass\n"
    lines = _lines(content)

    result = check_handler_naming(content, lines, (tmp_path / "fake" / "handler.py").as_posix())
    assert result is None


# ===========================================================================
# 13. trigger_check -- check_missing_trigger_events
# ===========================================================================


def test_missing_trigger_events_lifecycle(tmp_path):
    """Lifecycle function without trigger.fire() is flagged."""
    content = "def create_branch():\n    pass\n"
    lines = _lines(content)

    result = check_missing_trigger_events(content, lines, (tmp_path / "fake" / "module.py").as_posix())
    assert result is not None
    assert result["passed"] is False
    assert "create_" in result["message"]


def test_missing_trigger_events_with_fire(tmp_path):
    """Lifecycle function with trigger.fire() passes (returns None)."""
    content = 'def create_branch():\n    trigger.fire("branch_created")\n'
    lines = _lines(content)

    result = check_missing_trigger_events(content, lines, (tmp_path / "fake" / "module.py").as_posix())
    assert result is None


def test_missing_trigger_events_no_patterns(tmp_path):
    """File with no event-like patterns returns None."""
    content = "def do_work():\n    return True\n"
    lines = _lines(content)

    result = check_missing_trigger_events(content, lines, (tmp_path / "fake" / "module.py").as_posix())
    assert result is None


# ===========================================================================
# 14. trigger_check -- find_pattern_lines (via check_missing_trigger_events)
# ===========================================================================


def test_find_pattern_lines_detects_unlink(tmp_path):
    """Inline .unlink() without trigger.fire() is flagged."""
    content = "def cleanup():\n    path.unlink()\n"
    lines = _lines(content)

    result = check_missing_trigger_events(content, lines, (tmp_path / "fake" / "module.py").as_posix())
    assert result is not None
    assert result["passed"] is False
    assert ".unlink()" in result["message"]


def test_find_pattern_lines_detects_rename(tmp_path):
    """Inline .rename() without trigger.fire() is flagged."""
    content = "def move_file():\n    path.rename(new_path)\n"
    lines = _lines(content)

    result = check_missing_trigger_events(content, lines, (tmp_path / "fake" / "module.py").as_posix())
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


def test_per_function_prax_logger_shape_accepts(tmp_path):
    """Lifecycle doors that fire in their OWN bodies pass (live prax precedent)."""
    content = _PRAX_LOGGER_SHAPE
    lines = _lines(content)

    assert (
        check_missing_trigger_events(
            content, lines, (tmp_path / "fake" / "prax" / "apps" / "modules" / "logger.py").as_posix()
        )
        is None
    )


def test_per_function_prax_logger_shape_rejects_when_fires_move_out(tmp_path):
    """An unrelated fire elsewhere in the file no longer covers the lifecycle doors."""
    content = _PRAX_LOGGER_SHAPE_BROKEN
    lines = _lines(content)
    assert "trigger.fire(" in content  # the file still fires — file-level flag would pass it

    result = check_missing_trigger_events(
        content, lines, (tmp_path / "fake" / "prax" / "apps" / "modules" / "logger.py").as_posix()
    )
    assert result is not None
    assert result["passed"] is False
    assert "initialize_*_system" in result["message"]
    assert "shutdown_*_system" in result["message"]


def test_fire_in_one_function_does_not_exempt_another(tmp_path):
    """A fire in function A is not an exemption for function B in the same file. Mutant: a violation reported as passing in apps/handlers/aipass_standards/trigger_check.py — killed."""
    content = 'def create_thing():\n    trigger.fire("thing_created")\n\n\ndef delete_thing():\n    pass\n'
    lines = _lines(content)

    result = check_missing_trigger_events(content, lines, (tmp_path / "fake" / "module.py").as_posix())
    assert result is not None
    assert result["passed"] is False
    assert "delete_*" in result["message"]
    assert "create_*" not in result["message"]


def test_one_hop_delegation_acquits(tmp_path):
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

    assert check_missing_trigger_events(content, lines, (tmp_path / "fake" / "module.py").as_posix()) is None


def test_pattern10_unlink_scoped_to_enclosing_function(tmp_path):
    """An .unlink() is answered by the function it sits in, not by the whole file. Mutant: a violation reported as passing in apps/handlers/aipass_standards/trigger_check.py — killed."""
    content = 'def purge_cache(path):\n    trigger.fire("cache_purged")\n\n\ndef wipe_state(path):\n    path.unlink()\n'
    lines = _lines(content)

    result = check_missing_trigger_events(content, lines, (tmp_path / "fake" / "module.py").as_posix())
    assert result is not None
    assert result["passed"] is False
    assert ".unlink() file deletion on lines [6]" in result["message"]


def test_pattern10_module_level_keeps_file_level_behaviour(tmp_path):
    """A call outside any function has no function body to ask, so the file answers. Mutant: a violation reported as passing in apps/handlers/aipass_standards/trigger_check.py — killed."""
    exempt = 'trigger.fire("started")\nPath("a").unlink()\n'
    assert check_missing_trigger_events(exempt, _lines(exempt), (tmp_path / "fake" / "module.py").as_posix()) is None

    bare = 'Path("a").unlink()\n'
    result = check_missing_trigger_events(bare, _lines(bare), (tmp_path / "fake" / "module.py").as_posix())
    assert result is not None
    assert result["passed"] is False
    assert ".unlink()" in result["message"]


def test_unparseable_file_falls_back_to_file_level(tmp_path):
    """A file that does not parse keeps the old behaviour instead of dropping the check. Mutant: a violation reported as passing in apps/handlers/aipass_standards/trigger_check.py — killed."""
    broken_exempt = 'def create_thing(:\n    trigger.fire("thing_created")\n'
    assert (
        check_missing_trigger_events(broken_exempt, _lines(broken_exempt), (tmp_path / "fake" / "module.py").as_posix())
        is None
    )

    broken_bare = "def create_thing(:\n    pass\n"
    result = check_missing_trigger_events(
        broken_bare, _lines(broken_bare), (tmp_path / "fake" / "module.py").as_posix()
    )
    assert result is not None
    assert result["passed"] is False
    assert "create_*" in result["message"]
