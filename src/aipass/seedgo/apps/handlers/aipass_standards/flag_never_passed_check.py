# =================== AIPass ====================
# Name: flag_never_passed_check.py
# Description: Flag Never Passed Standards Checker Handler
# Version: 1.1.1
# Created: 2026-09-22
# Modified: 2026-10-24
# =============================================

"""Flag Never Passed Standards Checker Handler

Reference: flag_never_passed.md
"""

from functools import partial
import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import result, tail_name

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

#: Calls whose first argument (or ``args=``) is an argv for ANOTHER program, by the
#: module that owns them: a flag in that argv is never this branch's parser's.
ARGV_CALLS: Dict[str, frozenset[str]] = {
    "subprocess": frozenset({"run", "Popen", "call", "check_call", "check_output"}),
    "os": frozenset({"execv", "execve", "execvp", "execvpe", "spawnv", "spawnve", "spawnvp", "spawnvpe"}),
    "asyncio": frozenset({"create_subprocess_exec"}),
}

_HELP_ROW = "help"

CURE = "pass it to the parser in a test, or delete the branch nothing reaches"

#: A disposal copy is neither a parser nor a test.
ARCHIVE = ".archive"


def _live_files(root: Path) -> List[Path]:
    """Every .py under root, sorted, with anything under an .archive/ left out."""
    return [path for path in sorted(root.rglob("*.py")) if ARCHIVE not in path.relative_to(root).parts]


def _parse(path: Path) -> ast.Module | None:
    """A file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error; a verdict invented here misdirects its author.
    """
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError, ValueError) as exc:
        logger.info("[flag_never_passed] Unparseable, nothing scanned: %s", exc)
        return None


def declared_flags(branch_root: Path) -> Dict[str, Tuple[Path, int]]:
    """Every ``--flag`` a branch's parsers read, and where it is read.

    The walk starts at ``handle_command`` and follows the functions it calls in the SAME
    file (a parser is routinely one delegation deep), never into ``__main__`` or another module.
    """
    found: Dict[str, Tuple[Path, int]] = {}
    for path in _live_files(branch_root / "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        functions: Dict[str, ast.AST] = {
            f.name: f for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if ENTRY in functions:
            _parsed_here(functions, path, found)
    return found


def _argv_of(call: ast.Call) -> ast.AST | None:
    """The argv expression of a call that starts another program, or None.

    Only the dotted spelling is read (``subprocess.run``, ``os.execvp``): a bare
    ``run(...)`` is any function of that name, and guessing would acquit a real
    parser's literal.
    """
    func = call.func
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
        return None
    if func.attr not in ARGV_CALLS.get(func.value.id, frozenset()):
        return None
    if call.args:
        return call.args[0]
    return next((keyword.value for keyword in call.keywords if keyword.arg == "args"), None)


def _argv_literals(function: ast.AST) -> Set[int]:
    """Node ids of every string sitting in an argv this function hands to another program."""
    binds: Dict[str, List[ast.AST]] = {}
    argvs: List[ast.AST] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    binds.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.Call):
            argv = _argv_of(node)
            if argv is not None:
                argvs.append(argv)
    for argv in list(argvs):
        if isinstance(argv, ast.Name):
            argvs.extend(binds.get(argv.id, []))
    return {id(node) for argv in argvs for node in ast.walk(argv) if isinstance(node, ast.Constant)}


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
        another_program = _argv_literals(function)
        for node in ast.walk(function):
            if id(node) in another_program:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and FLAG.match(node.value):
                found.setdefault(node.value, (path, node.lineno))
            elif isinstance(node, ast.Call) and tail_name(node.func) in functions:
                stack.append(functions[tail_name(node.func)])


def _row_of(node: ast.List | ast.Tuple) -> Set[str]:
    """The string literals sitting directly in one list or tuple."""
    return {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}


def _harvest(roots: List[ast.AST]) -> Tuple[Set[str], Set[str], Set[str]]:
    """(flags exercised, flags shadowed by a --help row, names reached).

    ONE descent over the argument subtrees, with a visited set: a nested call's arguments
    are reachable from the outer call's too, and walking each separately is far slower.
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
    """(name -> the expression bound to it, every call-argument expression)."""
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
    if not isinstance(decorator, ast.Call) or tail_name(decorator.func) != "parametrize":
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
    for path in _live_files(tests_dir):
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


_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Flag never passed", "passed": passed, "message": message}]


def _clean_message(shadowed: Set[str]) -> str:
    """The passing message, carrying the help-shadowed count without a verdict."""
    if not shadowed:
        return "Every flag this branch parses is passed to it by a test"
    return (
        f"Every flag this branch parses is passed to it by a test "
        f"({len(shadowed)} appear only inside a --help argv, which the rule allows)"
    )


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch for flags its parsers read that no test ever passes."""
    if is_bypassed(branch_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    branch_root = Path(branch_path)
    if not (branch_root / "apps").is_dir():
        return _result(True, _one_check(True, "No apps/ — nothing parses a flag here"), 100)

    findings, shadowed = scan(branch_root)
    if not findings:
        return _result(True, _one_check(True, _clean_message(shadowed)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per flag would hide the rest.
    detail = "\n".join(
        f"{path.relative_to(branch_root)}:{line} {flag} is parsed and never passed - {CURE}"
        for path, line, flag in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
