# =================== AIPass ====================
# Name: stdlib_patch_check.py
# Description: Stdlib Patch Standards Checker Handler
# Version: 1.3.1
# Created: 2026-09-22
# Modified: 2026-10-24
# =============================================

"""
Stdlib Patch Standards Checker Handler

Reference: stdlib_patch.md
"""

from functools import partial
import ast
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import module_constants
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse, read_text, result, tail_name

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "STDLIB_PATCH"
STANDARD_KEY = "stdlib_patch"

#: The product's import root.
PRODUCT = "aipass"

#: The three verbs that replace a name rather than run it.
_PATCH_VERBS: frozenset[str] = frozenset({"patch", "object", "setattr"})

#: Edges a test must seal. No product-local seam would serve better.
_EDGE_MODULES: frozenset[str] = frozenset(
    {"subprocess", "socket", "urllib", "http", "smtplib", "ssl", "ftplib", "asyncio", "select"}
)

#: The interpreter's own I/O and module table, and the environment.
_EDGE_ATTRIBUTES: frozenset[str] = frozenset(
    {"sys.argv", "sys.stdout", "sys.stderr", "sys.stdin", "sys.path", "sys.modules", "sys.meta_path", "os.environ"}
)

CURE = "give the product a seam and patch that, or assert the effect on disk"


