# =================== AIPass ====================
# Name: handlers_check.py
# Description: Handlers Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Handlers Standards Checker Handler

Validates handler compliance with AIPass handler standards.
Checks handler independence, auto-detection pattern, no orchestration.
"""

import ast
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: all Python files
AUDIT_SCOPE = "all_files"
# Applies to production source only: the handler contract (no CLI, no orchestration)
# describes apps/handlers/ code. A test is neither a handler nor a caller of one.
APPLIES_TO = "production"

# Cross-handler/orchestration imports are purely import-statement checks, so a
# violation hiding in a package marker file must not be invisible to the audit
# the way it would be for content checkers (dead code, naming, etc.).
INCLUDE_INIT_FILES = True


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if handler follows handler standards

    Args:
        module_path: Path to Python handler to check
        bypass_rules: Optional list of bypass rules to apply

    Returns:
        dict: {
            'passed': bool,           # Overall pass/fail
            'checks': [               # Individual check results
                {
                    'name': str,      # Check name
                    'passed': bool,   # Pass/fail
                    'message': str,   # Details
                }
            ],
            'score': int,             # 0-100 percentage
            'standard': str           # Standard name
        }
    """
    checks = []
    path = Path(module_path)

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, "handlers", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "HANDLERS",
        }

    # Validate file exists
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "HANDLERS",
        }

    # Read file
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "HANDLERS",
        }

    # Only check files in handlers/ directory
    is_handler = "apps/handlers/" in module_path
    if not is_handler:
        return {
            "passed": True,
            "checks": [{"name": "Handler check", "passed": True, "message": "Not a handler file (skipped)"}],
            "score": 100,
            "standard": "HANDLERS",
        }

    # Check 1: Handler independence (no cross-handler imports except defaults)
    independence_check = check_handler_independence(content, lines, module_path)
    checks.append(independence_check)

    # Check 2: Auto-detection pattern (if module_name parameter exists)
    auto_detect_check = check_auto_detection(content)
    if auto_detect_check:
        checks.append(auto_detect_check)

    # Check 3: No orchestration logic (handlers shouldn't import modules)
    orchestration_check = check_no_orchestration(content, lines, module_path)
    if orchestration_check:
        checks.append(orchestration_check)

    # Calculate score
    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    # Overall pass if score >= 75%
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "handlers"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "HANDLERS"}


