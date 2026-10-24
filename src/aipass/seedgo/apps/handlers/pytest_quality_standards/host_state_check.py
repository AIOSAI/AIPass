# =================== AIPass ====================
# Name: host_state_check.py
# Description: v5 - a test that changes live host state and does not put it back
# Version: 1.0.1
# Created: 2026-09-08
# Modified: 2026-10-24
# =============================================

"""Does this test leave the machine the way it found it?

Reference: host_state.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Union

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "host_state"

TEST_DIRS: tuple = corpus.TEST_DIRS

#: Basenames, so an absolute path to the same binary still matches.
HOST_CONTROL_BINARIES: frozenset = frozenset(
    {
        "systemctl",
        "launchctl",
        "sc",
        "service",
        "systemd-run",
        "crontab",
        "shutdown",
        "reboot",
        "halt",
        "killall",
        "pkill",
        "kill",
        "update-rc.d",
        "chkconfig",
    }
)

SUBPROCESS_RUNNERS: frozenset = frozenset({"run", "call", "check_call", "check_output", "Popen"})

#: Narrow on purpose: `terminate()` on a Popen the unit opened is correct teardown.
SIGNAL_CALLS: frozenset = frozenset({"os.kill", "os.killpg", "signal.raise_signal"})

MUTATING_PATH_METHODS: frozenset = frozenset(
    {
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "rmdir",
        "touch",
        "rename",
        "replace",
        "chmod",
        "symlink_to",
        "hardlink_to",
    }
)

SHUTIL_MUTATORS: frozenset = frozenset(
    {"shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree", "shutil.move", "shutil.rmtree"}
)

HOME_ROOTS: frozenset = frozenset({"Path.home", "os.path.expanduser", "expanduser"})

ENV_MUTATOR_METHODS: frozenset = frozenset({"pop", "setdefault", "update", "clear"})

SANDBOX_FIXTURES: frozenset = frozenset({"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory"})

ENTRY_POINT_CALLS: frozenset = frozenset({"main", "handle_command", "route_command", "run_cli", "cli"})

#: Kept in step with `entry_point_diff`, which reads the same declarations.
COMMAND_CONSTANTS: frozenset = frozenset({"COMMANDS", "HANDLED_COMMANDS", "VERBS", "SUBCOMMANDS"})

#: Verbs too short for a literal match to be evidence; same number as `entry_point_diff`.
MINIMUM_VERB_LENGTH: int = 3

MAX_REPORTED: int = 12


def _names_under(node: ast.AST) -> Set[str]:
    """Every dotted call target and bare name under a node."""
    found: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Call):
            dotted = corpus.dotted_name(child.func)
            if dotted:
                found.add(dotted)
    return found


def _one_step_left(node: ast.AST) -> Optional[ast.AST]:
    """The next node leftward in an attribute, subscript, join or call chain."""
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        return node.value
    if isinstance(node, ast.BinOp):
        return node.left
    if isinstance(node, ast.Call):
        return node.func
    return None


def _root_of(node: ast.expr) -> str:
    """The leftmost name of an attribute or subscript chain, or ""."""
    current: ast.AST = node
    while not isinstance(current, ast.Name):
        nxt = _one_step_left(current)
        if nxt is None:
            return ""
        current = nxt
    return current.id


def _rooted_at_home(node: ast.expr, home_names: Set[str]) -> bool:
    """True when an expression resolves to somewhere under the real home."""
    if _root_of(node) in home_names:
        return True
    names = _names_under(node)
    if names & HOME_ROOTS:
        return True
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if child.value.startswith("~"):
                return True
    return False


def _bound_to(unit_node: ast.AST, seeds: frozenset) -> Set[str]:
    """Names assigned from an expression mentioning one of `seeds`, to a fixed point within the unit."""
    bound: Set[str] = set(seeds)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(unit_node):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets: Sequence[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
            if node.value is None or not (_names_under(node.value) & bound):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in bound:
                    bound.add(target.id)
                    changed = True
    return bound


def _is_patching_call(dotted: str) -> bool:
    """True when a dotted call spelling replaces a seam for the test's duration."""
    tail = dotted.rsplit(".", 1)[-1]
    if tail in {"setattr", "delattr"}:
        return dotted.startswith("monkeypatch.")
    return tail == "patch" or dotted.endswith(("patch.object", "patch.dict"))


