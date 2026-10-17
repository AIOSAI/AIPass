# =================== AIPass ====================
# Name: mock_console_check.py
# Description: Mock Console Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-10-17
# =============================================

"""
Mock Console Standards Checker Handler

Reference: mock_console.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "MOCK_CONSOLE"
STANDARD_KEY = "mock_console"

#: Every factory in unittest.mock that yields a mock. A console replaced by any
#: of them answers every call and writes to no channel.
_MOCK_FACTORIES: frozenset[str] = frozenset(
    {
        "Mock",
        "MagicMock",
        "AsyncMock",
        "NonCallableMock",
        "NonCallableMagicMock",
        "PropertyMock",
        "create_autospec",
    }
)

#: A console under one qualifier -- ``err_console``, ``out_console``. More than
#: one says the name is a verb phrase, not an object.
_QUALIFIED_CONSOLE = re.compile(r"[a-z]+_console")

#: The two patch verbs, by the name the call is made under.
_PATCH_CALLS: frozenset[str] = frozenset({"patch", "object"})

#: What a substitute is called in the message, by kind.
_MOCK = "a Mock"
_DEFAULT_MOCK = "a patch with no replacement (the default MagicMock)"
_BUFFERED = "a Rich Console on a buffer"
_RECORDING = "a recording Rich Console"
_FAKE = "a fake console class"

FIX = "read the channel with capsys.readouterr()"


def _tail_name(func: ast.expr) -> str:
    """The name a call is made under -- ``f`` for ``a.b.f(...)`` and ``f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_console_name(name: str | None) -> bool:
    """Whether this name is a console OBJECT -- ``console``, ``CONSOLE``,
    ``err_console``, ``Console``.

    One qualifier at most, which is what keeps a FUNCTION (``_print_event_to_console``) out.
    """
    lowered = (name or "").lower().lstrip("_")
    return lowered == "console" or bool(_QUALIFIED_CONSOLE.fullmatch(lowered))


