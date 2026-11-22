# =================== AIPass ====================
# Name: lowercase_name_check.py
# Description: Lowercase Name Checker Handler - the system speaks lowercase
# Version: 2.0.0
# Created: 2026-11-22
# Modified: 2026-11-22
# =============================================

"""
Lowercase Name Checker Handler

An agent's name is written in lowercase wherever the runtime reads or writes it: registry rows,
a branch's data files, and every string its code stores, prints or logs. Markdown is never opened.

Reference: lowercase_name.md
"""

import ast
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

from aipass.prax import logger
from aipass.sentry.apps.handlers.aipass_standards.check_support import parse, read_text, result
from aipass.sentry.apps.handlers.aipass_standards.skip_dirs import in_skipped_dir, is_disabled_file
from aipass.sentry.apps.handlers.bypass.utils import is_bypassed
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers.registry_scan import find_registry_upward

APPLIES_TO = "production"
AUDIT_SCOPE = "branch_level"
BRANCH_INPUTS = (".trinity/passport.json", "artifacts/birth_certificate.json", "DASHBOARD.local.json")

STANDARD = "lowercase_name"
REGISTRY_CURE = "drone @spawn sync-registry REGISTRY --lowercase"

#: (file, key path, the cure the finding names). A dashboard turns lowercase on its next refresh.
DATA_FIELDS: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    (".trinity/passport.json", ("branch_info", "branch_name"), REGISTRY_CURE),
    ("artifacts/birth_certificate.json", ("owner",), REGISTRY_CURE),
    ("DASHBOARD.local.json", ("branch",), "drone @prax dashboard refresh @BRANCH"),
)

CODE_DIRS = ("apps", "shared")
CAPITALISERS = frozenset({"upper", "title", "capitalize"})
NAME_WORDS = ("branch", "agent", "citizen", "sender", "recipient", "owner", "caller")

#: A run of letters, digits and underscores: "AI_MAIL" is one token, "AIPASS_REGISTRY" is not "AIPASS".
_TOKEN = re.compile(r"[A-Za-z0-9_]+")

#: Agent names that are also common words ("PUBLIC API", "each CLI runs", "IN MEMORY", "OWN HOOKS")
#: or the project's own name ("AIPASS root"). In capitals they count only where a name stands alone:
#: a [TAG] or [TAG:sub], an @address, a :NAME] tag, an =NAME value, a whole literal or one
#: wrapped in markup, or a banner opening ("CLI - ...", "[bold]AIPASS — ...", "API v2").
COMMON_NOUN_NAMES = frozenset({"cli", "api", "flow", "hooks", "memory", "trigger", "aipass"})
_NAME_POSITIONS = (
    r"\[{t}[\]:]",
    r"@{t}\b",
    r":{t}\]",
    r"={t}\b",
    r"(?:^|\])\s*{t}\s*(?:\[|$)",
    r"(?:^|\])\s*{t}\s+(?:[-—–]|v\d)",
)


def _check(name: str, passed: bool, message: str) -> Dict:
    """One row of the result's checks."""
    return {"name": name, "passed": passed, "message": message}


def _line_of(text: str, needle: str) -> int:
    """1-based line of the first ``needle`` in ``text``, or 0."""
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    return 0


# ---- the registry row, and the roster it proves --------------------------------------------


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
    """The roster, lowercase: the branch's own folder name and every row of its registry."""
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


# ---- stored name fields in the branch's data files ----------------------------------------


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
            checks.append(
                _check(
                    "stored_name",
                    False,
                    f"{rel}:{line} {keys[-1]} '{value}' is not lowercase - {cure.replace('@BRANCH', '@' + branch_root.name.lower())}",
                )
            )
    return checks


# ---- code: a name forced to capitals, or written in capitals -------------------------------


