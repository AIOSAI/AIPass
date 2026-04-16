# =================== AIPass ====================
# Name: hardcoded_key_check.py
# Description: Hardcoded Key Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Hardcoded Key Standards Checker Handler

Scans Python source files for hardcoded API keys matching known provider
prefixes (OpenRouter, OpenAI, Anthropic, Google, AWS, GitHub, Slack, etc.).
Placeholder values, comments, and docstrings are filtered out so only
genuine secrets trigger a failure.
"""

import re
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"

# -- Key patterns -----------------------------------------------------------
# Each tuple: (provider_label, compiled regex)
# Patterns require the key to appear inside quotes and be long enough to
# exclude obvious placeholders (minimum 8 chars after prefix).

_KEY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "OpenRouter (sk-or-v1-)",
        re.compile(r"""["'`](sk-or-v1-[A-Za-z0-9\-_]{8,})["'`]"""),
    ),
    (
        "OpenAI project (sk-proj-)",
        re.compile(r"""["'`](sk-proj-[A-Za-z0-9\-_]{8,})["'`]"""),
    ),
    (
        "Anthropic (sk-ant-)",
        re.compile(r"""["'`](sk-ant-[A-Za-z0-9\-_]{8,})["'`]"""),
    ),
    (
        "Google (AIza)",
        re.compile(r"""["'`](AIza[A-Za-z0-9\-_]{20,})["'`]"""),
    ),
    (
        "AWS (AKIA)",
        re.compile(r"""["'`](AKIA[A-Za-z0-9]{12,})["'`]"""),
    ),
    (
        "GitHub (ghp_/gho_/ghs_)",
        re.compile(r"""["'`](gh[pos]_[A-Za-z0-9]{8,})["'`]"""),
    ),
    (
        "Slack (xoxb-/xoxp-)",
        re.compile(r"""["'`](xox[bp]-[A-Za-z0-9\-]{8,})["'`]"""),
    ),
    (
        "Generic (key-)",
        re.compile(r"""["'`](key-[A-Za-z0-9\-_]{16,})["'`]"""),
    ),
]

# Placeholder indicators -- if the captured value matches any of these the
# hit is treated as documentation, not a real secret.
_PLACEHOLDER_VALUE_RE = re.compile(
    r"(?:your[_\-]?key|xxx+|example|placeholder|abc123|new\-key|"
    r"v1-\.\.\.|all[_\-]?x|test|fake|dummy|sample|\.\.\.|"
    r"your_key_here|key[-_]here|insert|changeme|<|>)",
    re.IGNORECASE,
)

_PLACEHOLDER_SUFFIX_RE = re.compile(
    r"[-_](?:here|example|test|xxx+|placeholder|abc|demo|key|secret|value)$",
    re.IGNORECASE,
)

# Words on the line (outside the key literal) that signal example context.
_EXAMPLE_CONTEXT_WORDS = frozenset(
    {
        "example",
        "template",
        "placeholder",
        "sample",
        "demo",
    }
)

# Pure comment line.
_PAT_COMMENT = re.compile(r"^\s*#")

# Regex compile context -- the key-like string is a detection pattern itself.
_PAT_REGEX_CONTEXT = re.compile(r"""re\.compile|r["']|\\[dws\^]""")


