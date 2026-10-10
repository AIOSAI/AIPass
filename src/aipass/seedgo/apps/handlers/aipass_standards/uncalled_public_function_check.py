# =================== AIPass ====================
# Name: uncalled_public_function_check.py
# Description: Uncalled Public Function Standards Checker Handler
# Version: 1.3.0
# Created: 2026-09-22
# Modified: 2026-10-10
# =============================================

"""
Uncalled Public Function Standards Checker Handler

Crack class O from the 2026-09-22 eyes-on review of @backup's tests: a public
function of a test file's DECLARED SUBJECT module -- the path in its one-line
docstring, test template v1 item 6 -- that no test in the branch ever calls.
The file claims to test that module; one of the module's public functions is
not tested by anything.

THE CRISP PART IS WHAT COUNTS AS CALLED, and it is the whole rule:

  * Named in a ``Call``, or an attribute access that is then called, IS
    called. ``share_mod.run_share(file_arg)`` is a call.
  * Named ONLY as a ``patch`` / ``monkeypatch.setattr`` target -- replaced and
    never run -- is NOT called. That is shape O1, and @backup's
    ``apps/backup.py:125 discover_modules`` is it exactly: four sites in
    ``test_cli_routing.py`` replace it with ``return_value=[fake_module]`` and
    nothing anywhere runs the real importlib discovery.
  * REACHED ONLY THROUGH THE PRODUCT is the false conviction to avoid, and the
    dispatch asked how I decide it. A name-level call graph over the branch's
    whole ``apps/``, seeded with every function name the tests DO call and
    closed to a fixed point: if the function is in that closure, some test
    already drives a real path into it and the rule acquits. That guard is not
    decoration -- it acquits 19 of the 21 candidates, including
    ``route_command`` and every ``print_introspection``, which ``main()``
    reaches for tests that call ``main()``.

  * CALLED BY PYTEST PROTOCOL is shape O3, acquitted (leg 1cd2e911): a hook
    a pytest plugin defines is called by pytest, never by a test. It is
    counted in the passing message, and it seeds the graph as a test call
    would, so the helpers only a hook calls are live. ``protocol_hooks``
    says which files count as plugins, and why.

  A name-level graph collapses two modules that both define ``run``, so it
  over-acquits rather than under-acquits. For a SCORED rule that is the right
  direction, and the number it acquits is reported rather than hidden.

A RETIRED TEST CALLS NOTHING (2026-10-10, devpulse d13d7c68 item A). Only live
test files are read -- ``tests/.archive`` and every SOURCE_SKIP_DIRS dir are
out, both in the call tally and in the unpatched-run pass -- the same cure
unused_conftest_fixture 1.1.0 got. See ``_live_test_files``.

CHECK FIRST, measured 2026-09-22 over the fleet:

  * 2 files convicted, 2 hits. @backup both: ``apps/backup.py:125
    discover_modules`` (O1) and ``apps/handlers/report/result.py:50
    new_result`` (O2 -- defined once and referenced nowhere in apps/ or
    tests/).
  * ONLY 69 OF THE FLEET'S 561 TEST FILES DECLARE A SUBJECT PATH AT ALL. That
    is the headline and it caps the rule: O cannot judge a file that never
    says what it tests. ``file_top``'s item 6 sub-rule convicts the other 492,
    and every file it cures hands this rule a new subject to read.
  * 21 uncalled public functions in those 69 files' subjects: 19 reachable
    through the product (acquitted), 1 O1, 1 O2.

THE DISPATCH SAID 16 FILES AND 23 HITS. Mine is 2 and 2, and the correction is
almost entirely the reachability guard plus reading the docstring properly: a
subject line can name TWO modules (``Tests for apps/modules/share.py and
apps/handlers/drive/share.py``) and a rule that takes only the first match
mis-attributes half of them.

WHERE I DISAGREE WITH THE DISPATCH, WITH THE LINE NUMBER:

  ``apps/modules/share.py run_share`` is given as the evidence line, "replaced
  at test_share.py 100, 112, 122 and never runs anywhere in the suite." It
  runs. ``test_caller_path.py:86`` calls ``share_mod.run_share(file_arg)`` for
  real, with Drive mocked beneath it. The brief's own wording is "no test
  anywhere in the branch's tests/ calls", so this rule ACQUITS it and is right
  to. The three ``test_share.py`` monkeypatches are real -- ``discarded_patch``
  already looked at them and found them SOUND, because they are recorders that
  are asserted -- but they are not the whole suite's relationship to that
  function.

  ``apps/handlers/diff/generator.py generate_diff_content`` is offered
  conditionally, "if generator.py is within the subject of a backup test
  file". It is not. ``test_versioned_engine.py`` declares
  ``apps/handlers/copy/versioned.py`` and ``apps/modules/restore.py``, and no
  @backup test file names ``generator.py``. The rule does not see it, which is
  correct and is also a hole: a module nothing declares as a subject is
  invisible to O no matter how untested it is.

  ``apps/modules/restore.py``'s bare-basename fallback is a coverage gap
  inside a function, not a function. O does not see it and should not, exactly
  as the dispatch said.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: the file says in its own docstring
that it tests this module. If a public function of that module is never
called, never reachable from anything called, and named only where it is being
replaced, then nothing in the suite has ever run it. There is no threshold and
nothing to tune.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import in_skipped_dir
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "branch_level"

STANDARD = "UNCALLED_PUBLIC_FUNCTION"
STANDARD_KEY = "uncalled_public_function"

#: A subject path as test template v1 item 6 spells it: a repo-relative .py path.
SUBJECT = re.compile(r"((?:apps|lib)[\w./-]*\.py)")

#: The three verbs that REPLACE a function rather than run it.
_PATCH_VERBS: frozenset[str] = frozenset({"patch", "object", "setattr"})

REPLACED = "O1 replaced by a patch and never run"
UNREACHED = "O2 never named by a test and unreachable from one"

#: Acquitted shapes -- counted in the passing message, never charged.
PRODUCT = "are reached only through the product, which the rule allows"
PROTOCOL = "O3 called by pytest protocol"

#: Every hook pytest 9.1's hookspec declares: the names pytest calls, never a test.
PYTEST_HOOKS: frozenset[str] = frozenset(
    {
        "pytest_addhooks",
        "pytest_addoption",
        "pytest_assertion_pass",
        "pytest_assertrepr_compare",
        "pytest_cmdline_main",
        "pytest_cmdline_parse",
        "pytest_collect_directory",
        "pytest_collect_file",
        "pytest_collection",
        "pytest_collection_finish",
        "pytest_collection_modifyitems",
        "pytest_collectreport",
        "pytest_collectstart",
        "pytest_configure",
        "pytest_deselected",
        "pytest_enter_pdb",
        "pytest_exception_interact",
        "pytest_fixture_post_finalizer",
        "pytest_fixture_setup",
        "pytest_generate_tests",
        "pytest_ignore_collect",
        "pytest_internalerror",
        "pytest_itemcollected",
        "pytest_keyboard_interrupt",
        "pytest_leave_pdb",
        "pytest_load_initial_conftests",
        "pytest_make_collect_report",
        "pytest_make_parametrize_id",
        "pytest_markeval_namespace",
        "pytest_plugin_registered",
        "pytest_pycollect_makeitem",
        "pytest_pycollect_makemodule",
        "pytest_pyfunc_call",
        "pytest_report_collectionfinish",
        "pytest_report_from_serializable",
        "pytest_report_header",
        "pytest_report_teststatus",
        "pytest_report_to_serializable",
        "pytest_runtest_call",
        "pytest_runtest_logfinish",
        "pytest_runtest_logreport",
        "pytest_runtest_logstart",
        "pytest_runtest_makereport",
        "pytest_runtest_protocol",
        "pytest_runtest_setup",
        "pytest_runtest_teardown",
        "pytest_runtestloop",
        "pytest_sessionfinish",
        "pytest_sessionstart",
        "pytest_terminal_summary",
        "pytest_unconfigure",
        "pytest_warning_recorded",
    }
)

#: The hooks whose definition makes a module a pytest plugin -- see ``protocol_hooks``.
PLUGIN_MARKERS: frozenset[str] = frozenset({"pytest_configure", "pytest_sessionstart"})

CURE = "call it in a test, or retire it"


def _tail_name(node: ast.AST) -> str:
    """The last name in a call target: ``a.b.c`` -> ``c``, ``f`` -> ``f``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _parse(path: Path) -> ast.Module | None:
    """A file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
    except (SyntaxError, OSError) as exc:
        logger.info("[uncalled_public_function] Unparseable, nothing scanned: %s", exc)
        return None


def subjects_of(tree: ast.Module, branch_root: Path) -> List[Path]:
    """Every module a test file's one-line docstring says it tests.

    ``findall``, not ``search``: ``Tests for apps/modules/share.py and
    apps/handlers/drive/share.py`` declares TWO subjects, and taking only the
    first mis-attributes the second module's functions to nobody.
    """
    docstring = ast.get_docstring(tree) or ""
    first = docstring.splitlines()[0] if docstring else ""
    return [path for path in (branch_root / m for m in SUBJECT.findall(first)) if path.is_file()]


def _named_target(node: ast.AST) -> str:
    """The name a patch argument points at, string target or object attribute."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.rsplit(".", 1)[-1]
    return _tail_name(node)