def _names_an_agent(node: ast.AST) -> bool:
    """Whether an expression is visibly an agent's name: one of its identifiers or string keys carries a NAME_WORD."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            word = sub.id
        elif isinstance(sub, ast.Attribute):
            word = sub.attr
        elif isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant):
            word = str(sub.slice.value)
        else:
            continue
        if any(name_word in word.lower() for name_word in NAME_WORDS):
            return True
    return False


def _compared(tree: ast.AST) -> Set[int]:
    """ids of comparison operands, and of a value whose local is read only as one: a case-fold shows nothing."""
    comparisons = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)]
    operands = {id(operand) for node in comparisons for operand in [node.left, *node.comparators]}
    folded = set()
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        reads: Dict[str, List[bool]] = {}
        for node in ast.walk(scope):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                reads.setdefault(node.id, []).append(id(node) in operands)
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if all(reads.get(node.targets[0].id, [False])):
                    folded.add(id(node.value))
    return operands | folded


def _docstrings(tree: ast.AST) -> Set[int]:
    """ids of the module, class and function docstrings: prose, never runtime output."""
    ids: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _capital_names(text: str, names: Set[str]) -> Iterator[str]:
    """Each roster name written in capitals in one string."""
    for match in _TOKEN.finditer(text):
        token = match.group()
        if not token.isupper() or token.lower() not in names:
            continue
        if token.lower() in COMMON_NOUN_NAMES and not any(
            re.search(position.format(t=re.escape(token)), text, re.MULTILINE) for position in _NAME_POSITIONS
        ):
            continue
        yield token


def _token_line(lines: List[str], node: ast.AST, token: str) -> int:
    """The source line a literal's token sits on: a concatenated literal spans lines its value does not show."""
    start = getattr(node, "lineno", 1)
    for number in range(start, (getattr(node, "end_lineno", None) or start) + 1):
        if number <= len(lines) and re.search(rf"\b{re.escape(token)}\b", lines[number - 1]):
            return number
    return start


def code_findings(source: str, filename: str, names: Set[str]) -> List[Tuple[int, str]]:
    """(line, message) for each agent name the code forces to capitals or writes in capitals."""
    tree = parse(source, filename, tag=STANDARD)
    if tree is None:
        return []
    compared, docstrings, lines = _compared(tree), _docstrings(tree), source.splitlines()
    found: Dict[Tuple[int, str], str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in CAPITALISERS
            and id(node) not in compared
            and _names_an_agent(node.func.value)
        ):
            found[(node.lineno, node.func.attr)] = f"an agent name is forced to capitals with .{node.func.attr}()"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            for token in _capital_names(node.value, names):
                found[(_token_line(lines, node, token), token)] = (
                    f"'{token}' is an agent name in capitals - write '{token.lower()}'"
                )
    return sorted((line, message) for (line, _), message in found.items())


def branch_root_of(file_path: Path) -> Path:
    """The branch a file sits in: the nearest folder holding apps/ and .trinity/, else its parent."""
    for parent in file_path.resolve().parents:
        if (parent / "apps").is_dir() and (parent / ".trinity").is_dir():
            return parent
    return file_path.resolve().parent


def _file_checks(path: Path, root: Path, names: Set[str], bypass_rules: Optional[list]) -> List[Dict]:
    """The code leg for one file, each finding named by its branch-relative path and line."""
    source = read_text(path, tag=STANDARD)
    if source is None:
        return [_check("capitalised_name", False, f"{path.name} cannot be read - its code is not judged")]
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name
    return [
        _check("capitalised_name", False, f"{rel}:{line} {message}")
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
        checks = [_check(STANDARD, True, f"every agent name {scope} writes is lowercase")]
    passed = all(check["passed"] for check in checks)
    return result(passed, checks, 100 if passed else 0, STANDARD)


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """The code leg over one file: what the checklist can judge as a file is written."""
    path = Path(module_path).resolve()
    root = branch_root_of(path)
    return _verdict(_file_checks(path, root, agent_names(root), bypass_rules), path.name)


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Every leg over one branch: its registry row, its data files and its code."""
    root = Path(branch_path).resolve()
    names = agent_names(root)
    checks = _registry_checks(root) + _data_checks(root)
    for path in _code_files(root):
        checks.extend(_file_checks(path, root, names, bypass_rules))
    verdict = _verdict(checks, root.name)
    json_handler.log_operation(STANDARD, {"branch": root.name, "findings": 0 if verdict["passed"] else len(checks)})
    return verdict