def _argument_text(argument: ast.expr) -> Set[str]:
    """The seam names one patch argument names, as text (f-strings piece by piece)."""
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return {argument.value}
    if isinstance(argument, ast.JoinedStr):
        found: Set[str] = set()
        for value in argument.values:
            found |= _argument_text(value)
        return found
    if isinstance(argument, ast.FormattedValue):
        return _argument_text(argument.value)
    name = corpus.dotted_name(argument) if isinstance(argument, (ast.Name, ast.Attribute)) else ""
    return {name} if name else set()


def module_level_strings(tree: ast.Module) -> Dict[str, str]:
    """Module-level names bound to a plain string literal."""
    strings: Dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        targets: Sequence[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                strings[target.id] = node.value.value
    return strings


def patched_targets(unit: corpus.TestUnit, module_strings: Optional[Dict[str, str]] = None) -> Set[str]:
    """Every seam this unit replaces, as text a finding can be matched against.

    Text, not resolved objects: resolving patch targets would import the branch under audit.
    """
    known = module_strings or {}
    targets: Set[str] = set()
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call) or not _is_patching_call(corpus.dotted_name(node.func)):
            continue
        for argument in node.args:
            for text in _argument_text(argument):
                targets.add(text)
                if text in known:
                    targets.add(known[text])
    return targets


def _seam_is_patched(patched: Set[str], needles: Sequence[str]) -> bool:
    """True when any patched target names any of the needles as whole dotted segments.

    `x.environment_name` is not `environ`, and `dict()` is no patch."""
    return any(needle and f".{needle}." in f".{target}." for target in patched for needle in needles)


