# =================== AIPass ====================
# Name: host_state_check.py
# Description: v5 - a test that changes live host state and does not put it back
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""Does this test leave the machine the way it found it?

    @pytest.mark.parametrize("verb", GATED_VERBS)      # holds "uninstall-timer"
    def test_a_stray_positional_is_refused(self, verb):
        with patch.object(sys, "argv", ["daemon", verb, "not_a_real_subarg_xyz"]):
            with pytest.raises(SystemExit):
                _daemon_mod.main()

Nothing is patched on the effectful seam. While the refusal gate exists the verb
never runs; on a red-first run, and on every mutation run that removes the gate,
`main()` reaches the real implementation and the real implementation runs
`systemctl --user stop` and `disable`, then deletes the unit files. Measured on
this machine: daemon-tick.timer stopped at 11:46:40 on 2026-09-07 with no
restart, and no scheduler tick ran for twenty-three hours. Two citizens missed
their windows.

PATRICK'S RULING, 2026-09-08, and it is narrower than "do not touch the host":
tests can't disable processes, they should restore to exact same state before the
test. The test is fine and good that it can enter something. So TOUCHING THE REAL
THING IS ALLOWED. Leaving it changed is the defect. This rule is about the
restore, never about the reach.

SIX SPECIES, FIVE OF THEM ORDINARY. SERVICE_CONTROL, PROCESS_SIGNAL, HOME_WRITE,
ENV_MUTATION and CWD_CHANGE are each a call in a test that reaches host state
with no restore and no patch on the seam. They are found the way every rule in
this pack finds things: by reading the unit.

THE SIXTH IS THE ONE THAT CATCHES THE INCIDENT, and it is why this rule reads
production. No AST reader can follow `main()` into `systemctl` - that is an
interpreter, not a reader. So the checker DERIVES the dangerous verbs from the
branch's own source: a module under the target that reaches host control AND
publishes a `COMMANDS`-style constant declares those verbs HOST-EFFECTFUL. A unit
that feeds one of them to an entry point, with nothing patched on the seam, is
flagged and told which module made the verb dangerous. Derived, never listed: a
hardcoded roster of verb names would be stale the first time a branch renamed
one, and stale in the silent direction.

ONE HOP OF NAME RESOLUTION, DELIBERATELY. The verb in the incident is not in the
unit at all - it is in a module-level `GATED_VERBS` list that a `parametrize`
decorator names. A rule that read only the unit's own literals would have missed
the very site it was written for. So a `parametrize` argvalues Name is resolved
against the file's own module-level assignments, once, with no chain-following.
That is the same one-hop shape `capture_never_read` already uses for a delegated
read, and it stops at the file boundary like everything else here.

WHAT ACQUITS A SITE, and these are the whole difference between a rule and a
nuisance:

  - THE SEAM IS PATCHED. `patch`, `patch.object`, `patch.dict` or
    `monkeypatch.setattr` naming the call, its module, or the module that makes
    the verb effectful, anywhere in the unit. A target held in a module-level
    constant - `patch(TIMER_SEAM)` - is resolved one hop to its string, because
    daemon wrote it that way first and a rule that only read literals told it to
    inline a constant it had every reason to keep.
  - `monkeypatch.setenv` / `delenv` / `chdir`. pytest restores those itself, by
    contract, on every path including a failure. Using them IS the cure.
  - THE PATH IS UNDER `tmp_path`. A write to a directory pytest created and
    removes is not host state. Names assigned from a `tmp_path`-rooted
    expression carry the acquittal, one hop, same as above.
  - A FIXTURE WITH A TEARDOWN AFTER ITS YIELD. Any statement after the last
    yield is the teardown - the plain `yield` then restore is the pytest idiom,
    and demanding a `try`/`finally` convicted thirty correct fixtures on the
    first fleet run. A fixture with a yield and nothing after it is a setup with
    no teardown, and that is the row.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM, all of it in the direction of FEWER
