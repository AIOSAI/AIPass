# =================== AIPass ====================
# Name: flag_never_passed_check.py
# Description: Flag Never Passed Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Flag Never Passed Standards Checker Handler

Crack class P from the 2026-09-22 eyes-on review of @backup's tests: the
product's ``handle_command`` parses a ``--flag`` out of ``args`` and no test in
the branch ever passes that flag to it. The flag's branch is unpinned -- delete
the parse, hardcode the default, and the suite stays green.

@backup's ``apps/modules/share.py:129`` is the shape::

    public = "--public" in args
    run_share(file_path, public=public)

``public = False`` survives all 21 share tests. The only place ``--public``
appears under ``backup/tests/`` is a help-text substring assertion and a tuple
of flag names iterated for a help sweep. Neither hands it to the parser.

WHAT COUNTS AS PASSING IT, and this is the whole rule. The literal must reach
an ARGUMENT of some call: ``handle_command("share", ["--public"])``, a
sub-handler (``handle_create([target, "--dry-run"])``, which is how @spawn
tests its flags), a ``monkeypatch.setattr(sys, "argv", [...])`` before
``main()``, a name bound to an argv list, or a ``parametrize`` argvalue whose
parameter is then handed over. A tuple that is only ITERATED is not an
argument, which is what keeps @backup's ``for flag in ("--name", ...,
"--public")`` help sweep from acquitting the very flag it names.

AN ARGV CARRYING ``--help`` OR ``-h`` EXERCISES NOTHING ELSE IN THAT ROW. The
product itself says so -- share.py returns from ``print_help()`` before it
reads ``args[0]`` -- so ``["drive_clear", root, "--force", "--help"]`` in
@backup's help sweep pins ``--help`` and leaves ``--force`` exactly as unpinned
as before. Without this the sweep acquitted three of the five flags the
reviewers named.

CHECK FIRST, measured 2026-09-22 over the fleet:

  * 27 files convicted, 43 hits, 8.8s. Nine branches. @aipass 14, @spawn 10,
    @backup 5, @seedgo 4 -- and @seedgo's four are mine to cure.
  * THE THREE CUTS, and the middle one is the instructive failure:
      the flag appears as ANY string under tests/      7 files,  9 hits
      the literal must reach a handle_command CALL    38 files, 82 hits
      any call argument, minus the --help rows        27 files, 43 hits
    The middle cut convicted all 20 of @spawn's flags, because @spawn tests
    its sub-handlers (``handle_create``) and never names ``handle_command``.
    A rule that only reads one function name mistakes a different spelling
    for an absent test.

DEVPULSE ASKED WHETHER P IS NEAR ITS FINAL SIZE. No. Their first cut of
7 files / 8 hits is the LOOSEST reading -- it reproduces here at 7 / 9. The
dispatch's own stricter wording, that a test must pass the literal to the
parser, is five times larger.

THE JUDGEMENT THEY ASKED ME TO NAME: a flag parsed only in a module's
``__main__`` block, or only in a helper that builds argv for something else,
is NOT declared and is never convicted. The declared set starts at
``handle_command`` and follows only the same-file functions it calls. The
router's contract is the one the tests exercise; a ``__main__``-only flag is a
different surface and belongs to whatever tests that entry point.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: if the literal never reaches the
parser in any test, the branch behind it is never taken, and deleting the
parse cannot turn the suite red. There is no threshold and nothing to tune.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "branch_level"

STANDARD = "FLAG_NEVER_PASSED"
STANDARD_KEY = "flag_never_passed"

#: The parser every branch routes through, and the root of the declared set.
ENTRY = "handle_command"

#: A long flag, whole-string. A substring of a help sentence is not a flag.
FLAG = re.compile(r"^--[A-Za-z][\w-]*$")

#: The two spellings that short-circuit a command before any other flag is read.
HELP: frozenset[str] = frozenset({"--help", "-h"})

#: Marker carried down a descent to say "this row is a help argv".
_HELP_ROW = "help"

CURE = "pass it to the parser in a test, or delete the branch nothing reaches"


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
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError) as exc:
        logger.info("[flag_never_passed] Unparseable, nothing scanned: %s", exc)
        return None