def _iter_import_modules(content: str) -> Iterator[Tuple[int, str, List[str]]]:
    """
    Parse content and yield (line_number, dotted_module, imported_names) for every
    real import statement — string literals, comments and docstrings can never
    produce a hit because the AST only contains actual import nodes.

    Relative imports (from . import x) are omitted entirely: they can't reference
    an absolute dotted path like "apps.handlers"/"apps.modules" and are always
    same-package, so callers don't need to special-case them.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        logger.info("Skipping import scan: SyntaxError during parse: %s", e)
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            yield node.lineno, node.module or "", [alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, []


def _line_text(lines: List[str], lineno: int, fallback: str) -> str:
    """Return the source line at 1-indexed lineno, or a fallback if out of range."""
    if 0 < lineno <= len(lines):
        return lines[lineno - 1].strip()
    return fallback


def _branch_of_path(module_path: str) -> Optional[str]:
    """Return the branch a file lives in, from the path segment before 'apps'.

    src/aipass/trigger/apps/handlers/escalation.py -> 'trigger'
    Absolute paths work too: the repo root ('AIPass') never equals 'apps'.
    """
    path_parts = Path(module_path).parts
    for i, part in enumerate(path_parts):
        if part == "apps" and i > 0:
            return path_parts[i - 1]
    return None


def _branch_before(module: str, marker: str) -> Optional[str]:
    """Return the branch segment sitting immediately before marker, or None.

    The None on a missing marker matters: splitting a string that does not
    contain the separator returns the WHOLE string, so the old handlers-only
    version answered 'modules' for 'aipass.spawn.apps.modules' -- a confident
    wrong branch name rather than "I cannot tell".

    Args:
        module: Dotted import path.
        marker: The layer separator to look for, e.g. ".apps.handlers".

    Returns:
        The branch name, or None when marker is absent or nothing precedes it.
    """
    if marker not in module:
        return None
    prefix = module.split(marker, 1)[0]
    parts = prefix.split(".")
    return parts[-1] if parts and parts[-1] else None


def _branch_of_import(module: str) -> Optional[str]:
    """Return the branch an 'apps.handlers' import targets.

    aipass.trigger.apps.handlers.events.error_detected -> 'trigger'
    Also handles the bare form: aipass.trigger.apps.handlers -> 'trigger'
    """
    return _branch_before(module, ".apps.handlers")


def _branch_of_modules_import(module: str) -> Optional[str]:
    """Return the branch an 'apps.modules' import targets.

    aipass.spawn.apps.modules -> 'spawn'
    """
    return _branch_before(module, ".apps.modules")


def check_handler_independence(content: str, lines: List[str], module_path: str) -> Dict:
    """
    Check handler independence - handlers are private to their own branch.

    The rule is branch-level, matching the published standard:
    - ALLOWED: same-branch handler imports, EVEN ACROSS PACKAGES
      (flow/apps/handlers/plan/create.py -> aipass.flow.apps.handlers.registry.load)
    - ALLOWED: from .decorators import catch_errors (relative, same package)
    - FORBIDDEN: cross-BRANCH handler imports -- another branch's handlers are
      private; consume its modules/ instead.

    Comparing packages instead of branches was the old behaviour. It rejected
    the standard's own documented ALLOWED example, and for a handler sitting at
    the handlers/ root it compared against the FILENAME, so such files could
    never pass whatever they imported.
    """
    forbidden_imports = []

    own_branch = _branch_of_path(module_path)
    if own_branch is None:
        # Not a recognisable branch layout -- the same-branch rule is not
        # evaluable here. Say so rather than flag every import as cross-branch.
        return {
            "name": "Handler independence",
            "passed": True,
            "message": "Branch could not be determined from path (independence rule not evaluated)",
        }

    for lineno, module, _names in _iter_import_modules(content):
        if "apps.handlers" not in module:
            continue

        # Allowed: any handler in this branch, whatever package it sits in
        if _branch_of_import(module) == own_branch:
            continue

        # Forbidden: another branch's handlers are not ours to import
        forbidden_imports.append(f"line {lineno}: {_line_text(lines, lineno, module)}")

    if forbidden_imports:
        return {
            "name": "Handler independence",
            "passed": False,
            "message": "Cross-branch handler imports detected (use that branch's modules/ instead): "
            + "; ".join(forbidden_imports),
        }

    return {"name": "Handler independence", "passed": True, "message": "No forbidden cross-branch handler imports"}


def _public_function_takes_module_name(content: str) -> bool:
    """True when a PUBLIC function accepts a ``module_name`` parameter.

    Auto-detection exists so a CALLER does not have to name itself: log_operation(
    operation, data, module_name=None) is the shape, and it is part of a handler's
    published surface. A private helper's parameter is internal plumbing — my own
    _module_file(module_name, source_root) resolves a dotted name it was given and
    has no caller to detect, and the regex that used to answer this question
    convicted it on the parameter NAME alone (found by dogfooding, 2026-08-31).

    The leading underscore is the discriminator because it is a real, visible
    property of the module's surface, not a spelling: renaming a public function
    to buy the exemption removes it from the API.

    An unparseable file falls back to the old text scan rather than answering no —
    a file we could not read is not evidence that the parameter is absent.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        logger.info("handlers: unparseable, falling back to the text scan for module_name: %s", exc)
        return bool(re.search(r"def\s+\w+\([^)]*module_name", content))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        args = node.args
        names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
        if args.vararg:
            names.append(args.vararg.arg)
        if args.kwarg:
            names.append(args.kwarg.arg)
        if "module_name" in names:
            return True
    return False