flags:

  - it does not follow calls. An effect reached through a helper the unit calls,
    or through a fixture defined in another file, is invisible. So is a restore
    performed in one.
  - a subprocess whose argv is assembled at runtime from variables is not read.
    Only a literal first element is evidence of which binary runs.
  - a verb that reaches host state through a module publishing no command set is
    not derived, and the units that call it are not flagged.
  - it cannot see a restore it is not shown - an `atexit` hook, a session fixture
    in a conftest two directories up, an external supervisor putting the unit
    back. A flagged site may be perfectly safe for a reason this file cannot
    read. It nominates. A human decides.
  - AND THE LIMIT THAT MATTERS MOST, stated in the rule text as well as here: a
    `finally` block does not run when the process is killed. A SIGKILL skips
    teardown, so no in-process restore is a guarantee. That is why the template
    lands the snapshot as a document under `tmp_path` and writes the restore
    idempotent - so a later run can finish an interrupted one.

STDLIB ONLY - `ast`, `pathlib`, `typing`, and the pack's own corpus reader, like
the rest of the pack. That constraint is why the pack lifts onto any project.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Union

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "host_state"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Programs that change what the machine is doing rather than what it contains.
#: Spelled as basenames so an absolute path to the same binary still matches.
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

#: The subprocess entry points. `Popen` is here because a started process that
#: is never waited on is exactly the leak this rule is about.
SUBPROCESS_RUNNERS: frozenset = frozenset({"run", "call", "check_call", "check_output", "Popen"})

#: Calls that signal a process the test did not create. Narrow on purpose:
#: `terminate()` on a Popen handle the unit itself opened is correct teardown,
#: not a finding, and telling the two apart needs the receiver.
SIGNAL_CALLS: frozenset = frozenset({"os.kill", "os.killpg", "signal.raise_signal"})

#: pathlib methods that change the filesystem. `read_*` and `exists` are absent
#: for the obvious reason: reading the host is not changing it.
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

#: shutil functions that change the filesystem, by dotted spelling.
SHUTIL_MUTATORS: frozenset = frozenset(
    {"shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree", "shutil.move", "shutil.rmtree"}
)

#: Expressions that root a path at the real user's home rather than a fixture.
HOME_ROOTS: frozenset = frozenset({"Path.home", "os.path.expanduser", "expanduser"})

#: `os.environ` mutators. Assignment and `del` are found structurally.
ENV_MUTATOR_METHODS: frozenset = frozenset({"pop", "setdefault", "update", "clear"})

#: Fixture names whose value pytest creates and removes. A write under one of
#: these is not host state.
SANDBOX_FIXTURES: frozenset = frozenset({"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory"})

#: Calls that run a branch's own command line for real. A host-effectful verb
#: handed to one of these is the incident shape.
ENTRY_POINT_CALLS: frozenset = frozenset({"main", "handle_command", "route_command", "run_cli", "cli"})

#: Module-level constants that publish a module's verbs. Kept in step with
#: `entry_point_diff`, which reads the same declarations for a different reason.
COMMAND_CONSTANTS: frozenset = frozenset({"COMMANDS", "HANDLED_COMMANDS", "VERBS", "SUBCOMMANDS"})

#: Verbs too short for a literal match to be evidence. Same reasoning, and the
#: same number, as `entry_point_diff`.
MINIMUM_VERB_LENGTH: int = 3

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message printing hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# READING WHAT A NAME IS ROOTED AT
# =============================================================================


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
    """The leftmost name of an attribute or subscript chain, or "".

    `home / "x" / "y"` roots at `home`; `Path.home() / ".config"` roots at the
    call, which `_names_under` reads instead.
    """
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
    """Names assigned from an expression mentioning one of `seeds`, one hop.

    ONE HOP, NOT A CHAIN. `home = Path.home()` then `target = home / "x"` are
    both caught because the second mentions `home`, which the first pass added -
    so the loop runs to a fixed point over the unit's own assignments and stops
    when a pass adds nothing. It never leaves the unit, never resolves an import
    and never executes anything.
    """
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


# =============================================================================
# READING WHAT THE UNIT HAS PATCHED
# =============================================================================


def _is_patching_call(dotted: str) -> bool:
    """True when a dotted call spelling replaces a seam for the test's duration."""
    tail = dotted.rsplit(".", 1)[-1]
    if tail in {"setattr", "delattr"}:
        return dotted.startswith("monkeypatch.")
    return tail in {"patch", "object", "dict"}


