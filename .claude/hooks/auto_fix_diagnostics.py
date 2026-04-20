#!/usr/bin/env python3
"""
PostToolUse Auto-fix Hook — Detects type errors and surfaces them for fixing.

Two-hook system:
  PostToolUse (this file) → runs pyright on edited file, saves errors to state
  PreToolUse (pre_edit_gate.py) → blocks edits to OTHER files until errors fixed

Key behaviors:
- Runs py_compile (syntax), ruff (lint), pyright (type errors) on edited file
- Runs seedgo checklist for AIPass standards
- Saves type errors to state file for PreToolUse gate
- Surfaces ALL errors in additionalContext so Claude sees them
- Smart batching per-file

Version: 5.1.0

CHANGELOG:
  - v5.1.0 (2026-04-19): Added ruff format --check to surface format drift.
  - v5.0.0 (2026-03-17): Replaced mcp__ide__getDiagnostics with direct pyright.
                          Added state file for PreToolUse gate integration.
                          Single-file pyright (not whole project).
  - v4.3.0 (2026-03-17): Added seedgo checklist integration
  - v4.0.0 (2025-11-27): Complete rewrite - actual validation, silent operation
"""

import json
import sys
import subprocess
from pathlib import Path

EDIT_TOOLS = ["Edit", "Write", "MultiEdit", "NotebookEdit"]
LAST_FILE_PATH = Path(__file__).parent / ".last_diagnostics_file"
STATE_FILE = Path(__file__).parent / ".diagnostics_state.json"
SKIP_EXTENSIONS = {".md", ".txt", ".log", ".csv", ".html"}

# AIPass-specific Python patterns to check
PYTHON_PATTERNS = {
    "bad_optional": {
        "pattern": ": str = None",
        "message": "Optional param should use 'str | None = None' pattern"
    },
    "logger_debug": {
        "pattern": "logger.debug(",
        "message": "Use logger.info for SystemLogger (logger.debug not supported)"
    },
    "return_error_msg": {
        "pattern": "return error_msg",
        "message": "Return None for error states, not error_msg string"
    },
    "open_no_encoding": {
        "pattern": "open(",
        "requires_missing": "encoding=",
        "message": "open() without encoding='utf-8'"
    },
    "log_not_log_operation": {
        "pattern": ".log(",
        "message": "Use log_operation() with success/error params, not .log()"
    },
    "dict_none_no_check": {
        "pattern": "Dict | None",
        "message": "Dict | None return: Add None check before using (if result is None: return)"
    }
}

# JSON-specific patterns for emoji corruption
JSON_CORRUPTION_CHARS = ['\ufffd', '\x00']