#: Every way a handler can ask "who called me". The point of the SET is that the
#: standard's question is whether the caller is detected, never which library
#: spells it — see :func:`_walks_the_caller_frame`.
_FRAME_WALK_CALLS = frozenset(
    {
        "sys._getframe",
        "inspect.currentframe",
        "inspect.stack",
        "inspect.getouterframes",
        "traceback.extract_stack",
        "traceback.walk_stack",
    }
)

#: Helper names that ARE the auto-detection, whatever they use inside.
_CALLER_HELPER_MARKERS = ("_get_caller_module_name", "get_caller")


def _module_name_is_optional(content: str) -> bool:
    """True when some public function lets ``module_name`` be omitted.

    AUTO-DETECTION ONLY MEANS SOMETHING IF THE ARGUMENT CAN BE MISSING. A
    required ``module_name`` is supplied by every caller at every call site;
    there is nothing to detect, and demanding a frame walk there asks for code
    that can never run.

    Measured 2026-08-31 across the fleet's 19 handler files with a public
    ``module_name``: 3 take it as REQUIRED and were red for a cure that would be
    dead code (@prax's logging/lifecycle.py, logging/setup.py and
    terminal/filtering.py). 16 take it optionally, which is the population this
    standard is actually about.

    Args:
        content: File source.

    Returns:
        True if any public function accepts ``module_name`` with a default,
        or absorbs it through ``*args`` / ``**kwargs``.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        # Unreadable is not evidence of absence — same rule as the scan above.
        logger.info("handlers: unparseable, assuming module_name is optional: %s", exc)
        return True

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
            continue
        args = node.args
        positional = [*args.posonlyargs, *args.args]
        first_defaulted = len(positional) - len(args.defaults)
        for index, arg in enumerate(positional):
            if arg.arg == "module_name" and index >= first_defaulted:
                return True
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            if arg.arg == "module_name" and default is not None:
                return True
        if (args.vararg and args.vararg.arg == "module_name") or (args.kwarg and args.kwarg.arg == "module_name"):
            return True
    return False


def _walks_the_caller_frame(content: str) -> bool:
    """True when the file asks who called it, BY ANY MECHANISM.

    THE CHECK USED TO MANDATE THE DEFECT. It accepted the literal string
    ``inspect.stack()`` as its proof, and told every failing handler to "use
    inspect.stack()". That call is the Windows dead-cwd defect the fleet spent
    this week removing: it reaches an unguarded ``os.path.realpath`` inside
    ``inspect.getmodule``, and ``ntpath.realpath`` reads ``os.getcwd()`` before
    checking anything. @prax cured their own site and the audit dropped the file
    to 66% and told them to put it back (reported 2026-08-31); they renamed a
    helper rather than restore the call, which fixed prax and left the checker
    pointed at the next branch to cure.

    So the acceptance is on the QUESTION, not the spelling. ``sys._getframe`` is
    the sound answer — seedgo's own json_handler has used it since the day
    inspect.stack() made audits slow — and it is what the failure message now
    names.

    AST, never a substring, and that matters in BOTH directions: the old text
    scan passed a file whose only ``inspect.stack()`` sat in a docstring or a
    comment. @drone hit the mirror image the same morning — a text BAN convicting
    the docstring that explained the cure. A string rule is too broad and too
    narrow at once.

    Args:
        content: File source.

    Returns:
        True if a call to any known frame-walk API, or to a named caller
        helper, appears anywhere in the file's parse tree.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        logger.info("handlers: unparseable, cannot see a frame walk: %s", exc)
        return False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            marker in node.name for marker in _CALLER_HELPER_MARKERS
        ):
            return True
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted_call_name(node.func)
        if dotted in _FRAME_WALK_CALLS or any(marker in dotted for marker in _CALLER_HELPER_MARKERS):
            return True
    return False


def _dotted_call_name(func: ast.expr) -> str:
    """Dotted spelling of a call target, or "" when it is not a plain name.

    Args:
        func: The ``func`` of an ``ast.Call``.

    Returns:
        e.g. ``"sys._getframe"``, ``"inspect.stack"``, ``"log_operation"``.
    """
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
        return ".".join(reversed(parts))
    return ""