def _argv_binary(node: ast.Call) -> str:
    """The host-control program a subprocess call runs, or ""."""
    if not node.args:
        return ""
    first = node.args[0]
    words: List[str] = []
    if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
        head = first.elts[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            words = [head.value]
    elif isinstance(first, ast.Constant) and isinstance(first.value, str):
        words = first.value.split()
    if not words:
        return ""
    program = Path(words[0].strip()).name
    return program if program in HOST_CONTROL_BINARIES else ""


def _service_control(unit: corpus.TestUnit, patched: Set[str]) -> List[Dict]:
    """Findings for subprocess calls that drive a service manager."""
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        dotted = corpus.dotted_name(node.func)
        tail = dotted.rsplit(".", 1)[-1]
        runs_subprocess = tail in SUBPROCESS_RUNNERS and dotted.startswith("subprocess.")
        if not runs_subprocess and dotted != "os.system":
            continue
        program = _argv_binary(node)
        if not program:
            continue
        if _seam_is_patched(patched, ("subprocess", "os.system", program)):
            continue
        rows.append(
            _finding(
                "SERVICE_CONTROL",
                unit,
                node.lineno,
                f"runs {program} through {dotted} with nothing patched and no restore in sight - "
                f"whatever this changes about the running machine stays changed",
            )
        )
    return rows


def _process_signal(unit: corpus.TestUnit, patched: Set[str]) -> List[Dict]:
    """Findings for signals sent to a process the unit did not create."""
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        dotted = corpus.dotted_name(node.func)
        if dotted not in SIGNAL_CALLS or _seam_is_patched(patched, (dotted, "os.kill", "signal")):
            continue
        rows.append(
            _finding(
                "PROCESS_SIGNAL",
                unit,
                node.lineno,
                f"{dotted} signals a process this unit did not start, and a signalled process is not "
                f"put back by a finally clause",
            )
        )
    return rows


def _home_write(unit: corpus.TestUnit, patched: Set[str]) -> List[Dict]:
    """Findings for writes to the real user's home directory."""
    home_names = _bound_to(unit.node, HOME_ROOTS)
    sandbox_names = _bound_to(unit.node, SANDBOX_FIXTURES)
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        dotted = corpus.dotted_name(node.func)
        tail = dotted.rsplit(".", 1)[-1]
        subject: Optional[ast.expr] = None
        if tail in MUTATING_PATH_METHODS and isinstance(node.func, ast.Attribute):
            subject = node.func.value
        elif dotted in SHUTIL_MUTATORS and node.args:
            subject = node.args[-1]
        if subject is None:
            continue
        if _root_of(subject) in sandbox_names or _names_under(subject) & SANDBOX_FIXTURES:
            continue
        if not _rooted_at_home(subject, home_names):
            continue
        if _seam_is_patched(patched, ("Path.home", "expanduser", "HOME")):
            continue
        rows.append(
            _finding(
                "HOME_WRITE",
                unit,
                node.lineno,
                f"{dotted or tail} writes under the real home directory rather than tmp_path, and "
                f"nothing in this unit puts the previous contents back",
            )
        )
    return rows


def _subscripts_environ(targets: Sequence[ast.expr]) -> bool:
    """True when any assignment or del target indexes os.environ."""
    return any(isinstance(t, ast.Subscript) and corpus.dotted_name(t.value) == "os.environ" for t in targets)


def _env_touch(node: ast.AST) -> str:
    """How a statement changes the process environment, or ""."""
    if isinstance(node, ast.Assign):
        return "assignment into os.environ" if _subscripts_environ(node.targets) else ""
    if isinstance(node, ast.Delete):
        return "del from os.environ" if _subscripts_environ(node.targets) else ""
    if not isinstance(node, ast.Call):
        return ""
    dotted = corpus.dotted_name(node.func)
    if dotted == "os.putenv":
        return "os.putenv"
    if dotted.startswith("os.environ.") and dotted.rsplit(".", 1)[-1] in ENV_MUTATOR_METHODS:
        return dotted
    return ""


def _lines_of(statements: Sequence[ast.stmt]) -> Set[int]:
    """Every line number under a block of statements."""
    return {getattr(child, "lineno", -1) for stmt in statements for child in ast.walk(stmt)}


def _names_in(statements: Sequence[ast.stmt]) -> Set[str]:
    """Every call and attribute spelling under a block of statements, as text."""
    found: Set[str] = set()
    for stmt in statements:
        for child in ast.walk(stmt):
            if isinstance(child, ast.Call):
                found.add(corpus.dotted_name(child.func))
            elif isinstance(child, ast.Attribute):
                found.add(corpus.dotted_name(child))
    return found


def _undone_in_a_finally(unit_node: ast.AST, node: ast.AST, needles: Sequence[str]) -> bool:
    """True when a statement is either half of an inline try/finally restore.

    Each half is read against the OTHER block; reading the whole `Try` flags the restore itself.
    """
    line = getattr(node, "lineno", -1)
    for candidate in ast.walk(unit_node):
        if not isinstance(candidate, ast.Try) or not candidate.finalbody:
            continue
        in_body = line in _lines_of(candidate.body)
        counterpart = candidate.finalbody if in_body else candidate.body
        if not in_body and line not in _lines_of(candidate.finalbody):
            continue
        if _seam_is_patched(_names_in(counterpart), needles):
            return True
    return False


def _env_mutation(unit: corpus.TestUnit, patched: Set[str], restoring_fixtures: Set[str]) -> List[Dict]:
    """Findings for os.environ changes pytest will not undo."""
    if _seam_is_patched(patched, ("os.environ", "environ")):
        return []
    if {argument.arg for argument in unit.node.args.args} & restoring_fixtures:
        return []
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        line = getattr(node, "lineno", unit.line)
        touched = _env_touch(node)
        if not touched or _undone_in_a_finally(unit.node, node, ("os.environ", "os.putenv")):
            continue
        rows.append(
            _finding(
                "ENV_MUTATION",
                unit,
                line,
                f"{touched} outlives this test - the interpreter's environment is process-wide, so "
                f"every later test in the session sees it. monkeypatch.setenv is restored for you",
            )
        )
    return rows


def _cwd_change(unit: corpus.TestUnit, patched: Set[str], restoring: Set[str]) -> List[Dict]:
    """Findings for os.chdir with no restore.

    `monkeypatch.chdir` acquits the whole unit: it restores the cwd it recorded, undoing later raw chdirs.
    """
    if any(corpus.dotted_name(n.func) == "monkeypatch.chdir" for n in ast.walk(unit.node) if isinstance(n, ast.Call)):
        return []
    if {argument.arg for argument in unit.node.args.args} & restoring:
        return []
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call) or corpus.dotted_name(node.func) != "os.chdir":
            continue
        if _seam_is_patched(patched, ("os.chdir", "chdir")):
            continue
        if _undone_in_a_finally(unit.node, node, ("os.chdir",)):
            continue
        rows.append(
            _finding(
                "CWD_CHANGE",
                unit,
                node.lineno,
                "os.chdir moves the whole process, not this test - a later test resolving a relative "
                "path lands somewhere else. monkeypatch.chdir is restored for you",
            )
        )
    return rows


