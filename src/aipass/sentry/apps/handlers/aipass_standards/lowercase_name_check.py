# =================== AIPass ====================
# Name: lowercase_name_check.py
# Description: Lowercase Name Checker Handler - the system speaks lowercase
# Version: 1.0.0
# Created: 2026-11-22
# Modified: 2026-11-22
# =============================================

"""
Lowercase Name Checker Handler

An agent's name is stored in lowercase: registry rows, a branch's data files, the code that
writes them, and spawn's non-markdown template files. Markdown is never opened.

Reference: lowercase_name.md
"""

import ast
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

from aipass.prax import logger
from aipass.sentry.apps.handlers.aipass_standards.check_support import (
    parse,
    read_text,
    result,
    tail_name,
)
from aipass.sentry.apps.handlers.aipass_standards.skip_dirs import (
    in_skipped_dir,
    is_disabled_file,
)
from aipass.sentry.apps.handlers.bypass.utils import is_bypassed
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers.registry_scan import find_registry_upward

APPLIES_TO = "production"
AUDIT_SCOPE = "branch_level"
BRANCH_INPUTS = (
    ".trinity/passport.json",
    "artifacts/birth_certificate.json",
    "DASHBOARD.local.json",
    "templates/*",
)

STANDARD = "lowercase_name"
REGISTRY_CURE = "drone @spawn sync-registry <registry> --lowercase"

#: (file, key path, the cure the finding names). A dashboard turns lowercase on its next refresh.
DATA_FIELDS: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    (
        ".trinity/passport.json",
        ("branch_info", "branch_name"),
        "the passport's owner rewrites branch_name",
    ),
    (
        "artifacts/birth_certificate.json",
        ("owner",),
        "no verb rewrites a certificate yet: mail @spawn",
    ),
    ("DASHBOARD.local.json", ("branch",), "drone @prax dashboard refresh @<branch>"),
)

#: spawn fills {{BRANCHNAME}} with the capital name and {{BRANCH}} with the lowercase one.
CAPITAL_TOKENS = ("{{BRANCHNAME}}",)
LOWER_TOKEN = "{{BRANCH}}"
TEMPLATE_DIR = "templates"
TEMPLATE_SKIP_PARTS = frozenset({".archive", "__pycache__", ".git"})
MARKDOWN_SUFFIX = ".md"

CODE_DIRS = ("apps", "shared")
CAPITALISERS = frozenset({"upper", "title", "capitalize"})
#: Calls whose result still spells their arguments; any other call is an unknown value.
STRING_METHODS = CAPITALISERS | {"format", "join", "replace", "strip", "lstrip", "rstrip"}
NAME_WORDS = ("branch", "agent", "citizen", "sender", "recipient", "owner")
#: A dict value counts as a name field only under a key carrying one of these.
FIELD_WORDS = NAME_WORDS + ("name", "from", "to", "by")
#: Screens and logs are not storage: the owner has not ruled on them.
DISPLAY_CALLS = frozenset(
    {
        "print",
        "debug",
        "info",
        "warning",
        "error",
        "critical",
        "exception",
        "success",
        "log_operation",
        "add_row",
    }
)
PATH_CALLS = frozenset({"open", "Path", "joinpath", "with_name", "write_text"})


def _check(name: str, passed: bool, message: str) -> Dict:
    """One row of the result's checks."""
    return {"name": name, "passed": passed, "message": message}


def _line_of(text: str, needle: str) -> int:
    """1-based line of the first ``needle`` in ``text``, or 0."""
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    return 0


# ---- leg 1: the registry row -------------------------------------------------------------


def _json(path: Path) -> Tuple[str, object]:
    """A JSON file's text and value. Raises ValueError when it cannot be read or parsed: never judged as empty."""
    text = read_text(path, tag=STANDARD)
    if text is None:
        raise ValueError(f"{path.name} cannot be read")
    try:
        return text, json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} does not parse: {exc}") from exc


