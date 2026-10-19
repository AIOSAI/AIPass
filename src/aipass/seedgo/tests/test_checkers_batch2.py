# =================== AIPass ====================
# Name: test_checkers_batch2.py
# Description: Tests for checker handlers batch 2
# Version: 1.1.0
# Created: 2026-03-29
# Modified: 2026-10-18
# =============================================

"""Tests for apps/handlers/aipass_standards/error_handling_check.py and seven batch-2 sibling checkers."""

# Covers handlers, hardcoded_key, help_text, imports, introspection, log_handler
# and log_level. Each checker gets 3 tests: clean pass, violation caught, bypass
# respected.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the eight checker modules under test parse and import

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.seedgo.apps.handlers.bypass import utils as _bypass_utils
from aipass.seedgo.apps.handlers.aipass_standards.error_handling_check import (
    check_module as check_error_handling,
)
from aipass.seedgo.apps.handlers.aipass_standards.handlers_check import (
    check_module as check_handlers,
)
from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_key_check import (
    check_module as check_hardcoded_key,
)
from aipass.seedgo.apps.handlers.aipass_standards.help_text_check import (
    check_module as check_help_text,
)
from aipass.seedgo.apps.handlers.aipass_standards.imports_check import (
    check_module as check_imports,
)
from aipass.seedgo.apps.handlers.aipass_standards.introspection_check import (
    check_module as check_introspection,
)
from aipass.seedgo.apps.handlers.aipass_standards.log_handler_check import (
    check_module as check_log_handler,
)
from aipass.seedgo.apps.handlers.aipass_standards.log_level_check import (
    check_module as check_log_level,
)


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


def _write(tmp_path: Path, name: str, content: str) -> str:
    """Write a temp .py file and return its string path."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


class TestErrorHandling:
    def test_error_handling_clean_passes(self, tmp_path: Path) -> None:
        code = """\
import os

def do_work():
    try:
        result = 1 / 0
    except ZeroDivisionError as e:
        print(f"Caught: {e}")
        return None
"""
        fp = _write(tmp_path, "clean_errors.py", code)
        result = check_error_handling(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "ERROR_HANDLING"

    def test_error_handling_violation_caught(self, tmp_path: Path) -> None:
        code = """\
def do_work():
    try:
        risky()
    except:
        pass
"""
        fp = _write(tmp_path, "bad_errors.py", code)
        result = check_error_handling(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0
        assert violations[0]["message"] == (
            "Silent failure detected (except: pass) in bad_errors.py at line 4 - errors should log/return"
        )

    def test_error_handling_bypass_respected(self, tmp_path: Path) -> None:
        code = """\
def do_work():
    try:
        risky()
    except:
        pass
"""
        fp = _write(tmp_path, "bypass_errors.py", code)
        bypass = [{"file": "bypass_errors.py", "standard": "error_handling"}]
        result = check_error_handling(fp, bypass_rules=bypass)
        assert result["score"] == 100


class TestHandlers:
    def test_handlers_clean_passes(self, tmp_path: Path) -> None:
        # The checker only runs checks for files whose path contains 'apps/handlers/'.
        # The seedgo/ segment matters: handler independence is judged per BRANCH, so
        # the fixture has to say which branch this file belongs to.
        handler_dir = tmp_path / "seedgo" / "apps" / "handlers" / "mypack"
        handler_dir.mkdir(parents=True)
        code = """\
from aipass.seedgo.apps.handlers.json import json_handler

def do_stuff():
    return True
"""
        fp = str(handler_dir / "clean_handler.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_handlers(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "HANDLERS"

    def test_handlers_violation_caught(self, tmp_path: Path) -> None:
        handler_dir = tmp_path / "apps" / "handlers" / "mypack"
        handler_dir.mkdir(parents=True)
        code = """\
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.modules.scanner import scan_all

def do_stuff():
    return scan_all()
