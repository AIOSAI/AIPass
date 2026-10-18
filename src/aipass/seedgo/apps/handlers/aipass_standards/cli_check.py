# =================== AIPass ====================
# Name: cli_check.py
# Description: CLI Standards Checker Handler
# Version: 1.0.2
# Created: 2026-03-05
# Modified: 2026-10-17
# =============================================

"""CLI Standards Checker Handler"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

AUDIT_SCOPE = "all_files"
# Applies to production source only: a test file is not a branch's CLI surface.
APPLIES_TO = "production"


#: `sys.stdout.write(x.stdout)`, `sys.stderr.write(x["stderr"])` and friends —
#: a router handing a completed subprocess's captured output straight through.
#: The stream names must CORRESPOND: writing a captured stderr to stdout is a
#: routing bug this check should keep catching, so it is not matched here.
_RELAYED_STREAM = re.compile(
    r"sys\.(?P<sink>stdout|stderr)\.write\(\s*[A-Za-z_][\w.]*"
    r"(?:\.(?P=sink)\b|\[\s*[\"'](?P=sink)[\"']\s*\]|\.get\(\s*[\"'](?P=sink)[\"'])"
)


def _is_raw_write_violation(line: str) -> bool:
    """Is this line a raw stream write the CLI standard should object to?"""
    code_part = line.split("#")[0] if "#" in line else line
    if "sys.stdout.write(" not in code_part and "sys.stderr.write(" not in code_part:
        return False
    return not _RELAYED_STREAM.search(code_part)


def _console_import_line(content: str) -> Optional[int]:
    """Line number of the module's OWN module-level import of the cli console."""
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        # A file this checker cannot parse gets no window and keeps every
        # finding. Ignorance is not evidence of a bootstrap.
        logger.info("cli: no console-import window, unparseable: %s", exc)
        return None
    best = None
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        module = getattr(node, "module", None) or (node.names[0].name if node.names else "")
        if module and module.startswith("aipass.cli"):
            best = node.lineno if best is None else min(best, node.lineno)
    return best


def _is_pre_console_bootstrap(line_number: int, console_line: Optional[int]) -> bool:
    """True for a raw write in the window before the console exists."""
    return console_line is not None and line_number < console_line


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows CLI standards"""
    checks = []
    path = Path(module_path)

    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "cli", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "CLI",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "CLI",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "CLI",
        }

    is_handler = "handlers/" in module_path
    is_module = "modules/" in module_path
    is_entry_point = path.name.endswith(".py") and "apps/" in module_path and path.parent.name == "apps"

    if is_handler:
        handler_separation_check = check_handler_separation(content)
        checks.append(handler_separation_check)

    if is_module or is_entry_point:
        cli_imports_check = check_cli_imports(content, module_path)
        if cli_imports_check:
            checks.append(cli_imports_check)

    if is_module or is_entry_point:
        print_usage_check = check_print_usage(content, lines, module_path, bypass_rules=bypass_rules)
        if print_usage_check:
            checks.append(print_usage_check)

    if is_module or is_entry_point:
        help_flag_check = check_help_flag(content)
        if help_flag_check:
            checks.append(help_flag_check)

    if is_module or is_entry_point:
        duplicate_display_check = check_duplicate_display_functions(content, module_path)
        if duplicate_display_check:
            checks.append(duplicate_display_check)

    # Files outside the 3-layer architecture are not subject to CLI standards.
    if not checks:
        return {
            "passed": True,
            "checks": [
                {
                    "name": "CLI check",
                    "passed": True,
                    "message": "File outside module/handler/entry architecture (skipped)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "CLI",
        }

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "cli"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "CLI"}


def _console_print_in_string(line: str, stripped: str) -> bool:
    before_pattern = line.split("console.print(")[0]
    single_quotes = before_pattern.count("'")
    double_quotes = before_pattern.count('"')
    if single_quotes % 2 == 1 or double_quotes % 2 == 1:
        return True
    if "=" in stripped and "console.print(" in stripped:
        before_console = stripped.split("console.print(")[0]
        last_eq_pos = before_console.rfind("=")
        if last_eq_pos != -1:
            after_eq = before_console[last_eq_pos + 1 :]
            sq_after = after_eq.count("'")
            dq_after = after_eq.count('"')
            if sq_after % 2 == 1 or dq_after % 2 == 1:
                return True
    return False


def _stderr_directed_print_lines(content: str) -> set:
    r"""Lines holding a ``print(..., file=sys.stderr)`` call."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return set()

    lines = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"):
            continue
        for keyword in node.keywords:
            if keyword.arg != "file":
                continue
            target = keyword.value
            if isinstance(target, ast.Attribute) and target.attr == "stderr":
                lines.add(node.lineno)
    return lines


