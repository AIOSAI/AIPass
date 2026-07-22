"""Tests for seedgo checker handlers — batch 8 (7 checkers)."""

# =================== META ====================
# Name: test_checkers_batch8.py
# Description: Unit tests for handlers, log_handler, log_level, log_structure, meta, naming, permission_flags
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
    bypass_pkg = MagicMock()
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    bypass_pkg.ignore_handler = bypass_ignore
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        bypass_ignore,
    )

    # Force re-imports so checkers pick up fresh mocks
    for mod_name in [
        "aipass.seedgo.apps.handlers.aipass_standards.handlers_check",
        "aipass.seedgo.apps.handlers.aipass_standards.log_handler_check",
        "aipass.seedgo.apps.handlers.aipass_standards.log_level_check",
        "aipass.seedgo.apps.handlers.aipass_standards.log_structure_check",
        "aipass.seedgo.apps.handlers.aipass_standards.meta_check",
        "aipass.seedgo.apps.handlers.aipass_standards.naming_check",
        "aipass.seedgo.apps.handlers.aipass_standards.permission_flags_check",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ===========================================================================
# 1. handlers_check -- check_handler_independence
# ===========================================================================


def test_handler_independence_clean(tmp_path):
    """Handler with no cross-handler imports passes."""
    content = (
        '"""Clean handler."""\n'
        "from aipass.seedgo.apps.handlers.json import json_handler\n"
        "\ndef do_work():\n    return True\n"
    )
    handler_path = str(tmp_path / "apps" / "handlers" / "audit" / "clean.py")

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_handler_independence,
    )

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True


def test_handler_independence_cross_import(tmp_path):
    """Handler importing from another handler package fails."""
    content = (
        '"""Cross handler import."""\n'
        "from aipass.seedgo.apps.handlers.error import error_handler\n"
        "\ndef do_work():\n    return True\n"
    )
    handler_path = str(tmp_path / "apps" / "handlers" / "audit" / "cross.py")

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_handler_independence,
    )

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is False
    assert "Cross-handler imports" in result["message"]


def test_handler_independence_same_package(tmp_path):
    """Handler importing from same package passes."""
    content = (
        '"""Same package import."""\n'
        "from aipass.seedgo.apps.handlers.audit import audit_helper\n"
        "\ndef do_work():\n    return True\n"
    )
    handler_path = str(tmp_path / "apps" / "handlers" / "audit" / "same.py")

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_handler_independence,
    )

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True


def test_handler_independence_fstring_guard_text_not_flagged(tmp_path):
    """An f-string that mentions apps.handlers as help text is not a real import."""
    content = (
        "def guard():\n"
        "    raise ImportError(\n"
        '        f"    from aipass.seedgo.apps.handlers.error import error_handler\\n"\n'
        "    )\n"
    )
    handler_path = str(tmp_path / "apps" / "handlers" / "audit" / "guard.py")

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_handler_independence,
    )

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is True


def test_handler_independence_flags_real_import_alongside_guard_text(tmp_path):
    """A real cross-handler import is still caught even when guard text sits nearby."""
    content = (
        "from aipass.seedgo.apps.handlers.error import error_handler\n"
        "\n"
        "def guard():\n"
        "    raise ImportError(\n"
        '        f"    from aipass.seedgo.apps.handlers.error import error_handler\\n"\n'
        "    )\n"
    )
    handler_path = str(tmp_path / "apps" / "handlers" / "audit" / "mixed.py")

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_handler_independence,
    )

    result = check_handler_independence(content, _lines(content), handler_path)
    assert result["passed"] is False
    assert "line 1" in result["message"]


# ===========================================================================
# 2. handlers_check -- check_auto_detection
# ===========================================================================


def test_auto_detection_not_needed():
    """No module_name parameter means auto-detection is not needed (returns None)."""
    content = "def do_work(file_path):\n    return True\n"

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_auto_detection,
    )

    result = check_auto_detection(content)
    assert result is None


def test_auto_detection_present():
    """Handler with module_name and inspect.stack() passes."""
    content = "import inspect\ndef do_work(module_name=None):\n    frame = inspect.stack()\n    return True\n"

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_auto_detection,
    )

    result = check_auto_detection(content)
    assert result is not None
    assert result["passed"] is True


