# =================== AIPass ====================
# Name: file_top_check.py
# Description: Test File Top Standards Checker Handler
# Version: 1.2.1
# Created: 2026-09-22
# Modified: 2026-10-24
# =============================================

"""Test File Top Standards Checker Handler

Reference: file_top.md
"""

from functools import partial
import ast
import re
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.meta_check import META_HEADER, META_HEADER_LEGACY
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import read_text, result

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "FILE_TOP"
STANDARD_KEY = "file_top"

#: meta_check's banner lines, canonical first. Imported so there is one rule.
_ACCEPTED_BANNERS: Tuple[str, ...] = (META_HEADER, META_HEADER_LEGACY)
_BANNER = re.compile(r"^#\s*=+\s*([A-Za-z]+)\s*=+\s*$")
_FOOTER = re.compile(r"^#\s*=+\s*$")

#: meta_check's own five. Item 5: "the same block product files carry".
_FIELDS: Tuple[str, ...] = ("Name", "Description", "Version", "Created", "Modified")

#: The declared pass block opens with this sentence.
_DECLARED_PASS = re.compile(r"^#\s*The declared pass\b")

#: A marker line inside it. The block may hold none; a malformed one is named.
_MARKER = re.compile(r"^#\s*seedgo:\s*no-test-needed\(([a-z_]+)\)")

_SUBJECT_PATH = re.compile(r"[A-Za-z_][\w.\-]*/[\w./\-]*\.py")

FIX = "see templates/test_template_v1.md items 5 to 7, and tests/test_readme_update.py"


def _header_span(lines: List[str]) -> Tuple[int, int]:
    """(first line, last line) of the leading comment block, 1-indexed.

    (0, 0) when the file does not open with one: a header pushed below a docstring is
    not a header that is first.
    """
    start = 0
    for index, line in enumerate(lines):
        if line.strip():
            start = index
            break
    else:
        return (0, 0)
    if not _BANNER.match(lines[start].strip()):
        return (0, 0)
    # The block ends at its footer or first non-comment line, however long it runs.
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped.startswith("#"):
            break
        if _FOOTER.match(stripped) and not _BANNER.match(stripped):
            return (start + 1, index + 1)
    return (start + 1, start + 1)


def _missing_fields(lines: List[str], first: int, last: int) -> List[str]:
    """Which of the five META fields the block does not carry."""
    body = "\n".join(lines[first - 1 : last])
    return [field for field in _FIELDS if not re.search(rf"^#\s*{field}:\s*\S", body, re.MULTILINE)]


def _docstring_node(tree: ast.Module) -> ast.Expr | None:
    """The module docstring's own node, so its line number can be read."""
    if not tree.body:
        return None
    first = tree.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return first
    return None


def _declared_pass_line(lines: List[str]) -> int:
    """The 1-indexed line the declared-pass block opens on, or 0."""
    for index, line in enumerate(lines):
        if _DECLARED_PASS.match(line.strip()):
            return index + 1
    return 0


def _opener(lines: List[str], doc_line: int) -> str:
    """What the file starts with instead of the header block.

    A shebang is a comment, not code: calling it code sends its author looking for an import.
    """
    if doc_line == 1:
        return "a docstring"
    first = next((line.strip() for line in lines if line.strip()), "")
    if first.startswith("#!"):
        return "a shebang"
    return "code"


def _header_findings(lines: List[str], doc_line: int) -> List[str]:
    """Item 5's message, or nothing when the header is right."""
    first, last = _header_span(lines)
    if not first:
        opener = _opener(lines, doc_line)
        return [f"item 5 META header: the file opens with {opener} — the header block comes first"]
    findings = []
    banner_line = lines[first - 1].strip()
    if banner_line not in _ACCEPTED_BANNERS:
        findings.append(f"item 5 META header: the banner line is `{banner_line}`, not `{META_HEADER}`")
    missing = _missing_fields(lines, first, last)
    if missing:
        findings.append(f"item 5 META header: missing {', '.join(missing)}")
    return findings


def _docstring_findings(tree: ast.Module, doc_line: int) -> List[str]:
    """Item 6's message, or nothing when the docstring is right."""
    text = ast.get_docstring(tree, clean=False)
    if text is None or not doc_line:
        return ["item 6 subject docstring: missing — one line naming the module this file tests"]
    body = text.strip()
    count = len(body.splitlines())
    if count != 1:
        return [f"item 6 subject docstring: {count} lines, not 1 — one line naming the module this file tests"]
    if not _SUBJECT_PATH.search(body):
        return ["item 6 subject docstring: names no path — say which module it tests, as a path"]
    return []


def _declared_pass_findings(lines: List[str], pass_line: int) -> List[str]:
    """Item 7's message, or nothing when the block is there and well formed."""
    if not pass_line:
        return ["item 7 declared pass: missing — what is NOT tested here, and what covers it"]
    findings = []
    for index in range(pass_line, len(lines)):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if not stripped.startswith("#"):
            break
        if not _MARKER.match(stripped):
            findings.append(f"item 7 declared pass: line {index + 1} is not a seedgo: no-test-needed(...) marker")
            break
    return findings


def _order_findings(doc_line: int, pass_line: int) -> List[str]:
    """What is out of order, top to bottom.

    Only the docstring-to-declared-pass pair is judged here: ``_header_span`` reads the
    first non-blank line, so a docstring above the header already fails item 5.
    """
    if doc_line and pass_line and pass_line < doc_line:
        return ["item 7 declared pass: the block is above the docstring — header, docstring, declared pass"]
    return []


def is_conftest(module_path: str) -> bool:
    """Whether this file is a conftest, which items 6 and 7 do not reach."""
    return Path(module_path).name == "conftest.py"


def holds_tests(tree: ast.Module) -> bool:
    """Whether pytest would collect anything here: a top-level ``test*`` function or ``Test*`` class."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            return True
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            return True
    return False


def scan(source: str, conftest: bool = False, excuse_plugin: bool = False) -> List[str]:
    """Every finding for one test file's top, in template order."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        logger.info("[file_top] Unparseable, nothing scanned: %s", exc)
        return []

    lines = source.splitlines()
    node = _docstring_node(tree)
    doc_line = node.lineno if node is not None else 0
    pass_line = _declared_pass_line(lines)
    findings = _header_findings(lines, doc_line)
    findings += _order_findings(doc_line, pass_line)
    if not conftest:
        # excuse_plugin: the per-file lane asks it (check_module); a scan of
        # bare source keeps judging item 6, as every scan-level pin expects.
        if not (excuse_plugin and not holds_tests(tree)):
            findings += _docstring_findings(tree, doc_line)
        findings += _declared_pass_findings(lines, pass_line)
    return findings


_read = partial(read_text, tag="file_top", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "File top", "passed": passed, "message": message}]


def _clean_message(conftest: bool) -> str:
    """What a passing file says."""
    if conftest:
        return "The header block is first (items 6 and 7 do not reach a conftest)"
    return "Header, one-line subject docstring, declared pass — in order"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file's top against template v1 items 5, 6 and 7."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    conftest = is_conftest(module_path)
    findings = scan(source, conftest=conftest, excuse_plugin=True)

    if not findings:
        return _result(True, _one_check(True, _clean_message(conftest)), 100)

    # One line per sub-rule, all inside ONE check: checklist._format_failure prints the
    # FIRST failed check and appends "(+N more)", which would hide two sub-rules.
    detail = "\n".join(f"{path.name}: {finding}" for finding in findings) + f"\n{FIX}"

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "findings": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
