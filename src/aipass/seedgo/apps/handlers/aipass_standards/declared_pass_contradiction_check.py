# =================== AIPass ====================
# Name: declared_pass_contradiction_check.py
# Description: Declared Pass Contradiction Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""
Declared Pass Contradiction Standards Checker Handler

Crack class H from the 2026-09-22 eyes-on review of @backup's tests. A test
file's declared pass -- the ``# seedgo: no-test-needed(X) -- prose`` block that
test template v1 item 4 asks for -- is a promise about what this file does NOT
cover. The promise is worth exactly as much as its accuracy, and two ways of
breaking it are mechanical.

  THE DECLARATION IS CONTRADICTED. The file says a constant's value needs no
  test, and then asserts that value as a literal. ``TRACKER_FILENAME``'s string
  is declared untested in ``test_drive_pipeline.py`` while three asserts pin
  ``"drive_tracker.json"``.

  THE DECLARATION NAMES NOTHING. ``test_ceiling_guard.py`` declares
  ``DEFAULT_MAX_SIZE_GB``; the constant is ``DEFAULT_MAX_TOTAL_GB``. A promise
  about a symbol that does not exist covers nothing at all, and the real
  constant stays uncovered behind it.

THE JUDGEMENT THIS RULE MAKES, and it is the whole rule: USING a declared
constant BY NAME is consistent with declaring it untested. ``assert CURE in
message`` survives any change to ``CURE``'s text -- it pins the wiring, not the
prose. ASSERTING ITS VALUE as a literal does not: ``assert x == "drive_tracker
.json"`` pins exactly the thing the file said it would not. So the rule reads
the constant's value out of the branch's ``apps/`` and looks for that literal
inside an assert in a test body. A bare mention of the name is never convicted.

SEARCH THE SOURCE TEXT FOR AN ABSENT NAME, NOT THE AST's NAMES. A declared
symbol can be an environment variable (a string, never an identifier), an
annotated dataclass field, or a directory segment inside a path. Collecting
def/class/Name/Attribute nodes missed all three and convicted 86 live symbols;
a word-boundary search of ``apps/`` leaves 3, and all three are real.

CHECK FIRST, measured 2026-09-23 over the fleet's 572 test files:

  * 37 files carry a declared pass at all, 137 lines between them.
  * 7 files, 8 scored: 5 contradicted constants, 3 absent names.
  * Reported with a count and charged to nobody, 106 in all: 39 lines that
    name no symbol (``mock call arguments and assertion shapes`` is prose, and
    prose is a legitimate declaration) and 67 dotted stdlib names
    (``Path.resolve``, ``os.scandir``), where a test's incidental use of the
    call is indistinguishable from testing it. Plus 3 declared LIBRARIES whose call
    feeds an assert. That last one is not scored on purpose --
    ``no_product_call`` already convicts ``test_ignore_pathspec.py:46``, the
    one case where the library really is the subject, and the other two files
    score 100 there, which proves their library call is the test's reading
    tool rather than its subject. A second verdict on the same defect sends
    the owner to the same place twice.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: both scored forms are contradictions