def check_handler_separation(content: str) -> Dict:
    """Check that handlers don't have console output"""
    lines = content.split("\n")
    stderr_prints = _stderr_directed_print_lines(content)

    in_docstring = False
    docstring_marker: Optional[str] = None
    console_print_lines = []
    cli_import_lines = []
    print_lines = []

    in_main_block = False
    main_block_indent = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip()) if line.strip() else 0

        if "if __name__ ==" in stripped and "__main__" in stripped:
            in_main_block = True
            main_block_indent = current_indent
            continue

        if in_main_block and stripped and current_indent <= main_block_indent:
            in_main_block = False

        if in_main_block:
            continue

        # Only the marker that opened a docstring block can close it; the other is content.
        triple_double = line.count('"""')
        triple_single = line.count("'''")
        if in_docstring:
            closer = triple_double if docstring_marker == '"""' else triple_single
            if closer % 2 == 1:
                in_docstring = False
                docstring_marker = None
            continue
        if triple_double % 2 == 1:
            in_docstring = True
            docstring_marker = '"""'
            continue
        if triple_single % 2 == 1:
            in_docstring = True
            docstring_marker = "'''"
            continue
        # Even count (e.g. \"\"\"text\"\"\") is a complete docstring on one line:
        # no state change, but the line is still not code.
        if triple_double >= 2 or triple_single >= 2:
            continue

        if in_docstring or stripped.startswith("#"):
            continue

        if "console.print(" in stripped:
            if _console_print_in_string(line, stripped):
                continue
            console_print_lines.append(i)

        if re.search(r"from aipass\.cli\.apps\.modules[\.\s]", stripped) or "from aipass.cli import" in stripped:
            if '"from aipass.cli' in line or "'from aipass.cli" in line:
                continue
            cli_import_lines.append(i)

        # Look for print() calls. A print DIRECTED AT stderr is a diagnostic,
        # not display, and the raw-write spelling of it has always passed.
        if re.search(r"^\s*print\s*\(", line) and i not in stderr_prints:
            print_lines.append(i)

    if console_print_lines:
        return {
            "name": "Handler separation",
            "passed": False,
            "message": f"Handler contains console.print() on lines {console_print_lines[:3]} (violates separation)",
        }

    if cli_import_lines:
        return {
            "name": "Handler separation",
            "passed": False,
            "message": f"Handler imports CLI services on lines {cli_import_lines[:3]} (handlers should not display)",
        }

    if print_lines:
        return {
            "name": "Handler separation",
            "passed": False,
            "message": f"Handler contains print() on lines {print_lines[:3]} (use logger instead)",
        }

    return {"name": "Handler separation", "passed": True, "message": "No console output detected (good separation)"}


def check_cli_imports(content: str, module_path: str = "") -> Optional[Dict]:
    """Check for CLI service imports"""
    # Exception: CLI branch uses internal imports (it's the implementation)
    if "/cli/apps/" in module_path.replace("\\", "/"):
        return {"name": "CLI service imports", "passed": True, "message": "CLI branch exempt (uses internal imports)"}

    has_cli_imports = (
        bool(re.search(r"from aipass\.cli\.apps\.modules[\.\s]", content)) or "from aipass.cli import" in content
    )

    if has_cli_imports:
        import_match = (
            re.search(r"from aipass\.cli\.apps\.modules\.\w+ import (.+)", content)
            or re.search(r"from aipass\.cli\.apps\.modules import (.+)", content)
            or re.search(r"from aipass\.cli import (.+)", content)
        )
        if import_match:
            imports = import_match.group(1)
            return {"name": "CLI service imports", "passed": True, "message": f"Using CLI services ({imports})"}

    has_console_print = "console.print(" in content
    has_print = bool(re.search(r"\bprint\s*\(", content))
    has_raw_write = "sys.stdout.write(" in content or "sys.stderr.write(" in content

    if has_console_print or has_print or has_raw_write:
        return {
            "name": "CLI service imports",
            "passed": False,
            "message": "Has output but missing CLI service imports (import from cli.apps.modules)",
        }

    return {"name": "CLI service imports", "passed": True, "message": "No CLI output needed"}