def test_auto_detection_missing():
    """Handler with module_name but no inspect.stack() fails."""
    content = "def do_work(module_name=None):\n    return True\n"

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_auto_detection,
    )

    result = check_auto_detection(content)
    assert result is not None
    assert result["passed"] is False
    assert "missing auto-detection" in result["message"]


def test_auto_detection_with_get_caller():
    """Handler with _get_caller_module_name passes auto-detection."""
    content = "def _get_caller_module_name():\n    pass\ndef do_work(module_name=None):\n    return True\n"

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_auto_detection,
    )

    result = check_auto_detection(content)
    assert result is not None
    assert result["passed"] is True


# ===========================================================================
# 3. handlers_check -- check_no_orchestration
# ===========================================================================


def test_no_orchestration_clean():
    """Handler with no module imports passes."""
    content = '"""Clean handler."""\n\ndef do_work():\n    return True\n'

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_no_orchestration,
    )

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is True


def test_no_orchestration_module_import():
    """Handler importing from apps.modules fails."""
    content = (
        '"""Bad handler."""\nfrom aipass.seedgo.apps.modules import audit_module\n\ndef do_work():\n    return True\n'
    )

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_no_orchestration,
    )

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is False
    assert "orchestration" in result["message"]


def test_no_orchestration_in_docstring():
    """Module import inside docstring is not flagged."""
    content = (
        '"""\nExample: from aipass.seedgo.apps.modules import audit_module\n"""\n\ndef do_work():\n    return True\n'
    )

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_no_orchestration,
    )

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is True


def test_no_orchestration_fstring_guard_text_not_flagged():
    """An import-guard error message built from an f-string is not a real import.

    Regression test: apps/handlers/__init__.py raises ImportError with help text
    like `f"    from {MY_BRANCH}.apps.modules.<module> import <function>\\n"` —
    the old text-matching check flagged this guard text as orchestration.
    """
    content = (
        "MY_BRANCH = 'aipass.seedgo'\n"
        "def guard():\n"
        "    raise ImportError(\n"
        '        f"    from {MY_BRANCH}.apps.modules.<module> import <function>\\n"\n'
        "    )\n"
    )

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_no_orchestration,
    )

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is True


def test_no_orchestration_flags_real_import_alongside_guard_text():
    """A real module import is still caught even when guard text sits nearby."""
    content = (
        "from aipass.seedgo.apps.modules.scanner import scan_all\n"
        "\n"
        "def guard():\n"
        "    raise ImportError(\n"
        '        f"    from aipass.seedgo.apps.modules.<module> import <function>\\n"\n'
        "    )\n"
    )

    from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
        check_no_orchestration,
    )

    result = check_no_orchestration(content, _lines(content))
    assert result is not None
    assert result["passed"] is False
    assert "line 1" in result["message"]


# ===========================================================================
# 4. log_handler_check -- check_no_raw_file_handler
# ===========================================================================


