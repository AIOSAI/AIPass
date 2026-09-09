# =================== AIPass ====================
# Name: fresh_clone_check.py
# Description: v5 - would this test pass on a machine that has only what the repo ships
# Version: 1.0.0
# Created: 2026-09-08
# Modified: 2026-09-08
# =============================================

"""Would this test pass on a machine that has only what the repo ships?

    def test_the_live_fleet_still_resolves_its_four_residents(self):
        projects_tree = reg.find_repo_root() / reg.RESIDENT_PROJECTS_DIR
        live = reg.get_resident_branches()
        if projects_tree.is_dir():
            assert set(live) == {"@baud", "@earmark", "@finch", "@aipass_site"}
        else:
            assert live == {}, "no projects/ tree on this machine"

That test was written to be safe everywhere and is red in exactly one place: a
fresh clone. `.gitignore` line 178 is `projects/*` and line 179 is
`!projects/README.md`, so a clone HAS a `projects/` directory - the tracked
README lives in it - and NONE of the four resident repos. CI took the FIRST arm
and found nothing. The else arm, the one written to protect CI, is unreachable
in CI.

MEASURED, NOT SUPPOSED. CI ran on a fresh clone for the first time after eight
waves of test work had landed overnight against Linux-only verification, and two
rows went red because their expected value came from state a clone does not have.
Both were self_skip cures: a skip stood in front of a test that reads THIS
machine, the cure removed the skip, and the assertion underneath it then depended
on the machine. The cure was right. What it uncovered had been hidden, not absent.

THE SAME FILE GETS IT RIGHT TWELVE LINES EARLIER, and that contrast is this whole
rule in one file:

    def test_a_passport_cannot_add_a_branch_no_registry_lists(self, tmp_path):
        stray = tmp_path / "projects" / "ghost" / "src" / "ghost" / ".trinity"
        stray.mkdir(parents=True)
        ...
        assert reg.get_resident_branches(tmp_path) == {}

Same resolver. One argument. The world it reads is the world the test built two
lines up, so the answer is the same on every machine that will ever run it. The
red one calls the same resolver with ZERO arguments and lets the host answer.

THREE ARMS, EACH NAMED IN ITS FINDING.

  IGNORED_PATH - the unit opens, lists, globs or stats a path whose spelling
    matches a root `.gitignore` pattern and is not rooted at `tmp_path`. A path
    the repo refuses to ship is a path a clone does not have. The path has to be
    REACHED ON THE FILESYSTEM, not merely mentioned: a bare `".trinity/local.json"`
    in an expected-value list is what a producer RETURNED, not a directory this
    unit opened, and reading spellings rather than reaches convicted eleven
    correct ai_mail units on the first run.

  BOTH_WORLDS - the unit branches on `exists()` / `is_dir()` / `is_file()` of a
    non-`tmp_path` path and asserts in BOTH arms. A test whose oracle is a
    runtime `if` on the machine has two oracles and proves neither: whichever arm
    this host takes is the only arm anybody ever reads, and the other one is
    prose. This is the arm that catches the ai_mail row.

  DERIVED_EXPECTED - `find_repo_root()`, a CLIMB from `Path(__file__)`,
    `Path.cwd()`, or a module-level or class-level constant built from one of
    them, handed BARE to the code under test as the world it should describe, or
    listed for its contents, with the answer then compared against a value spelled
    out in the file. This is the arm that catches the daemon row, where
    `BRANCH_ROOT = Path(__file__).resolve().parents[1]` is a CLASS constant - so
    class-level and module-level assignments are resolved one hop, the same single
    hop `host_state` uses to read a `parametrize` list.

THREE WORDS DO THE WORK IN THE THIRD ARM, and each of them was bought with a
measurement:

  BARE. `Path(__file__).parent / "fixtures" / "sample.json"` is machine-rooted and
  perfectly fresh-clone safe: the repo ships that file. What is not safe is
  handing a DIRECTORY to production and pinning what production found in it. So a
  derived root carrying any string literal is not a candidate, and
  `get_memory_health_status(str(self.BRANCH_ROOT), "DAEMON")` is.

  CLIMB. `__file__` alone is the running test file, which the repo ships by
  definition - it IS the test. Only `.parent`, `.parents` or `os.path.dirname`
  reaches a directory whose contents are this checkout's business. Measured: seven
  rows across @backup, @commons and @devpulse were `module_file(__file__)`, a
  resolver handed its own module path, and every one runs identically on a clone.

  WRITTEN DOWN. The EXPECTED side has to be a value the author typed - a literal,
  a list, a dict. A test that hands a root to production and then asserts a
  PROPERTY of the answer (`is_dir()`, `len(hits) == len(set(hits))`, one
  implementation equals another) answers the same on any machine. Measured: that
  one requirement took four families - @drone, @memory, @hooks twice - off the
  fleet in a single pass, and it is what makes the species name true.

Building a path to the module under test never flags: locating calls
(`sys.path.insert`, `spec_from_file_location`, `SourceFileLoader`) are excluded by
name, and such a path always carries a literal anyway.

THE IGNORE LIST IS SHIPPED AS A CONSTANT AND NEVER READ AT AUDIT TIME, and that
is a deliberate trade with a stated price. The needles below were DERIVED from
`/home/patrick/Projects/AIPass/.gitignore` by reading it line by line -
`.trinity/`, `.ai_mail.local/`, `logs/`, `projects/*`, `**/*_json/`,
`DASHBOARD.local.json` and the rest - and then frozen here. The pack is portable;
it lifts onto any Python project and must not go asking that project's VCS for
its configuration, both because a checker that read `.gitignore` would behave
differently in a worktree, a submodule or an export, and because the pack's one
standing promise is stdlib plus corpus and nothing about the audited tree beyond
its Python files. THE PRICE: a project with a different ignore file gets the
AIPass-shaped list. It under-reports there - a directory THAT project ignores and
this list does not spell is invisible - and it can over-report a segment another
project tracks.

READING THE IGNORE FILE LITERALLY IS PART OF THE PRICE BEING HONEST. Two
candidates were dropped by checking rather than assuming, both on 2026-09-08:
`.seedgo` is not in the ignore file at all and `git ls-files` shows
`.seedgo/README.md` and `.seedgo/bypass.json` tracked; `.daemon` is not a
directory line - the only `.daemon` entry is the FILE
`**/.daemon/last_wake_prompt.txt`, and `.daemon/schedule.json` is tracked, so
carrying `.daemon` as a segment convicted @daemon's test_schedule_file_is_a_valid_job
for reading a file the repo ships. `tools/` and `artifacts/` carry negations of
their own and are left out for the same reason. A rule that invents ignores is
worse than one that misses some.

WHAT ACQUITS A SITE, and these are the difference between a rule and a nuisance:

  - THE PATH IS ROOTED AT `tmp_path`, `tmp_path_factory`, `tmpdir`, a
    `TemporaryDirectory` or an `mkdtemp` - directly, or one hop through a name
    bound from one by an assignment, a `with ... as`, a `for ... in`, a
    comprehension or a tuple unpack. A test that builds `tmp_path / "projects" /
    "ghost"` names the ignored spelling on purpose and ships nothing.
  - A SAME-FILE FIXTURE THAT HANDS OUT A SANDBOX, to a fixed point over the
    file's fixtures: @ai_mail's `hosted_baud` requests `repo_root` and
    `repo_root` is the one that requests `tmp_path`. `temp_test_dir` is carried
    by NAME beside the pytest builtins, and only because the fleet's own
    conftest template defines it as `tmp_path / "test_workspace"` - a named
    exception with a reason, never a wildcard.
  - A NESTED `def` INSIDE A UNIT THAT ALREADY ROOTS A SANDBOX. A stand-in the
    test wrote is the test's own scope, and its parameters carry values the unit
    produced. Gated on the unit naming a sandbox at all, so a nested def reading
    real host state in a unit with no `tmp_path` is still a row.
  - THE TEST BUILDS THE TREE IT THEN READS. A `mkdir`, `write_text`,
    `write_bytes` or `touch` on a path carrying the same spelling, in the unit or
    in a same-file fixture the unit requests, means the world under the assertion
    is the world the test made.
  - THE UNIT CARRIES A `pytest.skip` OR `skipif` GUARDED BY AN EXISTENCE CHECK.
    That is a `self_skip` row - a test that reads this machine and steps aside
    when the machine is not it - and it is that rule's business, not this one's.
    Convicting it here would double-convict one line under two standards, and a
    fleet that gets two findings for one defect starts discounting both.
  - THE PATH IS REACHED THROUGH A NEGATED REGION. The ignore file's only `!`
    lines re-admit `src/aipass/spawn/templates/*/.trinity/**` and its siblings,
    with a comment explaining that a template must ship WHOLE. A frozen list
    cannot express a negation, so the negated region is spelled by the ROOT's
    name instead - `get_template_dir()`, `self._template()`, `tpl`, one hop.
  - A PATH USED ONLY TO IMPORT OR LOCATE THE MODULE UNDER TEST. Every test that
    loads a module by file path builds a machine-rooted path; none of them are
    making a claim about the machine.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM, all of it toward FEWER flags:

  - it does not read `.gitignore`, so it cannot know what THIS project ignores -
    see the trade above.
  - it does not follow calls. A read performed by a helper the unit calls, or by
    a fixture in a CONFTEST one directory up, is invisible; so is the build that
    would have acquitted it. @drone's `temp_test_dir` is exactly that shape and
    is reported for it.
  - a path the code under test HANDED BACK - `Path(result["archive_path"])` - is
    not traced to whatever built it. @spawn's birth-receipt row is hermetic under
    `tmp_path` and is reported anyway.
  - one hop of name resolution and no chains. `a = ROOT`, `b = a / ".trinity"`
    is followed; a third assignment is not.
  - it cannot run the clone. Nothing here checks out anything, imports anything
    or asks the filesystem a question - a rule about what a stranger's machine
    has must not be answered by asking this one. It reads text.
  - a flagged site may be perfectly safe for a reason a reader can see and this
    file cannot - a project that ships the directory anyway, a CI stage that
    populates it first. It nominates. A human decides.

STDLIB ONLY - `ast`, `pathlib`, `typing`, and the pack's own corpus reader, like
the rest of the pack. That constraint is why the pack lifts onto any project.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "fresh_clone"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Path SEGMENTS a fresh clone does not have, derived by reading the AIPass root
#: `.gitignore` and then frozen here. SHIPPED, NEVER READ AT AUDIT TIME: the pack
#: is portable and must not depend on the audited project's VCS config. The price
#: is stated in the module docstring and in the rule text - another project gets
#: the AIPass-shaped list.
IGNORED_SEGMENTS: frozenset = frozenset(
    {
        ".trinity",
        ".watchdog",
        ".ai_mail.local",
        "ai_mail.local",
        ".feedback.local",
        ".ai_central",
        ".archive",
        ".backup",
        ".backup_system",
        ".recovery",
        ".seed",
        ".spawn",
        ".chroma",
        "logs",
        "system_logs",
        "artifacts",
        "dropbox",
        "docs.local",
        "projects",
        "mutants",
        "backups",
        "backup_data",
        "branch_audits",
        "readme_history",
    }
)

#: `**/*_json/` - the module runtime JSON convention. A segment, not a filename:
#: `trigger_json/` is a directory of runtime state, `trigger.json` may be source.
IGNORED_SEGMENT_SUFFIXES: tuple = ("_json",)

#: Whole filenames the root `.gitignore` refuses.
IGNORED_FILE_NAMES: frozenset = frozenset(
    {
        "DASHBOARD.local.json",
        "STATUS.local.md",
        "STATUS.md",
        "AIPASS_REGISTRY.json",
        "AIPASS_ROOTS.json",
        "CLOSED_PLANS.local.json",
        "notepad.md",
        "dev.local.md",
        ".devpulse_secret.md",
        # `**/.daemon/last_wake_prompt.txt` is a FILE line, not a directory line.
        # Measured 2026-09-08: `.daemon/schedule.json` is tracked, and an earlier
        # draft carrying `.daemon` as a segment convicted daemon's
        # test_schedule_file_is_a_valid_job for reading a file the repo ships.
        # The ignore file is read literally, or the rule invents ignores.
        "last_wake_prompt.txt",
    }
)

#: The root `.gitignore`'s ONLY `!` negations, and what they mean here. Four
#: lines re-admit `src/aipass/spawn/templates/*/.trinity/**` and its siblings,
#: with a comment saying why: "a template must ship WHOLE (the 2026-08-17 CI red
#: proved it: swallowed payload dirs mean fresh clones mint citizens with no
#: birth certificate)". So a `.trinity` reached through something spelled
#: `template` IS shipped, and flagging it is exactly backwards. A frozen list
#: cannot express a negation, so the negated REGION is spelled instead.
#: Measured 2026-09-08: 7 @spawn rows, every one a template passport read.
#: THE PRICE: a project whose `templates/` really is ignored gets a hole there.
NEGATED_ROOT_SPELLINGS: tuple = ("template",)

#: `*.local.md` - the blanket line, and the plan-file prefixes beside it.
IGNORED_FILE_SUFFIXES: tuple = (".local.md",)
IGNORED_FILE_PREFIXES: tuple = ("FPLAN-", "DPLAN-", "RPLAN-", "TDPLAN-", "PPLAN-", "APLAN-")

#: Names whose value pytest (or tempfile) creates and removes. A path rooted at
#: one of these is the test's own world, whatever it is spelled.
SANDBOX_SEEDS: frozenset = frozenset(
    {
        "tmp_path",
        "tmp_path_factory",
        "tmpdir",
        "tmpdir_factory",
        "TemporaryDirectory",
        "NamedTemporaryFile",
        "mkdtemp",
        "mkstemp",
        "gettempdir",
        # A NAMED EXCEPTION, NOT A WILDCARD. `temp_test_dir` is not a pytest
        # builtin - it is the fleet's own sandbox, defined in
        # seedgo/templates/test_conftest_template.py as
        # `test_dir = tmp_path / "test_workspace"` with a yield and a cleanup,
        # and copied into branch conftests fleet-wide. It is listed here for
        # that reason and no other: it resolves to tmp_path in the template that
        # mints it. A conftest fixture is invisible to this reader (the limit is
        # published), so the ONE name the whole fleet shares is carried by name.
        # Measured 2026-09-08: 1 @drone row, test_project_root_message_does_not_
        # claim_a_passport, which plants its own registry under this fixture.
        "temp_test_dir",
    }
)

#: Call spellings that keep an expression a PATH. Used to decide whether a name
#: is worth resolving one hop: `result = _run(script, cwd=Path(__file__).parent)`
#: mentions a machine root inside a keyword and is a CompletedProcess, not a
#: path, and expanding it made @spawn's subprocess harness read as a derived
#: expectation twice. Measured 2026-09-08, both correct code.
PATH_SHAPED_CALLS: frozenset = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PosixPath", "str", "resolve", "absolute", "expanduser", "joinpath"}
)

#: Calls that answer "where am I" from the running machine.
MACHINE_ROOT_CALLS: frozenset = frozenset(
    {"find_repo_root", "get_repo_root", "find_branch_root", "get_branch_root", "repo_root", "getcwd", "cwd"}
)

#: Attributes and calls that climb from a file to a DIRECTORY. `__file__` alone
#: names the running test file, which the repo ships by definition - it IS the
#: test. Its ancestor directories are what hold whatever this machine happens to
#: have. Measured 2026-09-08: seven rows across @backup, @commons and @devpulse
#: were `module_file(__file__)` - a resolver handed its own module path - and
#: every one of them is correct code that a clone runs identically.
CLIMBING_ATTRIBUTES: frozenset = frozenset({"parent", "parents"})
CLIMBING_CALLS: frozenset = frozenset({"os.path.dirname", "dirname"})

#: Attributes that turn a machine path back into a PLATFORM constant. `/` is not
#: this checkout. Measured: ai_mail's test_returns_none_at_filesystem_root walks
#: `Path(Path(__file__).resolve().anchor)` to prove the resolver terminates at
#: the filesystem root, which is the same answer on every machine on this
#: platform, and the first draft called it a derived expectation.
PLATFORM_CONSTANT_ATTRIBUTES: frozenset = frozenset({"anchor", "root", "drive", "parts"})

#: Methods that ask the filesystem whether something is there.
EXISTENCE_METHODS: frozenset = frozenset({"exists", "is_dir", "is_file", "is_symlink", "isdir", "isfile"})

#: Methods that read a path rather than change it.
READING_METHODS: frozenset = frozenset(
    {
        "exists",
        "is_dir",
        "is_file",
        "is_symlink",
        "iterdir",
        "glob",
        "rglob",
        "read_text",
        "read_bytes",
        "open",
        "stat",
        "samefile",
    }
)

#: Functions that read a path handed to them as an argument.
READING_FUNCTIONS: frozenset = frozenset(
    {
        "open",
        "os.listdir",
        "os.scandir",
        "os.walk",
        "os.stat",
        "os.path.exists",
        "os.path.isdir",
        "os.path.isfile",
        "os.path.getsize",
        "json.load",
    }
)

#: Methods that list what a directory currently holds. Their RECEIVER is the
#: world, so the third arm reads it the way it reads a call argument.
LISTING_METHODS: frozenset = frozenset({"iterdir", "glob", "rglob", "scandir", "walk", "listdir"})

#: Methods and functions that CREATE what they name. A test that builds the tree
#: it then reads is measuring its own world, on any machine.
BUILDING_METHODS: frozenset = frozenset({"mkdir", "write_text", "write_bytes", "touch", "symlink_to", "hardlink_to"})
BUILDING_FUNCTIONS: frozenset = frozenset({"os.makedirs", "os.mkdir", "shutil.copytree", "shutil.copy", "shutil.copy2"})

#: Calls that merely POINT at something - import machinery, path plumbing,
#: formatting. A derived root reaching one of these is being located, not
#: described, and locating the module under test is exactly what tests do.
NOT_THE_WORLD: frozenset = frozenset(
    {
        "str",
        "Path",
        "PurePath",
        "fspath",
        "insert",
        "append",
        "chdir",
        "syspath_prepend",
        "spec_from_file_location",
        "module_from_spec",
        "SourceFileLoader",
        "exec_module",
        "print",
        "len",
        "repr",
        "format",
        "join",
        "relative_to",
        "resolve",
        "skip",
        "skipif",
        "fail",
        "patch",
        "object",
        "setattr",
        "setenv",
        "delenv",
        "monkeypatch",
        # String and container methods. A derived root reaching one of these is
        # being COMPARED or SPLIT, not described. Measured: daemon's
        # test_install_does_not_touch_the_real_home filters recorded writes with
        # `p.startswith(str(repo_root))`, which is a correct test doing string
        # work, and the first draft called it a world.
        "startswith",
        "endswith",
        "split",
        "rsplit",
        "strip",
        "lstrip",
        "rstrip",
        "replace",
        "lower",
        "upper",
        "encode",
        "decode",
        "count",
        "index",
        "find",
        "add",
        "get",
        "update",
        "extend",
        "sort",
        "sorted",
        "set",
        "list",
        "tuple",
        "dict",
        "int",
        "float",
        "bool",
    }
    | BUILDING_METHODS
    | EXISTENCE_METHODS
)

#: Calls whose name means "step aside on this machine". Paired with an existence
#: probe they are a `self_skip` row, and this rule leaves that unit alone.
SKIP_CALLS: frozenset = frozenset({"skip", "skipif"})

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message printing hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# READING NAMES AND WHAT THEY ARE ROOTED AT
# =============================================================================


def _tail(dotted: str) -> str:
    """The last component of a dotted call spelling."""
    return dotted.rsplit(".", 1)[-1]


def _names_under(node: ast.AST) -> Set[str]:
    """Every bare name and dotted call target under a node."""
    found: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Call):
            dotted = corpus.dotted_name(child.func)
            if dotted:
                found.add(dotted)
                found.add(_tail(dotted))
    return found


def _assign_targets(node: Union[ast.Assign, ast.AnnAssign]) -> Sequence[ast.expr]:
    """The target expressions of an assignment, in either spelling."""
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _bound_names(node: ast.AST) -> Dict[str, ast.expr]:
    """Every name assigned under a node, mapped to the expression it came from.

    Walks rather than reading the top level only, because the assignment that
    matters is routinely inside a `with` block or an `if`.
    """
    bound: Dict[str, ast.expr] = {}
    for child in ast.walk(node):
        if not isinstance(child, (ast.Assign, ast.AnnAssign)) or child.value is None:
            continue
        for target in _assign_targets(child):
            if isinstance(target, ast.Name):
                bound[target.id] = child.value
    return bound


def _nested_parameter_names(unit_node: ast.AST) -> Set[str]:
    """Every parameter of a function DEFINED INSIDE this unit.

    A nested `def` in a test body is a stand-in the unit wrote, and the values
    its parameters receive are values the unit produced - directly, or through
    the code under test out of data the unit built. That is the same scope the
    unit owns, not a hop across files.
    """
    names: Set[str] = set()
    for child in ast.walk(unit_node):
        if child is unit_node or not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        spec = child.args
        names |= {a.arg for a in [*spec.posonlyargs, *spec.args, *spec.kwonlyargs]}
    return names


def _sandbox_names(unit_node: ast.AST, seeds: Optional[Set[str]] = None) -> Set[str]:
    """Names that resolve to a directory pytest or tempfile creates and removes.

    A FIXED POINT OVER THE UNIT'S OWN ASSIGNMENTS, so `root = tmp_path / "x"`
    then `inner = root / "y"` both carry the acquittal. It never leaves the unit,
    never resolves an import and never executes anything - the same shape
    `host_state` uses for its `tmp_path` acquittal.

    ASSIGNMENTS, `with ... as`, `for ... in` AND COMPREHENSIONS, because a loop
    binds a name exactly the way an assignment does and pytest users write
    `for d in (a, b, c): read(d / "DASHBOARD.local.json")`. Measured 2026-09-08:
    one @flow row, where a, b and c were three tmp_path branches and `d` was the
    only spelling the reader saw.

    AND THE PARAMETERS OF A NESTED `def`, but ONLY IN A UNIT THAT ALREADY ROOTS A
    SANDBOX. @memory's test_missing_file_skipped builds `branch_dir = tmp_path /
    "src" / "aipass" / "empty_branch"`, puts `str(branch_dir)` into a dict, and
    hands that dict to a stand-in it defined three lines earlier:
    `def mock_get_path(branch, mem_type): p = Path(branch["path"]) / ".trinity"`.
    The world is tmp_path all the way down; the only thing the reader could see
    was a parameter name. The gate matters - a unit that names no sandbox at all
    gets no such acquittal, so a nested def reading real host state is still a
    row. This is generous inside one unit, which is the safe direction, and it
    is the reason it is spelled as a gate rather than as a blanket.

    `seeds` carries in the same-file fixtures that hand out a sandbox - see
    `sandbox_fixtures`, and see the six ai_mail rows that measured why.
    """
    bound: Set[str] = set(SANDBOX_SEEDS) | set(seeds or ())
    if _names_under(unit_node) & bound:
        bound |= _nested_parameter_names(unit_node)
    changed = True
    while changed:
        changed = False
        for child in ast.walk(unit_node):
            fresh = _names_bound_from(child, bound)
            if fresh:
                bound |= fresh
                changed = True
    return bound


def _binding_form(child: ast.AST) -> Tuple[Sequence[ast.expr], Optional[ast.expr]]:
    """The names a node binds and the value it binds them from, or ([], None).

    Three forms bind a name the same way for this reader - an assignment, a
    `with ... as`, and the target of a loop or comprehension - so they are read
    in one place and answered in one shape.
    """
    if isinstance(child, (ast.Assign, ast.AnnAssign)) and child.value is not None:
        return _assign_targets(child), child.value
    if isinstance(child, ast.withitem) and child.optional_vars is not None:
        return [child.optional_vars], child.context_expr
    if isinstance(child, (ast.For, ast.AsyncFor, ast.comprehension)):
        return [child.target], child.iter
    return [], None


def _names_bound_from(child: ast.AST, bound: Set[str]) -> Set[str]:
    """Names this binding adds to the sandbox set, given what is already in it."""
    targets, value = _binding_form(child)
    if value is None or not (_names_under(value) & bound):
        return set()
    return _target_names(targets) - bound


def _target_names(targets: Sequence[ast.expr]) -> Set[str]:
    """Every name an assignment binds, unpacking included.

    `project, reg = _make_project(tmp_path, ...)` binds two names off one
    sandbox-rooted call, and a reader that only understood a bare `Name` target
    called both of them live state. Measured 2026-09-08: four @spawn rows and
    five @memory rows, every one of them a tuple unpack of a tmp_path helper.
    Unpacking is generous - if any element is the sandbox, all of them carry the
    acquittal - and generous is the safe direction for a rule that accuses.
    """
    names: Set[str] = set()
    for target in targets:
        for child in ast.walk(target):
            if isinstance(child, ast.Name):
                names.add(child.id)
    return names


def _class_scopes(tree: ast.Module) -> Dict[str, Dict[str, ast.expr]]:
    """Class name -> the constants assigned directly in that class body.

    THE DAEMON ROW LIVES HERE. `BRANCH_ROOT = Path(__file__).resolve().parents[1]`
    is a class attribute, referenced as `self.BRANCH_ROOT` in every method below
    it. A reader that only knew module-level names would have called that unit
    clean while it handed the live branch root to the code under test.
    """
    return {node.name: _bound_names_in_body(node.body) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def _bound_names_in_body(body: Sequence[ast.stmt]) -> Dict[str, ast.expr]:
    """Names assigned directly in a statement list, one level deep."""
    bound: Dict[str, ast.expr] = {}
    for node in body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        for target in _assign_targets(node):
            if isinstance(target, ast.Name):
                bound[target.id] = node.value
    return bound


def unit_scope(unit: corpus.TestUnit, module_scope: Dict[str, ast.expr], classes: Dict[str, Dict]) -> Dict:
    """Every name this unit could resolve, one hop: module, class, then local.

    Local last on purpose - a unit that rebinds a module constant means the local
    one, and a rule reading the wrong half would be guessing.
    """
    scope: Dict[str, ast.expr] = dict(module_scope)
    scope.update(classes.get(unit.class_name, {}))
    scope.update(_bound_names(unit.node))
    return scope


def _one_hop(expr: ast.expr, scope: Dict[str, ast.expr]) -> List[ast.expr]:
    """The expression, plus the expression behind each name it mentions.

    ONE HOP, NEVER A CHAIN. Following assignments to a fixed point across scopes
    would mean re-implementing the interpreter and would start nominating a fleet.
    """
    forms: List[ast.expr] = [expr]
    for child in ast.walk(expr):
        key = ""
        if isinstance(child, ast.Name):
            key = child.id
        elif isinstance(child, ast.Attribute):
            key = child.attr
        behind = scope.get(key)
        if behind is not None and behind is not expr:
            forms.append(behind)
    return forms


# =============================================================================
# WHERE A NODE SITS - the ancestor walk both acquittals need
# =============================================================================


def parent_map(root: ast.AST) -> Dict[int, ast.AST]:
    """Child id -> parent node, for one unit.

    `ast` gives no way up, and every question this rule asks about a string
    literal - is it read, is it built, is it merely located - is a question about
    what encloses it.
    """
    parents: Dict[int, ast.AST] = {}
    for node in ast.walk(root):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _ancestors(node: ast.AST, parents: Dict[int, ast.AST]) -> List[ast.AST]:
    """Every node enclosing this one, innermost first."""
    chain: List[ast.AST] = []
    current = parents.get(id(node))
    while current is not None:
        chain.append(current)
        current = parents.get(id(current))
    return chain


def _call_role(call: ast.Call, child: ast.AST) -> str:
    """What one enclosing call does with the node under it: build, read, or "".

    A method's RECEIVER and a function's ARGUMENT are the same question asked two
    ways, so both are read here rather than at two call sites that drift apart.
    `child` is the DIRECT child of the call on the path up from the node - for a
    method call that is `call.func`, so receiver-ness is one identity test rather
    than a walk of the receiver subtree.
    """
    dotted = corpus.dotted_name(call.func)
    tail = _tail(dotted)
    on_receiver = child is call.func
    if on_receiver and tail in BUILDING_METHODS:
        return "build"
    if dotted in BUILDING_FUNCTIONS:
        return "build"
    if on_receiver and tail in READING_METHODS:
        return "read"
    if dotted in READING_FUNCTIONS:
        return "read"
    return ""


def _direct_role(node: ast.AST, parents: Dict[int, ast.AST]) -> str:
    """What the calls enclosing this node do with it: "build", "read", or "".

    Reads the enclosing chain once. "build" outranks "read" because a test that
    creates a path and then reads it back is measuring its own world - the
    acquittal has to win wherever both are true.
    """
    role = ""
    child: ast.AST = node
    ancestor = parents.get(id(node))
    while ancestor is not None:
        if isinstance(ancestor, ast.Call):
            found = _call_role(ancestor, child)
            if found == "build":
                return "build"
            role = role or found
        child, ancestor = ancestor, parents.get(id(ancestor))
    return role


def _bound_to_name(node: ast.AST, parents: Dict[int, ast.AST]) -> str:
    """The name this node is assigned to, or "".

    `document = branch / ".trinity"` says nothing on its own; what the unit then
    does with `document` is the evidence, and it lives nowhere in this node's
    ancestry.
    """
    for ancestor in _ancestors(node, parents):
        if not isinstance(ancestor, (ast.Assign, ast.AnnAssign)):
            continue
        names = [t.id for t in _assign_targets(ancestor) if isinstance(t, ast.Name)]
        if names:
            return names[0]
    return ""


def _name_uses(unit_node: ast.AST) -> Dict[str, List[ast.Name]]:
    """Name -> every load of that name inside the unit, walked once."""
    uses: Dict[str, List[ast.Name]] = {}
    for node in ast.walk(unit_node):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            uses.setdefault(node.id, []).append(node)
    return uses


def _role_of(node: ast.AST, parents: Dict[int, ast.AST], uses: Dict[str, List[ast.Name]]) -> str:
    """What the unit does with this node, following one assignment.

    ONE HOP THROUGH A NAME AND NO MORE, which is the same budget the rest of this
    file spends. `p = root / ".trinity"` then `p.read_text()` is followed;
    `q = p.parent` then `q.read_text()` is not.
    """
    role = _direct_role(node, parents)
    if role == "build":
        return "build"
    for use in uses.get(_bound_to_name(node, parents), ()):
        found = _direct_role(use, parents)
        if found == "build":
            return "build"
        role = role or found
    return role


def _is_written_down(node: ast.expr) -> bool:
    """True when an expression is a value the author TYPED rather than computed."""
    if isinstance(node, ast.Constant):
        return node.value is not None and not isinstance(node.value, bool)
    return isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict))


def pins_a_written_expectation(node: ast.Assert) -> bool:
    """True when this assert compares something against a value spelled in the file.

    THE NARROWING THAT MAKES THE SPECIES NAME TRUE, and it took four families off
    the fleet at once. `DERIVED_EXPECTED` is about an EXPECTED value copied off
    one machine - `sorted(result["structure_checks"]) == [".trinity/local.json",
    ".trinity/observations.json"]`. It is not about a test that hands a root to
    production and then asserts a PROPERTY of the answer.

    Measured 2026-09-08, all four correct code: @drone's find_repo_root pin
    asserts `is_absolute()`, `is_dir()` and "carries a project marker"; @memory's
    gateway pin asserts one implementation equals another, both handed the same
    root; @hooks' bash_writes pins assert `len(hits) == len(set(hits))` and
    "every target has an alphanumeric character". Every one of those answers the
    same on a fresh clone, because none of them wrote the machine's answer down.
    """
    for child in ast.walk(node.test):
        if not isinstance(child, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in child.ops):
            continue
        if any(_is_written_down(side) for side in [child.left, *child.comparators]):
            return True
    return False


def _asserted_names(unit_node: ast.AST) -> Set[str]:
    """Names compared against a written-down value somewhere in this unit."""
    found: Set[str] = set()
    for node in ast.walk(unit_node):
        if not isinstance(node, ast.Assert) or not pins_a_written_expectation(node):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                found.add(child.id)
    return found


def _path_expression_around(node: ast.expr, parents: Dict[int, ast.AST]) -> ast.expr:
    """The widest path-shaped expression enclosing a node.

    Climbs through `/` chains, attribute access, subscripts and calls, and stops
    at the first statement. That is the expression whose ROOT decides whether
    this path lives under `tmp_path`.

    Expression in, expression out: the climb stops at the first ancestor that is
    not one of four expression forms, so the widest node it can reach is still
    something the one-hop reader downstream can walk.
    """
    widest: ast.expr = node
    for ancestor in _ancestors(node, parents):
        if not isinstance(ancestor, (ast.BinOp, ast.Attribute, ast.Subscript, ast.Call)):
            break
        widest = ancestor
    return widest


# =============================================================================
# ARM ONE - A PATH THE REPO REFUSES TO SHIP
# =============================================================================


def is_ignored_segment(segment: str) -> bool:
    """True when one path segment matches a root `.gitignore` pattern.

    Segment-wise rather than substring-wise, so `logs` matches `branch/logs/x`
    and never matches `catalogs.py`.
    """
    if not segment or segment in {".", "..", "*"}:
        return False
    if segment in IGNORED_SEGMENTS or segment in IGNORED_FILE_NAMES:
        return True
    if segment.endswith(IGNORED_SEGMENT_SUFFIXES) or segment.endswith(IGNORED_FILE_SUFFIXES):
        return True
    return segment.startswith(IGNORED_FILE_PREFIXES)


def _ignored_spelling(text: str) -> str:
    """The first ignored segment inside one string literal, or "".

    A literal is split on both separators, so `".trinity/local.json"` and
    `"logs"` are read the same way one `/` chain would be.
    """
    for segment in text.replace("\\", "/").split("/"):
        if is_ignored_segment(segment):
            return segment
    return ""


def _path_literals(unit_node: ast.AST) -> List[Tuple[ast.Constant, str]]:
    """String literals sitting in a position that builds a path.

    THE NARROWING THAT KEEPS THIS ARM HONEST. A bare `".trinity/local.json"` in
    an expected-value list is DATA - it is what a producer returned, not a path
    this unit opened - and reading it as a path would convict the daemon row
    under the wrong species while telling a reader to go and look at a string.
    So a literal counts only when it is an operand of a `/` chain, an argument to
    a path constructor or a reading function, or a glob pattern.
    """
    found: List[Tuple[ast.Constant, str]] = []
    for node in ast.walk(unit_node):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            found.extend(_string_constants((node.left, node.right)))
        elif isinstance(node, ast.Call):
            found.extend(_literal_arguments(node))
    return found


def _string_constants(nodes: Sequence[ast.expr]) -> List[Tuple[ast.Constant, str]]:
    """Every string-literal node in a sequence, paired with its text."""
    return [(n, n.value) for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _literal_arguments(node: ast.Call) -> List[Tuple[ast.Constant, str]]:
    """String literal arguments to a call that treats them as a path."""
    dotted = corpus.dotted_name(node.func)
    tail = _tail(dotted)
    path_shaped = tail in {"Path", "PurePath", "PurePosixPath", "glob", "rglob", "joinpath"}
    path_shaped = path_shaped or dotted in READING_FUNCTIONS or dotted in {"os.path.join", "os.path.exists"}
    if not path_shaped:
        return []
    return _string_constants(node.args)


def _built_spellings(unit_node: ast.AST) -> Set[str]:
    """Ignored segments this unit CREATES, which is the acquittal for reading them."""
    parents = parent_map(unit_node)
    uses = _name_uses(unit_node)
    built: Set[str] = set()
    for literal, text in _path_literals(unit_node):
        segment = _ignored_spelling(text)
        if segment and _role_of(literal, parents, uses) == "build":
            built.add(segment)
    return built


def _rooted_in_a_negated_region(expr: ast.expr, scope: Dict[str, ast.expr]) -> bool:
    """True when the path is reached through something the ignore file re-admits.

    Read off the SPELLING of whatever roots the expression - `get_template_dir()`,
    `self._template()`, `template_path` - because that is all a static reader
    has. It is a text test and it is named as one.

    One hop through the scope, like everything else here, because @spawn writes
    `tpl = self._template()` at the top of the unit and reads `tpl / ".trinity"`
    underneath it.
    """
    for form in _one_hop(expr, scope):
        for name in _names_under(form):
            if any(spelling in name.lower() for spelling in NEGATED_ROOT_SPELLINGS):
                return True
    return False


def _ignored_path(
    unit: corpus.TestUnit, sandbox: Set[str], built_elsewhere: Set[str], scope: Dict[str, ast.expr]
) -> List[Dict]:
    """Findings for paths a fresh clone does not have."""
    parents = parent_map(unit.node)
    uses = _name_uses(unit.node)
    built = _built_spellings(unit.node) | built_elsewhere
    rows: List[Dict] = []
    for literal, text in _path_literals(unit.node):
        segment = _ignored_spelling(text)
        if not segment or segment in built:
            continue
        if _role_of(literal, parents, uses) != "read":
            continue
        spine = _path_expression_around(literal, parents)
        if _names_under(spine) & sandbox or _rooted_in_a_negated_region(spine, scope):
            continue
        rows.append(
            _finding(
                "IGNORED_PATH",
                unit,
                getattr(literal, "lineno", unit.line),
                f"reads '{text}' - the segment '{segment}' matches a root .gitignore pattern, so a "
                f"fresh clone has nothing there and this unit never builds it",
            )
        )
    return rows


# =============================================================================
# ARM TWO - AN ORACLE THAT IS A RUNTIME IF ON THE MACHINE
# =============================================================================


def _existence_probe(node: ast.AST) -> str:
    """The existence question an expression asks the filesystem, or ""."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        dotted = corpus.dotted_name(child.func)
        if _tail(dotted) in EXISTENCE_METHODS:
            return dotted or _tail(dotted)
    return ""


def _asserts_in(statements: Sequence[ast.stmt]) -> bool:
    """True when a block of statements contains an assert anywhere."""
    return any(isinstance(child, ast.Assert) for stmt in statements for child in ast.walk(stmt))


def _both_worlds(unit: corpus.TestUnit, sandbox: Set[str]) -> List[Dict]:
    """Findings for a unit that asserts one thing here and another thing there."""
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.If) or not node.orelse:
            continue
        probe = _existence_probe(node.test)
        if not probe or _names_under(node.test) & sandbox:
            continue
        if not (_asserts_in(node.body) and _asserts_in(node.orelse)):
            continue
        rows.append(
            _finding(
                "BOTH_WORLDS",
                unit,
                node.lineno,
                f"branches on {probe}() and asserts in both arms - the oracle is a runtime question about "
                f"THIS machine, so whichever arm this host takes is the only arm anyone ever runs and the "
                f"other one is prose. A fresh clone takes the arm you did not write for it",
            )
        )
    return rows


# =============================================================================
# ARM THREE - AN EXPECTED VALUE DERIVED FROM THIS MACHINE
# =============================================================================


def _climbs_to_a_directory(expr: ast.expr) -> bool:
    """True when an expression walks up from a file to the directory holding it."""
    for child in ast.walk(expr):
        if isinstance(child, ast.Attribute) and child.attr in CLIMBING_ATTRIBUTES:
            return True
        if isinstance(child, ast.Call) and corpus.dotted_name(child.func) in CLIMBING_CALLS:
            return True
    return False


def _machine_root_seed(expr: ast.expr) -> str:
    """How an expression asks the running machine where it is, or "".

    `__file__` counts only once it has been CLIMBED. The test file itself is
    shipped - it is the thing being run - so handing it to a resolver says
    nothing about the host. `Path(__file__).parents[1]` is a directory whose
    contents are this checkout's business and nobody else's.
    """
    for child in ast.walk(expr):
        if isinstance(child, ast.Attribute) and child.attr in PLATFORM_CONSTANT_ATTRIBUTES:
            return ""
    for child in ast.walk(expr):
        if isinstance(child, ast.Call) and _tail(corpus.dotted_name(child.func)) in MACHINE_ROOT_CALLS:
            return corpus.dotted_name(child.func) or "cwd"
    if _climbs_to_a_directory(expr) and any(
        isinstance(child, ast.Name) and child.id == "__file__" for child in ast.walk(expr)
    ):
        return "Path(__file__).parents[...]"
    return ""


def _holds_a_literal(expr: ast.expr) -> bool:
    """True when an expression spells any string out loud."""
    return any(isinstance(c, ast.Constant) and isinstance(c.value, str) for c in ast.walk(expr))


def _is_path_shaped(expr: ast.expr) -> bool:
    """True when an expression is a path chain rather than some other value.

    Walks leftward through `/` chains, attribute access, subscripts and the
    handful of calls that keep a path a path. A name bound to anything else -
    a subprocess result, a parsed document - is not resolved one hop, because
    the machine root it happens to MENTION is not the value it holds.
    """
    node: ast.AST = expr
    while True:
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
            continue
        if isinstance(node, ast.BinOp):
            node = node.left
            continue
        if not isinstance(node, ast.Call):
            return isinstance(node, ast.Name)
        called = _tail(corpus.dotted_name(node.func))
        if called in PATH_SHAPED_CALLS:
            node = node.func
            continue
        if called in MACHINE_ROOT_CALLS:
            return True
        return False


def bare_machine_root(expr: ast.expr, scope: Dict[str, ast.expr]) -> str:
    """The machine root this expression IS, with no literal segment on it, or "".

    BARE IS THE WHOLE NARROWING. `Path(__file__).parent / "fixtures" / "a.json"`
    is machine-rooted and fresh-clone safe, because the repo ships that file. A
    root with nothing appended is a DIRECTORY, and a directory handed to
    production is the machine answering a question the test was supposed to
    answer.
    """
    forms = [expr] + [f for f in _one_hop(expr, scope)[1:] if _is_path_shaped(f)]
    seed = ""
    for form in forms:
        seed = seed or _machine_root_seed(form)
    if not seed or any(_holds_a_literal(form) for form in forms):
        return ""
    return seed


def _reaches_an_assert(node: ast.AST, parents: Dict[int, ast.AST], asserted: Set[str]) -> bool:
    """True when a call's answer is compared against a value spelled in the file.

    Either the call sits inside such an assert, or its result is bound to a name
    one of them names. One hop through the assignment, like everything here.
    """
    for ancestor in _ancestors(node, parents):
        if isinstance(ancestor, ast.Assert):
            return pins_a_written_expectation(ancestor)
        if isinstance(ancestor, (ast.Assign, ast.AnnAssign)):
            names = {t.id for t in _assign_targets(ancestor) if isinstance(t, ast.Name)}
            if names & asserted:
                return True
    return False


def _world_arguments(call: ast.Call) -> List[ast.expr]:
    """The expressions this call is being handed as a world to describe.

    A method that LISTS reads its receiver, a function reads its arguments, and
    a call that only points at something - `str`, `sys.path.insert`,
    `spec_from_file_location` - is handed nothing at all.
    """
    dotted = corpus.dotted_name(call.func)
    tail = _tail(dotted)
    if tail in LISTING_METHODS and isinstance(call.func, ast.Attribute):
        return [call.func.value]
    if tail in NOT_THE_WORLD:
        return []
    return list(call.args)


def _derived_expected(unit: corpus.TestUnit, scope: Dict[str, ast.expr]) -> List[Dict]:
    """Findings for a value the machine, not the test, decided."""
    parents = parent_map(unit.node)
    asserted = _asserted_names(unit.node)
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        seeds = [bare_machine_root(a, scope) for a in _world_arguments(node)]
        seed = next((s for s in seeds if s), "")
        if not seed or not _reaches_an_assert(node, parents, asserted):
            continue
        rows.append(
            _finding(
                "DERIVED_EXPECTED",
                unit,
                node.lineno,
                f"hands {seed} - this machine's own root, with no path segment on it - to "
                f"{corpus.dotted_name(node.func) or 'a call'}() and then asserts on the answer. The expected "
                f"value is whatever this checkout happens to contain; a fresh clone contains something else",
            )
        )
    return rows


# =============================================================================
# ACQUITTALS THAT COVER A WHOLE UNIT
# =============================================================================


def skip_guarded(unit: corpus.TestUnit) -> bool:
    """True when the unit steps aside on a machine that lacks what it reads.

    THAT IS A `self_skip` ROW, NOT THIS RULE'S BUSINESS. A test carrying
    `pytest.skip` behind an `exists()` check has already declared that it reads
    the host; the standard that judges whether a skip is honest is `self_skip`,
    and convicting the same line here would hand a fleet two findings for one
    defect. A fleet that gets two findings for one defect discounts both.
    """
    calls = {_tail(corpus.dotted_name(n.func)) for n in ast.walk(unit.node) if isinstance(n, ast.Call)}
    return bool(calls & SKIP_CALLS) and bool(_existence_probe(unit.node))


def sandbox_fixtures(tree: ast.Module) -> Set[str]:
    """Same-file fixtures that hand out a directory pytest creates and removes.

    MEASURED, AND IT WAS THE LARGEST FALSE-POSITIVE FAMILY IN THE FIRST RUN. Six
    ai_mail rows were `repo`, a fixture that takes `tmp_path`, builds a whole
    registry tree inside it and yields it; the units then read
    `repo / "projects" / "baud"` and were flagged for naming an ignored segment
    they had built themselves two frames up. A fixture that requests `tmp_path`,
    `tmpdir` or a `TemporaryDirectory` hands out a sandbox, and every unit that
    requests that fixture inherits the acquittal.

    A FIXED POINT OVER THE FILE'S FIXTURES, because a chain of two is ordinary
    and was measured: ai_mail's `hosted_baud` requests `repo_root`, and
    `repo_root` is the one that requests `tmp_path`. A single hop called
    `hosted_baud` live state when it is a temp directory two frames up.

    Requested-by-name, same file - a fixture in a conftest is not seen, and that
    limit is published rather than papered over.
    """
    fixtures = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_fixture(n)]
    found: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in fixtures:
            parameters = {argument.arg for argument in node.args.args}
            if node.name in found or not ((parameters | _names_under(node)) & (SANDBOX_SEEDS | found)):
                continue
            found.add(node.name)
            changed = True
    return found


def _is_fixture(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    """True when a function carries a pytest fixture decorator."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _tail(corpus.dotted_name(target)) == "fixture":
            return True
    return False


def fixture_built_spellings(tree: ast.Module) -> Dict[str, Set[str]]:
    """Fixture name -> the ignored segments that fixture CREATES.

    Read once per file rather than once per unit: the same six fixtures were
    being re-parsed for every one of a file's four hundred units, and a rule the
    audit engine runs on eighteen branches cannot afford a quadratic.

    One hop, same file, no imports - the shape the rest of the pack uses for a
    delegated read. A fixture in a conftest is not seen, and that limit is
    published rather than papered over.
    """
    return {
        node.name: _built_spellings(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_fixture(node)
    }


# =============================================================================
# ANALYSIS
# =============================================================================


def _finding(species: str, unit: corpus.TestUnit, line: int, detail: str) -> Dict:
    """One row, in the shape every rule in this pack reports."""
    return {"nodeid": unit.nodeid, "line": line, "species": species, "detail": detail}


def unit_flags(
    unit: corpus.TestUnit,
    scope: Dict[str, ast.expr],
    handed_out: Optional[Set[str]] = None,
    fixture_built: Optional[Dict[str, Set[str]]] = None,
) -> List[Dict]:
    """Every fresh-clone finding in one unit, in species order.

    `handed_out` and `fixture_built` are the file's fixtures - which of them hand
    out a sandbox, and which of them build an ignored spelling. Both default to
    none deliberately, so a caller holding no file gets the answer for a unit
    standing alone rather than a silently generous one.
    """
    if skip_guarded(unit):
        return []
    requested = {argument.arg for argument in unit.node.args.args}
    sandbox = _sandbox_names(unit.node, requested & set(handed_out or ()))
    built: Set[str] = set()
    for name in requested:
        built |= (fixture_built or {}).get(name, set())
    return _ignored_path(unit, sandbox, built, scope) + _both_worlds(unit, sandbox) + _derived_expected(unit, scope)


def find_host_dependent(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit whose answer comes from this machine rather than the repo.

    ONE ROW PER UNIT, ALWAYS. A unit carrying two species is one unit a reader
    has to go and look at; counting findings would let a single test drive a
    project's score below zero, and a score that can go negative is one nobody
    believes twice.
    """
    rows: List[Dict] = []
    seen: Set[str] = set()
    for parsed in scanned.files:
        module_scope = _bound_names_in_body(parsed.tree.body)
        classes = _class_scopes(parsed.tree)
        handed_out = sandbox_fixtures(parsed.tree)
        fixture_built = fixture_built_spellings(parsed.tree)
        for unit in parsed.units:
            scope = unit_scope(unit, module_scope, classes)
            for row in unit_flags(unit, scope, handed_out, fixture_built):
                if row["nodeid"] not in seen:
                    seen.add(row["nodeid"])
                    rows.append(row)
    return rows


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests would pass on a fresh clone.

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
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
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
            "checks": [{"name": "Fresh clone survivable", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_host_dependent(scanned)
    score = int(((total - len(flagged)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Fresh clone survivable",
            "passed": not flagged,
            "message": (
                f"{total - len(flagged)}/{total} test units read only what the repo ships"
                if not flagged
                else (
                    f"{len(flagged)}/{total} test units take their answer from state a fresh clone "
                    "does not have: "
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
