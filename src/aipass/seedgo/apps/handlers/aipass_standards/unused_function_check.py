# =================== AIPass ====================
# Name: unused_function_check.py
# Description: Unused Function Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Unused Function Standards Checker Handler

Branch-level checker that detects functions defined but never referenced
elsewhere in the branch. Uses AST parsing to extract function definitions
and corpus-level text search to count references.

A function is flagged as unused when its name appears only in its own
definition line (i.e., it is never called or imported elsewhere in the
branch source).

Excluded from flagging:
    - Dunder methods (__init__, __str__, __repr__, etc.)
    - main(), handle_command() -- framework/entry-point conventions
    - Any function with a decorator (@property, @staticmethod, etc.)
"""

import ast
import io
import re
import tokenize
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"

# -- Directories to skip when collecting source files -------------------------
SKIP_DIRS = {
    "__pycache__", ".archive", "logs", "tests",
    "json_templates", "tools", ".trinity", ".aipass", ".ai_mail.local",
    ".venv", "venv", "node_modules", ".git", "site-packages",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".spawn",
    "backups", "reports", "docs", ".sorting_unprocessed",
}

# -- Function names excluded from analysis ------------------------------------
EXCLUDED_NAMES = {
    "main",
    "handle_command",
}

# -- Regex helpers for corpus stripping ---------------------------------------

# Matches `if __name__ == "__main__":` through end of file.
_MAIN_BLOCK_RE = re.compile(
    r"""^if\s+__name__\s*==\s*["']__main__["']\s*:.*""",
    re.MULTILINE | re.DOTALL,
)


# -- Bypass helper ------------------------------------------------------------

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


# -- File collection ----------------------------------------------------------

def _should_skip(path: Path) -> bool:
    """Return True if any path component is in the skip set."""
    return any(part in SKIP_DIRS for part in path.parts)


def _collect_python_files(branch_path: Path) -> list[Path]:
    """Collect all .py files in the branch, skipping irrelevant dirs."""
    files: list[Path] = []
    if not branch_path.is_dir():
        return files
    for py_file in branch_path.rglob("*.py"):
        if _should_skip(py_file):
            continue
        files.append(py_file)
    return sorted(files)


# -- Corpus preparation ------------------------------------------------------

def _strip_non_code(source: str) -> str:
    """
    Remove string literals, comments, and __main__ blocks from source.

    Uses Python's tokenizer for accurate string/comment detection.
    The old regex approach misidentified triple-quote characters inside
    code (e.g. ``line.count('\"\"\"')``) as string delimiters, eating
    surrounding code and causing false-positive unused-function reports.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError as exc:
        logger.info("Tokenizer failed, falling back to raw corpus: %s", exc)
        return _MAIN_BLOCK_RE.sub("", source)

    lines = source.split('\n')
    chars = [list(line) for line in lines]

    for tok in tokens:
        if tok.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        sr, sc = tok.start[0] - 1, tok.start[1]
        er, ec = tok.end[0] - 1, tok.end[1]
        for row in range(sr, er + 1):
            if row >= len(chars):
                break
            col_start = sc if row == sr else 0
            col_end = ec if row == er else len(chars[row])
            for col in range(col_start, min(col_end, len(chars[row]))):
                chars[row][col] = ' '

    result = '\n'.join(''.join(line) for line in chars)
    return _MAIN_BLOCK_RE.sub("", result)


# -- AST function extraction --------------------------------------------------

def _is_excluded(name: str) -> bool:
    """Return True if this function name should never be flagged."""
    if name.startswith("__") and name.endswith("__"):
        return True
    if name in EXCLUDED_NAMES:
        return True
    return False


def _has_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function has any decorator."""
    return len(node.decorator_list) > 0


def _extract_functions(py_file: Path) -> list[tuple[str, int]]:
    """
    Parse a .py file with AST and return (function_name, line_number) for each
    FunctionDef / AsyncFunctionDef that is not excluded and has no decorators.
    """
    try:
        source = py_file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        logger.info("Skipped %s: SyntaxError during parse", py_file)
        return []

    results: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_excluded(node.name):
                continue
            if _has_decorator(node):
                continue
            results.append((node.name, node.lineno))
    return results


# -- Reference counting -------------------------------------------------------

def _count_references_in_corpus(func_name: str, corpus: str) -> int:
    """
    Count how many times func_name appears as a word-bounded identifier
    in the corpus (docstrings and comments already stripped).

    Counts ALL occurrences including `def func_name(` lines.
    """
    pattern = re.compile(rf"\b{re.escape(func_name)}\b")
    return len(pattern.findall(corpus))


