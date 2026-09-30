# =================== AIPass ====================
# Name: duplicate_test_check.py
# Description: Duplicate Test Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Duplicate Test Standards Checker Handler

Crack class B from the 2026-09-22 eyes-on review of @backup's tests: a test
that adds nothing, because another test in the same file already asserts
everything it asserts. It doubles the maintenance and the runtime and it
widens no net. The reviewers found 24 of them across nine files.

TWO SHAPES, BOTH MECHANICAL, BOTH ON ONE CHECK:

  B1 CLONE -- two tests whose bodies are the same statements, docstring
     dropped. The name differs and nothing else does.
  B2 SUBSUMED -- every statement of X also appears in Y, and the statements Y
     adds beyond X are only asserts or bindings that call nothing. The
     restriction on Y's extras is the whole rule. Without it,
     ``test_floor_applies_with_no_backupignore`` (no .backupignore at all)
     reads as subsumed by ``test_floor_applies_when_the_file_never_names_tmp``
     (a .backupignore that omits tmp) -- but the second adds a
     ``write_text``, and a statement that changes the world makes it a
     DIFFERENT PRECONDITION, not a superset. Both reviewers called that pair
     SOUND. A binding like ``ignore = project / ".backupignore"`` changes
     nothing and does not break the reading.

WHAT THIS RULE HONESTLY DOES NOT SEE, stated first because it is the headline
number and it reorders the brief's priority list:

  OF @BACKUP'S 24 DUPLICATE ROWS, THIS CHECKER CONVICTS TWO. The other 22 are
  SEMANTIC duplication -- the same claim in a different spelling -- and no
  shape rule reaches them. ``test_drive_pipeline.py:783`` and
  ``test_drive_mocked.py:49`` pin the identical behaviour with ``[]`` versus
  ``drive_sync.PRIMARY_COMMAND``, ``capsys.readouterr().out`` versus a tuple
  unpack, and one extra ``assert err == ""``. A reader sees one test twice;
  an AST sees two different programs.

  The two it does convict are both confirmed rows and it invents none:
  ``test_cli_routing.py:250`` ("identical claim to line 163") as SUBSUMED, and
  ``test_dead_cwd_imports.py:828`` ("line-for-line the same assertion as 469")
  as a CLONE.

  That is the tuning answer for the owner: B is not the second-richest class
  by evidence yield. It is a cheap, zero-false-positive rule that catches the
  literal copies, and the reviewers' 24 need a judgement layer this cannot be.

ONE FILE, NOT THE BRANCH. Cross-file duplication is real and measured -- 21
files, 22 exact clones fleet-wide, and @backup's six drive_pipeline /
drive_mocked pairs are the kind of thing it would name. It is left out
because the verdict would have to be reported against one of two files and
this lane hands the checker one path at a time. It wants a branch-level lane;
the number is in the docs page so the owner can ask for one.

CHECK FIRST, measured 2026-09-22 over the fleet's 559 test files:

  * 59 files convicted, 92 hits, 6.8s -- 57 clones and 35 subsumed. Top three:
    @api 8 files, @seedgo 8, @trigger 6. The worst single file is @devpulse's
    ``test_git_gate.py`` at 6.
  * A widened B2 that accepts ANY extra statement in Y finds 130 files and
    204 hits, and convicts the SOUND pair above. That extra yield is bought
    with a false conviction rate this measurement cannot bound, so the narrow
    form ships and the wide number is reported.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: if every statement of your test
already appears, verbatim, in another test in the same file, and that other
test's only additions are asserts, your test excludes no failure the other
does not already exclude. There is no threshold and nothing to tune.
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "DUPLICATE_TEST"
STANDARD_KEY = "duplicate_test"

#: Prefix that makes a function a test, which is the only unit this rule judges.
TEST_PREFIX = "test_"

CLONE = "is the same test as"
SUBSUMED = "asserts nothing that is not already asserted by"

CURE = "delete it, or widen it until it excludes a failure the other does not"