def _live_test_files(tests_dir: Path) -> List[Path]:
    """Every ``.py`` under ``tests/`` that CI runs: ``.archive`` and every SOURCE_SKIP_DIRS dir out.

    A retired test calls nothing. ``tests/.archive`` is git-ignored, so a clean
    checkout does not have it: memory's ``validate_memory_file_structure`` read
    100 on memory's seat and 98 in CI because its one naming test sat there
    (devpulse d13d7c68 item A). The same cure as unused_conftest_fixture 1.1.0.
    """
    return [path for path in sorted(tests_dir.rglob("*.py")) if not in_skipped_dir(path, tests_dir)]


def _read_tests(tests_dir: Path, branch_root: Path) -> Tuple[Set[str], Set[str], Set[str], List[Path]]:
    """(called, replaced, named outside a patch, every declared subject)."""
    called: Set[str] = set()
    replaced: Set[str] = set()
    elsewhere: Set[str] = set()
    subjects: List[Path] = []
    for path in _live_test_files(tests_dir):
        tree = _parse(path)
        if tree is None:
            continue
        subjects.extend(subjects_of(tree, branch_root))
        _tally(tree, _patch_targets(tree, replaced), called, elsewhere)
    return called, replaced, elsewhere, subjects


def _tally(tree: ast.Module, skip: Set[int], called: Set[str], elsewhere: Set[str]) -> None:
    """Add one test file's calls and other mentions, patch arguments skipped.

    Lifted out of ``_read_tests`` for depth (seedgo, fleet green leg 8).
    """
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Call):
            called.add(_tail_name(node.func))
        elif isinstance(node, ast.Name):
            elsewhere.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            elsewhere.add(node.value.rsplit(".", 1)[-1])