"""
        fp = str(handler_dir / "bad_handler.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_handlers(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_handlers_bypass_respected(self, tmp_path: Path) -> None:
        handler_dir = tmp_path / "apps" / "handlers" / "mypack"
        handler_dir.mkdir(parents=True)
        code = """\
from aipass.seedgo.apps.modules.scanner import scan_all
"""
        fp = str(handler_dir / "bypass_handler.py")
        Path(fp).write_text(code, encoding="utf-8")
        bypass = [{"file": "bypass_handler.py", "standard": "handlers"}]
        result = check_handlers(fp, bypass_rules=bypass)
        assert result["score"] == 100

    def test_handlers_reports_all_forbidden_imports(self, tmp_path: Path) -> None:
        """A file with two cross-handler imports must report both, not just the first."""
        handler_dir = tmp_path / "apps" / "handlers" / "mypack"
        handler_dir.mkdir(parents=True)
        code = """\
from aipass.seedgo.apps.handlers.error import error_handler
from aipass.seedgo.apps.handlers.file import file_handler

def do_stuff():
    return True
"""
        fp = str(handler_dir / "double_violation.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_handlers(fp)
        independence = next(c for c in result["checks"] if c["name"] == "Handler independence")
        assert "line 1" in independence["message"]
        assert "line 2" in independence["message"]

    def test_handlers_reports_all_orchestration_imports(self, tmp_path: Path) -> None:
        """A file with two module (orchestration) imports must report both, not just the first."""
        handler_dir = tmp_path / "seedgo" / "apps" / "handlers" / "mypack"
        handler_dir.mkdir(parents=True)
        code = """\
from aipass.seedgo.apps.modules.scanner import scan_all
from aipass.seedgo.apps.modules.reporter import report_all

def do_stuff():
    return scan_all()
"""
        fp = str(handler_dir / "double_orchestration.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_handlers(fp)
        orchestration = next(c for c in result["checks"] if c["name"] == "No orchestration")
        assert "line 1" in orchestration["message"]
        assert "line 2" in orchestration["message"]


class TestHardcodedKey:
    def test_hardcoded_key_clean_passes(self, tmp_path: Path) -> None:
        code = """\
import os

API_KEY = os.environ.get("OPENAI_API_KEY", "")

def call_api():
    return API_KEY
"""
        fp = _write(tmp_path, "clean_keys.py", code)
        result = check_hardcoded_key(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "HARDCODED_KEY"

    def test_hardcoded_key_violation_caught(self, tmp_path: Path) -> None:
        # NOTE: the sk-or-v1-... literal below is a FAKE/synthetic key (patterned hex,
        # not a real credential). It exists only to prove the detector flags hardcoded keys.
        code = """\
API_KEY = "sk-or-v1-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e"

def call_api():
    return API_KEY
"""
        fp = _write(tmp_path, "bad_keys.py", code)
        result = check_hardcoded_key(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0
        assert violations[0]["message"] == "Found 1 hardcoded key(s) on lines 1"

    def test_hardcoded_key_bypass_respected(self, tmp_path: Path) -> None:
        # NOTE: same FAKE/synthetic sk-or-v1-... fixture key below — not a real credential.
        code = """\