between two statements in the same file. There is no threshold and nothing to
tune; the cure is to fix the declaration or drop the assert.
"""

import ast
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "DECLARED_PASS_CONTRADICTION"
STANDARD_KEY = "declared_pass_contradiction"

#: The declared-pass line test template v1 item 4 asks every test file to carry.
DECLARED = re.compile(r"#\s*seedgo:\s*no-test-needed\(([\w-]+)\)\s*(?:[-–—]+)?\s*(.*)")

#: The category whose promise is about a VALUE, and so the one a literal can contradict.
CONSTANT = "constant"

#: A token is a symbol, not prose, when it is UPPER_CASE or snake_case.
UPPER = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]{3,})\b")
SNAKE = re.compile(r"\b(_?[a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")

#: A dotted name in the prose: reported, never scored.
DOTTED = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")

#: Covered-elsewhere references name a test file, not a symbol under test.
ELSEWHERE = "test_"

CURE_PINNED = "assert the constant by name, or drop the line that declares it untested"
CURE_ABSENT = "name the symbol that exists, or drop the line"


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[declared_pass_contradiction] Unparseable, nothing scanned: %s", exc)
        return None


def declarations(source: str) -> List[Tuple[int, str, str]]:
    """(line, category, prose) for every declared-pass line in this file."""
    found: List[Tuple[int, str, str]] = []
    for line, text in enumerate(source.splitlines(), 1):
        match = DECLARED.match(text.strip())
        if match:
            found.append((line, match.group(1), match.group(2)))
    return found


def symbols(prose: str) -> Set[str]:
    """The identifier-shaped tokens in a declared-pass line's prose.

    A covered-elsewhere reference (``tests/test_bypass.py``) names the file that
    does the covering, which is the declaration working, not failing.
    """
    found = {token for rule in (UPPER, SNAKE) for token in rule.findall(prose)}
    return {token for token in found if not token.startswith(ELSEWHERE)}


def _branch_root(path: Path) -> Path | None:
    """The branch a test file lives in: the parent of its ``tests/`` directory."""
    for parent in path.resolve().parents:
        if (parent / "tests").is_dir() and (parent / "apps").is_dir():
            return parent
    return None


@lru_cache(maxsize=64)
def product_facts(branch_root: Path) -> Tuple[Dict[str, object], str]:
    """(module-level constants and their values, the whole apps/ source text).

    The text is what answers "does this name exist": a name can be an env-var
    string, an annotated field, or a path segment, and only the text sees all
    three.
    """
    values: Dict[str, object] = {}
    chunks: List[str] = []
    for path in sorted((branch_root / "apps").rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.info("[declared_pass_contradiction] Cannot read %s: %s", path, exc)
            continue
        chunks.append(source)
        tree = _parse(source)
        if tree is None:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    values.setdefault(target.id, node.value.value)
    return values, "\n".join(chunks)


def pinned_literals(tree: ast.Module) -> Set[str]:
    """Every string literal that appears inside an assert in a test body."""
    found: Set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(ELSEWHERE)):
            continue
        for statement in ast.walk(node):
            if not isinstance(statement, ast.Assert):
                continue
            for inner in ast.walk(statement):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    found.add(inner.value)
    return found


def _exists(name: str, text: str) -> bool:
    """Whether the branch's product source mentions this name at all."""
    return re.search(r"\b" + re.escape(name) + r"\b", text) is not None


def scan(source: str, branch_root: Path | None) -> Tuple[List[Tuple[int, str, str]], int]:
    """((line, name, what is wrong) scored, how many lines were reported not judged)."""
    tree = _parse(source)
    if tree is None:
        return [], 0

    declared = declarations(source)
    if not declared:
        return [], 0

    values, text = product_facts(branch_root) if branch_root else ({}, "")
    literals = pinned_literals(tree)
    scored: List[Tuple[int, str, str]] = []
    reported = 0
    for line, category, prose in declared:
        named = symbols(prose)
        dotted = len(DOTTED.findall(prose))
        reported += dotted
        if not named:
            # Prose-only, and counted ONCE: a line that names a dotted stdlib
            # call is already in the count above, not prose on top of it.
            reported += 0 if dotted else 1
            continue
        for name in sorted(named):
            value = values.get(name)
            if category == CONSTANT and isinstance(value, str) and value and value in literals:
                scored.append((line, name, f"its value {value!r} is asserted as a literal - {CURE_PINNED}"))
            elif branch_root is not None and not _exists(name, text):
                scored.append((line, name, f"names nothing in {branch_root.name}/apps - {CURE_ABSENT}"))
    return sorted(scored), reported


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[declared_pass_contradiction] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Declared pass contradiction", "passed": passed, "message": message}]


def _clean_message(reported: int) -> str:
    """The passing message, carrying the unjudged count without a verdict."""
    if not reported:
        return "Every declared pass here holds"
    shape = "line names" if reported == 1 else "lines name"
    return (
        f"Every declared pass here holds ({reported} {shape} prose or a stdlib call, which a rule cannot tell from use)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file's declared pass against what the file actually does.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard.

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

    findings, reported = scan(source, _branch_root(path))
    if not findings:
        return _result(True, _one_check(True, _clean_message(reported)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per declaration would show the
    # first and hide the rest behind a count.
    detail = "\n".join(f"{path.name}:{line} declares {name} needs no test, but {why}" for line, name, why in findings)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