def run_python_checks(file_path: str) -> list[str]:
    """Run actual Python validation - returns list of errors."""
    errors = []

    # 1. Syntax check with py_compile
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", file_path],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            errors.append(f"SYNTAX: {result.stderr.strip()}")
    except Exception:
        pass

    # 2. Ruff check (if available) - fast linter
    try:
        result = subprocess.run(
            ["ruff", "check", "--select=E,F,W", "--output-format=text", file_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n")[:5]:
                errors.append(f"LINT: {line}")
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # 3. Ruff format check — detect format drift
    try:
        result = subprocess.run(
            ["ruff", "format", "--check", file_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            errors.append(f"FORMAT: {Path(file_path).name} needs ruff format (run: ruff format {Path(file_path).name})")
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # 4. AIPass-specific pattern checks
    try:
        content = Path(file_path).read_text(encoding="utf-8")
        lines = content.split("\n")

        for check in PYTHON_PATTERNS.values():
            pattern = check["pattern"]
            message = check["message"]
            requires_missing = check.get("requires_missing")

            if requires_missing:
                if pattern in content and requires_missing not in content:
                    errors.append(f"PATTERN: {message}")
                continue

            for line in lines:
                stripped = line.strip()
                if stripped.startswith(("#", '"', "'")):
                    continue
                if f'"{pattern}' in line or f"'{pattern}" in line:
                    continue
                if pattern in line:
                    errors.append(f"PATTERN: {message}")
                    break
    except Exception:
        pass

    return errors


def run_pyright_check(file_path: str) -> list[dict]:
    """Run pyright on a single file. Returns list of error dicts."""
    # Skip hook files - they don't follow project standards
    if '/.claude/hooks/' in file_path:
        return []

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyright", "--outputjson", file_path],
            capture_output=True,
            text=True,
            timeout=15
        )

        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return []

        errors = []
        for diag in data.get("generalDiagnostics", []):
            severity = diag.get("severity", "")
            if severity == "error":
                line = diag.get("range", {}).get("start", {}).get("line", 0)
                message = diag.get("message", "Unknown error")
                errors.append({
                    "line": line,
                    "message": message[:100]
                })

        return errors[:10]  # Max 10 errors

    except FileNotFoundError:
        return []  # pyright not installed
    except subprocess.TimeoutExpired:
        return []  # Timeout — don't block
    except Exception:
        return []


def save_diagnostics_state(file_path: str, errors: list[dict]):
    """Save type errors to state file for PreToolUse gate."""
    try:
        if errors:
            state = {
                "file": str(Path(file_path).resolve()),
                "errors": errors
            }
            STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        else:
            # No errors — clear the state
            if STATE_FILE.exists():
                STATE_FILE.unlink()
    except Exception:
        pass


def run_json_checks(file_path: str) -> list[str]:
    """Run actual JSON validation - returns list of errors."""
    errors = []

    try:
        content = Path(file_path).read_text(encoding="utf-8")

        for char in JSON_CORRUPTION_CHARS:
            if char in content:
                errors.append(f"EMOJI CORRUPTION: Found corrupted character '{repr(char)}'")
                break

        try:
            data = json.loads(content)

            if isinstance(data, dict):
                for key in ['allowed_emojis', 'emojis', 'emoji_list']:
                    if key in data and isinstance(data[key], list):
                        for item in data[key]:
                            if isinstance(item, str) and len(item) == 1:
                                if ord(item) < 128 and item not in '\u2713\u2717':
                                    errors.append(f"EMOJI CORRUPTION: Suspicious char '{item}' in {key}")
                                    break

        except json.JSONDecodeError as e:
            errors.append(f"JSON SYNTAX: {e.msg} at line {e.lineno}")

    except Exception as e:
        errors.append(f"READ ERROR: {e!s}")

    return errors


def run_seedgo_checklist(file_path: str) -> list[str]:
    """Run seedgo standards checklist — returns violations only."""
    if '/.claude/hooks/' in file_path:
        return []

    try:
        result = subprocess.run(
            ["drone", "@seedgo", "checklist", file_path],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(Path.home() / "Projects" / "AIPass")
        )

        if result.returncode != 0:
            return []

        violations = []
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("\u2717"):
                violation = line[1:].strip()
                if violation:
                    violations.append(violation)

        return violations[:5]

    except FileNotFoundError:
        return []
    except Exception:
        return []


def should_skip_file(file_path: str) -> bool:
    """Check if file should be skipped."""
    if not file_path:
        return True
    ext = Path(file_path).suffix.lower()
    return ext in SKIP_EXTENSIONS


def is_same_file_as_last(file_path: str) -> bool:
    """Smart batching DISABLED — always recheck.

    Previously skipped rechecks on the same file, but this caused
    errors introduced on second edit to be missed (state file didn't
    exist from first clean edit, so skip triggered). The 1.7s pyright
    cost per edit is acceptable for correctness.
    """
    return False


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        if tool_name not in EDIT_TOOLS:
            return

        if should_skip_file(file_path):
            return

        if is_same_file_as_last(file_path):
            return

        # Collect all errors
        errors = []
        file_type = ""

        if file_path.endswith(".py"):
            file_type = "Python"
            errors = run_python_checks(file_path)

            # Seedgo standards checklist
            seedgo_violations = run_seedgo_checklist(file_path)
            for v in seedgo_violations:
                errors.append(f"SEEDGO: {v}")

            # Pyright type errors (single file)
            type_errors = run_pyright_check(file_path)
            for te in type_errors:
                errors.append(f"TYPE: L{te['line']}: {te['message']}")

            # Save type errors to state file for PreToolUse gate
            save_diagnostics_state(file_path, type_errors)

        elif file_path.endswith(".json"):
            file_type = "JSON"
            errors = run_json_checks(file_path)
        else:
            return

        # Build output
        if errors:
            error_text = "\n".join(f"  - {e}" for e in errors)
            context = f"""[AUTO-FIX] {len(errors)} error(s) in {Path(file_path).name}:
{error_text}

Fix these errors in {Path(file_path).name} now. Do not skip or defer."""

            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": context
                },
                "systemMessage": f"[AUTO-FIX] {len(errors)} error(s) — fix before continuing"
            }
            print(json.dumps(output))
        else:
            output = {
                "systemMessage": "[diagnostics] ok"
            }
            print(json.dumps(output))

    except Exception:
        pass  # Silent fail


if __name__ == "__main__":
    main()
