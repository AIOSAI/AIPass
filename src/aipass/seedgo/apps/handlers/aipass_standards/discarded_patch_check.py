# =================== AIPass ====================
# Name: discarded_patch_check.py
# Description: Discarded Patch Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Discarded Patch Standards Checker Handler

Crack class R from the 2026-09-22 eyes-on review of @backup's tests: a test
replaces a function in ITS OWN BRANCH with a mock, hands the mock nothing,
binds it to nothing, and asserts nothing about it. The replacement is pure
silence. The product's call to that function is then unpinned, and the call
can be deleted with the suite green.

@backup's ``test_ceiling_guard.py`` is the shape in one file. Every test wraps
``check_ceiling`` in ``patch("aipass.backup...audit.trail.log_operation")``
and discards the mock. The reviewer's finding: **delete ``_log_breach``
(ceiling.py:168-179) entirely and all 21 tests pass.** The refusal's ops-log
entry is the only forensic trace of a runaway refusal, and nothing pins it.

WHAT STAYS LEGAL, and each acquittal is a measured cut:

  * PATCHING ANOTHER BRANCH, A GATEWAY, THE CLOCK OR THE NETWORK. That is an
    edge, and sealing an edge is what a test is supposed to do. Only a target
    inside the test file's OWN branch is judged -- the branch is read from
    the file's path, and the target from an ``aipass.<branch>.`` string or a
    name imported from that package.
  * A REPLACEMENT HANDED OVER. ``patch(target, tmp_path)`` redirects a path
    constant at a test-owned directory; ``return_value=``, ``side_effect=``,
    ``new=``, ``new_callable=``, ``wraps=``, ``spec=`` and ``autospec=`` all
    drive or shape what the product gets. That is a seam doing work, not a
    mock thrown away. This one acquittal took the count from 1,025 to 692.
  * AN ``as`` BINDING THAT IS REFERENCED, and a ``@patch`` parameter that is
    referenced. Asserting on the mock is the whole cure.
  * A PATCH IN A FIXTURE OR A HELPER. The branch conftest's seam is the
    sanctioned place to silence infrastructure; a patch in a test body that
    duplicates it is the defect. Only ``def test_*`` bodies are judged.

THE THIRD SPELLING, ``monkeypatch.setattr``, WHICH THE DISPATCH NAMED. It has
no bare-mock form -- the replacement is a required argument -- so the
handed-over acquittal above lets every one of the fleet's 1,838 own-branch
calls through. 222 of them hand over something ANONYMOUS: ``Mock()`` with no
arguments, or ``lambda *a, **k: None``. Nothing binds it, it records nothing,
and the silenced call is exactly as unpinned as a discarded ``patch``. A
NAMED replacement is acquitted (the name is read at the ``setattr`` itself and
no name set can tell an asked mock from an ignored one); a RECORDER lambda is
acquitted by its body, which is how ``test_share.py`` stays clean.

CHECK FIRST, measured 2026-09-22 over the fleet's 561 test files:

  * 73 files convicted, 529 hits, 6.4s. Top three: @seedgo 12 files,
    @commons 10, @api 7 -- my own branch is worst, and it stays worst until
    it is cured. The worst single file is @ai_mail's
    ``test_dispatch_monitor.py`` at 65, then @seedgo's
    ``test_coverage_audit.py`` at 56.
  * BY SPELLING: ``patch`` / ``patch.object`` 47 files and 309 hits,
    ``monkeypatch.setattr`` 26 files and 220 hits.
  * FIVE CUTS, 6,401 -> 309, and the LAST one was the biggest correction.
    Any patch with an unused binding: 250 files, 6,401 hits. Own-branch
    targets only: 203 / 3,547. Nothing handed over: 111 / 1,025, then
    97 / 692 once ``patch(target, new)``'s second POSITIONAL argument was
    read as the replacement it is. Test bodies only, plus the ``@patch``
    decorator form: 110 / 786 over the whole ``with`` shape.
  * THEN 786 -> 309, because the mock is very often asserted AFTER the
    ``with`` block closes, not inside it. Reading only the block's own
    statements convicted 51 files and 331 hits that are perfectly sound.
    That single mistake was worth more than half the remaining count.