def _argument_text(argument: ast.expr) -> Set[str]:
    """The seam names one patch argument names, as text.

    An f-string is read piece by piece - `patch(f"{ROUTER}.error")` names both
    the constant tail and the name holding the module path, and either half may
    be the one a finding needs to match against.
    """
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
    """Module-level names bound to a plain string literal.

    The other half of the one hop: `TIMER_SEAM = "aipass.daemon...._run_systemctl"`
    at the top of a file, named by every `patch()` below it.
    """
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

    Collects the string argument of `patch`/`patch.dict`, the attribute name and
    receiver of `patch.object`, and the target of `monkeypatch.setattr`. The
    result is deliberately TEXT rather than resolved objects: a rule that
    resolved patch targets would be importing the branch under audit.

    A bare Name is kept AND its module-level string is added, one hop, so
    `patch(TIMER_SEAM)` acquits the same site that `patch("...timer_install...")`
    does. `module_strings` defaults to none: a caller holding no tree gets the
    literal-only reading rather than a silently generous one.
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
    """True when any patched target names any of the needles."""
    for target in patched:
        for needle in needles:
            if needle and needle in target:
                return True
    return False


# =============================================================================
# THE FIVE DIRECT SPECIES
# =============================================================================


def _argv_binary(node: ast.Call) -> str:
    """The host-control program a subprocess call runs, or "".

    Reads the FIRST element of a literal argv list, or the first word of a
    literal command string. A runtime-assembled argv yields nothing, which is
    the blind spot named in the module docstring rather than a guess.
    """
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
    """How a statement changes the process environment, or "".

    Assignment and `del` are found structurally rather than by name, because
    `os.environ["X"] = "y"` has no call in it to read.
    """
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

    A unit that sets an environment variable inside a `try` and deletes it in the
    `finally` HAS restored it, on every path including the failing one. That is
    the cure written inline instead of in a fixture, and it must not be flagged
    as the defect.

    BOTH HALVES, AND THE SECOND HALF IS WHY THIS WAS REWRITTEN. The first version
    read the whole `Try` for its evidence and the try body alone for its
    location, so the CHANGE was acquitted and the RESTORE was flagged - the rule
    convicted the exact code the rule text teaches - while a `finally` that
    restored nothing acquitted the change anyway, because the body's own mention
    satisfied the walk. Each half is now read against the OTHER block: a change
    in the body is acquitted by a finally that names the same state, and a
    statement in the finally is the restore of a body that touched it.
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

    `monkeypatch.chdir` ACQUITS THE WHOLE UNIT, in the unit or in a fixture it
    requests, and that is a statement about how monkeypatch works rather than a
    convenience. It records the working directory at the moment it is called and
    restores THAT at teardown - so a later raw `os.chdir` deeper into the same
    test is undone too. drone's test_finds_registry_file is exactly that shape,
    through its `lock_dir` fixture, and it is correct code.
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


# =============================================================================
# THE SIXTH SPECIES - VERBS PRODUCTION MADE DANGEROUS
# =============================================================================