# -- Helpers ----------------------------------------------------------------


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed."""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        if rule.get("standard") and rule.get("standard") != standard:
            continue
        rule_file = rule.get("file", "")
        if rule_file and rule_file not in file_path:
            continue
        rule_lines = rule.get("lines", [])
        if rule_lines and line is not None and line not in rule_lines:
            continue
        return True
    return False


def _is_placeholder(key_value: str) -> bool:
    """Return True if the captured key value looks like a placeholder."""
    if _PLACEHOLDER_VALUE_RE.search(key_value):
        return True
    if _PLACEHOLDER_SUFFIX_RE.search(key_value):
        return True
    return False


# -- Core detection ---------------------------------------------------------


def _scan_line(lineno: int, line: str) -> list[tuple[int, str]]:
    """
    Check a single source line for hardcoded key literals.

    Returns a list of (lineno, provider_label) tuples for each finding.
    Skips comment lines, example-context lines, regex-compile contexts,
    and placeholder values.
    """
    if _PAT_COMMENT.match(line):
        return []

    line_lower = line.lower()
    if any(word in line_lower for word in _EXAMPLE_CONTEXT_WORDS):
        return []

    if _PAT_REGEX_CONTEXT.search(line):
        return []

    findings: list[tuple[int, str]] = []
    for label, pattern in _KEY_PATTERNS:
        for match in pattern.finditer(line):
            key_val = match.group(1)
            if _is_placeholder(key_val):
                continue
            findings.append((lineno, label))
    return findings


def _scan_file(file_path: Path) -> list[tuple[int, str]]:
    """
    Scan a single Python file for hardcoded keys.

    Skips __init__.py files, docstring regions, and comment lines.
    Returns a list of (lineno, provider_label) tuples.
    """
    if file_path.name == "__init__.py":
        return []

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        logger.info("Cannot read %s for key scanning", file_path)
        return []

    lines = content.splitlines()
    findings: list[tuple[int, str]] = []
    in_docstring = False

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Track triple-quoted docstrings
        triple_count = stripped.count('"""') + stripped.count("'''")
        if triple_count:
            if triple_count % 2 == 1:
                in_docstring = not in_docstring
            # Skip the line itself whether it opens or closes a docstring
            continue

        if in_docstring:
            continue

        findings.extend(_scan_line(lineno, line))

    return findings


# -- Public entry point -----------------------------------------------------


def check_module(module_path: str, bypass_rules: list | None = None) -> dict:
    """
    Check if a Python file contains hardcoded API keys.

    Args:
        module_path: Path to the Python file to check.
        bypass_rules: Optional list of bypass rules to skip certain checks.

    Returns:
        dict with keys: passed, score, checks, standard.
    """
    # Whole-file bypass
    if is_bypassed(module_path, "hardcoded_key", bypass_rules=bypass_rules):
        result = {
            "passed": True,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "score": 100,
            "standard": "HARDCODED_KEY",
        }
        json_handler.log_operation(
            "check_completed",
            {"file": str(module_path), "score": 100, "standard": "hardcoded_key"},
        )
        return result

    path = Path(module_path)

    # File existence
    if not path.exists():
        result = {
            "passed": False,
            "checks": [
                {
                    "name": "File exists",
                    "passed": False,
                    "message": f"File not found: {module_path}",
                }
            ],
            "score": 0,
            "standard": "HARDCODED_KEY",
        }
        json_handler.log_operation(
            "check_completed",
            {"file": str(module_path), "score": 0, "standard": "hardcoded_key"},
        )
        return result

    # Skip __init__.py
    if path.name == "__init__.py":
        result = {
            "passed": True,
            "checks": [
                {
                    "name": "Hardcoded API keys",
                    "passed": True,
                    "message": "__init__.py skipped",
                }
            ],
            "score": 100,
            "standard": "HARDCODED_KEY",
        }
        json_handler.log_operation(
            "check_completed",
            {"file": str(module_path), "score": 100, "standard": "hardcoded_key"},
        )
        return result

    # Scan the file
    raw_findings = _scan_file(path)

    # Filter out bypassed lines
    findings: list[tuple[int, str]] = []
    for lineno, label in raw_findings:
        if not is_bypassed(module_path, "hardcoded_key", lineno, bypass_rules):
            findings.append((lineno, label))

    # Build the single check entry
    checks: list[dict] = []
    if findings:
        line_numbers = [f[0] for f in findings]
        preview = ", ".join(str(ln) for ln in line_numbers[:3])
        suffix = f" (and {len(line_numbers) - 3} more)" if len(line_numbers) > 3 else ""
        checks.append(
            {
                "name": "Hardcoded API keys",
                "passed": False,
                "message": f"Found {len(findings)} hardcoded key(s) on lines {preview}{suffix}",
            }
        )
    else:
        checks.append(
            {
                "name": "Hardcoded API keys",
                "passed": True,
                "message": "No hardcoded API keys detected",
            }
        )

    # Score
    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int(passed_checks / total_checks * 100) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": score, "standard": "hardcoded_key"},
    )

    return {
        "passed": overall_passed,
        "checks": checks,
        "score": score,
        "standard": "HARDCODED_KEY",
    }
