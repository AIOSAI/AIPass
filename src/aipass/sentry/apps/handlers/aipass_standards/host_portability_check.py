# =================== AIPass ====================
# Name: host_portability_check.py
# Description: Host Portability Standards Checker Handler
# Version: 1.8.0
# Created: 2026-09-12
# Modified: 2026-11-14
# =============================================

"""Host Portability Standards Checker Handler.

Reference: host_portability.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from aipass.prax import logger
from aipass.sentry.apps.handlers.aipass_standards.applicability import is_retired_path, is_test_path
from aipass.sentry.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS, is_disabled_file
from aipass.sentry.apps.handlers.bypass.ignore_handler import is_sentry_ignored, load_ignore_entries
from aipass.sentry.apps.handlers.bypass.utils import is_bypassed
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers.aipass_standards.check_support import (
    collect_child_linenos,
    find_enclosing_function,
    lines_in_guarded_blocks,
    tail_name,
)

# APPLIES_TO: its own corpus already reads tests/; a missing binary in a test is real.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "HOST_PORTABILITY"
_BYPASS_KEY = "host_portability"

#: Directories this checker never walks, plus the two trees that are not source.
_SKIP_DIRS = SOURCE_SKIP_DIRS

#: The roots a branch's own code lives in: most failures this standard exists to prevent were tests,
#: and skills keeps its built-in skills in lib/. Widened HERE only; the per-file audit corpus stays apps/.
_CORPUS_ROOTS = ("apps", "tests", "lib")

#: Except types that make a missing binary a handled fact rather than a crash.
#: `lines_in_guarded_blocks` already covers OSError and the import family;
#: FileNotFoundError and the broad catches are added here.
_FS_EXCEPT_TYPES = frozenset(
    {
        "FileNotFoundError",
        "NotADirectoryError",
        "IsADirectoryError",
        "IOError",
        "EnvironmentError",
        "Exception",
        "BaseException",
    }
)

#: The pytest context that expects an exception; around a missing-file error it is a guard.
RAISES = "raises"

#: The ONLY argv[0] names read. Measured, not imagined: each one is absent on
#: at least one Linux host (a container, a CI runner, a desktop without that terminal).
_NON_PORTABLE_BINARIES = frozenset(
    {
        "tmux",
        "systemctl",
        "loginctl",
        "sysctl",
        "gnome-terminal",
        "xfce4-terminal",
        "konsole",
        "xterm",
    }
)

#: Portable enough that scoring them adds 134 rows and no bugs. Named rather
#: than merely omitted so a later reader knows the omission was a decision.
PORTABLE_BINARIES = frozenset(
    {"git", "bash", "sh", "drone", "python3", "sleep", "gh", "ps", "lsof", "pgrep", "npm", "ruff"}
)

_SUBPROCESS_RUNNERS = frozenset({"run", "Popen", "check_output", "call", "check_call"})

#: Below this the branch fails the standard, matching every other checker here.
PASS_THRESHOLD = 75

#: Arm D: the generic classes whose __new__ picks a flavour. A concrete flavour
#: (PosixPath, PurePosixPath, ...) carries its own _flavour on every Python.
_FLAVOURLESS_BASES = frozenset({"Path", "PurePath"})
_FLAVOUR_FIX = "below Python 3.12 Path.__new__ needs _flavour on the subclass (AttributeError on 3.10 and 3.11)"

#: Arm G: (since, backport). shortcut: backported modules only; add a 3.14 module when a floor allows one.
_VERSION_BOUND = {
    "tomllib": ((3, 11), "tomli"),
    "zoneinfo": ((3, 9), "backports.zoneinfo"),
    "graphlib": ((3, 9), "graphlib_backport"),
}
_FLOOR = re.compile(r"""^requires-python\s*=\s*["']\s*>=\s*3\.(\d+)""", re.MULTILINE)
_SCOPE_EDGES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