API_KEY = "sk-or-v1-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e"
"""
        fp = _write(tmp_path, "bypass_keys.py", code)
        bypass = [{"file": "bypass_keys.py", "standard": "hardcoded_key"}]
        result = check_hardcoded_key(fp, bypass_rules=bypass)
        assert result["score"] == 100

    def test_an_unreadable_file_fails_by_name(self, tmp_path: Path) -> None:
        # A directory named like a module: it exists, and no read of it
        # succeeds. Unread is not "no key".
        target = tmp_path / "keys.py"
        target.mkdir()
        result = check_hardcoded_key(str(target))
        assert result["score"] == 0
        assert [c["message"] for c in result["checks"]] == ["Cannot read the file, so it was not scanned for keys"]

    def test_a_key_in_a_triple_quoted_literal_in_code_is_found(self, tmp_path: Path) -> None:
        # The same FAKE/synthetic sk-or-v1-... fixture key, not a real credential.
        code = 'API_KEY = """sk-or-v1-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e"""\n'
        result = check_hardcoded_key(_write(tmp_path, "literal_keys.py", code))
        assert [c["message"] for c in result["checks"] if not c["passed"]] == ["Found 1 hardcoded key(s) on lines 1"]

    def test_a_key_inside_a_multi_line_docstring_is_prose(self, tmp_path: Path) -> None:
        code = '"""Shape:\n    API_KEY = "sk-or-v1-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e"\n"""\nx = 1\n'
        result = check_hardcoded_key(_write(tmp_path, "doc_keys.py", code))
        assert result["score"] == 100

    def test_a_key_after_a_docstring_quoting_the_other_delimiter_is_found(self, tmp_path: Path) -> None:
        code = '"""Quotes \'\'\' in prose."""\nAPI_KEY = "sk-or-v1-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e"\n'
        result = check_hardcoded_key(_write(tmp_path, "after_doc_keys.py", code))
        assert [c["message"] for c in result["checks"] if not c["passed"]] == ["Found 1 hardcoded key(s) on lines 2"]


