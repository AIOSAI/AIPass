# =================== AIPass ====================
# Name: test_checkers_batch2.py
# Description: Tests for checker handlers batch 2
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""
Tests for 8 seedgo checker handlers:
  error_handling, handlers, hardcoded_key, help_text,
  imports, introspection, log_handler, log_level.

Each checker gets 3 tests: clean pass, violation caught, bypass respected.
"""

import pytest
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, content: str) -> str:
    """Write a temp .py file and return its string path."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# ===================================================================
# 1. error_handling_check
# ===================================================================


class TestErrorHandling:
    def test_error_handling_clean_passes(self, tmp_path: Path) -> None:
        code = '''\
import os

def do_work():
    try:
        result = 1 / 0
    except ZeroDivisionError as e:
        print(f"Caught: {e}")
        return None
'''
        fp = _write(tmp_path, "clean_errors.py", code)
        result = check_error_handling(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "ERROR_HANDLING"

    def test_error_handling_violation_caught(self, tmp_path: Path) -> None:
        code = '''\
def do_work():
    try:
        risky()
    except:
        pass
'''
        fp = _write(tmp_path, "bad_errors.py", code)
        result = check_error_handling(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0
        assert "silent failure" in violations[0]["message"].lower() or "except" in violations[0]["message"].lower()

    def test_error_handling_bypass_respected(self, tmp_path: Path) -> None:
        code = '''\
def do_work():
    try:
        risky()
    except:
        pass
'''
        fp = _write(tmp_path, "bypass_errors.py", code)
        bypass = [{"file": "bypass_errors.py", "standard": "error_handling"}]
        result = check_error_handling(fp, bypass_rules=bypass)
        assert result["score"] == 100


# ===================================================================
# 2. handlers_check
# ===================================================================


class TestHandlers:
    def test_handlers_clean_passes(self, tmp_path: Path) -> None:
        # The checker only runs checks for files whose path contains 'apps/handlers/'
        handler_dir = tmp_path / "apps" / "handlers" / "mypack"
        handler_dir.mkdir(parents=True)
        code = '''\
from aipass.seedgo.apps.handlers.json import json_handler

def do_stuff():
    return True
'''
        fp = str(handler_dir / "clean_handler.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_handlers(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "HANDLERS"

    def test_handlers_violation_caught(self, tmp_path: Path) -> None:
        handler_dir = tmp_path / "apps" / "handlers" / "mypack"
        handler_dir.mkdir(parents=True)
        code = '''\
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.modules.scanner import scan_all

def do_stuff():
    return scan_all()
'''
        fp = str(handler_dir / "bad_handler.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_handlers(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_handlers_bypass_respected(self, tmp_path: Path) -> None:
        handler_dir = tmp_path / "apps" / "handlers" / "mypack"
        handler_dir.mkdir(parents=True)
        code = '''\
from aipass.seedgo.apps.modules.scanner import scan_all
'''
        fp = str(handler_dir / "bypass_handler.py")
        Path(fp).write_text(code, encoding="utf-8")
        bypass = [{"file": "bypass_handler.py", "standard": "handlers"}]
        result = check_handlers(fp, bypass_rules=bypass)
        assert result["score"] == 100


# ===================================================================
# 3. hardcoded_key_check
# ===================================================================


class TestHardcodedKey:
    def test_hardcoded_key_clean_passes(self, tmp_path: Path) -> None:
        code = '''\
import os

API_KEY = os.environ.get("OPENAI_API_KEY", "")

def call_api():
    return API_KEY
'''
        fp = _write(tmp_path, "clean_keys.py", code)
        result = check_hardcoded_key(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "HARDCODED_KEY"

    def test_hardcoded_key_violation_caught(self, tmp_path: Path) -> None:
        code = '''\
API_KEY = "sk-or-v1-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e"

def call_api():
    return API_KEY
'''
        fp = _write(tmp_path, "bad_keys.py", code)
        result = check_hardcoded_key(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0
        assert "hardcoded" in violations[0]["message"].lower() or "key" in violations[0]["message"].lower()

    def test_hardcoded_key_bypass_respected(self, tmp_path: Path) -> None:
        code = '''\
API_KEY = "sk-or-v1-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e"
'''
        fp = _write(tmp_path, "bypass_keys.py", code)
        bypass = [{"file": "bypass_keys.py", "standard": "hardcoded_key"}]
        result = check_hardcoded_key(fp, bypass_rules=bypass)
        assert result["score"] == 100


# ===================================================================
# 4. help_text_check
# ===================================================================


class TestHelpText:
    def test_help_text_clean_passes(self, tmp_path: Path) -> None:
        code = '''\
def print_help():
    print("Usage: drone @seedgo audit")
    print("Run an audit on the current branch.")
'''
        fp = _write(tmp_path, "clean_help.py", code)
        result = check_help_text(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "HELP_TEXT"

    def test_help_text_violation_caught(self, tmp_path: Path) -> None:
        code = '''\
def print_help():
    print("Usage: python3 tools/scanner.py --all")
    print("Run the scanner tool.")
'''
        fp = _write(tmp_path, "bad_help.py", code)
        result = check_help_text(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_help_text_bypass_respected(self, tmp_path: Path) -> None:
        code = '''\
def print_help():
    print("Usage: python3 tools/scanner.py --all")
'''
        fp = _write(tmp_path, "bypass_help.py", code)
        bypass = [{"file": "bypass_help.py", "standard": "help_text"}]
        result = check_help_text(fp, bypass_rules=bypass)
        assert result["score"] == 100


# ===================================================================
# 5. imports_check
# ===================================================================


class TestImports:
    def test_imports_clean_passes(self, tmp_path: Path) -> None:
        code = '''\
import os
import sys
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler


def process():
    logger.info("Processing")
    return True
'''
        fp = _write(tmp_path, "clean_imports.py", code)
        result = check_imports(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "IMPORTS"

    def test_imports_violation_caught(self, tmp_path: Path) -> None:
        code = '''\
import sys
sys.path.insert(0, "/some/path")

from aipass.prax import logger


def process():
    logger.info("Processing")
    return True
'''
        fp = _write(tmp_path, "bad_imports.py", code)
        result = check_imports(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_imports_bypass_respected(self, tmp_path: Path) -> None:
        code = '''\
import sys
sys.path.insert(0, "/some/path")
'''
        fp = _write(tmp_path, "bypass_imports.py", code)
        bypass = [{"file": "bypass_imports.py", "standard": "imports"}]
        result = check_imports(fp, bypass_rules=bypass)
        assert result["score"] == 100


# ===================================================================
# 6. introspection_check
# ===================================================================


class TestIntrospection:
    def test_introspection_clean_passes(self, tmp_path: Path) -> None:
        # File must be in apps/ to be detected as entry point, or modules/ for module
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        code = '''\
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
'''
        fp = str(modules_dir / "scanner.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_introspection(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "INTROSPECTION"

    def test_introspection_violation_caught(self, tmp_path: Path) -> None:
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        code = '''\
def handle_command(command, args):
    if args[0] == "scan":
        return do_scan()
    return False
'''
        fp = str(modules_dir / "bad_module.py")
        Path(fp).write_text(code, encoding="utf-8")
        result = check_introspection(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_introspection_bypass_respected(self, tmp_path: Path) -> None:
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        code = '''\
def handle_command(command, args):
    return False
'''
        fp = str(modules_dir / "bypass_mod.py")
        Path(fp).write_text(code, encoding="utf-8")
        bypass = [{"file": "bypass_mod.py", "standard": "introspection"}]
        result = check_introspection(fp, bypass_rules=bypass)
        assert result["score"] == 100


# ===================================================================
# 7. log_handler_check
# ===================================================================


class TestLogHandler:
    def test_log_handler_clean_passes(self, tmp_path: Path) -> None:
        code = '''\
from aipass.prax import logger

def do_work():
    logger.info("Working")
    return True
'''
        fp = _write(tmp_path, "clean_logging.py", code)
        result = check_log_handler(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "LOG_HANDLER"

    def test_log_handler_violation_caught(self, tmp_path: Path) -> None:
        code = '''\
import logging

handler = logging.FileHandler("/var/log/app.log")
handler2 = logging.StreamHandler()
my_logger = logging.getLogger("app")
my_logger.addHandler(handler)
my_logger.addHandler(handler2)
'''
        fp = _write(tmp_path, "bad_logging.py", code)
        result = check_log_handler(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_log_handler_bypass_respected(self, tmp_path: Path) -> None:
        code = '''\
import logging

handler = logging.FileHandler("/var/log/app.log")
my_logger = logging.getLogger("app")
my_logger.addHandler(handler)
'''
        fp = _write(tmp_path, "bypass_logging.py", code)
        bypass = [{"file": "bypass_logging.py", "standard": "log_handler"}]
        result = check_log_handler(fp, bypass_rules=bypass)
        assert result["score"] == 100


# ===================================================================
# 8. log_level_check
# ===================================================================


class TestLogLevel:
    def test_log_level_clean_passes(self, tmp_path: Path) -> None:
        code = '''\
from aipass.prax import logger

def process():
    logger.info("Processing started")
    try:
        result = compute()
    except Exception as e:
        logger.error("System failure during compute: %s", e)
    logger.warning("User provided unknown command")
    return True
'''
        fp = _write(tmp_path, "clean_levels.py", code)
        result = check_log_level(fp)
        assert result["passed"] is True
        assert result["score"] >= 75
        assert result["standard"] == "LOG_LEVEL"

    def test_log_level_violation_caught(self, tmp_path: Path) -> None:
        code = '''\
from aipass.prax import logger

def handle_command(command, args):
    if command == "unknown":
        logger.error("Unknown command: %s", command)
    return False
'''
        fp = _write(tmp_path, "bad_levels.py", code)
        result = check_log_level(fp)
        assert result["score"] < 100
        violations = [c for c in result["checks"] if not c["passed"]]
        assert len(violations) > 0

    def test_log_level_bypass_respected(self, tmp_path: Path) -> None:
        code = '''\
from aipass.prax import logger

def handle_command(command, args):
    if command == "unknown":
        logger.error("Unknown command: %s", command)
    return False
'''
        fp = _write(tmp_path, "bypass_levels.py", code)
        bypass = [{"file": "bypass_levels.py", "standard": "log_level"}]
        result = check_log_level(fp, bypass_rules=bypass)
        assert result["score"] == 100