#: Arm E: the two spellings a path can carry. RESOLVED passed through
#: ``.resolve()`` / ``os.path.realpath`` (or a same-file helper that returns
#: one); AS_GIVEN is the host's own answer, which keeps a symlinked prefix.
RESOLVED = "resolved"
AS_GIVEN = "as given"
#: Calls whose answer keeps the spelling the host hands out (a home or temp dir reached through a symlink).
_HOST_SPELLINGS = (
    "Path.home",
    "Path.cwd",
    "os.getcwd",
    "tempfile.gettempdir",
    "tempfile.mkdtemp",
    "tempfile.TemporaryDirectory",
)
#: Calls and methods that carry their first argument's (or receiver's) spelling through.
_CARRYING_WRAPPERS = frozenset({"str", "Path", "PurePath", "PosixPath", "os.fspath", "os.path.join"})
_CARRYING_METHODS = frozenset({"as_posix", "joinpath", "absolute", "with_name", "with_suffix"})
#: Methods that compare two paths' spellings.
_PATH_COMPARISONS = frozenset({"relative_to", "is_relative_to", "startswith"})
_SPELLING_FIX = (
    "one side passes through resolve(), the other is Path.home()/Path.cwd()/os.getcwd()/tempfile as given; "
    "a symlinked prefix (a home or temp dir reached through a symlink) makes them differ - resolve both"
)


def _handler_catches(handler: ast.ExceptHandler, wanted: frozenset) -> bool:
    """True if this except clause names one of ``wanted`` (or is bare)."""
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id in wanted
    if isinstance(handler.type, ast.Tuple):
        return any(isinstance(elt, ast.Name) and elt.id in wanted for elt in handler.type.elts)
    return False


def _fs_except_lines(tree: ast.Module) -> Set[int]:
    """Lines inside a try that catches a missing-file / broad error.

    Union this with ``lines_in_guarded_blocks``, which already covers OSError
    and the import family but not FileNotFoundError or ``except Exception``.
    """
    lines: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(_handler_catches(h, _FS_EXCEPT_TYPES) for h in node.handlers):
            lines.update(collect_child_linenos(node))
        if isinstance(node, (ast.With, ast.AsyncWith)) and any(_expects_missing(i.context_expr) for i in node.items):
            lines.update(collect_child_linenos(node))
    return lines


def _expects_missing(context: ast.expr) -> bool:
    """``pytest.raises(X)`` where X is a missing-file error: the test passes on every host.

    A missing binary inside it raises where the host lacks it, which is what the test claims.
    """
    if not (isinstance(context, ast.Call) and tail_name(context.func) == RAISES and context.args):
        return False
    expected = context.args[0]
    names = expected.elts if isinstance(expected, ast.Tuple) else [expected]
    return any(tail_name(name) in _FS_EXCEPT_TYPES | {"OSError"} for name in names)


