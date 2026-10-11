# =================== AIPass ====================
# Name: accepted_and_never_used_parameter_check.py
# Description: Accepted And Never Used Parameter Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""
Accepted And Never Used Parameter Standards Checker Handler

Crack class M from the 2026-09-22 eyes-on review. A product function accepts a
parameter and no path in its body ever reads it. The caller computes a value,
hands it over, and it goes nowhere.

``backup/apps/handlers/cleanup/mirror.py:92`` is the specimen and the shape at
its worst::

    def cleanup_deleted_files(backup_path, source_dir, should_ignore, result, dry_run=False):
        \"\"\"...
        should_ignore: Callable(Path) -> bool for ignore check.
        \"\"\"

``should_ignore`` is documented, accepted, and never called. At the other end,
``copy/snapshot.py:93`` builds ``lambda p: _should_ignore_for_cleanup(p, ...)``
to pass in. **Those are not two defects, they are one**: the caller builds a
predicate, the callee drops it, and the mirror cleanup ignores nothing. The
verdict belongs on the accepting side, which is where the cure lives.

WHAT IT IS NOT: this is not tidiness. A dropped parameter is a promise in the
signature that the body does not keep, so every caller reasons about behaviour
that never happens. The docstring above is the proof -- it describes a contract
the function never honours.

HOW YOU TELL A PROTOCOL, which is the question the dispatch asked. A signature
is only the product's to change if the product is the one calling it. Four
shapes are acquitted, and all four say "somebody else owns this shape":

  THE BRANCH NEVER CALLS IT. ``pytest_runtest_logfinish(nodeid, location)`` is
  dictated by pytest's hookspec; ``handle_stop(hook_data)`` is dispatched by the
  bridge under its name. Nothing in the branch calls either, so nothing in the
  branch may narrow them. Whether such a function should exist at all is
  ``unused_function``'s verdict, not this one's.

  THE NAME IS HANDED OFF AS A VALUE. A bare mention -- not a call, not its own
  ``def`` line -- means the function was passed to something that will call it:
  ``signal.signal(signal.SIGINT, signal_handler)``, or a dispatch table. The
  consumer fixed the arity.

  IT IS A FALLBACK FOR AN IMPORT THAT FAILED. A ``def`` inside an
  ``except ImportError`` handler stands in for the real module and must match
  it. @trigger's ``registry_should_dispatch(fingerprint)`` returns ``True``
  without reading ``fingerprint`` **because that is what a no-op shim does**.

  THE NAME IS DEFINED MORE THAN ONCE IN THE BRANCH. Two defs of one name are a
  shared shape with two implementations; one of them may legitimately ignore
  what the other needs.

Plus the ordinary exemptions: ``self`` and ``cls``, ``*args`` and ``**kwargs``
(never named, so never judged), dunders, a decorated function (the decorator
may read the signature), a stub body (``pass``, ``...``,
``raise NotImplementedError``), and any parameter whose name starts with ``_``,
which is Python's own way of writing "accepted and deliberately ignored".