WHICH OF THE DISPATCH'S EVIDENCE LINES IT CONVICTS:

  * ``test_ceiling_guard.py`` -- 14 lines, every ``log_operation`` discard.
    CONVICTED, and this is the reviewer's own finding 5. Its line 278 is NOT
    convicted: it binds two patchers and asserts ``assert_not_called`` on
    both, one line below the block. That is the cure, working.
  * ``test_handlers_filesystem.py`` -- 15 lines. CONVICTED at 71 and 89, the
    ``log_operation`` halves of those two ``with`` blocks.
  * ``test_handlers_filesystem.py`` 68 and 83, the
    ``whitelist.config.load_project_config`` patches: **DECLINED, and the
    reviewer agrees the defect is real but it is not this one.** Its verdict
    is OUT-OF-PLACE because ``filter_paths`` NEVER REACHES the patched
    function -- a dead patch, not a discarded one. That needs the product's
    call graph; one file's AST cannot see it. Both also carry
    ``return_value=``, so the mock is not discarded, it is answering.
  * ``test_share.py`` 100, 112, 122: **DECLINED, and they are right.** Each
    is ``monkeypatch.setattr(share_module, "run_share", lambda ...:
    ran.append(...))`` followed by ``assert ran == []``. The reviewer marked
    them SOUND -- "recorder proves run_share unreached". A recorder that is
    asserted is the cure, not the defect.
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "DISCARDED_PATCH"
STANDARD_KEY = "discarded_patch"

#: The product's import root.
PRODUCT = "aipass"

#: Prefix that makes a function a test, which is the only unit this rule judges.
TEST_PREFIX = "test_"

#: The two spellings of a patch that this rule can read a target off.
_PATCH_VERBS: frozenset[str] = frozenset({"patch", "object"})

#: Keywords that either DRIVE the product or shape what the mock will refuse.
#: Any one of them means the replacement is in use, not thrown away.
_HANDED_OVER: frozenset[str] = frozenset(
    {"return_value", "side_effect", "new", "new_callable", "wraps", "autospec", "spec"}
)

#: The fixture name pytest injects. Any other spelling is not judged.
_MONKEYPATCH = "monkeypatch"

#: A mock class whose bare call builds a throwaway nothing can be asked.
_THROWAWAY: frozenset[str] = frozenset({"Mock", "MagicMock", "AsyncMock"})

CURE = "assert on the mock, or drop the patch and let the call stand"


def _tail_name(func: ast.expr) -> str:
    """The name a call is made under -- ``f`` for ``a.b.f(...)`` and ``f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _base_name(node: ast.expr) -> str:
    """The leftmost name of a dotted expression -- ``mod`` for ``mod.a.b``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def branch_of(module_path: str) -> str:
    """The branch a test file lives in, read from its own path.

    ``src/aipass/backup/tests/test_x.py`` is @backup's, so
    ``aipass.backup.*`` is its own code and everything else is an edge. The
    path is the only honest source: a test file imports a dozen branches and
    no import tells you which one it belongs to.
    """
    parts = Path(module_path).resolve().parts
    for index in range(len(parts) - 1, 0, -1):
        if parts[index - 1] == PRODUCT:
            return parts[index]
    return ""