def test_no_raw_file_handler_clean():
    """File without logging.FileHandler passes."""
    lines: List[str] = [
        '"""Clean module."""',
        "import logging",
        "logger = logging.getLogger(__name__)",
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.log_handler_check import (
        check_no_raw_file_handler,
    )

    result = check_no_raw_file_handler(lines, "/fake/path.py")
    assert result["passed"] is True


def test_no_raw_file_handler_violation():
    """File with logging.FileHandler fails."""
    # seedgo:bypass standard=log_handler reason="test data for checker validation"
    lines: List[str] = [
        '"""Bad module."""',
        "import logging",
        'handler = logging.FileHandler("app.log")',
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.log_handler_check import (
        check_no_raw_file_handler,
    )

    result = check_no_raw_file_handler(lines, "/fake/path.py")
    assert result["passed"] is False
    assert "FileHandler" in result["message"]


# ===========================================================================
# 5. log_handler_check -- check_no_raw_stream_handler
# ===========================================================================


def test_no_raw_stream_handler_no_file_logging():
    """No file-based logging means stream handler check not applicable."""
    lines: List[str] = [
        "import logging",
        "logger = logging.getLogger(__name__)",
        "",
    ]
    content = "\n".join(lines)

    from aipass.seedgo.apps.handlers.aipass_standards.log_handler_check import (
        check_no_raw_stream_handler,
    )

    result = check_no_raw_stream_handler(lines, "/fake/path.py", content)
    assert result["passed"] is True
    assert "not applicable" in result["message"]


def test_no_raw_stream_handler_violation():
    """StreamHandler with file logging is a violation."""
    # seedgo:bypass standard=log_handler reason="test data for checker validation"
    lines: List[str] = [
        "import logging",
        'handler = logging.FileHandler("app.log")',
        "stream = logging.StreamHandler()",
        "",
    ]
    content = "\n".join(lines)

    from aipass.seedgo.apps.handlers.aipass_standards.log_handler_check import (
        check_no_raw_stream_handler,
    )

    result = check_no_raw_stream_handler(lines, "/fake/path.py", content)
    assert result["passed"] is False
    assert "StreamHandler" in result["message"]


def test_no_raw_stream_handler_clean():
    """File logging present but no StreamHandler passes."""
    # seedgo:bypass standard=log_handler reason="test data for checker validation"
    lines: List[str] = [
        "import logging",
        'handler = logging.FileHandler("app.log")',
        "",
    ]
    content = "\n".join(lines)

    from aipass.seedgo.apps.handlers.aipass_standards.log_handler_check import (
        check_no_raw_stream_handler,
    )

    result = check_no_raw_stream_handler(lines, "/fake/path.py", content)
    assert result["passed"] is True


# ===========================================================================
# 6. log_level_check -- check_error_not_user_input
# ===========================================================================


def test_error_not_user_input_clean():
    """ERROR used for system failures passes."""
    lines: List[str] = [
        '"""Module."""',
        'logger.error("System crash: %s", error)',
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.log_level_check import (
        check_error_not_user_input,
    )

    result = check_error_not_user_input(lines, "/fake/path.py")
    assert result["passed"] is True


def test_error_not_user_input_violation():
    """ERROR used for user-input pattern fails."""
    # seedgo:bypass standard=log_level reason="test data for checker validation"
    lines: List[str] = [
        '"""Module."""',
        'logger.error("Unknown command: %s", cmd)',
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.log_level_check import (
        check_error_not_user_input,
    )

    result = check_error_not_user_input(lines, "/fake/path.py")
    assert result["passed"] is False
    assert "user input" in result["message"]


def test_error_not_user_input_in_docstring():
    """ERROR pattern inside a docstring is ignored."""
    # seedgo:bypass standard=log_level reason="test data for checker validation"
    lines: List[str] = [
        '"""',
        'logger.error("Unknown command: %s", cmd)',
        '"""',
        "pass",
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.log_level_check import (
        check_error_not_user_input,
    )

    result = check_error_not_user_input(lines, "/fake/path.py")
    assert result["passed"] is True


# ===========================================================================
# 7. log_level_check -- check_command_routing_level
# ===========================================================================


def test_command_routing_level_no_routing():
    """File without command routing returns None."""
    content = "def do_work():\n    pass\n"

    from aipass.seedgo.apps.handlers.aipass_standards.log_level_check import (
        check_command_routing_level,
    )

    result = check_command_routing_level(content, _lines(content), "/fake/path.py")
    assert result is None


def test_command_routing_level_clean():
    """Command routing with proper WARNING level passes."""
    content = 'def route_command(cmd):\n    logger.warning("Unknown command: %s", cmd)\n'

    from aipass.seedgo.apps.handlers.aipass_standards.log_level_check import (
        check_command_routing_level,
    )

    result = check_command_routing_level(content, _lines(content), "/fake/path.py")
    assert result is not None
    assert result["passed"] is True


def test_command_routing_level_violation():
    """Command routing with ERROR for user-input pattern fails."""
    # seedgo:bypass standard=log_level reason="test data for checker validation"
    content = 'def route_command(cmd):\n    logger.error("Unknown command: %s", cmd)\n'

    from aipass.seedgo.apps.handlers.aipass_standards.log_level_check import (
        check_command_routing_level,
    )

    result = check_command_routing_level(content, _lines(content), "/fake/path.py")
    assert result is not None
    assert result["passed"] is False
    assert "ERROR" in result["message"] or "WARNING" in result["message"]


# ===========================================================================
# 8. log_structure_check -- check_branch_post
# ===========================================================================


def test_check_branch_post_no_logs(tmp_path):
    """Branch with no logs returns empty violations."""
    branch = tmp_path / "mybranch"
    branch.mkdir()

    from aipass.seedgo.apps.handlers.aipass_standards.log_structure_check import (
        check_branch_post,
    )

    violations, scores = check_branch_post(str(branch))
    assert violations == []
    assert scores == []


def test_check_branch_post_with_system_logs(tmp_path):
    """Branch with local logs and system logs passes."""
    branch = tmp_path / "mybranch"
    branch.mkdir()
    logs_dir = branch / "logs"
    logs_dir.mkdir()
    (logs_dir / "app.log").write_text("log line", encoding="utf-8")

    # Create repo-level registry and system_logs
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{}", encoding="utf-8")
    sys_logs = tmp_path / "system_logs"
    sys_logs.mkdir()
    (sys_logs / "mybranch_system.log").write_text("system log", encoding="utf-8")

    from aipass.seedgo.apps.handlers.aipass_standards.log_structure_check import (
        check_branch_post,
    )

    violations, scores = check_branch_post(str(branch))
    assert 100 in scores


def test_check_branch_post_local_no_system(tmp_path):
    """Branch with local logs but no system logs is flagged."""
    branch = tmp_path / "mybranch"
    branch.mkdir()
    logs_dir = branch / "logs"
    logs_dir.mkdir()
    (logs_dir / "app.log").write_text("log line", encoding="utf-8")

    # Create repo-level registry and system_logs, but no branch-specific system log
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{}", encoding="utf-8")
    sys_logs = tmp_path / "system_logs"
    sys_logs.mkdir()

    from aipass.seedgo.apps.handlers.aipass_standards.log_structure_check import (
        check_branch_post,
    )

    violations, scores = check_branch_post(str(branch))
    assert 50 in scores
    assert len(violations) == 1
    assert "prax dispatch" in violations[0]["issues"][0]


# ===========================================================================
# 9. meta_check -- check_meta_presence
# ===========================================================================


def test_meta_presence_valid():
    """Content with both header and footer markers passes."""
    content = (
        "# =================== AIPass ====================\n"
        "# Name: test.py\n"
        "# Description: Test file\n"
        "# Version: 1.0.0\n"
        "# Created: 2026-01-01\n"
        "# Modified: 2026-01-01\n"
        "# =============================================\n"
    )

    from aipass.seedgo.apps.handlers.aipass_standards.meta_check import (
        check_meta_presence,
    )

    result = check_meta_presence(content)
    assert result["passed"] is True


def test_meta_presence_missing_header():
    """Content without header marker fails."""
    content = "# Name: test.py\n# =============================================\n"

    from aipass.seedgo.apps.handlers.aipass_standards.meta_check import (
        check_meta_presence,
    )

    result = check_meta_presence(content)
    assert result["passed"] is False
    assert "header" in result["message"]


def test_meta_presence_legacy_header():
    """Content with legacy META header passes."""
    content = (
        "# =================== META ====================\n"
        "# Name: test.py\n"
        "# =============================================\n"
    )

    from aipass.seedgo.apps.handlers.aipass_standards.meta_check import (
        check_meta_presence,
    )

    result = check_meta_presence(content)
    assert result["passed"] is True


# ===========================================================================
# 10. meta_check -- check_meta_placement
# ===========================================================================


def test_meta_placement_at_top():
    """META block at line 1 passes."""
    content = "# =================== AIPass ====================\nrest of file\n"

    from aipass.seedgo.apps.handlers.aipass_standards.meta_check import (
        check_meta_placement,
    )

    result = check_meta_placement(content)
    assert result["passed"] is True


def test_meta_placement_not_at_top():
    """META block not at line 1 fails."""
    content = '"""Docstring first."""\n# =================== AIPass ====================\n'

    from aipass.seedgo.apps.handlers.aipass_standards.meta_check import (
        check_meta_placement,
    )

    result = check_meta_placement(content)
    assert result["passed"] is False
    assert "first line" in result["message"]


# ===========================================================================
# 11. meta_check -- check_required_fields
# ===========================================================================


def test_required_fields_all_present():
    """All required META fields present passes."""
    content = (
        "# =================== AIPass ====================\n"
        "# Name: test.py\n"
        "# Description: Test file\n"
        "# Version: 1.0.0\n"
        "# Created: 2026-01-01\n"
        "# Modified: 2026-01-01\n"
        "# =============================================\n"
    )

    from aipass.seedgo.apps.handlers.aipass_standards.meta_check import (
        check_required_fields,
    )

    results = check_required_fields(content, "test.py")
    assert all(r["passed"] for r in results)


def test_required_fields_missing_version():
    """Missing Version field fails."""
    content = (
        "# =================== AIPass ====================\n"
        "# Name: test.py\n"
        "# Description: Test file\n"
        "# Created: 2026-01-01\n"
        "# Modified: 2026-01-01\n"
        "# =============================================\n"
    )

    from aipass.seedgo.apps.handlers.aipass_standards.meta_check import (
        check_required_fields,
    )

    results = check_required_fields(content, "test.py")
    version_result = [r for r in results if "Version" in r["name"]]
    assert len(version_result) == 1
    assert version_result[0]["passed"] is False


def test_required_fields_wrong_name():
    """Name field not matching filename fails."""
    content = (
        "# =================== AIPass ====================\n"
        "# Name: wrong_name.py\n"
        "# Description: Test file\n"
        "# Version: 1.0.0\n"
        "# Created: 2026-01-01\n"
        "# Modified: 2026-01-01\n"
        "# =============================================\n"
    )

    from aipass.seedgo.apps.handlers.aipass_standards.meta_check import (
        check_required_fields,
    )

    results = check_required_fields(content, "test.py")
    name_result = [r for r in results if "Name" in r["name"]]
    assert len(name_result) == 1
    assert name_result[0]["passed"] is False
    assert "wrong_name.py" in name_result[0]["message"]


# ===========================================================================
# 12. naming_check -- check_file_naming
# ===========================================================================


def test_file_naming_snake_case(tmp_path):
    """Snake_case filename passes."""
    f = tmp_path / "good_module.py"
    f.write_text("pass", encoding="utf-8")

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_file_naming,
    )

    result = check_file_naming(str(f), f)
    assert result["passed"] is True


def test_file_naming_bad_case(tmp_path):
    """Uppercase filename fails."""
    f = tmp_path / "BadModule.py"
    f.write_text("pass", encoding="utf-8")

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_file_naming,
    )

    result = check_file_naming(str(f), f)
    assert result["passed"] is False
    assert "invalid characters" in result["message"]


def test_file_naming_redundant_prefix(tmp_path):
    """Filename with redundant parent dir prefix fails."""
    parent = tmp_path / "audit"
    parent.mkdir()
    f = parent / "audit_ops.py"
    f.write_text("pass", encoding="utf-8")

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_file_naming,
    )

    result = check_file_naming(str(f), f)
    assert result["passed"] is False
    assert "redundant prefix" in result["message"]


def test_file_naming_init(tmp_path):
    """__init__.py passes (Python-reserved)."""
    f = tmp_path / "__init__.py"
    f.write_text("", encoding="utf-8")

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_file_naming,
    )

    result = check_file_naming(str(f), f)
    assert result["passed"] is True


# ===========================================================================
# 13. naming_check -- check_function_naming
# ===========================================================================


def test_function_naming_all_snake():
    """All snake_case functions pass."""
    content = "def do_work():\n    pass\n\ndef get_data():\n    pass\n"

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_function_naming,
    )

    result = check_function_naming(content)
    assert result is not None
    assert result["passed"] is True