def _control_binary_anywhere(tree: ast.AST) -> str:
    """A host-control program named by any string literal under a node.

    Whole module, not the call: production builds argv on one line and runs it on another.
    """
    for child in ast.walk(tree):
        if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
            continue
        words = child.value.split()
        head = Path(words[0]).name if words else ""
        if head in HOST_CONTROL_BINARIES:
            return head
    return ""


def _runs_a_subprocess(tree: ast.Module) -> bool:
    """True when a module starts a child process anywhere in it."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = corpus.dotted_name(node.func)
        tail = dotted.rsplit(".", 1)[-1]
        if (tail in SUBPROCESS_RUNNERS and dotted.startswith("subprocess.")) or dotted == "os.system":
            return True
    return False


def _module_reaches_host_control(tree: ast.Module) -> str:
    """How a production module reaches host state, or "" (no acquittals on the production side)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in SIGNAL_CALLS:
            return corpus.dotted_name(node.func)
    if not _runs_a_subprocess(tree):
        return ""
    return _control_binary_anywhere(tree)


def _declared_verbs(tree: ast.Module) -> List[str]:
    """Verbs a module publishes through a COMMANDS-style constant."""
    verbs: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets: Sequence[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id in COMMAND_CONSTANTS for t in targets):
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List, ast.Set)):
            continue
        for element in node.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                verbs.append(element.value)
    return verbs


def host_effectful_verbs(scanned: corpus.Corpus) -> Dict[str, Dict]:
    """Verb -> the module and program that make it dangerous."""
    effectful: Dict[str, Dict] = {}
    for relpath in sorted(scanned.production_trees):
        tree = scanned.production_trees[relpath]
        program = _module_reaches_host_control(tree)
        if not program:
            continue
        for verb in _declared_verbs(tree):
            if len(verb) >= MINIMUM_VERB_LENGTH:
                effectful.setdefault(verb, {"module": relpath, "program": program})
    return effectful