def _subprocess_aliases(tree: ast.Module) -> frozenset:
    """Names this module calls the subprocess module by."""
    names: Set[str] = {"subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess" and alias.asname:
                    names.add(alias.asname)
    return frozenset(names)


def _runner_argv0(node: ast.Call, aliases: frozenset) -> str:
    """The bare literal argv[0] of a subprocess runner call, or "".

    A Name, a starred element or an f-string argv[0] returns "" on purpose: a dynamic spelling is usually the cure.
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _SUBPROCESS_RUNNERS:
        return ""
    if not (isinstance(func.value, ast.Name) and func.value.id in aliases):
        return ""
    if not node.args:
        return ""
    argv = node.args[0]
    if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
        return ""
    head = argv.elts[0]
    if isinstance(head, ast.Constant) and isinstance(head.value, str):
        return head.value
    return ""


def _which_guarded_names(func: ast.AST) -> Set[str]:
    """Binary names this function probes with ``shutil.which(...)``."""
    probed: Set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        called_which = (isinstance(target, ast.Attribute) and target.attr == "which") or (
            isinstance(target, ast.Name) and target.id == "which"
        )
        if not called_which or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            probed.add(first.value)
    return probed


def _binary_violations(tree: ast.Module) -> Tuple[List[Tuple[int, str]], int]:
    """Arm B: a non-portable binary run with nothing standing behind it.

    Returns the violations and the count of sites that acquitted, so the
    message can say how much of the picture the score is NOT carrying.
    """
    aliases = _subprocess_aliases(tree)
    nominations: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _runner_argv0(node, aliases)
        if name in _NON_PORTABLE_BINARIES:
            nominations.append((node.lineno, name))
    if not nominations:
        return [], 0

    handled = lines_in_guarded_blocks(tree) | _fs_except_lines(tree)

    violations: List[Tuple[int, str]] = []
    acquitted = 0
    for lineno, name in nominations:
        if lineno in handled:
            acquitted += 1
            continue
        enclosing = find_enclosing_function(tree, lineno)
        if enclosing is not None and name in _which_guarded_names(enclosing):
            acquitted += 1
            continue
        violations.append(
            (
                lineno,
                f"runs {name!r} with no shutil.which({name!r}) probe or "
                "FileNotFoundError handler - a missing binary raises out of exec, "
                "so check=False does not help",
            )
        )
    return violations, acquitted


def _flavourless_subclasses(tree: ast.Module) -> List[Tuple[int, str]]:
    """Classes whose base is ``Path`` or ``PurePath`` itself and carry no ``_flavour``."""
    violations: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {tail_name(base) for base in node.bases} & _FLAVOURLESS_BASES
        carried = any("_flavour" in ast.dump(statement) for statement in node.body)
        if bases and not carried:
            violations.append((node.lineno, f"class {node.name}({min(bases)}) - {_FLAVOUR_FIX}"))
    return violations


def _dotted(node: ast.expr) -> str:
    """``a.b.c`` for a Name/Attribute chain, else ''."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _is_host_spelling(call: ast.Call) -> bool:
    """Path.home() / Path.cwd() / os.getcwd() / tempfile.* as the host hands it out."""
    dotted = _dotted(call.func)
    return any(dotted == name or dotted.endswith("." + name) for name in _HOST_SPELLINGS)


def _call_spelling(call: ast.Call, env: Dict[str, str], funcs: Dict[str, str]) -> str:
    """The spelling a call's result carries: RESOLVED, AS_GIVEN or '' (unknown)."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "resolve":
        return RESOLVED
    if _dotted(func) == "os.path.realpath":
        return RESOLVED
    if _is_host_spelling(call):
        return AS_GIVEN
    if isinstance(func, ast.Name) and func.id in funcs:
        return funcs[func.id]
    if (_dotted(func) in _CARRYING_WRAPPERS or tail_name(func) in _CARRYING_WRAPPERS) and call.args:
        return _spelling(call.args[0], env, funcs)
    if isinstance(func, ast.Attribute) and func.attr in _CARRYING_METHODS:
        return _spelling(func.value, env, funcs)
    return ""


def _spelling(node: ast.expr, env: Dict[str, str], funcs: Dict[str, str]) -> str:
    """RESOLVED when the value passed through resolve(), AS_GIVEN when it is the host's spelling, else ''."""
    if isinstance(node, ast.Call):
        return _call_spelling(node, env, funcs)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _spelling(node.left, env, funcs)
    if isinstance(node, ast.Attribute) and node.attr in ("parent", "parents"):
        return _spelling(node.value, env, funcs)
    if isinstance(node, ast.Subscript):
        return _spelling(node.value, env, funcs)
    if isinstance(node, ast.Name):
        return env.get(node.id, "")
    if isinstance(node, (ast.Tuple, ast.List)) and node.elts:
        kinds = {_spelling(element, env, funcs) for element in node.elts}
        return kinds.pop() if len(kinds) == 1 else ""
    if isinstance(node, (ast.GeneratorExp, ast.ListComp)):
        return _spelling(node.elt, env, funcs)
    return ""


def _bind(target: ast.expr, value: ast.expr, env: Dict[str, str], funcs: Dict[str, str]) -> None:
    """Record the spelling each assigned name now carries (last assignment wins)."""
    if isinstance(target, ast.Name):
        env[target.id] = _spelling(value, env, funcs)
    elif isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts):
            kinds = [_spelling(element, env, funcs) for element in value.elts]
        else:
            kinds = [_spelling(value, env, funcs)] * len(target.elts)
        for element, kind in zip(target.elts, kinds):
            if isinstance(element, ast.Name):
                env[element.id] = kind


def _own_nodes(func: ast.AST) -> List[ast.AST]:
    """Every node in *func*'s body, nested defs and lambdas excluded, in source order."""
    found: List[ast.AST] = []
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return sorted(found, key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)))


def _compared_pairs(node: ast.AST) -> List[Tuple[ast.expr, ast.expr]]:
    """The (left, right) operand pairs a node compares as paths, else []."""
    if isinstance(node, ast.Compare):
        pairs: List[Tuple[ast.expr, ast.expr]] = []
        operands = [node.left, *node.comparators]
        for left, op, right in zip(operands, node.ops, operands[1:]):
            if isinstance(op, (ast.Eq, ast.NotEq)):
                pairs.append((left, right))
            elif isinstance(op, (ast.In, ast.NotIn)) and isinstance(right, ast.Attribute) and right.attr == "parents":
                pairs.append((left, right.value))
        return pairs
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _PATH_COMPARISONS
        and len(node.args) == 1
        and not isinstance(node.args[0], ast.Tuple)
    ):
        return [(node.func.value, node.args[0])]
    return []


