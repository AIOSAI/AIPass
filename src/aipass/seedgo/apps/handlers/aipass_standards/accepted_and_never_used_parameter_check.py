# =================== AIPass ====================
# Name: accepted_and_never_used_parameter_check.py
# Description: Accepted And Never Used Parameter Standards Checker Handler
# Version: 1.0.1
# Created: 2026-09-23
# Modified: 2026-10-24
# =============================================

"""Accepted And Never Used Parameter Standards Checker Handler

Reference: accepted_and_never_used_parameter.md
"""

from functools import partial
import ast
import io
import re
import tokenize
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse, read_text, result

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"
READS_BRANCH = True

STANDARD = "ACCEPTED_AND_NEVER_USED_PARAMETER"
STANDARD_KEY = "accepted_and_never_used_parameter"

PRODUCT_DIR = "apps"

SKIP_PARTS = frozenset({".venv", "__pycache__", "node_modules", ".git", ".archive", "tests", "json_templates"})

BOUND = frozenset({"self", "cls"})

IMPORT_FAILURES = frozenset({"ImportError", "ModuleNotFoundError"})

STUB_RAISE = "NotImplementedError"

DUNDER = re.compile(r"^__\w+__$")

#: A call site in the branch text, which also matches the `def name(` line.
CALL = re.compile(r"\b(\w+)\s*\(")

TOKEN = re.compile(r"\b(\w+)\b")

DEFINITION = re.compile(r"\bdef\s+(\w+)")

CURE = "read the parameter, forward it, or drop it from the signature"

FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef)


_parse = partial(parse, tag="accepted_and_never_used_parameter")


def _branch_root(path: Path) -> Path | None:
    """The branch a product file lives in: the parent of its ``apps/`` directory."""
    for parent in path.resolve().parents:
        if (parent / PRODUCT_DIR).is_dir() and (parent / ".trinity").is_dir():
            return parent
    return None


def product_files(branch_root: Path) -> List[Path]:
    """Every live ``apps/`` source file in this branch."""
    return sorted(
        path
        for path in (branch_root / PRODUCT_DIR).rglob("*.py")
        if not any(part in SKIP_PARTS for part in path.parts) and "(disabled)" not in path.name
    )


def code_only(source: str) -> str:
    """The file with every string and comment blanked out.

    The corpus is read as TEXT, so a name written in prose would count as a mention;
    ``unused_function`` strips its corpus the same way for the same reason.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError) as exc:
        # An IndentationError (a file caught mid-save) is a SyntaxError: degrade to raw text.
        logger.info("[accepted_and_never_used_parameter] Tokenizer failed, raw corpus: %s", exc)
        return source

    rows = [list(line) for line in source.split("\n")]
    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row - 1, min(end_row, len(rows))):
            first = start_col if row == start_row - 1 else 0
            last = end_col if row == end_row - 1 else len(rows[row])
            for col in range(first, min(last, len(rows[row]))):
                rows[row][col] = " "
    return "\n".join("".join(row) for row in rows)


def imported_names(source: str) -> List[str]:
    """Every local name this file binds by importing it."""
    tree = _parse(source)
    if tree is None:
        return []
    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.extend(alias.asname or alias.name.split(".")[0] for alias in node.names)
    return names


@lru_cache(maxsize=64)
def branch_facts(branch_root: Path) -> Tuple[FrozenSet[str], FrozenSet[str], FrozenSet[str]]:
    """(handed off as a value, called by this branch, defined more than once).

    Counted over the branch's whole ``apps/`` text: who owns a signature cannot be
    answered from one file.
    """
    chunks: List[str] = []
    bound: Dict[str, int] = {}
    for path in product_files(branch_root):
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.info("[accepted_and_never_used_parameter] Cannot read %s: %s", path, exc)
            continue
        chunks.append(code_only(source))
        for name in imported_names(source):
            bound[name] = bound.get(name, 0) + 1
    corpus = "\n".join(chunks)

    calls = _tally(CALL, corpus)
    tokens = _tally(TOKEN, corpus)
    defs = _tally(DEFINITION, corpus)

    # A `def name(` line matches TOKEN and CALL once each, so those two cancel and
    # what is left over is a BARE reference: the name handed to somebody else as a
    # value. An IMPORT is not a hand-off: it only makes the name callable.
    handed = {name for name, count in tokens.items() if count - calls.get(name, 0) - bound.get(name, 0) > 0}
    called = {name for name, count in calls.items() if count - defs.get(name, 0) > 0}
    twice = {name for name, count in defs.items() if count > 1}
    return frozenset(handed), frozenset(called), frozenset(twice)


def _tally(pattern: re.Pattern, corpus: str) -> Dict[str, int]:
    """How many times each name the pattern captures appears in the text."""
    counts: Dict[str, int] = {}
    for name in pattern.findall(corpus):
        counts[name] = counts.get(name, 0) + 1
    return counts


def is_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the body only declares a shape: ``pass``, ``...`` or a raise."""
    body = [stmt for stmt in node.body if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))]
    if not body:
        return True
    if len(body) > 1:
        return False
    only = body[0]
    if isinstance(only, ast.Pass):
        return True
    if isinstance(only, ast.Raise) and only.exc is not None:
        raised = only.exc.func if isinstance(only.exc, ast.Call) else only.exc
        return isinstance(raised, ast.Name) and raised.id == STUB_RAISE
    return False


def parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> List[str]:
    """Every NAMED parameter this function accepts, minus the ones nobody chose."""
    args = node.args
    named = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    return [arg.arg for arg in named if arg.arg not in BOUND and not arg.arg.startswith("_")]


def names_read(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Set[str]:
    """Every name the body reads.

    A docstring is an ``ast.Constant``, never an ``ast.Name``, so naming a parameter in
    the prose does not clear it.

    ``ast.Name`` is the whole test: ``ast.keyword.arg`` is the CALLEE's parameter name, so
    ``helper(should_ignore=other)`` must not clear this body's ``should_ignore``.
    """
    return {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}


def import_fallbacks(tree: ast.Module) -> Set[int]:
    """The id() of every function defined inside an ``except ImportError``."""
    found: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not _catches_import(node):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.add(id(inner))
    return found


def _catches_import(handler: ast.ExceptHandler) -> bool:
    """Whether this handler is the one that runs when an import failed."""
    caught = handler.type
    if caught is None:
        return False
    parts = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(isinstance(part, ast.Name) and part.id in IMPORT_FAILURES for part in parts)


def scan(source: str, facts: Tuple[FrozenSet[str], FrozenSet[str], FrozenSet[str]]) -> Tuple[List[Tuple], int]:
    """((line, function, parameter) scored, how many parameters a shape acquitted)."""
    tree = _parse(source)
    if tree is None:
        return [], 0

    handed, called, twice = facts
    fallbacks = import_fallbacks(tree)
    scored: List[Tuple[int, str, str]] = []
    acquitted = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        accepted = parameters(node)
        if not accepted:
            continue
        owned_elsewhere = node.name in handed or node.name in twice or node.name not in called
        if DUNDER.match(node.name) or node.decorator_list or is_stub(node) or owned_elsewhere:
            acquitted += len(accepted)
            continue
        if id(node) in fallbacks:
            acquitted += len(accepted)
            continue
        read = names_read(node)
        scored.extend((node.lineno, node.name, name) for name in accepted if name not in read)
    return sorted(scored), acquitted


_read = partial(read_text, tag="accepted_and_never_used_parameter", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Accepted and never used parameter", "passed": passed, "message": message}]


def _clean_message(acquitted: int) -> str:
    """The passing message, carrying the unjudged count without a verdict."""
    if not acquitted:
        return "Every parameter here is read"
    shape = "parameter sits" if acquitted == 1 else "parameters sit"
    return f"Every parameter here is read ({acquitted} {shape} on a signature somebody else owns)"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a product file for parameters its own bodies never read."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    branch_root = _branch_root(path)
    if branch_root is None:
        # Who owns a signature cannot be answered without the branch.
        return _result(True, _one_check(True, "No branch root above this file, nothing judged"), 100)

    findings, acquitted = scan(source, branch_facts(branch_root))
    if not findings:
        return _result(True, _one_check(True, _clean_message(acquitted)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per parameter would hide the rest.
    detail = "\n".join(
        f"{path.name}:{line} {func} accepts {name} and never reads it - {CURE}" for line, func, name in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
