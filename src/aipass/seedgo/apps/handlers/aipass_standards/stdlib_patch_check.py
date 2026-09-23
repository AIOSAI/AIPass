# =================== AIPass ====================
# Name: stdlib_patch_check.py
# Description: Stdlib Patch Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Stdlib Patch Standards Checker Handler

Crack class Q from the 2026-09-22 eyes-on review of @backup's tests: a
``patch`` whose target is a STDLIB function the product calls to do its own
work. Replacing it is process-wide, and the oracle becomes spelling-specific --
the test passes only while the product keeps reaching that exact name.

``test_ceiling_guard.py:103`` is the evidence line and the perfect shape::

    with patch.object(ceiling.os.path, "getsize", side_effect=AssertionError):

``ceiling.os`` IS the real ``os``. That line replaces ``posixpath.getsize`` for
every module in the process. Rewrite ``check_ceiling`` to use ``Path.stat()``
-- the same measurement, a different spelling -- and the guard silently stops
being tested.

THE JUDGEMENT THE DISPATCH ASKED ME TO NAME: which non-aipass targets are
sanctioned, and why. The line is not "stdlib versus product", it is:

  SANCTIONED -- an EDGE the test must seal. A process, the network, the
  environment, the interpreter's own I/O and module table. Sealing an edge is
  what a test is supposed to do, and there is no product-local seam that would
  be better:
      subprocess, socket, urllib, http, smtplib, ssl, ftplib, asyncio, select
      sys.argv  sys.stdout  sys.stderr  sys.stdin  sys.path  sys.modules
      os.environ
  819 hits acquitted, 662 of them ``subprocess``. Running a real subprocess in
  a unit test is the defect; patching it is the cure.

  SCORED -- the product's OWN work, done through the stdlib. The filesystem,
  the clock, serialisation, imports, ``open``. The product could have been
  given a seam and was not, so the test reaches around it into a shared
  namespace:
      importlib 218 | sys (not the six above) 211 | os 126 | builtins 97 |
      pathlib 94 | shutil 93 | time 54 | tempfile 9 | inspect 5 | signal 3 |
      logging 2 | datetime 2

FOUR CUTS, 6,926 -> 916, and the third is the one worth remembering:

  raw dotted root                             363 files, 6,926 hits
  the root resolved through the file's imports 208 files, 1,993 hits
  aipass name-collisions checked ON DISK       175 files, 1,584 hits
  edges sanctioned                             155 files,   916 hits

``aipass/ai_mail/apps/handlers/contacts/email.py`` is a product module whose
name collides with stdlib ``email``, and 291 hits were that one collision. A
segment is only stdlib when the aipass path up to it does NOT exist as a file
on disk. Guessing from the name alone convicts a third of @ai_mail.

WHAT IT REFUSES TO JUDGE, reported with a count: 2,246 targets bound to a local
name by assignment rather than an import (``mod = importlib.import_module(...)``
then ``patch.object(mod.os, ...)``). The AST cannot say what ``mod`` is, so the
rule says nothing. That is the honest edge of a resolution-based rule, and it
is larger than everything it convicts.

THE DISPATCH'S FIRST CUT SAID 53 FILES AND 362 HITS. This is 155 and 916, and I
have not tuned toward the smaller number: the sanctioned list above is drawn on
the edge/own-work line, not on where the count lands.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: a patched stdlib name is replaced for
the whole process, so the test pins the product's SPELLING rather than its
behaviour. Change the spelling without changing the behaviour and the test
stops testing anything, silently. There is no threshold and nothing to tune.
"""

import ast
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

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
    {"sys.argv", "sys.stdout", "sys.stderr", "sys.stdin", "sys.path", "sys.modules", "os.environ"}
)

CURE = "give the product a seam and patch that, or assert the effect on disk"


def _tail_name(node: ast.AST) -> str:
    """The last name in a call target: ``a.b.c`` -> ``c``, ``f`` -> ``f``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


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


@lru_cache(maxsize=2048)
def is_product_module(dotted: str) -> bool:
    """Whether ``aipass.a.b`` names a real file or package on disk.

    The whole defence against a name collision. ``aipass...contacts.email`` is
    @ai_mail's own module, not stdlib ``email``, and only the filesystem can
    say so -- that one collision was 291 false convictions.
    """
    base = _source_root().joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _imports(tree: ast.Module) -> Dict[str, str]:
    """Local name -> the dotted module or member it was imported from."""
    found: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                found[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return found


def _through_product(segments: List[str]) -> str:
    """The stdlib module reached THROUGH an aipass path, or "" if none is.

    ``ceiling.os.path`` resolves to ``aipass.backup...ceiling.os.path``: walk
    the chain while it is still a real product module, and the first segment
    that is stdlib AND is not a product module on disk is the answer.
    """
    for index in range(1, len(segments)):
        prefix = segments[: index + 1]
        if is_product_module(".".join(prefix)):
            continue
        return segments[index] if segments[index] in sys.stdlib_module_names else ""
    return ""


def _resolve(target: ast.AST, imports: Dict[str, str]) -> str:
    """The target as a fully dotted path, or "" when nothing can resolve it."""
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value
    written = _dotted(target)
    if not written:
        return ""
    head, _, rest = written.partition(".")
    if head not in imports:
        return ""
    return f"{imports[head]}.{rest}" if rest else imports[head]


def _sanctioned(chain: str, module: str) -> bool:
    """Whether this target is an edge the test is right to seal."""
    return module in _EDGE_MODULES or any(seam in chain for seam in _EDGE_ATTRIBUTES)


def _module_of(chain: str) -> str:
    """The stdlib module this target lands in, or "" when it is product code."""
    segments = chain.split(".")
    if segments[0] == PRODUCT:
        return _through_product(segments)
    return segments[0] if segments[0] in sys.stdlib_module_names else ""


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[stdlib_patch] Unparseable, nothing scanned: %s", exc)
        return None


def scan(source: str) -> Tuple[List[Tuple[int, str, str]], int]:
    """((line, target, module) scored, how many targets could not be resolved)."""
    tree = _parse(source)
    if tree is None:
        return [], 0

    imports = _imports(tree)
    scored: List[Tuple[int, str, str]] = []
    unresolved = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _tail_name(node.func) not in _PATCH_VERBS or not node.args:
            continue
        written = _dotted(node.args[0]) or getattr(node.args[0], "value", "")
        chain = _resolve(node.args[0], imports)
        if not chain:
            unresolved += 1
            continue
        module = _module_of(chain)
        if not module or _sanctioned(chain, module):
            continue
        scored.append((node.lineno, str(written), module))
    return sorted(scored), unresolved


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[stdlib_patch] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


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
    """Check a test file for patches of stdlib work the product owns.

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

    scored, unresolved = scan(source)
    if not scored:
        return _result(True, _one_check(True, _clean_message(unresolved)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per patch would show the
    # first and hide the rest behind a count.
    detail = "\n".join(
        f"{path.name}:{line} {target} replaces {module} process-wide - {CURE}" for line, target, module in scored
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(scored)},
    )
    return _result(False, _one_check(False, detail), 0)