def test_function_naming_camel_case():
    """CamelCase function fails."""
    content = "def DoWork():\n    pass\n"

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_function_naming,
    )

    result = check_function_naming(content)
    assert result is not None
    assert result["passed"] is False
    assert "DoWork" in result["message"]


def test_function_naming_no_functions():
    """No functions returns None."""
    content = "X = 42\n"

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_function_naming,
    )

    result = check_function_naming(content)
    assert result is None


def test_function_naming_dunder_skipped():
    """Dunder methods are skipped from violation checks but still counted."""
    content = "class Foo:\n    def __init__(self):\n        pass\n"

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_function_naming,
    )

    result = check_function_naming(content)
    # __init__ is found but skipped from violation checks, so it passes
    assert result is not None
    assert result["passed"] is True


# ===========================================================================
# 14. naming_check -- check_constant_naming
# ===========================================================================


def test_constant_naming_upper():
    """UPPER_CASE constants pass."""
    content = 'MY_CONST = "hello"\nANOTHER = 42\n'

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_constant_naming,
    )

    result = check_constant_naming(content)
    assert result is not None
    assert result["passed"] is True


def test_constant_naming_lowercase():
    """Lowercase constants fail."""
    content = 'my_const = "hello"\n'

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_constant_naming,
    )

    result = check_constant_naming(content)
    assert result is not None
    assert result["passed"] is False
    assert "my_const" in result["message"]