def _target_attr(node: ast.expr) -> str:
    """The attribute a patch target names -- ``console`` for ``"a.b.console"``.

    An f-string target is read from its last literal part, so ``f"{MOD}.console"`` is read.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.rsplit(".", 1)[-1]
    if isinstance(node, ast.JoinedStr):
        for part in reversed(node.values):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                return part.value.rsplit(".", 1)[-1]
    return ""


def _fake_console_classes(nodes: List[ast.AST]) -> Set[str]:
    """Classes defined in this file that carry a ``print`` method."""
    return {
        node.name
        for node in nodes
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(body, (ast.FunctionDef, ast.AsyncFunctionDef)) and body.name == "print" for body in node.body
        )
    }


def _direct_substitute(node: ast.expr, fakes: Set[str]) -> str | None:
    """What stand-in this expression builds, or None when it builds none."""
    if not isinstance(node, ast.Call):
        return None
    name = _tail_name(node.func)
    if name in _MOCK_FACTORIES:
        return _MOCK
    if name in fakes:
        return _FAKE
    if name == "Console":
        keywords = {keyword.arg for keyword in node.keywords}
        if "file" in keywords:
            return _BUFFERED
        if "record" in keywords:
            return _RECORDING
    return None


def _helper_returns(nodes: List[ast.AST], fakes: Set[str]) -> Dict[str, str]:
    """Same-file functions whose ``return`` hands back a stand-in.

    One hop, and one hop only: a helper returning ``(console, buffer)`` has its first element installed.
    """
    helpers: Dict[str, str] = {}
    for function in nodes:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            candidates = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
            for candidate in candidates:
                kind = _direct_substitute(candidate, fakes)
                if kind is not None:
                    helpers.setdefault(function.name, kind)
    return helpers


def _bindings(nodes: List[ast.AST], fakes: Set[str], helpers: Dict[str, str]) -> Dict[str, str]:
    """Names bound ONLY to a stand-in, and what that stand-in is.

    A name assigned anything else anywhere in the file is dropped: one pass cannot say which value
    reaches the install.
    """
    bound: Dict[str, str] = {}
    rejected: Set[str] = set()
    for node in nodes:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        kind = _direct_substitute(node.value, fakes)
        if kind is None and isinstance(node.value, ast.Call):
            kind = helpers.get(_tail_name(node.value.func))
        names: List[str] = []
        if isinstance(target, ast.Name):
            names = [target.id]
        elif isinstance(target, ast.Tuple):
            names = [element.id for element in target.elts if isinstance(element, ast.Name)]
        for name in names:
            if kind is None:
                rejected.add(name)
            else:
                bound.setdefault(name, kind)
    return {name: kind for name, kind in bound.items() if name not in rejected}


def _substitute(node: ast.expr | None, fakes: Set[str], bound: Dict[str, str]) -> str | None:
    """What stand-in this value is, following a name one hop."""
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return bound.get(node.id)
    return _direct_substitute(node, fakes)


def _patch_install(node: ast.Call, fakes: Set[str], bound: Dict[str, str]) -> str | None:
    """What a ``patch`` or ``patch.object`` call puts over a console, if any.

    A patch given no replacement is the whole offence on its own: mock hands the product a MagicMock by default.
    """
    if node.args and _is_console_name(_target_attr(node.args[0])):
        replacement = node.args[1] if len(node.args) > 1 else None
    elif len(node.args) > 1 and _is_console_name(_target_attr(node.args[1])):
        replacement = node.args[2] if len(node.args) > 2 else None
    else:
        return None

    keywords = {keyword.arg: keyword.value for keyword in node.keywords}
    if replacement is None:
        replacement = keywords.get("new") or keywords.get("new_callable")
    if replacement is None:
        return _DEFAULT_MOCK
    if isinstance(replacement, ast.Name) and replacement.id in _MOCK_FACTORIES:
        return _MOCK
    return _substitute(replacement, fakes, bound)


def _setattr_install(node: ast.Call, fakes: Set[str], bound: Dict[str, str]) -> str | None:
    """What a ``setattr`` call puts over a console, if any.

    Both forms: ``setattr(module, "console", x)`` and monkeypatch's two-argument
    ``setattr("pkg.mod.console", x)``.
    """
    if len(node.args) >= 3 and _is_console_name(_target_attr(node.args[1])):
        return _substitute(node.args[2], fakes, bound)
    if len(node.args) == 2 and _is_console_name(_target_attr(node.args[0])):
        return _substitute(node.args[1], fakes, bound)
    return None


def _install_findings(nodes: List[ast.AST], fakes: Set[str], bound: Dict[str, str]) -> List[Tuple[int, str]]:
    """(line, what was installed) for every stand-in put where the product looks."""
    found: List[Tuple[int, str]] = []
    for node in nodes:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Attribute) and _is_console_name(target.attr):
                kind = _substitute(node.value, fakes, bound)
                if kind is not None:
                    found.append((node.lineno, f"{kind} installed over the product's console"))
        if not isinstance(node, ast.Call):
            continue
        name = _tail_name(node.func)
        kind = None
        if name in _PATCH_CALLS:
            kind = _patch_install(node, fakes, bound)
        elif name == "setattr":
            kind = _setattr_install(node, fakes, bound)
        if kind is not None:
            found.append((node.lineno, f"{kind} installed over the product's console"))
    return found


def _handoff_findings(nodes: List[ast.AST], fakes: Set[str], bound: Dict[str, str]) -> List[Tuple[int, str]]:
    """(line, what was handed) for a stand-in passed as a ``console`` argument."""
    found: List[Tuple[int, str]] = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if not _is_console_name(keyword.arg):
                continue
            kind = _substitute(keyword.value, fakes, bound)
            if kind is not None:
                found.append((keyword.value.lineno, f"{kind} handed to the product as its console"))
    return found


def _parse(source: str, what: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ruff already convicts a syntax error; a line number invented for an unparseable file misleads.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[mock_console] Unparseable, nothing %s: %s", what, exc)
        return None


def scan(source: str) -> List[Tuple[int, str, str]]:
    """(line, what was found, fix) for every console stand-in the product gets."""
    tree = _parse(source, "scanned")
    if tree is None:
        return []

    # One walk, reused by all five passes: separate walks doubled this rule's cost over the fleet.
    nodes = list(ast.walk(tree))
    fakes = _fake_console_classes(nodes)
    bound = _bindings(nodes, fakes, _helper_returns(nodes, fakes))

    hits: List[Tuple[int, str, str]] = []
    seen: Set[Tuple[int, str]] = set()
    for line, what in _install_findings(nodes, fakes, bound) + _handoff_findings(nodes, fakes, bound):
        if (line, what) in seen:
            continue
        seen.add((line, what))
        hits.append((line, what, FIX))
    return sorted(hits)


def counted_renderer_consoles(source: str) -> List[int]:
    """Lines building a ``Console(file=...)`` the file never installs.

    Counted, never convicted. The subject is what Rich does to a string, and
    ``capsys`` cannot capture an output the product never wrote. Only ever read
    for a file with no hits, which is what makes "never installs" true.
    """
    tree = _parse(source, "counted")
    if tree is None:
        return []

    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _tail_name(node.func) == "Console"
        and any(keyword.arg == "file" for keyword in node.keywords)
    )


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[mock_console] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Mock console", "passed": passed, "message": message}]


def _clean_message(renderers: List[int]) -> str:
    """What a passing file says, carrying the renderer-console count."""
    if not renderers:
        return "The console the product prints to is the real one"
    subject = "console is" if len(renderers) == 1 else "consoles are"
    return (
        f"The console the product prints to is the real one "
        f"({len(renderers)} renderer {subject} counted, which the rule allows)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file for a console stand-in handed to the product."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    hits = [h for h in scan(source) if not is_bypassed(module_path, STANDARD_KEY, h[0], bypass_rules)]

    if not hits:
        return _result(True, _one_check(True, _clean_message(counted_renderer_consoles(source))), 100)

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    detail = "\n".join(f"{path.name}:{line} {what} - {fix}" for line, what, fix in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