def _patch_targets(tree: ast.AST, replaced: Set[str]) -> Set[int]:
    """Record every patched name and return the nodes that naming occupies.

    The target of a patch is not a mention of the function anywhere else, so
    those nodes are skipped when the "named outside a patch" set is built.
    """
    skip: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _tail_name(node.func) not in _PATCH_VERBS:
            continue
        for argument in node.args[:2]:
            replaced.add(_named_target(argument))
            skip |= {id(inner) for inner in ast.walk(argument)}
    return skip


def _aliases(tree: ast.AST) -> Dict[str, str]:
    """asname -> the name it imports, for every ``from x import f as g`` in a file."""
    return {
        alias.asname: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.asname
    }


def _calls(function: ast.AST, aliases: Dict[str, str]) -> Set[str]:
    """The names a function calls, an imported alias also read as the name it imports.

    devpulse's dispatches.py calls ``_owner_address``, which is guard's
    ``owner_address`` imported under another name (seedgo, fleet green leg 10).
    """
    edges = {_tail_name(n.func) for n in ast.walk(function) if isinstance(n, ast.Call)}
    return edges | {aliases[e] for e in edges if e in aliases}


def _functions(tree: ast.AST) -> List[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function definition in a tree, nested ones included."""
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def protocol_hooks(tree: ast.Module | None) -> Set[str]:
    """The module-level hooks pytest calls in this module, when it is a plugin.

    THE FILE TEST: a module is a plugin when it defines ``pytest_configure``
    or ``pytest_sessionstart``. The dispatch offered three tests (a
    conftest.py, a module under payload/, or this one) and asked for one. This
    one reads what the file IS, not where it sits:

      * the audit_hygiene payload is loaded with ``-p`` from a scratch copy,
        so neither its name nor its directory is what makes pytest call it;
      * a payload/ rule would acquit anything dropped under that directory and
        miss a plugin anywhere else;
      * a conftest.py lives in tests/, which no subject path under apps/ names.

    The cost, said plainly: a plugin that defines neither marker -- only
    ``pytest_runtest_call``, say -- is still judged. The rule errs toward
    judging.
    """
    if tree is None:
        return set()
    hooks = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in PYTEST_HOOKS
    }
    return hooks if hooks & PLUGIN_MARKERS else set()


def product_graph(branch_root: Path, hooks: Set[str] | None = None) -> Dict[str, Set[str]]:
    """Function name -> the names it calls, over the branch's whole ``apps/``.

    ``.archive`` and the other SOURCE_SKIP_DIRS are not product: a retired
    caller in the graph acquits a live function nothing runs. When ``hooks``
    is given, every plugin hook under ``apps/`` is added to it: pytest calls
    those, so they seed reachability as a test call would (leg 1cd2e911).
    """
    graph: Dict[str, Set[str]] = {}
    apps = branch_root / "apps"
    for path in sorted(apps.rglob("*.py")):
        if in_skipped_dir(path, apps):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        if hooks is not None:
            hooks |= protocol_hooks(tree)
        aliases = _aliases(tree)
        for function in _functions(tree):
            graph.setdefault(function.name, set()).update(_calls(function, aliases))
    return graph


def reachable(graph: Dict[str, Set[str]], seeds: Set[str]) -> Set[str]:
    """Everything the product can get to from what the tests actually call."""
    seen: Set[str] = set()
    stack = list(seeds)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        stack.extend(graph.get(name, ()))
    return seen


def _publics(path: Path) -> List[Tuple[str, int]]:
    """(name, line) for every module-level public def in a subject module."""
    tree = _parse(path)
    if tree is None:
        return []
    return [
        (node.name, node.lineno)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]


def _patched(node: ast.AST) -> Set[str]:
    """The names the patch calls inside one node replace."""
    found: Set[str] = set()
    _patch_targets(node, found)
    return found


def _autouse(function: ast.AST) -> bool:
    """Whether a function is a ``fixture(autouse=True)``, which patches every test it sees."""
    calls = [d for d in getattr(function, "decorator_list", []) if isinstance(d, ast.Call)]
    return any(k.arg == "autouse" and getattr(k.value, "value", False) is True for d in calls for k in d.keywords)


def run_unpatched(tests_dir: Path, graph: Dict[str, Set[str]]) -> Set[str]:
    """Every name some test reaches with nothing in THAT test replacing it.

    A patch in one test does not stop another test running the real function:
    cli's print_introspection test runs the discover_modules its stub_module
    fixture replaces elsewhere (seedgo, fleet green leg 10). What replaces a
    name for a test: its body and decorators, its class's decorators, the
    fixtures it names, and every autouse fixture under tests/.
    """
    trees = [tree for tree in (_parse(p) for p in _live_test_files(tests_dir)) if tree is not None]
    helpers: Dict[str, Set[str]] = {}
    patches: Dict[str, Set[str]] = {}
    autouse: Set[str] = set()
    for tree in trees:
        aliases = _aliases(tree)
        for function in _functions(tree):
            helpers.setdefault(function.name, set()).update(_calls(function, aliases))
            patches.setdefault(function.name, set()).update(_patched(function))
            if _autouse(function):
                autouse |= _patched(function)
    combined = {name: graph.get(name, set()) | helpers.get(name, set()) for name in {*graph, *helpers}}
    run: Set[str] = set()
    for tree in trees:
        owners = {
            id(item): set().union(*(_patched(d) for d in node.decorator_list))
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            for item in node.body
        }
        for test in _functions(tree):
            if not test.name.startswith("test"):
                continue
            replaced = autouse | _patched(test) | owners.get(id(test), set())
            for argument in test.args.args:
                replaced |= patches.get(argument.arg, set())
            run |= reachable(combined, helpers.get(test.name, set())) - replaced
    return run


def _verdict(name: str, replaced: Set[str], elsewhere: Set[str], live: Set[str], run: Set[str]) -> str:
    """Which shape this uncalled public function is, or "" when it is acquitted.

    A replaced name some test runs unpatched is not "never run" (leg 10).
    """
    if name in replaced and name not in elsewhere and name not in run:
        return REPLACED
    if name in replaced or name in live or name in elsewhere:
        return ""
    return UNREACHED


def scan(branch_root: Path) -> Tuple[List[Tuple[Path, int, str, str]], Dict[str, int]]:
    """(findings, acquitted uncalled functions by shape: PRODUCT or PROTOCOL)."""
    tests_dir = branch_root / "tests"
    acquitted = {PRODUCT: 0, PROTOCOL: 0}
    if not tests_dir.is_dir() or not (branch_root / "apps").is_dir():
        return [], acquitted

    called, replaced, elsewhere, subjects = _read_tests(tests_dir, branch_root)
    if not subjects:
        return [], acquitted

    hooks: Set[str] = set()
    graph = product_graph(branch_root, hooks)
    live = reachable(graph, called | hooks)
    run = run_unpatched(tests_dir, graph)
    findings: List[Tuple[Path, int, str, str]] = []
    for subject in dict.fromkeys(subjects):
        protocol = protocol_hooks(_parse(subject))
        for name, line in _publics(subject):
            if name in called:
                continue
            shape = PROTOCOL if name in protocol else _verdict(name, replaced, elsewhere, live, run)
            if shape in (REPLACED, UNREACHED):
                findings.append((subject, line, name, shape))
            else:
                acquitted[shape or PRODUCT] += 1
    return sorted(findings), acquitted


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Uncalled public function", "passed": passed, "message": message}]


def _clean_message(acquitted: Dict[str, int]) -> str:
    """The passing message, carrying each acquitted count without a verdict.

    The device ``weak_oracle`` uses for its soft oracles: a number the owner
    asked for rides along, and nobody is charged for it. Here it is the size of
    the reachability guard, which is the rule's biggest judgement, and the
    hooks pytest calls by protocol, one count per shape.
    """
    counts = "; ".join(f"{count} {shape}" for shape, count in acquitted.items() if count)
    message = "Every public function of every declared subject is called by a test"
    return f"{message} ({counts})" if counts else message


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch for public functions of a declared subject nothing calls.

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo).
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(branch_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    branch_root = Path(branch_path)
    findings, acquitted = scan(branch_root)
    if not findings:
        return _result(True, _one_check(True, _clean_message(acquitted)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per function would show the
    # first and hide the rest behind a count.
    detail = "\n".join(
        f"{path.relative_to(branch_root)}:{line} {name} - {shape} - {CURE}" for path, line, name, shape in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