@lru_cache(maxsize=16)
def _registry_rows(registry: str, mtime: float) -> Tuple[Tuple[str, str, int], ...]:
    """(name, path, line) for every row; ``mtime`` keys the cache to the file's state. Raises ValueError."""
    text, data = _json(Path(registry))
    rows = data.get("branches", []) if isinstance(data, dict) else []
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    named = [(str(row.get("name", "")), str(row.get("path", ""))) for row in rows if isinstance(row, dict)]
    return tuple((name, path, _line_of(text, json.dumps(name))) for name, path in named)


def _registry(branch_root: Path) -> Optional[Path]:
    """The registry at or above the branch, or None (a clean checkout holds none)."""
    return find_registry_upward(branch_root.resolve())


def agent_names(branch_root: Path) -> Set[str]:
    """Lowercase agent names this branch can prove: its own folder name and its registry's rows."""
    names = {branch_root.name.lower()}
    registry = _registry(branch_root)
    if registry is None:
        return names
    try:
        rows = _registry_rows(str(registry), registry.stat().st_mtime)
    except ValueError as exc:
        logger.warning("[%s] %s proves no agent names, the registry leg fails it: %s", STANDARD, registry, exc)
        return names
    return names | {name.lower() for name, _, _ in rows if name}


def _registry_checks(branch_root: Path) -> List[Dict]:
    """This branch's own row: a capital name or an absolute path fails, naming the row."""
    registry = _registry(branch_root)
    if registry is None:
        return []
    try:
        rows = _registry_rows(str(registry), registry.stat().st_mtime)
    except ValueError as exc:
        return [_check("registry_unreadable", False, f"{exc} - no row in it is judged")]
    checks = []
    for name, raw, line in rows:
        path = Path(raw)
        resolved = path if path.is_absolute() else registry.parent / path
        if resolved.resolve() != branch_root.resolve():
            continue
        where = f"{registry.name}:{line} row '{name}'"
        if name != name.lower():
            checks.append(_check("registry_name", False, f"{where}: name is not lowercase - {REGISTRY_CURE}"))
        if path.is_absolute():
            checks.append(_check("registry_path", False, f"{where}: path {raw} is absolute - {REGISTRY_CURE}"))
    return checks


# ---- leg 2: stored name fields in the branch's data files ----------------------------------


def _data_checks(branch_root: Path) -> List[Dict]:
    """The passport's branch name, the certificate's owner, the dashboard's branch."""
    checks = []
    for rel, keys, cure in DATA_FIELDS:
        path = branch_root / rel
        if not path.is_file():
            continue
        try:
            text, value = _json(path)
        except ValueError as exc:
            checks.append(_check("stored_name", False, f"{rel}: {exc} - its name field is not judged"))
            continue
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, str) and value != value.lower():
            line = _line_of(text, json.dumps(value))
            checks.append(_check("stored_name", False, f"{rel}:{line} {keys[-1]} '{value}' is not lowercase - {cure}"))
    return checks


# ---- leg 5: capital tokens in non-markdown template files ----------------------------------


def _template_files(branch_root: Path) -> Iterator[Path]:
    """Every non-markdown file under the branch's templates/; markdown is never yielded, so never read."""
    root = branch_root / TEMPLATE_DIR
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if path.suffix.lower() == MARKDOWN_SUFFIX or any(part in TEMPLATE_SKIP_PARTS for part in rel_parts):
            continue
        if path.is_file():
            yield path


def _template_checks(branch_root: Path) -> List[Dict]:
    """A capital token in a template file's name or text fails."""
    checks = []
    for path in _template_files(branch_root):
        rel = path.relative_to(branch_root).as_posix()
        text = read_text(path, tag=STANDARD, errors="replace")
        if text is None:
            checks.append(_check("template_token", False, f"{rel} cannot be read - its tokens are not judged"))
            continue
        for token in CAPITAL_TOKENS:
            line = _line_of(text, token) if token in text else (1 if token in rel else 0)
            if line:
                checks.append(
                    _check(
                        "template_token",
                        False,
                        f"{rel}:{line} holds {token}, filled in capitals - use {LOWER_TOKEN}",
                    )
                )
    return checks