def _control_binary_anywhere(tree: ast.AST) -> str:
    """A host-control program named by any string literal under a node.

    PRODUCTION ASSEMBLES ARGV IN WAYS THE TEST SIDE DOES NOT, and this is the
    line the rule would have failed on. daemon builds
    `cmd = ["systemctl", "--user", *args]` on one line and calls
    `subprocess.run(cmd, ...)` on another, so the call itself holds no literal
    at all: a reader that only inspected the call would have derived nothing and
    missed the very incident this rule exists for. Reading the whole module is
    generous in the direction of DERIVING MORE dangerous verbs, which is the
    safe direction - over-deriving costs a reader a look, under-deriving costs a
    scheduler twenty-three hours.
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
    """How a production module reaches host state, or "".

    The same five shapes the test side looks for, asked of production with no
    acquittals: a module that runs `systemctl` reaches host control whether or
    not it also restores, because what it does to the host is its job.
    """
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
    """Verb -> the module and program that make it dangerous.

    A module qualifies only when it does BOTH: reaches host control, and
    publishes verbs. A module that runs `systemctl` and publishes nothing gives
    a reader no verb to look for, and a module full of verbs that touches
    nothing is an ordinary CLI.
    """
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
    """Module-level names bound to a literal collection of strings.

    ONE HOP OF RESOLUTION AND NO MORE, which is the whole reason this exists:
    the verb in the incident lives in a module-level `GATED_VERBS` list that a
    `parametrize` decorator names, so a rule reading only the unit's own
    literals would have missed the site it was written for.
    """
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

    THE DECORATORS AND THE BODY, because the incident shape appears both ways in
    one file: `TestUnknownArgumentIsRefused` parametrizes over `GATED_VERBS`
    while `test_help_outranks_the_gate` loops over the same list inside the unit.
    A reader that only walked the body would have called the first one clean
    while it drove exactly the same twelve verbs through exactly the same
    `main()`. One `ast.walk` covers both: `decorator_list` is a field of the
    function node, so walking the unit descends into it. An earlier version
    spliced the decorators in explicitly and seeded the set from
    `string_constants`; both were measured dead - the suite stayed green with
    either removed - and a dead line that looks load-bearing is the one a later
    reader deletes the wrong half of.
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


# =============================================================================
# FIXTURES - A YIELD WITH NO FINALLY IS A SETUP WITH NO TEARDOWN
# =============================================================================


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

    A BARE `yield` FOLLOWED BY RESTORE CODE IS THE CORRECT PYTEST IDIOM AND MUST
    NOT BE FLAGGED. pytest runs a yield fixture's teardown when the test FAILS as
    well as when it passes; `try`/`finally` buys one extra case - an exception
    raised inside the fixture itself between the change and the yield - and not
    the case people reach for it for. Demanding it would have convicted
    @ai_mail's clean_env, which saves four variables, yields, and puts all four
    back. Measured before this narrowing: 1 fixture row fleet-wide, and it was
    that one. The rule now asks the honest question - is there a teardown at all.
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
    """Same-file fixtures that put a kind of host state back, by kind.

    THE ACQUITTALS THE FLEET MEASUREMENT DEMANDED, and both were real:

      env - @ai_mail's test_send_identity strips four identity variables in a
        `clean_env` fixture and restores them after the yield; twenty-nine of its
        units then set one of those same four inside the test. Reading the units
        alone called all twenty-nine unrestored when the file restores every one.

      cwd - @drone's `lock_dir` fixture calls `monkeypatch.chdir(tmp_path)` and
        the unit then does a raw `os.chdir` deeper into that tree. monkeypatch
        recorded the ORIGINAL directory and restores it at teardown, so the later
        chdir is undone too. One row, and it was correct code.

    One hop, same file, no imports - the shape `capture_never_read` already uses
    for a delegated read. A fixture in a conftest is not seen, and that limit is
    published rather than papered over.
    """
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
    """Every fixture that reaches host state and hands it over with no teardown.

    A fixture is the right place to touch the host - it is the one place a
    restore runs for a failing test too. This finds the half-built version: the
    setup landed, the teardown never did.
    """
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


# =============================================================================
# ANALYSIS
# =============================================================================


def fixture_count(scanned: corpus.Corpus) -> int:
    """How many fixtures the corpus holds.

    THE DENOMINATOR HAS TO HOLD EVERY SUBJECT THE RULE JUDGES. `find_unrestored`
    reports fixture rows as well as unit rows; scoring those against a count of
    units alone let one file of unrestoring fixtures drive a project below zero,
    and a score that can go negative is one nobody believes twice.
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

    `restoring` defaults to none deliberately: a caller holding no tree gets the
    answer for a unit standing alone, which is the pre-acquittal reading, rather
    than a silently generous one.
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

    ONE ROW PER UNIT, ALWAYS. A unit carrying three species is one unit a reader
    has to go and look at; counting the findings would let a single test drive a
    project's score below zero, and a score that can go negative is one nobody
    believes twice.
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


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests put the machine back.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to be
            excused from. Wiring a bypass before the standard can fail would be
            granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory. A project with no tests reports not_applicable rather than a
        number, because zero tests measured is not zero quality found.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS, with_production=True)
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. A project whose only test file has a syntax error must never report
    # what a project with no tests at all reports.
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