def _body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> List[ast.stmt]:
    """A function's statements with the docstring dropped.

    Two tests that differ only in their prose are the same test. The prose is
    still worth having; it is just not a second pin.
    """
    statements = list(function.body)
    first = statements[0] if statements else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return statements[1:]
    return statements


def _shape(statement: ast.stmt) -> str:
    """One statement as position-free text: formatting drops out, meaning does not.

    ``ast.dump`` omits ``lineno`` and ``col_offset`` unless asked for them, so
    the dump alone already ignores line breaks, indentation and comments while
    every identifier and every constant survives. Constants are KEPT on
    purpose: ``*.log`` and ``*.txt`` are two different claims about the
    product, and a rule that blanked them convicted 345 files with 2,415 hits
    fleet-wide. An earlier cut round-tripped through ``unparse`` and ``parse``
    first, which found the identical duplicates and cost 7.8s over the fleet.
    """
    return ast.dump(statement)


def _harmless(statement: ast.stmt) -> bool:
    """Whether a statement Y adds beyond X leaves the world exactly as it was.

    An assert reads. A binding whose value calls nothing reads. Anything else
    -- a bare call, a ``with``, a loop -- may have built the precondition that
    makes Y a different test rather than a bigger one.
    """
    if isinstance(statement, ast.Assert):
        return True
    if isinstance(statement, (ast.Assign, ast.AnnAssign)):
        value = statement.value
        return value is not None and not any(isinstance(n, ast.Call) for n in ast.walk(value))
    return False


def _tests(tree: ast.Module) -> List[Tuple[int, str, Dict[str, ast.stmt]]]:
    """(line, name, statements by shape) for every test with a body in this file."""
    found: List[Tuple[int, str, Dict[str, ast.stmt]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith(TEST_PREFIX):
            continue
        statements = {_shape(s): s for s in _body(node)}
        if statements:
            found.append((node.lineno, node.name, statements))
    return found


def _clones(tests: List[Tuple[int, str, Dict[str, ast.stmt]]]) -> List[Tuple[int, str, str, str]]:
    """B1: tests whose statement sets are equal. The later copy is the finding."""
    groups: Dict[Tuple[str, ...], List[Tuple[int, str]]] = {}
    for line, name, statements in tests:
        groups.setdefault(tuple(sorted(statements)), []).append((line, name))
    findings: List[Tuple[int, str, str, str]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        # The FIRST by line is the original; every later one is the copy. Stable
        # under an edit anywhere else in the file, which a "shortest" rule is not.
        original = min(members)[1]
        findings.extend((line, name, CLONE, original) for line, name in sorted(members)[1:])
    return findings


def _subsumed(tests: List[Tuple[int, str, Dict[str, ast.stmt]]], claimed: Set[str]) -> List[Tuple[int, str, str, str]]:
    """B2: tests wholly contained in another whose extras change no world."""
    findings: List[Tuple[int, str, str, str]] = []
    for line, name, statements in tests:
        if name in claimed:
            continue
        for _other_line, other, bigger in tests:
            if other == name or not set(statements) < set(bigger):
                continue
            if all(_harmless(bigger[shape]) for shape in set(bigger) - set(statements)):
                findings.append((line, name, SUBSUMED, other))
                break
    return findings


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[duplicate_test] Unparseable, nothing scanned: %s", exc)
        return None


def scan(source: str) -> List[Tuple[int, str, str, str]]:
    """(line, test, relation, the other test) for each duplicate in this file."""
    tree = _parse(source)
    if tree is None:
        return []
    tests = _tests(tree)
    clones = _clones(tests)
    # A clone is already the strongest reading. Charging it again as subsumed
    # would print the same test twice under two names for one defect.
    subsumed = _subsumed(tests, {name for _line, name, _rel, _other in clones})
    return sorted(clones + subsumed)


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[duplicate_test] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Duplicate test", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for tests another test in the same file already covers.

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

    findings = scan(source)
    if not findings:
        return _result(True, _one_check(True, "Every test here asserts something no other test does"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per test would show the first
    # and hide the rest behind a count.
    detail = "\n".join(
        f"{path.name}:{line} {name} {relation} {other} - {CURE}" for line, name, relation, other in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