# ---- leg 3: code that capitalises an agent name on its way into storage --------------------


def _is_text(node: Optional[ast.AST]) -> bool:
    """Whether a node is a string literal."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _words(node: ast.AST) -> Iterator[str]:
    """Every identifier and string-subscript key an expression is built from, lowercased."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            yield sub.id.lower()
        elif isinstance(sub, ast.Attribute):
            yield sub.attr.lower()
        elif isinstance(sub, ast.Subscript) and _is_text(sub.slice):
            yield sub.slice.value.lower()  # type: ignore[attr-defined]


def _names_an_agent(node: ast.AST) -> bool:
    """Whether an expression is visibly an agent's name: one of its words carries a NAME_WORD."""
    return any(word in token for token in _words(node) for word in NAME_WORDS)


def _capitalises(node: ast.AST, tainted: Set[str]) -> bool:
    """Whether an expression carries an agent name in capitals: a capitaliser call, or a tainted local."""
    for sub in _value_nodes(node):
        if isinstance(sub, ast.Name) and sub.id in tainted:
            return True
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in CAPITALISERS
            and _names_an_agent(sub.func.value)
        ):
            return True
    return False


def _value_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """The nodes whose text survives into the value: a call's arguments do not, unless it is a string method."""
    stack = [node]
    while stack:
        sub = stack.pop()
        yield sub
        if isinstance(sub, ast.Call):
            through = isinstance(sub.func, ast.Attribute) and sub.func.attr in STRING_METHODS
            stack.extend([sub.func, *sub.args] if through else [sub.func])
        else:
            stack.extend(ast.iter_child_nodes(sub))


def _capital_constant(node: Optional[ast.AST], names: Set[str], stem: bool = False) -> Optional[str]:
    """A string literal spelling an agent's name in capitals (``stem``: its part before the first dot)."""
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return None
    text = node.value.split(".")[0] if stem else node.value
    return node.value if text.isupper() and text.lower() in names else None


def _scope_nodes(scope: ast.AST) -> List[ast.AST]:
    """Every node of one scope: a nested function is its own scope, so its locals never leak into this one."""
    nodes: List[ast.AST] = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        nodes.append(node)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))
    return nodes


def _tainted(nodes: List[ast.AST]) -> Set[str]:
    """Locals assigned a capitalised agent name in one scope, followed through re-assignment."""
    assigns = [
        node
        for node in nodes
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
    ]
    tainted: Set[str] = set()
    grew = True
    while grew:
        before = len(tainted)
        tainted |= {
            node.targets[0].id  # type: ignore[union-attr]
            for node in assigns
            if _capitalises(node.value, tainted)
        }
        grew = len(tainted) > before
    return tainted


def _display_lines(tree: ast.AST) -> Set[int]:
    """Every line inside a screen or log call: what is printed or logged is not stored."""
    lines: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and tail_name(node.func) in DISPLAY_CALLS:
            lines.update(getattr(sub, "lineno", 0) for sub in ast.walk(node))
    return lines


def _field_key(key: Optional[ast.AST]) -> bool:
    """Whether a dict key is a string naming a name field (``from_name``, ``branch``, ...)."""
    return _is_text(key) and any(word in key.value.lower() for word in FIELD_WORDS)  # type: ignore[union-attr]


def _node_sinks(node: ast.AST) -> List[Tuple[ast.AST, Optional[ast.AST], str]]:
    """(expression, its key or None, the kind of store) for each value this one node stores."""
    if isinstance(node, ast.Dict):
        stored: List[Tuple[ast.AST, Optional[ast.AST], str]] = [(k, None, "dict key") for k in node.keys if k]
        return stored + [(value, key, "dict value") for key, value in zip(node.keys, node.values)]
    if isinstance(node, ast.Assign):
        stores = [target for target in node.targets if isinstance(target, ast.Subscript)]
        return [pair for t in stores for pair in ((t.slice, None, "stored key"), (node.value, t.slice, "stored value"))]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return [(node.left, None, "path"), (node.right, None, "path")]
    if isinstance(node, ast.Call) and tail_name(node.func) in PATH_CALLS and node.args:
        return [(node.args[0], None, "path")]
    return []


