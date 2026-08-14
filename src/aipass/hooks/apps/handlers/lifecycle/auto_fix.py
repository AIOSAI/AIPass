# =================== AIPass ====================
# Name: auto_fix.py
# Version: 1.0.0
# Description: Post-edit diagnostics — syntax, lint, type, pattern, seedgo checks (PostToolUse)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-05-22
# Modified: 2026-06-09
# =============================================

"""Runs diagnostics on edited files and surfaces errors for the agent to fix."""

import json
import os
import subprocess
import sys
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
STATE_FILE = Path(__file__).parent.parent.parent.parent.parent / ".diagnostics_state.json"
SKIP_EXTENSIONS = {".md", ".txt", ".log", ".csv", ".html"}

PYTHON_PATTERNS = {
    "bad_optional": {
        "pattern": ": str = None",
        "message": "Optional param should use 'str | None = None' pattern",
    },
    "return_error_msg": {
        "pattern": "return error_msg",
        "message": "Return None for error states, not error_msg string",
    },
    "open_no_encoding": {
        "pattern": "open(",
        "requires_missing": "encoding=",
        "message": "open() without encoding='utf-8'",
    },
    "log_not_log_operation": {
        "pattern": ".log(",
        "message": "Use log_operation() with success/error params, not .log()",
    },
    "dict_none_no_check": {
        "pattern": "Dict | None",
        "message": "Dict | None return: Add None check before using (if result is None: return)",
    },
}

JSON_CORRUPTION_CHARS = ["�", "\x00"]


def _check_syntax(file_path: str) -> list[str]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", file_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return [f"SYNTAX: {result.stderr.strip()}"]
    except Exception as exc:
        logger.info("[HOOKS] auto_fix: py_compile failed: %s", exc)
    return []


def _check_ruff_lint(file_path: str) -> list[str]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select=E,F,W", "--output-format=concise", file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode not in (0, 1):
            logger.info("[HOOKS] auto_fix: ruff lint error: %s", result.stderr.strip())
            return []
        if result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            violations = [line for line in lines if ".py:" in line]
            return [f"LINT: {line}" for line in violations[:5]]
    except Exception as exc:
        logger.info("[HOOKS] auto_fix: ruff lint failed: %s", exc)
    return []


def _check_ruff_format(file_path: str) -> list[str]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--check", file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 1:
            name = Path(file_path).name
            return [f"FORMAT: {name} needs ruff format (run: ruff format {name})"]
        if result.returncode not in (0, 1):
            logger.info("[HOOKS] auto_fix: ruff format error: %s", result.stderr.strip())
    except Exception as exc:
        logger.info("[HOOKS] auto_fix: ruff format check failed: %s", exc)
    return []


def _check_line_pattern(line: str, pattern: str) -> bool:
    stripped = line.strip()
    if stripped.startswith(("#", '"', "'")):
        return False
    if f'"{pattern}' in line or f"'{pattern}" in line:
        return False
    return pattern in line


def _check_patterns(file_path: str) -> list[str]:
    errors: list[str] = []
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
                if _check_line_pattern(line, pattern):
                    errors.append(f"PATTERN: {message}")
                    break
    except Exception as exc:
        logger.info("[HOOKS] auto_fix: pattern check failed: %s", exc)
    return errors


def _run_python_checks(file_path: str) -> list[str]:
    errors: list[str] = []
    errors.extend(_check_syntax(file_path))
    errors.extend(_check_ruff_lint(file_path))
    errors.extend(_check_ruff_format(file_path))
    errors.extend(_check_patterns(file_path))
    return errors


def _run_ruff_lint_structured(file_path: str) -> list[dict]:
    if "/.claude/hooks/" in file_path:
        return []
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select=E,F,W", "--output-format=json", file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode not in (0, 1):
            logger.info("[HOOKS] auto_fix: ruff structured lint error: %s", result.stderr.strip())
            return []
        if not result.stdout.strip():
            return []
        violations = json.loads(result.stdout)
        if not isinstance(violations, list):
            return []
        errors: list[dict] = []
        for v in violations[:10]:
            line = v.get("location", {}).get("row", 0)
            code = v.get("code", "?")
            message = v.get("message", "unknown")[:100]
            errors.append({"line": line, "message": f"{code}: {message}"})
        return errors
    except json.JSONDecodeError as exc:
        logger.info("[HOOKS] auto_fix: ruff JSON parse failed: %s", exc)
    except subprocess.TimeoutExpired:
        logger.info("[HOOKS] auto_fix: ruff structured lint timed out")
    except Exception as exc:
        logger.info("[HOOKS] auto_fix: ruff structured lint failed: %s", exc)
    return []