def check_auto_detection(content: str) -> Optional[Dict]:
    """Check that a handler detects its caller when ``module_name`` is omissible.

    TWO CLAUSES, both AST and both measured before landing (2026-08-31):
      1. some PUBLIC function takes ``module_name`` and lets it be omitted —
         a required parameter has nothing to detect;
      2. the file walks the caller frame by SOME mechanism, or carries a named
         caller helper.

    WHAT THIS CHECK CANNOT SEE, named here rather than left for the next branch
    to discover: it reads the parameter's NAME, so a ``module_name`` that is an
    event PAYLOAD field rather than a caller identity looks identical to it.
    @trigger's events/warning_logged.py is the live example — its
    ``module_name`` is the module that logged a warning, carried in the event,
    and its caller is the event bus. Auto-detecting there would be wrong. That
    distinction is semantic and I have no structural measure for it, so it stays
    a finding with its blind spot stated rather than a clause I cannot defend.

    Args:
        content: File source.

    Returns:
        A check dict, or None when the standard does not apply to this file.
    """
    if not _public_function_takes_module_name(content):
        return None  # No module_name parameter, auto-detection not needed

    if not _module_name_is_optional(content):
        return None  # Callers always supply it — there is nothing to detect

    if _walks_the_caller_frame(content):
        return {
            "name": "Auto-detection pattern",
            "passed": True,
            "message": "Auto-detection pattern implemented (caller frame is read)",
        }

    return {
        "name": "Auto-detection pattern",
        "passed": False,
        "message": (
            "Has an optional module_name but never reads the caller frame "
            "(use sys._getframe — NOT inspect.stack(), which needs a readable cwd on Windows). "
            "If this module_name is an event payload rather than a caller identity, say so — "
            "the checker reads the name and cannot tell them apart."
        ),
    }


def check_no_orchestration(content: str, lines: List[str], module_path: str = "") -> Optional[Dict]:
    """Check that a handler does not reach up into its OWN branch's modules layer.

    Handlers are pure implementation; orchestration lives in modules/. A handler
    importing its own branch's modules inverts that and is the shape that can
    actually close a cycle.

    - FORBIDDEN: from aipass.seedgo.apps.modules import x, inside seedgo's handlers
    - ALLOWED: from aipass.spawn.apps.modules import x -- another branch's modules
      package is its PUBLIC GATEWAY, and check_handler_independence explicitly
      sends cross-branch callers there ("use that branch's modules/ instead").
      Refusing it here closed the only door that check leaves open, which made
      every cross-branch consumer non-compliant whichever import it wrote.

    Unknown branch stays STRICT, deliberately the opposite default to
    check_handler_independence: that check cannot evaluate its rule without a
    branch, while this one still has a real question to answer, and widening it
    would let every own-branch orchestration import pass whenever a caller
    omitted the path.

    Args:
        content: Source of the file being checked.
        lines: The same source split into lines, for quoting the offending line.
        module_path: Path of the file, used to tell own-branch from cross-branch.

    Returns:
        Check dict, or None when the check does not apply.
    """
    module_imports = []

    own_branch = _branch_of_path(module_path) if module_path else None

    for lineno, module, _names in _iter_import_modules(content):
        if "apps.modules" not in module:
            continue

        # Allowed: Service imports (prax.apps.modules.logger, cli.apps.modules)
        if "prax.apps.modules.logger" in module or "cli.apps.modules" in module:
            continue

        # Allowed: another branch's modules gateway -- its public door
        imported_branch = _branch_of_modules_import(module)
        if own_branch and imported_branch and imported_branch != own_branch:
            continue

        # Forbidden: this branch's own modules (orchestration)
        module_imports.append(f"line {lineno}: {_line_text(lines, lineno, module)}")

    if module_imports:
        return {
            "name": "No orchestration",
            "passed": False,
            "message": "Handler imports modules (orchestration): " + "; ".join(module_imports),
        }

    return {"name": "No orchestration", "passed": True, "message": "No module imports detected (pure implementation)"}