def check_print_usage(
    content: str, lines: List[str], module_path: str = "", bypass_rules: list | None = None
) -> Optional[Dict]:
    """Check for bare print() statements (should use console.print() instead)"""
    console_line = _console_import_line(content)
    print_lines = []
    parser_print_help_lines = []
    format_help_lines = []
    raw_write_lines = []

    in_main_block = False
    main_block_indent = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip()) if line.strip() else 0

        if "if __name__ ==" in stripped and "__main__" in stripped:
            in_main_block = True
            main_block_indent = current_indent
            continue

        if in_main_block and stripped and current_indent <= main_block_indent:
            in_main_block = False

        if in_main_block:
            continue

        if stripped.startswith("#"):
            continue

        if is_bypassed(module_path, "cli", line=i, bypass_rules=bypass_rules):
            continue

        if "parser.print_help()" in stripped:
            if "#" in line:
                code_part = line.split("#")[0]
                if "parser.print_help()" in code_part:
                    parser_print_help_lines.append(i)
            else:
                parser_print_help_lines.append(i)

        if ".format_help()" in stripped:
            if "#" in line:
                code_part = line.split("#")[0]
                if ".format_help()" in code_part:
                    format_help_lines.append(i)
            else:
                format_help_lines.append(i)

        # Raw sys.stdout/stderr.write() bypasses Rich, except a captured-stream relay
        # or a write in the window before this module's own console exists.
        if _is_raw_write_violation(line) and not _is_pre_console_bootstrap(i, console_line):
            raw_write_lines.append(i)

        if re.search(r"(?<![.\w])print\s*\(", line):
            if "#" in line:
                code_part = line.split("#")[0]
                if re.search(r"(?<![.\w])print\s*\(", code_part):
                    print_lines.append(i)
            else:
                print_lines.append(i)

    from pathlib import Path

    filename = Path(module_path).name if module_path else "file"

    if parser_print_help_lines:
        return {
            "name": "print() usage",
            "passed": False,
            "message": (
                f"Found parser.print_help() in {filename} on lines "
                f"{parser_print_help_lines[:3]} (uses plain print() - use Rich console.print() instead)"
            ),
        }

    if format_help_lines:
        return {
            "name": "print() usage",
            "passed": False,
            "message": (
                f"Found .format_help() in {filename} on lines "
                f"{format_help_lines[:3]} (returns plain argparse text - write Rich help instead)"
            ),
        }

    if raw_write_lines:
        return {
            "name": "print() usage",
            "passed": False,
            "message": (
                f"Found {len(raw_write_lines)} sys.stdout/stderr.write() in {filename} "
                f"(use console.print() instead) on lines "
                f"{raw_write_lines[:3]}{'...' if len(raw_write_lines) > 3 else ''}"
            ),
        }

    if print_lines:
        return {
            "name": "print() usage",
            "passed": False,
            "message": (
                f"Found {len(print_lines)} print() statements in {filename} "
                f"(use console.print() instead) on lines "
                f"{print_lines[:3]}{'...' if len(print_lines) > 3 else ''}"
            ),
        }

    has_console_print = "console.print(" in content

    if has_console_print:
        return {"name": "print() usage", "passed": True, "message": "Using console.print() (no bare print() found)"}

    return None  # No output at all


def check_help_flag(content: str) -> Optional[Dict]:
    """Check for --help flag implementation"""
    has_help_flag = "--help" in content and ("-h" in content or "help" in content)

    has_argparse = "argparse.ArgumentParser" in content or "import argparse" in content

    has_print_help = "def print_help" in content

    if has_print_help or (has_help_flag and has_argparse):
        return {"name": "--help flag", "passed": True, "message": "--help flag implemented"}

    if "__main__" not in content:
        return None  # Not an executable module

    return {
        "name": "--help flag",
        "passed": False,
        "message": "--help flag not implemented (modules should respond to --help)",
    }


def _module_level_function_names(content: str) -> set:
    """Return names of functions defined at MODULE level (not methods on a class).

    Walking tree.body rather than ast.walk() is the whole point: a nested def or
    a class method is not a module-level display helper.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        logger.info("Skipping display-function scan: SyntaxError during parse: %s", e)
        return set()

    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def check_duplicate_display_functions(content: str, module_path: str = "") -> Optional[Dict]:
    """Check for duplicate display functions that should use CLI service instead."""
    if "/cli/apps/" in module_path.replace("\\", "/"):
        return None

    # Exception: Prax logger IS the logging system — it defines these legitimately
    if "/prax/apps/modules/logger" in module_path.replace("\\", "/"):
        return None

    cli_display_functions = ["header", "success", "error", "warning", "info"]

    # Module-level defs only: a class exposing .error/.warning/.info is the fleet's logger
    # API, not a duplicate of cli.display; parsing also ignores "def error(" in strings.
    defined_at_module_level = _module_level_function_names(content)
    duplicates_found = [name for name in cli_display_functions if name in defined_at_module_level]

    if duplicates_found:
        return {
            "name": "CLI display functions",
            "passed": False,
            "message": (
                f"Defines own {', '.join(duplicates_found)}() - "
                f"use from cli.apps.modules.display import {', '.join(duplicates_found)}"
            ),
        }

    return {"name": "CLI display functions", "passed": True, "message": "No duplicate CLI display functions defined"}