def _bind_statement(node: ast.AST, env: Dict[str, str], funcs: Dict[str, str]) -> None:
    """Apply one assignment, annotated assignment or ``with ... as`` to *env*."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            _bind(target, node.value, env, funcs)
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        _bind(node.target, node.value, env, funcs)
    elif isinstance(node, ast.withitem) and node.optional_vars is not None:
        _bind(node.optional_vars, node.context_expr, env, funcs)


def _walk_function(func: ast.AST, funcs: Dict[str, str]) -> Tuple[List[str], List[Tuple[int, ast.AST]]]:
    """One pass over *func* in source order: (spellings of its returns, mixed comparisons)."""
    env: Dict[str, str] = {}
    returns: List[str] = []
    mixed: List[Tuple[int, ast.AST]] = []
    for node in _own_nodes(func):
        kinds = [{_spelling(left, env, funcs), _spelling(right, env, funcs)} for left, right in _compared_pairs(node)]
        if {RESOLVED, AS_GIVEN} in kinds:
            mixed.append((getattr(node, "lineno", 0), node))
        if isinstance(node, ast.Return) and node.value is not None:
            returns.append(_spelling(node.value, env, funcs))
        _bind_statement(node, env, funcs)
    return returns, mixed


def _function_spellings(tree: ast.Module) -> Dict[str, str]:
    """Same-file module-level functions whose every known return carries one spelling.

    ``aipass_home()`` returns ``_absolute(raw)`` (RESOLVED) or None: RESOLVED.
    ``_search_bounds()`` returns ``Path.cwd(), Path.home()``: AS_GIVEN. Iterated to
    a fixed point so a helper of a helper is followed, inside this file only.
    """
    defs = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    funcs: Dict[str, str] = {}
    for _round in range(len(defs) + 1):
        changed = False
        for func in defs:
            kinds = {kind for kind in _walk_function(func, funcs)[0] if kind}
            spelling = kinds.pop() if len(kinds) == 1 else ""
            if spelling and funcs.get(func.name) != spelling:
                funcs[func.name] = spelling
                changed = True
        if not changed:
            break
    return funcs


def _mixed_spelling_comparisons(tree: ast.Module) -> List[Tuple[int, str]]:
    """In one function, a resolve()d path compared with Path.home()/cwd()/tempfile as given."""
    funcs = _function_spellings(tree)
    violations: List[Tuple[int, str]] = []
    seen: Set[int] = set()
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for lineno, node in _walk_function(func, funcs)[1]:
            if lineno in seen:
                continue
            seen.add(lineno)
            text = ast.unparse(node)
            text = text if len(text) <= 80 else text[:77] + "..."
            violations.append((lineno, f"`{text}` - {_SPELLING_FIX}"))
    return violations


#: Either one empties git's config; then nothing on the host answers who commits.
_GIT_CONFIG_EMPTIERS = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"})
#: git resolves author and committer separately, and the email is what a runner cannot auto-detect.
_COMMIT_EMAILS = ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL")
_IDENTITY_FIX = "a CI runner has no email git can auto-detect, so git commit exits 128; set "


def _unanswered_git_identity(tree: ast.Module) -> List[Tuple[int, str]]:
    """A file that empties git's config names no commit email: green only where the host supplies one.

    File-local: a fixture cannot know which consumer commits, so the file that empties the config answers.
    """
    strings = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    emptied = sorted(lineno for lineno, value in strings if value in _GIT_CONFIG_EMPTIERS)
    if not emptied or any("user.email" in value for _lineno, value in strings):
        return []
    named = {value for _lineno, value in strings}
    missing = [name for name in _COMMIT_EMAILS if name not in named]
    if not missing:
        return []
    return [(emptied[0], f"empties git's config, no {' or '.join(missing)} - {_IDENTITY_FIX}{', '.join(missing)}")]


def _imported_modules(node: ast.AST) -> List[str]:
    """The absolute module names an import statement loads."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and not node.level and node.module:
        return [node.module]
    return []


