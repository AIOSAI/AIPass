# =================== AIPass ====================
# Name: file_top_check.py
# Description: Test File Top Standards Checker Handler
# Version: 1.1.0
# Created: 2026-09-22
# Modified: 2026-09-27
# =============================================

"""
Test File Top Standards Checker Handler

Test template v1, items 5, 6 and 7 -- the top of a test file, in order:

    5. the META header block first, the same block product files carry,
       banner and all -- meta_check's banner rule, not a second copy of it
    6. then the module docstring: ONE line, naming the subject as a path
    7. then the declared pass: what is NOT tested here and what covers it

They are one shape, not three, which is why they are one checker with three
sub-rules -- ``imports`` carries six the same way. The ORDER is half the rule:
a docstring above the header is convicted by sub-rule 5 even though the header
is present, because "top to bottom" is the template's own heading.

CHECK FIRST, 2026-09-22, and this is why the checker exists. Three standards
already read a file's head and NONE of them reaches a test file:

    meta            APPLIES_TO = "production". It validates exactly this block
                    and never sees tests/.
    documentation   APPLIES_TO = "production". Docstrings, same blind spot.
    template        branch_level and ADVISORY: it reads the branch's prompt,
                    README and passport for un-configured stub markers. It has
                    nothing to do with a file's top.

So no line here is charged twice, and items 5 to 7 had no checker at all.

THE BANNER IS meta_check's, IMPORTED, NOT COPIED. The template once said "for
a test file the banner word is META" while ``meta_check`` called META the
LEGACY spelling and AIPass the canonical one; 345 of 579 fleet test files
opened with AIPass. The owner ruled (2026-09-27): AIPass is the banner word for
product and test files alike. So a test file's banner passes exactly when
``meta_check`` would pass it on a product file: its ``META_HEADER`` (AIPass) or
its ``META_HEADER_LEGACY`` (META), the whole line, stripped. One rule in one
place -- if meta_check retires the legacy line, this follows. The 72 squashed
``# ===================AIPASS====================`` banners meta_check refuses,
so this refuses them too, and the message prints the line meta_check wants.

THE FIELDS ARE meta_check's FIVE, not a new list: Name, Description, Version,
Created, Modified. Item 5 says "the same block product files carry", and that
is the block they carry.

conftest.py IS JUDGED ON SUB-RULE 5 ONLY, decided from the template's text.
The numbered items live under the heading "File shape, top to bottom" and the
template's conftest section (C1 to C4) is about which FIXTURES belong there --
it never speaks about a header, a docstring or a declared pass. Item 6 asks for
"one line naming the SUBJECT as a path" and a conftest has no subject: it is
shared setup, not a test of anything. Item 7 asks what is NOT tested HERE, and
a file that contains no tests has nothing to answer. Item 5 has no such
problem: a conftest is a Python file and every Python file in the fleet carries
the block. 21 conftests are in the corpus; 7 of them already open with a header.

Measured 2026-09-22 over 579 fleet test files, before the rule landed:

    META block first         367 (63%)   -- of which 22 use the META banner
    a module docstring       562 (97%)
    exactly one line         223 (39%)
    a declared-pass block      7 ( 1%)   -- all seven in seedgo, all written
                                            by hand for the gold-seal series

The declared pass is the item with no fleet habit at all, and the template says
why it matters: "In the trial this slot is where six tests got dropped: writing
it does the deciding."
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.meta_check import META_HEADER, META_HEADER_LEGACY
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

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

#: The declared pass opens with this sentence in all seven files that have one.
_DECLARED_PASS = re.compile(r"^#\s*The declared pass\b")

#: A marker line inside it. The block may hold none; a malformed one is named.
_MARKER = re.compile(r"^#\s*seedgo:\s*no-test-needed\(([a-z_]+)\)")

#: A path names the subject: a directory, a slash, and a .py file.
_SUBJECT_PATH = re.compile(r"[A-Za-z_][\w.\-]*/[\w./\-]*\.py")

FIX = "see templates/test_template_v1.md items 5 to 7, and tests/test_readme_update.py"


def _header_span(lines: List[str]) -> Tuple[int, int]:
    """(first line, last line) of the leading comment block, 1-indexed.

    (0, 0) when the file does not open with one. Only a block at the very
    top counts: "top to bottom" is the rule, so a header pushed below a
    docstring is not a header that is first.
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
    for index in range(start + 1, min(len(lines), start + 20)):
        if _FOOTER.match(lines[index].strip()) and not _BANNER.match(lines[index].strip()):
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

    16 fleet test files open with a shebang, which is a comment and not code;
    a message that called it code would send its author looking for an import.
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

    Only the docstring-to-declared-pass pair is judged here. A docstring ABOVE
    the header needs no separate rule: ``_header_span`` reads the first
    non-blank line, so a header pushed below anything is not a header that is
    first, and item 5 already says so. A mutant that disabled a check for it
    survived the suite, which is how the dead branch was found.
    """
    if doc_line and pass_line and pass_line < doc_line:
        return ["item 7 declared pass: the block is above the docstring — header, docstring, declared pass"]
    return []


def is_conftest(module_path: str) -> bool:
    """Whether this file is a conftest, which items 6 and 7 do not reach.

    Decided from the template's text, not by taste: item 6 wants "one line
    naming the SUBJECT as a path" and a conftest has no subject, item 7 asks
    what is NOT tested HERE and a conftest holds no tests. Item 5 still binds:
    every Python file in the fleet carries the block.
    """
    return Path(module_path).name == "conftest.py"


def scan(source: str, conftest: bool = False) -> List[str]:
    """Every finding for one test file's top, in template order.

    A file that does not parse yields nothing: ruff already convicts the
    syntax error, and naming a missing docstring in a file Python cannot read
    would send its author to the wrong place.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[file_top] Unparseable, nothing scanned: %s", exc)
        return []

    lines = source.splitlines()
    node = _docstring_node(tree)
    doc_line = node.lineno if node is not None else 0
    pass_line = _declared_pass_line(lines)
    findings = _header_findings(lines, doc_line)
    findings += _order_findings(doc_line, pass_line)
    if not conftest:
        findings += _docstring_findings(tree, doc_line)
        findings += _declared_pass_findings(lines, pass_line)
    return findings


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[file_top] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "File top", "passed": passed, "message": message}]


def _clean_message(conftest: bool) -> str:
    """What a passing file says."""
    if conftest:
        return "The header block is first (items 6 and 7 do not reach a conftest)"
    return "Header, one-line subject docstring, declared pass — in order"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file's top against template v1 items 5, 6 and 7.

    Args:
        module_path: Path to the test file to check.
        bypass_rules: Optional bypass rules, applied per standard and per line.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    conftest = is_conftest(module_path)
    findings = scan(source, conftest=conftest)

    if not findings:
        return _result(True, _one_check(True, _clean_message(conftest)), 100)

    # One line per sub-rule, all inside ONE check rather than one check each --
    # checklist._format_failure prints the FIRST failed check and appends
    # "(+N more)", so three checks would show one sub-rule and hide two, and
    # the dispatch asks that an author see which of the three is missing.
    detail = "\n".join(f"{path.name}: {finding}" for finding in findings) + f"\n{FIX}"

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "findings": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