def _finding(expr: ast.AST, key: Optional[ast.AST], kind: str, tainted: Set[str], names: Set[str]) -> str:
    """Why one stored expression fails, or ""."""
    if _capitalises(expr, tainted):
        return f"an agent name is capitalised into a {kind}"
    constant = _capital_constant(expr, names, stem=kind == "path")
    if constant and (kind not in ("dict value", "stored value") or _field_key(key)):
        return f"'{constant}' is an agent name in capitals, stored as a {kind}"
    return ""


def code_findings(source: str, filename: str, names: Set[str]) -> List[Tuple[int, str]]:
    """(line, message) for each agent name capitalised, or spelled in capitals, on its way into storage."""
    tree = parse(source, filename, tag=STANDARD)
    if tree is None:
        return []
    shown = _display_lines(tree)
    scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    found: Dict[int, str] = {}
    for scope in scopes:
        nodes = _scope_nodes(scope)
        tainted = _tainted(nodes)
        for expr, key, kind in (sink for node in nodes for sink in _node_sinks(node)):
            line = getattr(expr, "lineno", 0)
            if line and line not in shown and line not in found:
                message = _finding(expr, key, kind, tainted, names)
                if message:
                    found[line] = message
    return sorted(found.items())


def branch_root_of(file_path: Path) -> Path:
    """The branch a file sits in: the nearest folder holding apps/ and .trinity/, else its parent."""
    for parent in file_path.resolve().parents:
        if (parent / "apps").is_dir() and (parent / ".trinity").is_dir():
            return parent
    return file_path.resolve().parent


def _file_checks(path: Path, names: Set[str], bypass_rules: Optional[list]) -> List[Dict]:
    """The code leg for one file; a row waives one line, and says why."""
    source = read_text(path, tag=STANDARD)
    if source is None:
        return []
    return [
        _check("capitalised_name", False, f"{path.name}:{line} {message}")
        for line, message in code_findings(source, str(path), names)
        if not is_bypassed(str(path), STANDARD, line=line, bypass_rules=bypass_rules)
    ]


def _code_files(branch_root: Path) -> List[Path]:
    """The branch's production Python under apps/ and shared/."""
    files = []
    for directory in CODE_DIRS:
        root = branch_root / directory
        if not root.is_dir():
            continue
        files.extend(
            path
            for path in sorted(root.rglob("*.py"))
            if not in_skipped_dir(path, branch_root) and "tests" not in path.parts and not is_disabled_file(path.name)
        )
    return files


def _verdict(checks: List[Dict], scope: str) -> Dict:
    """Pass or fail, nothing between: one finding fails the standard."""
    if not checks:
        checks = [_check(STANDARD, True, f"every agent name stored in {scope} is lowercase")]
    passed = all(check["passed"] for check in checks)
    return result(passed, checks, 100 if passed else 0, STANDARD)


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """The code leg over one file: what the checklist can judge as a file is written."""
    path = Path(module_path)
    return _verdict(_file_checks(path, agent_names(branch_root_of(path)), bypass_rules), path.name)


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Every leg over one branch: its registry row, data files, template files and code."""
    root = Path(branch_path).resolve()
    names = agent_names(root)
    checks = _registry_checks(root) + _data_checks(root) + _template_checks(root)
    for path in _code_files(root):
        checks.extend(_file_checks(path, names, bypass_rules))
    verdict = _verdict(checks, root.name)
    json_handler.log_operation(
        STANDARD,
        {"branch": root.name, "findings": 0 if verdict["passed"] else len(checks)},
    )
    return verdict