def declared_flags(branch_root: Path) -> Dict[str, Tuple[Path, int]]:
    """Every ``--flag`` a branch's parsers read, and where it is read.

    The walk starts at ``handle_command`` and follows the functions it calls in
    the SAME file, because a parser is routinely one delegation deep. It does
    not follow into ``__main__`` or into another module: see the judgement note
    in the module docstring.
    """
    found: Dict[str, Tuple[Path, int]] = {}
    for path in sorted((branch_root / "apps").rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        functions: Dict[str, ast.AST] = {
            f.name: f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if ENTRY in functions:
            _parsed_here(functions, path, found)
    return found


def _parsed_here(functions: Dict[str, ast.AST], path: Path, found: Dict[str, Tuple[Path, int]]) -> None:
    """Follow one file's parser and record every flag literal it reads."""
    seen: Set[str] = set()
    stack: List[ast.AST] = [functions[ENTRY]]
    while stack:
        function = stack.pop()
        name = getattr(function, "name", "")
        if name in seen:
            continue
        seen.add(name)
        for node in ast.walk(function):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and FLAG.match(node.value):
                found.setdefault(node.value, (path, node.lineno))
            elif isinstance(node, ast.Call) and _tail_name(node.func) in functions:
                stack.append(functions[_tail_name(node.func)])


def _row_of(node: ast.List | ast.Tuple) -> Set[str]:
    """The string literals sitting directly in one list or tuple."""
    return {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}


def _harvest(roots: List[ast.AST]) -> Tuple[Set[str], Set[str], Set[str]]:
    """(flags exercised, flags shadowed by a --help row, names reached).

    ONE descent over the argument subtrees, with a visited set: a nested call's
    arguments are reachable from the outer call's too, and walking each one
    separately took the fleet from 8.8s to 59s with identical findings.
    """
    flags: Set[str] = set()
    shadowed: Set[str] = set()
    names: Set[str] = set()
    seen: Set[int] = set()
    stack: List[Tuple[ast.AST, str]] = [(node, "") for node in roots]
    while stack:
        node, row = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, (ast.List, ast.Tuple)):
            literals = _row_of(node)
            if literals & HELP:
                flags |= literals & HELP
                shadowed |= {s for s in literals if FLAG.match(s)} - HELP
                row = _HELP_ROW
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and FLAG.match(node.value):
            if row != _HELP_ROW:
                flags.add(node.value)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        for child in ast.iter_child_nodes(node):
            stack.append((child, row))
    return flags, shadowed, names


def _bindings(tree: ast.Module) -> Tuple[Dict[str, ast.AST], List[ast.AST]]:
    """(name -> the expression bound to it, every call-argument expression).

    Both in ONE walk. Collecting the arguments separately walked every node of
    every test file twice for no new finding.
    """
    binds: Dict[str, ast.AST] = {}
    arguments: List[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            arguments.extend(node.args)
            arguments.extend(keyword.value for keyword in node.keywords)
        if isinstance(node, ast.Assign) and node.value is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    binds[target.id] = node.value
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                _parametrized(decorator, binds)
    return binds, arguments


def _parametrized(decorator: ast.AST, binds: Dict[str, ast.AST]) -> None:
    """Bind each name a ``parametrize`` spells to the argvalues behind it."""
    if not isinstance(decorator, ast.Call) or _tail_name(decorator.func) != "parametrize":
        return
    if len(decorator.args) < 2 or not isinstance(decorator.args[0], ast.Constant):
        return
    spelled = decorator.args[0].value
    if not isinstance(spelled, str):
        return
    for name in re.split(r"[,\s]+", spelled.strip()):
        if name:
            binds[name] = decorator.args[1]


def exercised_flags(branch_root: Path) -> Tuple[Set[str], Set[str]]:
    """(flags a test hands to a parser, flags that ride only in a --help argv)."""
    exercised: Set[str] = set()
    shadowed: Set[str] = set()
    tests_dir = branch_root / "tests"
    if not tests_dir.is_dir():
        return exercised, shadowed
    for path in sorted(tests_dir.rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        binds, arguments = _bindings(tree)
        direct, hidden, names = _harvest(arguments)
        indirect, hidden_too, _ = _harvest([binds[name] for name in names if name in binds])
        exercised |= direct | indirect
        shadowed |= hidden | hidden_too
    return exercised, shadowed - exercised


def scan(branch_root: Path) -> Tuple[List[Tuple[Path, int, str]], Set[str]]:
    """(findings, flags counted as help-shadowed) for one branch."""
    declared = declared_flags(branch_root)
    if not declared:
        return [], set()
    exercised, shadowed = exercised_flags(branch_root)
    findings = [(path, line, flag) for flag, (path, line) in declared.items() if flag not in exercised]
    return sorted(findings), {flag for flag in shadowed if flag in declared}


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Flag never passed", "passed": passed, "message": message}]


def _clean_message(shadowed: Set[str]) -> str:
    """The passing message, carrying the help-shadowed count without a verdict.

    The device ``weak_oracle`` uses for its soft oracles and ``named_encoding``
    for latin-1: a number the owner asked for rides along, and nobody is
    charged for it.
    """
    if not shadowed:
        return "Every flag this branch parses is passed to it by a test"
    return (
        f"Every flag this branch parses is passed to it by a test "
        f"({len(shadowed)} appear only inside a --help argv, which the rule allows)"
    )


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch for flags its parsers read that no test ever passes.

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo).
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(branch_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    branch_root = Path(branch_path)
    if not (branch_root / "apps").is_dir():
        return _result(True, _one_check(True, "No apps/ — nothing parses a flag here"), 100)

    findings, shadowed = scan(branch_root)
    if not findings:
        return _result(True, _one_check(True, _clean_message(shadowed)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per flag would show the first
    # and hide the rest behind a count.
    detail = "\n".join(
        f"{path.relative_to(branch_root)}:{line} {flag} is parsed and never passed - {CURE}"
        for path, line, flag in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