def _module_level_collections(tree: ast.Module) -> Dict[str, List[str]]:
    """Module-level names bound to a literal collection of strings (the one-hop verb lookup)."""
    collections: Dict[str, List[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets: Sequence[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not isinstance(node.value, (ast.Tuple, ast.List, ast.Set)):
            continue
        strings = [e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if not strings:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                collections[target.id] = strings
    return collections


def _verbs_reaching_unit(unit: corpus.TestUnit, module_collections: Dict[str, List[str]]) -> Set[str]:
    """Every verb string this unit could receive, literals plus one hop.

    One `ast.walk` covers decorators and body: `decorator_list` is a field of the function node.
    """
    reaching: Set[str] = set()
    for child in ast.walk(unit.node):
        if isinstance(child, ast.Name) and child.id in module_collections:
            reaching.update(module_collections[child.id])
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            reaching.add(child.value)
    return reaching


def _calls_an_entry_point(unit: corpus.TestUnit) -> str:
    """The entry-point call this unit makes, or "" when it makes none."""
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        dotted = corpus.dotted_name(node.func)
        if dotted.rsplit(".", 1)[-1] in ENTRY_POINT_CALLS:
            return dotted
    return ""


def _effectful_verb(
    unit: corpus.TestUnit,
    effectful: Dict[str, Dict],
    collections: Dict[str, List[str]],
    patched: Set[str],
) -> List[Dict]:
    """Findings for a host-effectful verb driven through a real entry point."""
    entry_point = _calls_an_entry_point(unit)
    if not entry_point:
        return []
    rows: List[Dict] = []
    for verb in sorted(_verbs_reaching_unit(unit, collections) & set(effectful)):
        site = effectful[verb]
        module_stem = Path(site["module"]).stem
        if _seam_is_patched(patched, (module_stem, site["program"], "subprocess")):
            continue
        rows.append(
            _finding(
                "EFFECTFUL_VERB",
                unit,
                unit.line,
                f"drives the verb '{verb}' through {entry_point}() with nothing patched on the seam - "
                f"{site['module']} implements it by running {site['program']}, so on any run where the "
                f"guard under test is absent this changes the machine and leaves it changed",
            )
        )
    return rows


def _is_fixture(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    """True when a function carries a pytest fixture decorator."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if corpus.dotted_name(target).rsplit(".", 1)[-1] == "fixture":
            return True
    return False


def _yield_statements(node: ast.AST) -> List[ast.AST]:
    """Every statement in a fixture body that is, or contains, a yield."""
    return [stmt for stmt in ast.walk(node) if isinstance(stmt, (ast.Yield, ast.YieldFrom))]


def _teardown_after_yield(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    """True when a fixture does anything after handing its value over.

    A bare `yield` then restore is the pytest idiom; do not demand `try`/`finally` (host_state.md).
    """
    yields = _yield_statements(node)
    if not yields:
        return False
    last_yield_line = max(getattr(y, "lineno", -1) for y in yields)
    for stmt in ast.walk(node):
        if isinstance(stmt, (ast.Assign, ast.Delete, ast.Expr, ast.For, ast.If, ast.With)):
            if getattr(stmt, "lineno", -1) > last_yield_line:
                return True
    return False


def restoring_fixtures(tree: ast.Module) -> Dict[str, Set[str]]:
    """Same-file fixtures that put a kind of host state back, by kind (conftest fixtures are not seen)."""
    found: Dict[str, Set[str]] = {"env": set(), "cwd": set()}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_fixture(node):
            continue
        calls = {corpus.dotted_name(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)}
        reads_env = any(corpus.dotted_name(n) == "os.environ" for n in ast.walk(node) if isinstance(n, ast.Attribute))
        if any(_env_touch(n) for n in ast.walk(node)) and reads_env and _teardown_after_yield(node):
            found["env"].add(node.name)
        if "monkeypatch.chdir" in calls:
            found["cwd"].add(node.name)
        elif "os.chdir" in calls and _teardown_after_yield(node):
            found["cwd"].add(node.name)
    return found


def unrestoring_fixtures(scanned: corpus.Corpus) -> List[Dict]:
    """Every fixture that reaches host state and hands it over with no teardown."""
    rows: List[Dict] = []
    for parsed in scanned.files:
        for node in ast.walk(parsed.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_fixture(node):
                continue
            fixture = corpus.TestUnit(name=node.name, node=node, relpath=parsed.relpath, line=node.lineno)
            patched = patched_targets(fixture, module_level_strings(parsed.tree))
            reached = (
                _service_control(fixture, patched)
                + _process_signal(fixture, patched)
                + _home_write(fixture, patched)
                + _env_mutation(fixture, patched, set())
                + _cwd_change(fixture, patched, set())
            )
            if not reached or _teardown_after_yield(node):
                continue
            rows.append(
                {
                    "nodeid": f"{parsed.relpath}::{node.name}",
                    "line": node.lineno,
                    "species": "FIXTURE_NO_TEARDOWN",
                    "detail": (
                        f"this fixture reaches host state ({reached[0]['species']}) and hands it to the "
                        f"test with nothing after the yield, so the change outlives every test that uses it"
                    ),
                }
            )
    return rows


def fixture_count(scanned: corpus.Corpus) -> int:
    """How many fixtures the corpus holds.

    The denominator must count fixtures too, or fixture rows drive a score below zero.
    """
    return sum(
        1
        for parsed in scanned.files
        for node in ast.walk(parsed.tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_fixture(node)
    )


def _finding(species: str, unit: corpus.TestUnit, line: int, detail: str) -> Dict:
    """One row, in the shape every rule in this pack reports."""
    return {"nodeid": unit.nodeid, "line": line, "species": species, "detail": detail}


def unit_flags(
    unit: corpus.TestUnit,
    effectful: Dict[str, Dict],
    collections: Dict[str, List[str]],
    restoring: Optional[Dict[str, Set[str]]] = None,
    module_strings: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """Every host-state finding in one unit.

    `restoring` defaults to none: a caller with no tree gets the strict reading, not a generous one.
    """
    patched = patched_targets(unit, module_strings)
    fixtures = restoring or {}
    return (
        _service_control(unit, patched)
        + _process_signal(unit, patched)
        + _home_write(unit, patched)
        + _env_mutation(unit, patched, fixtures.get("env", set()))
        + _cwd_change(unit, patched, fixtures.get("cwd", set()))
        + _effectful_verb(unit, effectful, collections, patched)
    )


def find_unrestored(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit and fixture that changes host state without putting it back.

    One row per unit, always: counting findings would let one test drive the score below zero.
    """
    effectful = host_effectful_verbs(scanned)
    rows: List[Dict] = []
    seen: Set[str] = set()
    for parsed in scanned.files:
        collections = _module_level_collections(parsed.tree)
        restoring = restoring_fixtures(parsed.tree)
        strings = module_level_strings(parsed.tree)
        for unit in parsed.units:
            for row in unit_flags(unit, effectful, collections, restoring, strings):
                if row["nodeid"] not in seen:
                    seen.add(row["nodeid"])
                    rows.append(row)
    for row in unrestoring_fixtures(scanned):
        if row["nodeid"] not in seen:
            seen.add(row["nodeid"])
            rows.append(row)
    return rows


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests put the machine back.

    `bypass_rules` is accepted for the scoring-API contract and not read: shadow mode gates nothing.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS, with_production=True)
    total = scanned.unit_count()

    # Built before the early return: an all-unparseable project must not read as "no tests".
    unreadable: List[Dict] = []
    if scanned.unparseable:
        unreadable.append(
            {
                "name": "Corpus readable",
                "passed": True,
                "message": (
                    f"{len(scanned.unparseable)} test file(s) could not be parsed and were NOT "
                    f"measured: {', '.join(scanned.unparseable[:MAX_REPORTED])}"
                ),
            }
        )
    production_limit = scanned.production_limits()
    if production_limit:
        unreadable.append({"name": "Production readable", "passed": True, "message": production_limit})

    if total == 0:
        measured = (
            "no test files found - nothing measured, so nothing scored"
            if not scanned.unparseable
            else (
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present but "
                f"unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Host state restored", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_unrestored(scanned)
    population = total + fixture_count(scanned)
    score = int(((population - len(flagged)) / population) * 100)
    checks: List[Dict] = [
        {
            "name": "Host state restored",
            "passed": not flagged,
            "message": (
                f"{population - len(flagged)}/{population} test units and fixtures leave the machine as they found it"
                if not flagged
                else (
                    f"{len(flagged)}/{population} test units and fixtures change live host state "
                    "with no visible restore: "
                    + ", ".join(f"{r['nodeid']} ({r['species']})" for r in flagged[:MAX_REPORTED])
                    + (f" (+{len(flagged) - MAX_REPORTED} more)" if len(flagged) > MAX_REPORTED else "")
                )
            ),
        }
    ]
    checks.extend(unreadable)

    return {
        "passed": True,
        "score": score,
        "checks": checks,
        "standard": STANDARD_NAME.upper(),
        "advisory": True,
        "violations": flagged,
    }
