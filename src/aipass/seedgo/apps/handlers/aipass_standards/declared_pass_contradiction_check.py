# =================== AIPass ====================
# Name: declared_pass_contradiction_check.py
# Description: Declared Pass Contradiction Standards Checker Handler
# Version: 1.1.1
# Created: 2026-09-23
# Modified: 2026-10-24
# =============================================

"""Declared Pass Contradiction Standards Checker Handler

Reference: declared_pass_contradiction.md
"""

from functools import partial
import ast
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import in_skipped_dir
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse, read_text, result

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"
READS_BRANCH = True

STANDARD = "DECLARED_PASS_CONTRADICTION"
STANDARD_KEY = "declared_pass_contradiction"

#: The declared-pass line test template v1 item 4 asks every test file to carry.
DECLARED = re.compile(r"#\s*seedgo:\s*no-test-needed\(([\w-]+)\)\s*(?:[-–—]+)?\s*(.*)")

#: The category whose promise is about a VALUE, and so the one a literal can contradict.
CONSTANT = "constant"

#: A token is a symbol, not prose, when it is UPPER_CASE or snake_case.
UPPER = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]{3,})\b")
SNAKE = re.compile(r"\b(_?[a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")

DOTTED = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")

ELSEWHERE = "test_"

CURE_PINNED = "assert the constant by name, or drop the line that declares it untested"
CURE_ABSENT = "name the symbol that exists, or drop the line"


_parse = partial(parse, tag="declared_pass_contradiction")


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

    The text answers "does this name exist": an env-var string, an annotated field or a
    path segment is only visible there. SOURCE_SKIP_DIRS are not apps/.
    """
    values: Dict[str, object] = {}
    chunks: List[str] = []
    apps = branch_root / "apps"
    for path in sorted(apps.rglob("*.py")):
        if in_skipped_dir(path, apps):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.info("[declared_pass_contradiction] Cannot read %s: %s", path, exc)
            continue
        chunks.append(source)
        tree = _parse(source, str(path))
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


_read = partial(read_text, tag="declared_pass_contradiction", errors="ignore")
_result = partial(result, standard=STANDARD)


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
    """Check a test file's declared pass against what the file actually does."""
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
    # check and appends "(+N more)", so one check per declaration would hide the rest.
    detail = "\n".join(f"{path.name}:{line} declares {name} needs no test, but {why}" for line, name, why in findings)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