CHECK FIRST, measured 2026-09-23 over the fleet's apps/ trees. The dispatch's
own first cut was 83 files and 157 hits; the acquittals above take it to the
numbers in the docs page, and the gap is protocol shapes, not tuning.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: reading the parameter once anywhere in
the body clears it, and that reading is the whole point. There is no threshold
and nothing to tune -- the cure is to use it, forward it, or drop it.
"""

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

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

STANDARD = "ACCEPTED_AND_NEVER_USED_PARAMETER"
STANDARD_KEY = "accepted_and_never_used_parameter"

#: The product tree this rule reads, and the only one it judges.
PRODUCT_DIR = "apps"

#: Directories that are not live product code.
SKIP_PARTS = frozenset({".venv", "__pycache__", "node_modules", ".git", ".archive", "tests", "json_templates"})

#: Bound by the call, never by the caller.
BOUND = frozenset({"self", "cls"})

#: The exceptions whose handler holds a stand-in for a module that would not import.
IMPORT_FAILURES = frozenset({"ImportError", "ModuleNotFoundError"})

#: A body that only declares a shape raises this and nothing else.
STUB_RAISE = "NotImplementedError"

#: `def __init__` and friends: the interpreter fixes those signatures.
DUNDER = re.compile(r"^__\w+__$")

#: A call site in the branch text, which also matches the `def name(` line.
CALL = re.compile(r"\b(\w+)\s*\(")

#: Every identifier-shaped token, so a bare mention can be told from a call.
TOKEN = re.compile(r"\b(\w+)\b")

#: A definition line, subtracted from both counts above.
DEFINITION = re.compile(r"\bdef\s+(\w+)")

CURE = "read the parameter, forward it, or drop it from the signature"

#: Either def node, which every helper below accepts.
FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef)


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[accepted_and_never_used_parameter] Unparseable, nothing scanned: %s", exc)
        return None


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

    Not tidiness -- correctness. The corpus is read as TEXT, so a name written
    in prose counts as a mention. This very checker's docstring says
    ``pytest_runtest_logfinish(nodeid, location)``, and that one sentence made
    the branch look like it called pytest's hook, which convicted both of its
    parameters. ``unused_function`` strips its corpus the same way for the same
    reason.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError) as exc:
        # An IndentationError is a SyntaxError, not a TokenError, and a file caught
        # mid-save raises it. Degrade to the raw text rather than losing the branch.
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
    """Every local name this file binds by importing it.

    Told apart from a hand-off deliberately. ``from mirror import
    cleanup_deleted_files`` mentions the name without calling it, which reads as
    "passed to somebody else" unless imports are subtracted -- and that one
    miscount acquitted the specimen.
    """
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

    All three are counted over the branch's whole ``apps/`` text, because all
    three answer the same question -- who owns this signature -- and none of
    them can be answered from one file.
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
    # value. An IMPORT is not a hand-off -- it only makes the name callable -- and
    # counting it as one acquitted the mirror.py specimen this rule was built for.
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
    """Every NAMED parameter this function accepts, minus the ones nobody chose.

    ``*args`` and ``**kwargs`` are absent by construction -- they are not named
    parameters, and a body that ignores them is forwarding a shape, not
    dropping a value. A leading underscore is Python's own way of writing
    "accepted and deliberately ignored", and is taken at its word.
    """
    args = node.args
    named = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    return [arg.arg for arg in named if arg.arg not in BOUND and not arg.arg.startswith("_")]


def names_read(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Set[str]:
    """Every name the body reads.

    A docstring is an ``ast.Constant``, never an ``ast.Name``, so naming a
    parameter in the prose does not clear it -- which is the mirror.py defect
    exactly: documented, accepted, never called.

    ``ast.Name`` is the whole test, and deliberately. A first cut also collected
    ``ast.keyword.arg``, on the theory that forwarding by keyword counts as
    reading -- but ``inner.arg`` is the CALLEE's parameter name, not this
    function's. ``helper(should_ignore=other)`` would then have cleared a
    ``should_ignore`` this body never touched. Forwarding the real value is
    already an ``ast.Name`` on the right-hand side, so nothing was lost.
    """
    return {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}


def import_fallbacks(tree: ast.Module) -> Set[int]:
    """The id() of every function defined inside an ``except ImportError``.

    A shim for a module that would not import must match the signature of the
    thing it stands in for, so the branch does not own its shape.
    """
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


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[accepted_and_never_used_parameter] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


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
    """Check a product file for parameters its own bodies never read.

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

    branch_root = _branch_root(path)
    if branch_root is None:
        # Who owns a signature cannot be answered without the branch, and a
        # verdict guessed from one file would convict every callback in it.
        return _result(True, _one_check(True, "No branch root above this file, nothing judged"), 100)

    findings, acquitted = scan(source, branch_facts(branch_root))
    if not findings:
        return _result(True, _one_check(True, _clean_message(acquitted)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per parameter would show the
    # first and hide the rest behind a count.
    detail = "\n".join(
        f"{path.name}:{line} {func} accepts {name} and never reads it - {CURE}" for line, func, name in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