class TestHelpText:
    def test_help_text_clean_passes(self, tmp_path: Path) -> None:
        code = """\
def print_help():
    print("Usage: drone @seedgo audit")
    print("Run an audit on the current branch.")
"""
        fp = _write(tmp_path, "clean_help.py", code)
        result = check_help_text(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "HELP_TEXT"

    def test_help_text_violation_caught(self, tmp_path: Path) -> None:
        code = """\
def print_help():
    print("Usage: python3 tools/scanner.py --all")
    print("Run the scanner tool.")
"""
        fp = _write(tmp_path, "bad_help.py", code)
        result = check_help_text(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_help_text_bypass_respected(self, tmp_path: Path) -> None:
        code = """\
def print_help():
    print("Usage: python3 tools/scanner.py --all")
"""
        fp = _write(tmp_path, "bypass_help.py", code)
        bypass = [{"file": "bypass_help.py", "standard": "help_text"}]
        result = check_help_text(fp, bypass_rules=bypass)
        assert result["score"] == 100

    def test_a_python_command_in_a_one_line_docstring_is_prose(self, tmp_path: Path) -> None:
        code = 'def f():\n    """Run python3 tools/x.py first."""\n    return 1\n'
        assert check_help_text(_write(tmp_path, "doc_one.py", code))["passed"] is True

    def test_a_python_command_in_a_multi_line_docstring_is_prose(self, tmp_path: Path) -> None:
        code = 'def f():\n    """Help.\n\n    Run python3 tools/x.py first.\n    """\n    return 1\n'
        assert check_help_text(_write(tmp_path, "doc_multi.py", code))["passed"] is True

    def test_an_inline_comment_after_a_mixed_delimiter_docstring_is_not_help_text(self, tmp_path: Path) -> None:
        code = "'''Uses \"\"\" in prose.'''\nx = 1  # see python3 tools/x.py\n"
        result = check_help_text(_write(tmp_path, "mixed.py", code))
        assert result["passed"] is True

    def test_a_triple_quoted_help_literal_body_is_read(self, tmp_path: Path) -> None:
        code = 'HELP = """\nRun python3 tools/x.py now.\n"""\n'
        result = check_help_text(_write(tmp_path, "literal_help.py", code))
        assert "on line 2 " in result["checks"][0]["message"]


class TestImports:
    def test_imports_clean_passes(self, tmp_path: Path) -> None:
        code = """\
import os
import sys
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler


def process():
    logger.info("Processing")
    return True
"""
        fp = _write(tmp_path, "clean_imports.py", code)
        result = check_imports(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "IMPORTS"

    def test_imports_violation_caught(self, tmp_path: Path) -> None:
        code = """\
import sys
sys.path.insert(0, "/some/path")

from aipass.prax import logger


def process():
    logger.info("Processing")
    return True
"""
        fp = _write(tmp_path, "bad_imports.py", code)
        result = check_imports(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_imports_bypass_respected(self, tmp_path: Path) -> None:
        code = """\
import sys
sys.path.insert(0, "/some/path")
"""
        fp = _write(tmp_path, "bypass_imports.py", code)
        bypass = [{"file": "bypass_imports.py", "standard": "imports"}]
        result = check_imports(fp, bypass_rules=bypass)
        assert result["score"] == 100


class TestTheLoggerSubRuleIsProductionOnly:
    """A test file owes no logger; the checker's other five sub-rules still run."""

    # Over twenty code lines on purpose: the logger sub-rule already exempts
    # small files, so a short sample would pass for the wrong reason and the
    # production half of this class would prove nothing.
    NO_LOGGER = """\
import os
from pathlib import Path

from aipass.seedgo.apps.handlers.json import json_handler

ROOT = Path(os.sep)
NAMES = ("alpha", "beta", "gamma")


def collect(base):
    found = []
    for name in NAMES:
        candidate = base / name
        if candidate.exists():
            found.append(candidate)
    return found


def describe(base):
    entries = collect(base)
    if not entries:
        return "nothing"
    return ", ".join(entry.name for entry in entries)


def record(base):
    json_handler.log_operation("described", {"base": str(base), "detail": describe(base)})
    return True
"""

    def _in(self, tmp_path: Path, *parts: str) -> str:
        """The same source, written at whichever path the test is about."""
        target = tmp_path.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.NO_LOGGER, encoding="utf-8")
        return str(target)

    def test_a_test_file_without_a_logger_scores_a_hundred(self, tmp_path: Path) -> None:
        assert check_imports(self._in(tmp_path, "tests", "test_thing.py"))["score"] == 100

    def test_a_conftest_without_a_logger_scores_a_hundred(self, tmp_path: Path) -> None:
        """conftest.py is a test file by name, wherever it sits."""
        assert check_imports(self._in(tmp_path, "conftest.py"))["score"] == 100

    def test_the_same_source_under_apps_is_still_convicted(self, tmp_path: Path) -> None:
        """Byte-identical content, production path: proves the gate reads the PATH."""
        result = check_imports(self._in(tmp_path, "apps", "modules", "thing.py"))

        failed = [c["name"] for c in result["checks"] if not c["passed"]]
        assert failed == ["Prax logger import (recommended)"]

    def test_a_test_file_is_still_convicted_for_hacking_sys_path(self, tmp_path: Path) -> None:
        """The other sub-rules did not move: only the logger one is gated."""
        target = tmp_path / "tests" / "test_hacky.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('import sys\nsys.path.insert(0, "x")\n' + self.NO_LOGGER, encoding="utf-8")

        result = check_imports(str(target))

        failed = [c["name"] for c in result["checks"] if not c["passed"]]
        assert failed == ["No sys.path hacking"]


class TestADoorOwesNoLogger:
    """A door re-exports and logs nothing, whatever its length (DPLAN-0404)."""

    NAMES = [f"name_{n:02d}" for n in range(20)]
    DOOR = (
        "from aipass.spawn.apps.handlers.registry import (\n"
        + "".join(f"    {name},\n" for name in NAMES)
        + ")\n\n__all__ = "
        + repr(NAMES)
        + "\n"
    )

    @pytest.mark.parametrize(
        ("name", "rows"), [("door_registry.py", []), ("registry_view.py", ["Prax logger import (recommended)"])]
    )
    def test_the_logger_row_reads_the_door_name(self, tmp_path: Path, name: str, rows: list) -> None:
        target = tmp_path / "spawn" / "apps" / "modules" / name
        target.parent.mkdir(parents=True)
        target.write_text(self.DOOR, encoding="utf-8")

        result = check_imports(str(target))

        assert [c["name"] for c in result["checks"] if not c["passed"]] == rows


class TestIntrospection:
    def test_introspection_clean_passes(self, tmp_path: Path) -> None:
        # File must be in apps/ to be detected as entry point, or modules/ for module
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        code = """\
def print_introspection():
    print("Module: scanner")
    print("Version: 1.0.0")

def handle_command(command, args):
    if not args:
        print_introspection()
        return True
    if "--help" in args or "-h" in args:
        print("Help text here")
        return True
    return False
"""
        fp = str(modules_dir / "scanner.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_introspection(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "INTROSPECTION"

    def test_introspection_violation_caught(self, tmp_path: Path) -> None:
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        code = """\
def handle_command(command, args):
    if args[0] == "scan":
        return do_scan()
    return False
"""
        fp = str(modules_dir / "bad_module.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_introspection(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_introspection_bypass_respected(self, tmp_path: Path) -> None:
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        code = """\
def handle_command(command, args):
    return False
"""
        fp = str(modules_dir / "bypass_mod.py")
        Path(fp).write_text(code, encoding="utf-8")
        bypass = [{"file": "bypass_mod.py", "standard": "introspection"}]
        result = check_introspection(fp, bypass_rules=bypass)
        assert result["score"] == 100


class TestLogHandler:
    def test_log_handler_clean_passes(self, tmp_path: Path) -> None:
        code = """\
from aipass.prax import logger

def do_work():
    logger.info("Working")
    return True
"""
        fp = _write(tmp_path, "clean_logging.py", code)
        result = check_log_handler(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "LOG_HANDLER"

    def test_log_handler_violation_caught(self, tmp_path: Path) -> None:
        code = """\
import logging

handler = logging.FileHandler("/var/log/app.log")
handler2 = logging.StreamHandler()
my_logger = logging.getLogger("app")
my_logger.addHandler(handler)
my_logger.addHandler(handler2)
"""
        fp = _write(tmp_path, "bad_logging.py", code)
        result = check_log_handler(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_log_handler_bypass_respected(self, tmp_path: Path) -> None:
        code = """\
import logging

handler = logging.FileHandler("/var/log/app.log")
my_logger = logging.getLogger("app")
my_logger.addHandler(handler)
"""
        fp = _write(tmp_path, "bypass_logging.py", code)
        bypass = [{"file": "bypass_logging.py", "standard": "log_handler"}]
        result = check_log_handler(fp, bypass_rules=bypass)
        assert result["score"] == 100


class TestLogLevel:
    def test_log_level_clean_passes(self, tmp_path: Path) -> None:
        code = """\
from aipass.prax import logger

def process():
    logger.info("Processing started")
    try:
        result = compute()
    except Exception as e:
        logger.error("System failure during compute: %s", e)
    logger.warning("User provided unknown command")
    return True
"""
        fp = _write(tmp_path, "clean_levels.py", code)
        result = check_log_level(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "LOG_LEVEL"

    def test_log_level_violation_caught(self, tmp_path: Path) -> None:
        code = """\
from aipass.prax import logger

def handle_command(command, args):
    if command == "unknown":
        logger.error("Unknown command: %s", command)
    return False
"""
        fp = _write(tmp_path, "bad_levels.py", code)
        result = check_log_level(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_log_level_bypass_respected(self, tmp_path: Path) -> None:
        code = """\
from aipass.prax import logger

def handle_command(command, args):
    if command == "unknown":
        logger.error("Unknown command: %s", command)
    return False
"""
        fp = _write(tmp_path, "bypass_levels.py", code)
        bypass = [{"file": "bypass_levels.py", "standard": "log_level"}]
        result = check_log_level(fp, bypass_rules=bypass)
        assert result["score"] == 100