def _dotted(node: ast.AST) -> str:
    """A target written out: ``ceiling.os.path`` from its Attribute chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


@lru_cache(maxsize=1)
def _source_root() -> Path:
    """The directory the ``aipass`` package sits in, for the on-disk check."""
    here = Path(__file__).resolve()
    for index, part in enumerate(here.parts):
        if part == PRODUCT:
            return Path(*here.parts[:index])
    return here.parent


def _module_file(dotted: str) -> Path | None:
    """The source file for ``aipass.a.b``, as a module or a package."""
    base = _source_root().joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=2048)
def is_product_module(dotted: str) -> bool:
    """Whether ``aipass.a.b`` names a real file or package on disk.

    The whole defence against a name collision: ``aipass...contacts.email`` is @ai_mail's own module,
    not stdlib ``email``, and only the filesystem can say so.
    """
    return _module_file(dotted) is not None


@lru_cache(maxsize=2048)
def bound_to(dotted: str, name: str) -> str | None:
    """What ``name`` inside product module ``dotted`` was imported from.

    ``upload.Path`` is ``pathlib.Path`` because ``upload.py`` imports it; a class the module DEFINES answers "".
    None when the module cannot be read or parsed: an unread import list is not an acquittal.
    """
    source = _module_file(dotted)
    if source is None:
        return ""
    try:
        tree = ast.parse(source.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError, ValueError) as exc:
        logger.info("[stdlib_patch] Cannot read %s: %s", source, exc)
        return None
    return _imports(tree).get(name, "")


def _imports(tree: ast.Module) -> Dict[str, str]:
    """Local name -> the dotted module or member it was imported from.

    A RELATIVE import keeps its leading dots, so ``from ..json import json_handler`` has an empty root,
    neither ``aipass`` nor stdlib, and a sibling package is never mistaken for stdlib ``json``.
    """
    found: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            here = "." * node.level
            for alias in node.names:
                origin = f"{node.module}.{alias.name}" if node.module else alias.name
                found[alias.asname or alias.name] = f"{here}{origin}"
    return found


def _through_product(segments: List[str]) -> str | None:
    """The stdlib module reached THROUGH an aipass path, "" if none is, None if unread.

    ``ceiling.os.path`` resolves to ``aipass.backup...ceiling.os.path``: walk
    the chain while it is still a real product module, and the first segment
    that leaves the product is the one to judge.

    A stdlib CLASS (``upload.Path``) does not announce itself as a module does, so the name is resolved
    through the product module's own imports; a class the module DEFINES still answers "".
    """
    for index in range(1, len(segments)):
        prefix = segments[: index + 1]
        if is_product_module(".".join(prefix)):
            continue
        name = segments[index]
        if name in sys.stdlib_module_names:
            return name
        origin = bound_to(".".join(segments[:index]), name)
        if origin is None:
            return None
        root = origin.split(".")[0]
        return root if root in sys.stdlib_module_names and not is_product_module(root) else ""
    return ""


def _resolve(target: ast.AST, imports: Dict[str, str], constants: Dict[str, str]) -> str:
    """The target as a fully dotted path, or "" when nothing can resolve it.

    An f-string resolves when every field is a module-level string constant (``module_constants.joined_text``).
    """
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value
    if isinstance(target, ast.JoinedStr):
        return module_constants.joined_text(target, constants)
    written = _dotted(target)
    if not written:
        return ""
    head, _, rest = written.partition(".")
    if head not in imports:
        return ""
    return f"{imports[head]}.{rest}" if rest else imports[head]


def _target(node: ast.Call, imports: Dict[str, str], constants: Dict[str, str], source: str) -> Tuple[str, str]:
    """(as written, fully dotted) for a patch call's target, its attribute included.

    ``patch.object(sys, "argv", ...)`` names the object first and the attribute second; reading the first
    alone would judge a patch of all of ``sys``. The attribute is joined only onto a stdlib object.
    """
    first = node.args[0]
    if isinstance(first, ast.JoinedStr):
        written = ast.get_source_segment(source, first) or ""
    else:
        written = str(_dotted(first) or getattr(first, "value", ""))
    chain = _resolve(first, imports, constants)
    second = node.args[1] if len(node.args) > 1 else None
    attribute = second.value if isinstance(second, ast.Constant) and isinstance(second.value, str) else ""
    if attribute and tail_name(node.func) in ("object", "setattr") and not isinstance(first, ast.Constant):
        if chain and chain.split(".")[0] != PRODUCT:
            return written, f"{chain}.{attribute}"
    return written, chain


def _sanctioned(chain: str, module: str) -> bool:
    """Whether this target is an edge the test is right to seal."""
    return module in _EDGE_MODULES or any(seam in chain for seam in _EDGE_ATTRIBUTES)


def _module_of(chain: str) -> str | None:
    """The stdlib module this target lands in, "" when it is product code, None if unread."""
    segments = chain.split(".")
    if segments[0] == PRODUCT:
        return _through_product(segments)
    return segments[0] if segments[0] in sys.stdlib_module_names else ""


_parse = partial(parse, tag="stdlib_patch")


def scan(source: str, path: Path | None = None) -> Tuple[List[Tuple[int, str, str]], int]:
    """((line, target, module) scored, how many targets could not be resolved).

    ``path`` lets a constant imported from the file's own ``support_*.py`` resolve like a local one.
    """
    tree = _parse(source)
    if tree is None:
        return [], 0

    imports = _imports(tree)
    constants = module_constants.file_constants(tree, path)
    scored: List[Tuple[int, str, str]] = []
    unresolved = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or tail_name(node.func) not in _PATCH_VERBS or not node.args:
            continue
        written, chain = _target(node, imports, constants, source)
        if not chain:
            unresolved += 1
            continue
        module = _module_of(chain)
        if module is None:
            unresolved += 1
            continue
        if not module or _sanctioned(chain, module):
            continue
        scored.append((node.lineno, str(written), module))
    return sorted(scored), unresolved


_read = partial(read_text, tag="stdlib_patch", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Stdlib patch", "passed": passed, "message": message}]


def _clean_message(unresolved: int) -> str:
    """The passing message, carrying the unresolved count without a verdict."""
    if not unresolved:
        return "Every patch here targets product code or an edge worth sealing"
    shape = "target" if unresolved == 1 else "targets"
    return (
        f"Every patch here targets product code or an edge worth sealing "
        f"({unresolved} locally-bound {shape} could not be resolved and were not judged)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for patches of stdlib work the product owns."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    scored, unresolved = scan(source, path)
    # A rule with `lines` acquits those rows alone: the file-level ask above passes no line.
    scored = [
        row for row in scored if not is_bypassed(module_path, STANDARD_KEY, line=row[0], bypass_rules=bypass_rules)
    ]
    if not scored:
        return _result(True, _one_check(True, _clean_message(unresolved)), 100)

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    detail = "\n".join(
        f"{path.name}:{line} {target} replaces {module} process-wide - {CURE}" for line, target, module in scored
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(scored)},
    )
    return _result(False, _one_check(False, detail), 0)