def test_constant_naming_function_call_ignored():
    """Constants assigned via function call are ignored."""
    content = "logger = logging.getLogger(__name__)\n"

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_constant_naming,
    )

    result = check_constant_naming(content)
    # Function call assignment is skipped, no constants to check
    assert result is None


# ===========================================================================
# 15. naming_check -- check_class_naming
# ===========================================================================


def test_class_naming_pascal():
    """PascalCase class passes."""
    content = "class MyClass:\n    pass\n"

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_class_naming,
    )

    result = check_class_naming(content)
    assert result is not None
    assert result["passed"] is True


def test_class_naming_snake():
    """snake_case class fails."""
    content = "class my_class:\n    pass\n"

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_class_naming,
    )

    result = check_class_naming(content)
    assert result is not None
    assert result["passed"] is False
    assert "my_class" in result["message"]


def test_class_naming_no_classes():
    """No classes returns None."""
    content = "def do_work():\n    pass\n"

    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import (
        check_class_naming,
    )

    result = check_class_naming(content)
    assert result is None


# ===========================================================================
# 16. permission_flags_check -- check_no_dangerous_flags
# ===========================================================================


def test_no_dangerous_flags_clean():
    """File with only approved permission flags passes."""
    lines: List[str] = [
        '"""Clean module."""',
        '"--permission-mode bypassPermissions"',
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.permission_flags_check import (
        check_no_dangerous_flags,
    )

    result = check_no_dangerous_flags(lines, "/fake/path.py")
    assert result["passed"] is True


def test_no_dangerous_flags_violation():
    """File with prohibited permission bypass flag fails."""
    # seedgo:bypass standard=permission_flags reason="test data for checker validation"
    lines: List[str] = [
        '"""Module."""',
        'cmd = "--dangerously-skip-permissions"',
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.permission_flags_check import (
        check_no_dangerous_flags,
    )

    result = check_no_dangerous_flags(lines, "/fake/path.py")
    assert result["passed"] is False
    assert "Dangerous" in result["message"]


def test_no_dangerous_flags_in_docstring():
    """Prohibited flag inside docstring is ignored."""
    # seedgo:bypass standard=permission_flags reason="test data for checker validation"
    lines: List[str] = [
        '"""',
        "Use --dangerously-skip-permissions for testing",
        '"""',
        "pass",
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.permission_flags_check import (
        check_no_dangerous_flags,
    )

    result = check_no_dangerous_flags(lines, "/fake/path.py")
    assert result["passed"] is True


def test_no_dangerous_flags_skip_permissions():
    """File with --skip-permissions fails."""
    # seedgo:bypass standard=permission_flags reason="test data for checker validation"
    lines: List[str] = [
        '"""Module."""',
        'cmd = "--skip-permissions"',
        "",
    ]

    from aipass.seedgo.apps.handlers.aipass_standards.permission_flags_check import (
        check_no_dangerous_flags,
    )

    result = check_no_dangerous_flags(lines, "/fake/path.py")
    assert result["passed"] is False


def test_no_dangerous_flags_bypass_rule():
    """Prohibited flag bypassed by rule passes."""
    # seedgo:bypass standard=permission_flags reason="test data for checker validation"
    lines: List[str] = [
        '"""Module."""',
        'cmd = "--dangerously-skip-permissions"',
        "",
    ]
    bypass_rules = [{"standard": "permission_flags", "file": "/fake/path.py"}]

    from aipass.seedgo.apps.handlers.aipass_standards.permission_flags_check import (
        check_no_dangerous_flags,
    )

    result = check_no_dangerous_flags(lines, "/fake/path.py", bypass_rules=bypass_rules)
    assert result["passed"] is True