def _version_bound_imports(tree: ast.Module, floor: Tuple[int, int] | None) -> List[Tuple[int, str]]:
    """An import of a stdlib module newer than the declared floor whose guard never imports its backport.

    A degraded except branch runs only on the floor's CI lane; tests written on a newer seat pin the other answer.
    """
    if floor is None:
        return []
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    violations: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for name in _imported_modules(node):
            since, backport = _VERSION_BOUND.get(name, (floor, ""))
            if since <= floor:
                continue
            guard = parents.get(node)
            while guard is not None and not isinstance(guard, (ast.Try, ast.If, *_SCOPE_EDGES)):
                guard = parents.get(guard)
            if isinstance(guard, (ast.Try, ast.If)) and any(
                backport in _imported_modules(inner) for inner in ast.walk(guard)
            ):
                continue
            violations.append(
                (
                    node.lineno,
                    f"import {name} - stdlib from {since[0]}.{since[1]}, the declared floor is {floor[0]}.{floor[1]}: "
                    f"fall back to `import {backport} as {name}` in the same try, so the floor's lane runs "
                    "the answer every other lane tests",
                )
            )
    return violations


#: Tests an empty directory passes; ``is_file`` is not here because a sandbox mounts directories only.
_DIR_PASSING = frozenset({"exists", "is_dir", "isdir"})
_EMPTY_GIT_FIX = (
    "an empty directory passes, and a sandbox mounts an empty .git in each writable root; "
    "accept `marker.is_file() or (marker.is_dir() and any(marker.iterdir()))`"
)


def _names_git(node: ast.expr) -> bool:
    """``x / ".git"`` or ``os.path.join(..., ".git")``."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        last = node.right
    elif isinstance(node, ast.Call) and node.args and tail_name(node.func) == "join":
        last = node.args[-1]
    else:
        return False
    return isinstance(last, ast.Constant) and last.value == ".git"


def _operand(call: ast.Call) -> ast.expr | None:
    """The path a call is about: ``os.path.f(x)``'s x, else ``x.f()``'s x."""
    if call.args:
        return call.args[0]
    return call.func.value if isinstance(call.func, ast.Attribute) else None


def _opens_marker(node: ast.AST) -> bool:
    """``.git / "HEAD"``, ``join(..., ".git", "HEAD")``, or a listing of ``.git`` itself."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return isinstance(node.right, ast.Constant) and node.right.value == "HEAD" and _names_git(node.left)
    if not isinstance(node, ast.Call):
        return False
    if tail_name(node.func) == "join" and len(node.args) > 1:
        tail = [arg.value if isinstance(arg, ast.Constant) else None for arg in node.args[-2:]]
        return tail == [".git", "HEAD"]
    operand = _operand(node)
    return tail_name(node.func) in {"iterdir", "listdir", "scandir"} and operand is not None and _names_git(operand)


def _reads_inside(func: ast.AST | None) -> bool:
    """The enclosing function also looks inside the marker, not merely at its name."""
    return func is not None and any(_opens_marker(node) for node in ast.walk(func))


def _empty_git_markers(tree: ast.Module) -> List[Tuple[int, str]]:
    """A .git existence test that an empty directory satisfies, in a function that never looks inside."""
    violations: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _DIR_PASSING:
            continue
        operand = _operand(node)
        if operand is None or not _names_git(operand) or _reads_inside(find_enclosing_function(tree, node.lineno)):
            continue
        violations.append((node.lineno, f"`{ast.unparse(node)}` - {_EMPTY_GIT_FIX}"))
    return violations


def _declared_floor(branch_root: Path) -> Tuple[int, int] | None:
    """The nearest pyproject.toml's ``requires-python >=3.N``; None when none declares one.

    An unreadable pyproject raises: a floor nobody could read is not a floor nobody declared."""
    for folder in (branch_root, *branch_root.parents):
        pyproject = folder / "pyproject.toml"
        if not pyproject.is_file():
            continue
        match = _FLOOR.search(pyproject.read_text(encoding="utf-8"))
        return (3, int(match.group(1))) if match else None
    return None


def _corpus_files(branch_root: Path, ignore_entries: list) -> List[Path]:
    """Every auditable .py file under apps/, tests/ and lib/."""
    files: List[Path] = []
    for root_name in _CORPUS_ROOTS:
        root = branch_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if is_disabled_file(path.name) or is_retired_path(str(path)):
                continue
            if is_sentry_ignored(str(path), branch_root, ignore_entries):
                continue
            files.append(path)
    return files