def _run_pyright_check(file_path: str) -> list[dict]:
    if "/.claude/hooks/" in file_path:
        return []
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyright", "--outputjson", file_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.info("[HOOKS] auto_fix: pyright JSON parse failed: %s", exc)
            return []

        errors: list[dict] = []
        for diag in data.get("generalDiagnostics", []):
            if diag.get("severity", "") == "error":
                line = diag.get("range", {}).get("start", {}).get("line", 0)
                message = diag.get("message", "Unknown error")
                errors.append({"line": line, "message": message[:100]})
        return errors[:10]
    except FileNotFoundError:
        logger.info("[HOOKS] auto_fix: pyright not installed")
    except subprocess.TimeoutExpired:
        logger.info("[HOOKS] auto_fix: pyright timed out")
    except Exception as exc:
        logger.info("[HOOKS] auto_fix: pyright failed: %s", exc)
    return []


def _run_seedgo_checklist(file_path: str) -> list[str]:
    if "/.claude/hooks/" in file_path:
        return []
    aipass_home = os.environ.get("AIPASS_HOME", "")
    if not aipass_home:
        return []
    try:
        result = subprocess.run(
            ["drone", "@seedgo", "checklist", file_path],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=aipass_home,
        )
        if result.returncode != 0:
            return []
        violations: list[str] = []
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("✗"):
                violation = line[1:].strip()
                if violation:
                    violations.append(violation)
        return violations[:5]
    except FileNotFoundError:
        logger.info("[HOOKS] auto_fix: drone not found for seedgo checklist")
    except Exception as exc:
        logger.info("[HOOKS] auto_fix: seedgo checklist failed: %s", exc)
    return []


def _save_diagnostics_state(file_path: str, errors: list[dict]) -> None:
    try:
        if errors:
            state = {"file": str(Path(file_path).resolve()), "errors": errors}
            STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        else:
            if STATE_FILE.exists():
                STATE_FILE.unlink()
    except Exception as exc:
        logger.info("[HOOKS] auto_fix: state file write failed: %s", exc)


def _check_emoji_list(items: list, key: str) -> str | None:
    for item in items:
        if not isinstance(item, str) or len(item) != 1:
            continue
        if ord(item) < 128 and item not in "✓✗":
            return f"EMOJI CORRUPTION: Suspicious char '{item}' in {key}"
    return None


def _run_json_checks(file_path: str) -> list[str]:
    errors: list[str] = []
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        logger.info("[HOOKS] auto_fix: json read failed: %s", e)
        return [f"READ ERROR: {e!s}"]

    for char in JSON_CORRUPTION_CHARS:
        if char in content:
            errors.append(f"EMOJI CORRUPTION: Found corrupted character '{char!r}'")
            break

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.info("[HOOKS] auto_fix: json syntax error in %s: %s", file_path, e)
        errors.append(f"JSON SYNTAX: {e.msg} at line {e.lineno}")
        return errors

    if not isinstance(data, dict):
        return errors

    for key in ("allowed_emojis", "emojis", "emoji_list"):
        values = data.get(key)
        if not isinstance(values, list):
            continue
        finding = _check_emoji_list(values, key)
        if finding:
            errors.append(finding)

    return errors


def handle(hook_data: dict) -> dict:
    """Run diagnostics on edited files and surface errors.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (JSON additionalContext or empty) and exit_code.
    """
    try:
        tool_name = hook_data.get("tool_name", "")
        if tool_name not in EDIT_TOOLS:
            return {"stdout": "", "exit_code": 0}

        tool_input = hook_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return {"stdout": "", "exit_code": 0}

        ext = Path(file_path).suffix.lower()
        if ext in SKIP_EXTENSIONS:
            return {"stdout": "", "exit_code": 0}

        errors: list[str] = []

        if file_path.endswith(".py"):
            errors = _run_python_checks(file_path)

            seedgo_violations = _run_seedgo_checklist(file_path)
            for v in seedgo_violations:
                errors.append(f"SEEDGO: {v}")

            type_errors = _run_pyright_check(file_path)
            for te in type_errors:
                errors.append(f"TYPE: L{te['line']}: {te['message']}")

            ruff_lint_errors = _run_ruff_lint_structured(file_path)
            _save_diagnostics_state(file_path, ruff_lint_errors + type_errors)

        elif file_path.endswith(".json"):
            errors = _run_json_checks(file_path)
        else:
            return {"stdout": "", "exit_code": 0}

        if errors:
            error_text = "\n".join(f"  - {e}" for e in errors)
            context = (
                f"[AUTO-FIX] {len(errors)} error(s) in {Path(file_path).name}:\n"
                f"{error_text}\n\n"
                f"Fix these errors in {Path(file_path).name} now. Do not skip or defer."
            )
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": context,
                },
                "systemMessage": f"[AUTO-FIX] {len(errors)} error(s) — fix before continuing",
            }
            return {"stdout": json.dumps(result), "exit_code": 0, "sound": "auto fix diagnostics"}

        result = {"systemMessage": "[diagnostics] ok"}
        return {"stdout": json.dumps(result), "exit_code": 0}

    except Exception as exc:
        logger.info("[HOOKS] auto_fix: unexpected error (allowing): %s", exc)
        return {"stdout": "", "exit_code": 0}