def _own_names(tree: ast.Module, branch: str) -> Set[str]:
    """Names this file binds from its OWN branch's package."""
    package = f"{PRODUCT}.{branch}"
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(package):
            names |= {alias.asname or alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            names |= {a.asname or a.name.split(".")[0] for a in node.names if a.name.startswith(package)}
    return names


def _tests(tree: ast.Module) -> List[Tuple[ast.AST, List[ast.AST], Set[str]]]:
    """Each test, its own nodes, and every name read inside it -- ONE descent.

    Three separate walks (find the tests, collect each one's names, find each
    one's ``with`` blocks) re-walk every node three times, and the names pass
    used ``ast.unparse`` on top. One stack descent carrying the enclosing test
    down took the fleet from 8.1s with identical findings -- the same shape
    ``state_leak`` needed for the same reason.

    Names are collected as ``ast.Name`` ids rather than rendered source: a
    binding called ``m`` matched the letter m inside any identifier when the
    body was text.
    """
    nodes: Dict[int, List[ast.AST]] = {}
    names: Dict[int, Set[str]] = {}
    owners: Dict[int, ast.AST] = {}
    stack: List[Tuple[ast.AST, ast.AST | None]] = [(tree, None)]
    while stack:
        node, enclosing = stack.pop()
        is_test = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(TEST_PREFIX)
        if enclosing is None and is_test:
            enclosing = node
            nodes[id(node)], names[id(node)], owners[id(node)] = [], set(), node
        if enclosing is not None:
            nodes[id(enclosing)].append(node)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names[id(enclosing)].add(node.id)
        for child in ast.iter_child_nodes(node):
            stack.append((child, enclosing))
    return [(owners[key], nodes[key], names[key]) for key in nodes]


def _is_patch(node: ast.AST) -> bool:
    """Whether this call is ``patch(...)`` or ``patch.object(...)``."""
    return isinstance(node, ast.Call) and _tail_name(node.func) in _PATCH_VERBS


def _targets_own_branch(call: ast.Call, branch: str, own: Set[str]) -> bool:
    """Whether the patched thing lives in the test's own branch."""
    if not call.args:
        return False
    target = call.args[0]
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value.startswith(f"{PRODUCT}.{branch}.")
    return _base_name(target) in own


def _handed_over(call: ast.Call) -> bool:
    """Whether a replacement was handed to the patch rather than left as a bare mock.

    ``patch(target, NEW)`` puts the replacement in the SECOND positional slot
    and ``patch.object(obj, "name", NEW)`` in the third. Missing that cost
    333 false convictions -- every ``patch("...FLOW_JSON_DIR", tmp_path)`` in
    @flow and every ``patch("...MODULES_DIR", tmp_path)`` in @aipass, which
    are the seam pointing the product at a test-owned directory.
    """
    if {keyword.arg for keyword in call.keywords} & _HANDED_OVER:
        return True
    slot = 2 if _tail_name(call.func) == "patch" else 3
    return len(call.args) >= slot


def _is_monkeypatch(node: ast.AST) -> bool:
    """Whether this call is ``monkeypatch.setattr(...)``."""
    if not isinstance(node, ast.Call) or _tail_name(node.func) != "setattr":
        return False
    return _base_name(node.func) == _MONKEYPATCH


def _anonymous_silence(call: ast.Call) -> bool:
    """Whether the replacement handed over is a throwaway nothing can observe.

    ``monkeypatch.setattr`` has no bare-mock form -- the replacement is a
    required argument -- so ``_handed_over`` acquits every one of the fleet's
    1,838 own-branch calls. 222 of them hand over something ANONYMOUS:
    ``Mock()`` with no arguments, or ``lambda *a, **k: None``. Nothing binds
    it, it records nothing, and the product's call to the silenced function is
    exactly as unpinned as a discarded ``patch``.

    A NAMED replacement is acquitted even when nothing asks it, because the
    name is read at the ``setattr`` call itself and no name set can tell the
    two apart. A recorder lambda is acquitted by its body: @backup's
    ``test_share.py`` 100, 112 and 122 append to a list and then assert on it,
    which both reviewers marked SOUND.
    """
    replacement = call.args[-1]
    if isinstance(replacement, ast.Lambda):
        return isinstance(replacement.body, ast.Constant) and replacement.body.value is None
    if not isinstance(replacement, ast.Call):
        return False
    return _tail_name(replacement.func) in _THROWAWAY and not replacement.args and not replacement.keywords


def _discarded_monkeypatches(nodes: List[ast.AST], branch: str, own: Set[str]) -> List[Tuple[int, str]]:
    """Every ``monkeypatch.setattr`` of own code whose stand-in nothing can ask."""
    findings: List[Tuple[int, str]] = []
    for node in nodes:
        if not _is_monkeypatch(node) or not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        if _targets_own_branch(node, branch, own) and _anonymous_silence(node):
            findings.append((node.lineno, _target_of(node)))
    return findings


def _target_of(call: ast.Call) -> str:
    """The patched thing, as a reader would name it."""
    if not call.args:
        return "the patch"
    target = call.args[0]
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        return f"{ast.unparse(target)}.{call.args[1].value}"
    return ast.unparse(target)


def _discarded_in_with(nodes: List[ast.AST], branch: str, own: Set[str], body: Set[str]) -> List[Tuple[int, str]]:
    """Every ``with patch(...)`` in this test whose mock nothing ever touches.

    ``body`` is every name read anywhere in the WHOLE test, not just inside
    the ``with`` block. ``snap.assert_not_called()`` lives AFTER the block
    closes -- @backup's ``test_ceiling_guard.py:278`` binds two patchers and
    asserts both one line below the ``with``. Reading only the block's own
    statements convicted it twice, and that one mistake was 51 files and 331
    hits fleet-wide: 640 hits fell to 309.
    """
    findings: List[Tuple[int, str]] = []
    for node in nodes:
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            call = item.context_expr
            if not _is_patch(call) or not isinstance(call, ast.Call):
                continue
            if not _targets_own_branch(call, branch, own) or _handed_over(call):
                continue
            bound = item.optional_vars
            if isinstance(bound, ast.Name) and bound.id in body:
                continue
            findings.append((call.lineno, _target_of(call)))
    return findings


def _discarded_in_decorators(function: ast.AST, branch: str, own: Set[str], body: Set[str]) -> List[Tuple[int, str]]:
    """Every ``@patch`` whose injected parameter the body never mentions.

    ``@patch`` decorators bind BOTTOM-UP: the decorator closest to the ``def``
    fills the first parameter. Reading them in source order fills the wrong
    slots and then reports the wrong line.
    """
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    parameters = [arg.arg for arg in function.args.args if arg.arg not in ("self", "cls")]
    decorators = [d for d in reversed(function.decorator_list) if _is_patch(d)]

    findings: List[Tuple[int, str]] = []
    for index, decorator in enumerate(decorators):
        if not isinstance(decorator, ast.Call) or index >= len(parameters):
            continue
        if not _targets_own_branch(decorator, branch, own) or _handed_over(decorator):
            continue
        if parameters[index] not in body:
            findings.append((decorator.lineno, _target_of(decorator)))
    return findings


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[discarded_patch] Unparseable, nothing scanned: %s", exc)
        return None


def scan(source: str, branch: str) -> List[Tuple[int, str]]:
    """(line, target) for each patch of the test's own branch that nothing observes."""
    tree = _parse(source)
    if tree is None or not branch:
        return []

    own = _own_names(tree, branch)
    findings: List[Tuple[int, str]] = []
    for function, nodes, names in _tests(tree):
        findings.extend(_discarded_in_with(nodes, branch, own, names))
        findings.extend(_discarded_in_decorators(function, branch, own, names))
        findings.extend(_discarded_monkeypatches(nodes, branch, own))
    return sorted(findings)


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[discarded_patch] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Discarded patch", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for patches of its own branch that nothing observes.

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

    branch = branch_of(module_path)
    if not branch:
        # Outside src/aipass/<branch>/ there is no "own branch" to compare a
        # target against, and every patch would read as an edge.
        return _result(True, _one_check(True, "Outside a branch — no own code to discard a patch of"), 100)

    findings = scan(source, branch)
    if not findings:
        return _result(True, _one_check(True, f"Every patch of @{branch}'s own code is observed"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per patch would show the
    # first and hide the rest behind a count.
    detail = "\n".join(
        f"{path.name}:{line} {target} is patched and never observed - {CURE}" for line, target in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