def _relative(path: Path, branch_root: Path) -> str:
    """Branch-relative posix path, falling back to the absolute one."""
    try:
        return path.relative_to(branch_root).as_posix()
    except ValueError as exc:
        logger.info("[host_portability] %s not relative to %s: %s", path, branch_root, exc)
        return path.as_posix()


def scan_file(file_path: str, floor: Tuple[int, int] | None = None) -> Tuple[List[Tuple[int, str]], int]:
    """Every arm (B, D to H) over one file. Returns (violations, acquitted binary sites).

    Arm G runs only with the branch's declared ``floor``; arm H only outside a test tree, whose fixtures plant .git.

    A file that cannot be read or parsed reports NOTHING: an unparseable file is ruff's business.
    """
    path = Path(file_path)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[host_portability] cannot read %s: %s", path, exc)
        return [], 0
    try:
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, ValueError) as exc:
        logger.info("[host_portability] skipped %s: %s", path, exc)
        return [], 0

    violations, acquitted = _binary_violations(tree)
    violations.extend(_flavourless_subclasses(tree))
    violations.extend(_mixed_spelling_comparisons(tree))
    violations.extend(_unanswered_git_identity(tree))
    violations.extend(_version_bound_imports(tree, floor))
    if not is_test_path(str(path)):
        violations.extend(_empty_git_markers(tree))
    violations.sort(key=lambda row: row[0])
    return violations, acquitted


def _result(score: int, checks: List[Dict], branch_path: str) -> Dict:
    """The pack's result shape, logged once."""
    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": score, "standard": _BYPASS_KEY},
    )
    return {
        "passed": score >= PASS_THRESHOLD,
        "checks": checks,
        "score": score,
        "standard": STANDARD_NAME,
    }


def _violation_items(rows: Iterable[Tuple[str, int, str]]) -> List[Dict]:
    """Violations in the shape branch_audit's display reader expects."""
    return [{"file": rel, "line": lineno, "name": detail} for rel, lineno, detail in rows]


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch for host assumptions: a missing binary, a 3.12-only Path subclass, an empty .git as a repo."""
    branch_root = Path(branch_path)

    if is_bypassed(branch_path, _BYPASS_KEY, bypass_rules=bypass_rules):
        return _result(
            100,
            [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .sentry/bypass.json"}],
            branch_path,
        )

    ignore_entries = load_ignore_entries(branch_root)
    files = _corpus_files(branch_root, ignore_entries)
    floor = _declared_floor(branch_root.resolve())
    if not files:
        return _result(
            100,
            [{"name": "Host portability", "passed": True, "message": "No apps/, tests/ or lib/ Python files to check"}],
            branch_path,
        )

    rows: List[Tuple[str, int, str]] = []
    dirty_files: Set[str] = set()
    acquitted_total = 0
    for path in files:
        rel = _relative(path, branch_root)
        violations, acquitted = scan_file(str(path), floor)
        acquitted_total += acquitted
        for lineno, detail in violations:
            if is_bypassed(rel, _BYPASS_KEY, lineno, bypass_rules):
                continue
            rows.append((rel, lineno, detail))
            dirty_files.add(rel)

    score = int((len(files) - len(dirty_files)) / len(files) * 100)
    checks: List[Dict] = []

    if rows:
        preview = "; ".join(f"{rel}:{lineno} {detail.split(' - ')[0]}" for rel, lineno, detail in rows[:3])
        suffix = f" (and {len(rows) - 3} more)" if len(rows) > 3 else ""
        checks.append(
            {
                "name": "Host portability",
                "passed": False,
                "message": (
                    f"{len(rows)} host assumption(s) in {len(dirty_files)}/{len(files)} files: {preview}{suffix}"
                ),
                "violations": _violation_items(rows),
            }
        )
    else:
        checks.append(
            {
                "name": "Host portability",
                "passed": True,
                "message": f"No host assumptions in {len(files)} files",
            }
        )

    if acquitted_total:
        checks.append(
            {
                "name": "Handled binary calls",
                "passed": True,
                "message": (
                    f"{acquitted_total} call(s) to a non-portable binary already carry a "
                    "shutil.which() probe or a FileNotFoundError handler "
                    "- context, not scored"
                ),
            }
        )

    return _result(score, checks, branch_path)
