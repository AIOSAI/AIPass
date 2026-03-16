#!/usr/bin/env python3
"""
Silent Auto-fix Hook - Runs ACTUAL validation and tells Claude to fix silently.

Key behaviors:
- Runs real linters (ruff, py_compile) not just pattern lists
- Validates JSON with json.load()
- Outputs via additionalContext so Claude sees errors
- Claude fixes silently without announcing
- Simple indicator for user console
- Smart batching per-file

Version: 4.3.0
"""

import json
import sys
import subprocess
from pathlib import Path

EDIT_TOOLS = ["Edit", "Write", "MultiEdit", "NotebookEdit"]
LAST_FILE_PATH = Path(__file__).parent / ".last_diagnostics_file"
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
            for line in result.stdout.strip().split("\n")[:5]:  # Max 5 errors
                errors.append(f"LINT: {line}")
    except FileNotFoundError:
        pass  # ruff not installed
    except Exception:
        pass

    # 3. AIPass-specific pattern checks
    try:
        content = Path(file_path).read_text(encoding="utf-8")
        lines = content.split("\n")

        for check in PYTHON_PATTERNS.values():
            pattern = check["pattern"]
            message = check["message"]
            requires_missing = check.get("requires_missing")

            # For patterns that require something to be missing
            if requires_missing:
                if pattern in content and requires_missing not in content:
                    errors.append(f"PATTERN: {message}")
                continue

            # Standard pattern check - scan lines
            for line in lines:
                stripped = line.strip()
                # Skip comments and strings
                if stripped.startswith(("#", '"', "'")):
                    continue
                # Skip if pattern appears in a string on this line
                if f'"{pattern}' in line or f"'{pattern}" in line:
                    continue
                if pattern in line:
                    errors.append(f"PATTERN: {message}")
                    break  # One error per pattern type
    except Exception:
        pass

    return errors


def run_json_checks(file_path: str) -> list[str]:
    """Run actual JSON validation - returns list of errors."""
    errors = []

    try:
        content = Path(file_path).read_text(encoding="utf-8")

        # Check for emoji corruption before parsing
        for char in JSON_CORRUPTION_CHARS:
            if char in content:
                errors.append(f"EMOJI CORRUPTION: Found corrupted character '{repr(char)}' - check allowed_emojis arrays")
                break

        # Try to parse JSON
        try:
            data = json.loads(content)

            # Check for corruption in emoji arrays specifically
            if isinstance(data, dict):
                for key in ['allowed_emojis', 'emojis', 'emoji_list']:
                    if key in data and isinstance(data[key], list):
                        for item in data[key]:
                            if isinstance(item, str) and len(item) == 1:
                                if ord(item) < 128 and item not in '\u2713\u2717':
                                    errors.append(f"EMOJI CORRUPTION: Suspicious char '{item}' in {key} - may be corrupted emoji")
                                    break

        except json.JSONDecodeError as e:
            errors.append(f"JSON SYNTAX: {e.msg} at line {e.lineno}")

    except Exception as e:
        errors.append(f"READ ERROR: {e!s}")

    return errors


def run_seedgo_checklist(file_path: str) -> list[str]:
    """Run seedgo standards checklist — returns violations only."""
    # Skip Claude hooks - they don't follow project standards
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
            return []  # Command failed, skip

        violations = []
        current_standard = None

        for line in result.stdout.split("\n"):
            line = line.strip()

            # Checklist output format: "✗ standard_name: detail"
            if line.startswith("\u2717"):
                violation = line[1:].strip()
                if violation:
                    violations.append(violation)

        return violations[:5]  # Top 5 only

    except FileNotFoundError:
        return []  # drone not available
    except Exception:
        return []


def should_skip_file(file_path: str) -> bool:
    """Check if file should be skipped."""
    if not file_path:
        return True
    ext = Path(file_path).suffix.lower()
    return ext in SKIP_EXTENSIONS


def is_same_file_as_last(file_path: str) -> bool:
    """Smart batching - skip if same file as last check."""
    try:
        if LAST_FILE_PATH.exists():
            last = LAST_FILE_PATH.read_text(encoding="utf-8").strip()
            if last == file_path:
                return True
        LAST_FILE_PATH.write_text(file_path, encoding="utf-8")
    except Exception:
        pass
    return False


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        # Only process edit tools
        if tool_name not in EDIT_TOOLS:
            return

        # Skip non-code files
        if should_skip_file(file_path):
            return

        # Smart batching - don't re-check same file
        if is_same_file_as_last(file_path):
            return

        # Determine file type and run checks
        errors = []
        file_type = ""

        if file_path.endswith(".py"):
            file_type = "Python"
            errors = run_python_checks(file_path)
            # Seedgo standards checklist (Python files only)
            seedgo_violations = run_seedgo_checklist(file_path)
            for v in seedgo_violations:
                errors.append(f"SEEDGO: {v}")

        elif file_path.endswith(".json"):
            file_type = "JSON"
            errors = run_json_checks(file_path)
        else:
            return  # No validation for other types yet

        # Build context message
        context = ""
        ide_instruction = f"\n\nAlso run mcp__ide__getDiagnostics on {file_path} to check for type errors. Fix any errors found silently."

        if errors:
            error_text = "\n".join(f"  - {e}" for e in errors)
            context = f"""[AUTO-FIX REQUIRED] {len(errors)} validation error(s) in {Path(file_path).name}:
{error_text}

MANDATORY: You MUST fix every error listed above in {Path(file_path).name} before proceeding with any other work. Edit the file now to resolve these issues. Do not skip, defer, or ignore — fix them immediately, then continue with your task."""

        # For Python files, also check IDE diagnostics for type errors
        if file_path.endswith(".py"):
            if errors:
                context += ide_instruction
            else:
                # No other errors, but still check IDE diagnostics
                context = f"[TYPE-CHECK] Run mcp__ide__getDiagnostics on {file_path} and fix any type errors silently."
                errors = ["IDE diagnostics check requested"]

            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": context
                },
                "systemMessage": f"[AUTO-FIX] {len(errors)} issue(s) — fix before continuing"
            }
            print(json.dumps(output))
            # Exit 0 so JSON additionalContext is delivered to the model
        elif errors:
            # JSON or other file with errors
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": context
                },
                "systemMessage": f"[AUTO-FIX] {len(errors)} issue(s) — fix before continuing"
            }
            print(json.dumps(output))
            # Exit 0 so JSON additionalContext is delivered to the model
        else:
            # No errors - just tiny indicator
            output = {
                "systemMessage": "[diagnostics] ok"
            }
            print(json.dumps(output))

    except Exception:
        pass  # Silent fail


if __name__ == "__main__":
    main()