def _count_def_lines(func_name: str, corpus: str) -> int:
    """
    Count definition lines (def func_name / async def func_name) in corpus.
    """
    pattern = re.compile(
        rf"\basync\s+def\s+{re.escape(func_name)}\b"
        rf"|\bdef\s+{re.escape(func_name)}\b"
    )
    return len(pattern.findall(corpus))


# -- Branch-level check (audit pipeline entry) --------------------------------

def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """
    Check a branch for unused function definitions.

    Scans all .py files, builds a text corpus, extracts function definitions
    via AST, and flags any function whose name appears only in its own
    definition (no call references elsewhere).

    Args:
        branch_path: Path to branch root directory.
        bypass_rules: Optional list of bypass rules from .seedgo/bypass.json.

    Returns:
        dict with keys: passed, score, checks, standard.
    """
    branch = Path(branch_path)

    # Check if entire standard is bypassed
    if is_bypassed(branch_path, "unused_function", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "score": 100,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "standard": "UNUSED_FUNCTION",
        }

    # Phase 1: Collect all .py files
    py_files = _collect_python_files(branch)
    if not py_files:
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "unused_function"},
        )
        return {
            "passed": True,
            "score": 100,
            "checks": [
                {
                    "name": "Unused functions",
                    "passed": True,
                    "message": "No .py files found in branch",
                }
            ],
            "standard": "UNUSED_FUNCTION",
        }

    # Phase 2: Build cleaned text corpus from all files
    file_sources: dict[Path, str] = {}
    for py_file in py_files:
        try:
            raw = py_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            logger.info("Cannot read %s for unused function analysis", py_file)
            continue
        file_sources[py_file] = _strip_non_code(raw)

    corpus = "\n".join(file_sources.values())

    # Phase 3: Extract function definitions from all files
    all_functions: list[tuple[str, int, Path]] = []
    for py_file in py_files:
        for func_name, lineno in _extract_functions(py_file):
            all_functions.append((func_name, lineno, py_file))

    total_functions = len(all_functions)

    if total_functions == 0:
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "unused_function"},
        )
        return {
            "passed": True,
            "score": 100,
            "checks": [
                {
                    "name": "Unused functions",
                    "passed": True,
                    "message": "No eligible functions found",
                }
            ],
            "standard": "UNUSED_FUNCTION",
        }

    # Phase 4: For each function, check if it has references beyond its definition
    unused_functions: list[dict] = []

    for func_name, lineno, py_file in all_functions:
        # Check bypass at file+line level
        if is_bypassed(str(py_file), "unused_function", lineno, bypass_rules):
            continue

        total_refs = _count_references_in_corpus(func_name, corpus)
        def_count = _count_def_lines(func_name, corpus)
        call_refs = total_refs - def_count

        if call_refs <= 0:
            try:
                rel_path = py_file.relative_to(branch)
            except ValueError:
                logger.info("File %s not relative to branch, using full path", py_file)
                rel_path = py_file
            unused_functions.append({
                "name": func_name,
                "file": str(rel_path),
                "line": lineno,
            })

    # Score: clean_functions / total_functions * 100
    clean_count = total_functions - len(unused_functions)
    score = int(clean_count / total_functions * 100) if total_functions > 0 else 100
    passed = score >= 75

    # Build check entry
    if unused_functions:
        # Build a summary of unused functions (cap at 15 for readability)
        details = [
            f"  {uf['name']} ({uf['file']}:{uf['line']})"
            for uf in unused_functions[:15]
        ]
        if len(unused_functions) > 15:
            details.append(f"  ... and {len(unused_functions) - 15} more")
        detail_text = "\n".join(details)

        checks = [
            {
                "name": "Unused functions",
                "passed": passed,
                "message": (
                    f"{len(unused_functions)} unused out of {total_functions} "
                    f"functions ({score}% clean)\n{detail_text}"
                ),
                "unused": unused_functions,
            }
        ]
    else:
        checks = [
            {
                "name": "Unused functions",
                "passed": True,
                "message": f"All {total_functions} functions are referenced",
            }
        ]

    json_handler.log_operation(
        "check_completed",
        {
            "branch": branch_path,
            "score": score,
            "standard": "unused_function",
            "total_functions": total_functions,
            "unused_count": len(unused_functions),
        },
    )

    return {
        "passed": passed,
        "score": score,
        "checks": checks,
        "standard": "UNUSED_FUNCTION",
    }
