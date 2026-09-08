# =================== AIPass ====================
# Name: posix_literal_check.py
# Description: v5 - a path claim that is only true on the platform it was written on
# Version: 1.1.0
# Created: 2026-09-01
# Modified: 2026-09-08
# =============================================

r"""Does this test hardcode one platform's path shape?

    slash_tmp = Path("/tmp").resolve()
    assert slash_tmp in roots

On POSIX that is `/tmp`. On Windows `/tmp` is DRIVE-RELATIVE: ntpath attaches the
current drive and `resolve()` hands back `D:\tmp`. The same line therefore means a
different thing on the other half of the matrix, and the assertion underneath it
accuses code that is working perfectly.

WHERE IT CAME FROM. A windows-setup leg went red on a return-value pin written the
same morning to catch a platform assumption: it compared against `RESOLVED: /tmp`
and CI handed it `D:\tmp`. The species was named in the report and the acquittal
rate asked for before it became a rule, which is the right order to do it in.

THE MEASUREMENT THAT DECIDED THE SHAPE, taken before the original nominator was
written, over 721 test files and 32,841 assert statements:

  - "an assert containing a rooted string literal" ........ 501 sites, 112 files
  - "a rooted literal reaching any callable named
     resolve / realpath / abspath" ....................... 10 sites, 3 files
  - THIS RULE (the receiver must BE a path constructor, or
     the callee an os.path-shaped function) ............... 4 sites, 1 file

The middle arm is the instructive one. Six of its ten sites were
`target_module.resolve("@canary", {...})` - a BRANCH-NAME resolver that happens to
share a verb with pathlib, holding a rooted literal in a dict value it never
resolves. A rule keyed on the method NAME nominates those six forever, and a rule
with that acquittal rate teaches a fleet to ignore it inside a week. Keyed on the
RECEIVER instead, it nominates none of them. That is the whole design.

THE REVERSE SHAPE, AND WHY THIS FILE GREW TWO MORE ARMS ON 2026-09-08. A CI
matrix ran Linux and Windows together for the first time after eight waves of
test work had landed overnight on Linux-only verification. Four rows went red on
a separator, and not one of them held a rooted literal or a resolver. They were
the mirror image of arms 1 and 2:

    assert bypassed[0]["name"] == "File: apps/something.py"   # RETURNED-PATH
    reported = str(warned.call_args)                          # REPR-HAYSTACK
    assert str(logs_dir / "app.log") in reported

ARM 3, RENDERED-PATH / RETURNED-PATH. The code under test renders a Path to TEXT
and the test compares that text with a literal that spells the separator
forward. The
producers are ordinary - `str(item.relative_to(template_path))` at
architecture_check.py:452, `str(relative_path)` at prax scanner.py:57 - and
`str()` of a Path is the HOST's dialect: `apps/something.py` here,
`apps\something.py` there. The literal is right on exactly the leg it was
written on.

ARM 4, REPR-HAYSTACK. `str(mock.call_args)` renders its arguments through
`repr()`, and `repr()` of a Windows path DOUBLES the separator. A needle built
correctly - `str(logs_dir / "app.log")` - still cannot be found inside that
haystack, because the haystack is not the argument, it is a rendering of the
argument. The cure is to assert on `call_args.args[n]` (or `.kwargs`) directly
and never on a rendered repr.

ARM 3 IS SPLIT DOWN THE MIDDLE, AND THE MEASUREMENT IS WHY. The first fleet run
of the undivided arm returned 64 rows and 27 of them were on seedgo - and most
of seedgo's are correct, portable code. `corpus.py:202` returns
`path.relative_to(root).as_posix()`, so every test asserting
`"tests/test_broken.py" in named[0]["message"]` is reading a string that is
posix on every host, forever, on purpose. Sixteen of those 27 are in this pack's
own `test_pytest_quality_pack.py` alone.

The trap is that they are the SAME AST SHAPE as the rows that broke CI. What
separates `result["relative_path"] == "pkg/gamma.py"` (red on Windows) from
`named[0]["message"]` (correct everywhere) is entirely off-screen: prax
`scanner.py:57` renders with `str()`, seedgo `corpus.py:202` renders with
`.as_posix()`. No AST reader of the TEST can see that, and this pack does not
read production for this rule.

A scoring arm that convicts correct code is how a standard gets switched off -
`assertion_shape.md` says exactly that in its own text. So the arm is split by
what the checker CAN see, WHO WROTE THE RENDERING DOWN:

  - SCORING, species RENDERED-PATH. The rendering is visible in the unit -
    `str(x)`, an f-string, `"%s" % x` - over something that looks like a path.
    The TEST chose the dialect, on the line the reader is looking at, so nothing
    off-screen can make it right and the row moves the number.
  - NOMINATE-ONLY, species RETURNED-PATH. The compared value came BACK from the
    code under test: a dict subscript, an attribute, a call result. Whether the
    producer normalised is unreadable from here, so the row is reported in its
    own check line with `passed: True` and is excluded from the score and from
    the failing count. It is a place to look, not a charge.

Both halves get the same cure, which is the other reason the split costs a
reader nothing: compare Path to Path, or put `.as_posix()` on both sides.

WHAT ARM 3 ACTUALLY KEYS ON, SAID PLAINLY, BECAUSE ITS WEAKEST EVIDENCE IS THE
ONE IT MOST OFTEN USES. The scoring shapes are read only when the thing being
rendered LOOKS like a path - a Path constructor, a `/` join, a `tmp_path`-shaped
fixture, or a name, attribute or key spelled `path`, `dir`, `file`, `root`,
`src`, `dest`, `target`, `location`. The nominate-only shapes - a SUBSCRIPT into
a dict or a result (`result["gamma"]["relative_path"]`), an ATTRIBUTE
(`parsed.path`), a CALL RESULT - cannot prove their value came from a Path at
all. This file never claims they do. It reads the accompanying evidence instead:
the spelling is path-ish, OR the unit builds a Path anywhere in its body (a
`Path(...)`, a `/` join, a `tmp_path` fixture). That is circumstantial and it is
written down here so nobody mistakes it for a proof - which is a second reason
this half does not score. It fires on `result["path"] == "src/demo/vera"`; it
does NOT fire on `payload["body"] == "a/b"` inside a unit that never touches a
path, and it CANNOT fire on a dict a helper filled in another file.

WHAT KEEPS ARM 3 OFF THE OTHER 497. A literal only counts when it is RELATIVE -
a rooted one is arms 1 and 2's subject, and of the 501 rooted sites measured
above, 497 are data. Then the text has to look like a filesystem path rather
than a sentence with a slash in it: the run of path characters needs two
segments AND either a trailing slash, a second separator, or a file extension on
its last segment. Measured over the same 18 branches: 353 comparisons hold a
literal with a slash between two path characters, 155 of those have a rendering
or a returned value on the other side, and this narrowing takes it to 68. The 87
it drops were read
one by one, and they fall into six groups: a rooted literal the test wrote down
as INPUT and got back (`/bin/bash`, `/usr/local/bin/claude`, `/logs/flow.log`)
- much the largest group, and arms 1-2's subject, not this one; a fraction or a
rate (`11/10`, `343/300`, `2/2 test scopes`, `150 lines/min`, `50/s`); prose
carrying a slash (`Throwaway path (temp/scratchpad)`); a pytest nodeid; a name
that is not a path at all (`anthropic/claude-3.5-sonnet`, `citizen/drone-fix`,
an scp remote, the route `/v1/fleet`); and three two-segment relative paths with
no extension (`src/daemon`, `src/my_agent`, `apps/handlers`). Only that last
group is a real path, and the floor gives those three up on purpose, because the
same floor is what removes the fractions.

THE COST OF THE TWO NEW ARMS, MEASURED BEFORE AND AFTER over every branch with a
`.trinity` directory. Arms 1-2 found 0 rows fleet-wide (the five sites the
2026-09-07 dialect measurement named have since been cured), so all of this is
new. 70 rows across 8 branches, and the split decides what they cost:

  - SCORED: 2 rows, both REPR-HAYSTACK, both on trigger. Seventeen branches
    stay at 100 and trigger goes to 99. RENDERED-PATH - the scoring half of arm
    3 - finds ZERO rows in this fleet, and that is worth saying out loud rather
    than hiding: nobody here writes `str(p) == "a/b.py"` in a test. The arm is
    kept because it is the shape the cure turns INTO if it is done wrong.
  - NOMINATED, scoring nothing: 68 RETURNED-PATH rows - seedgo 31, spawn 14,
    daemon 9, api 6, drone 4, prax 3, aipass 1.

The nominate-only half is a superset of the shape that broke CI, which is the
point: seedgo's two rows and prax's one are in it, named by nodeid, in a check
line a reader can act on, and they move no number they cannot be defended
against.

WIDENING THE NOMINATE-ONLY HALF FROM SUBSCRIPTS TO ATTRIBUTES AND CALL RESULTS
COST 6 ROWS, measured: 62 -> 68, all of them unscored. seedgo +4, drone +1
(`parsed.path == "foo/bar.txt"`), spawn +1 (`baud.relative_path ==
"src/baud/baud"`). A returned value is a returned value whichever way the source
spells the access, and reading only subscripts would have been a hole with no
reason behind it.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM. It does not claim a flagged line is
wrong. A test that deliberately exercises POSIX spelling - a fence refusing
`/etc/passwd`, a parser fed a known-rooted input - is a legitimate site and stays.
What the flag buys is that the decision gets MADE rather than inherited from
whichever platform the author happened to be standing on.

IT ALSO SAYS NOTHING ABOUT THE MACHINE IT RUNS ON. `"/tmp"` is judged by its first
character and `"C:/tmp"` by its second and third, as text, never by asking the
running interpreter what it would do with them. A rule about portability that
consulted the host would be reporting a different standard on every leg of a
matrix, which is the defect it exists to find. It is also why this file's own pins
can be written on any host and mean the same thing.

ITS HONEST LIMITS, all of them in the direction of FEWER flags:

  - it reads the RECEIVER, so `home = Path("/tmp")` followed by `home.resolve()`
    is invisible. Chasing the value through a variable would mean following
    assignments, and the moment it does that it starts nominating the whole fleet.
  - `from os.path import realpath` then `realpath("/tmp")` is invisible: the call
    target is a bare name, and the module gate wants a dotted receiver whose last
    segment ends in `path`. `import os.path as osp` defeats it for the same reason.
  - a resolver reached through a module that NAMES ITS DIALECT - `ntpath.abspath`,
    `posixpath.realpath` - is acquitted from 2026-09-07. It was convicted until
    then, and that was this file contradicting its own premise: the hazard is that
    `os.path` MEANS a different module per host, so the line means two things. A
    call that spells `ntpath` means one thing everywhere, on every leg, and is the
    cure a flagged site gets rewritten INTO. Measured across 22 branches before
    the change: 5 rows fleet-wide, of which this acquits 2 - both in this pack's
    own hazard demonstration - and no other branch moves, because @drone's three
    are all the receiver arm, which is untouched.
  - it walks TEST UNITS, so a literal resolved in a fixture, in a module-level
    constant or in a helper the unit calls is not seen. Nothing here follows a
    call.
  - a rooted literal that is never resolved is not read at all. 501 sites carry
    one; four of them put it through a resolver, and the other 497 are data.

AND THE NEW ARMS' OWN LIMITS, in the same direction:

  - arm 3 reads ONE comparison. A relpath rendered into a variable on one line
    and compared on the next is invisible, because nothing here follows an
    assignment except arm 4's single hop.
  - arm 3 cannot see `.as_posix()` when the cure lives in PRODUCTION. That is
    the seedgo cluster named above, and it is the whole reason the returned half
    nominates instead of scoring: `corpus._relpath` returns `.as_posix()`, the
    string is posix on every host, and the test asserting on it is right. The
    acquittal it does honour is `.as_posix()`, `os.sep`, `os.path.join` or
    `os.fspath` spelled inside the comparison itself.
  - text that merely CONTAINS a path is read the same as text that is one -
    `"   M src/x.py"`, a line of porcelain output, is nominated. Narrowing to
    whole-literal paths would have dropped `"File: apps/something.py"`, which is
    one of the four rows this arm exists for.
  - arm 4 follows a rendered call record one hop through a local `name = ...`
    and no further. A haystack built in a helper, or reassigned twice, is not
    seen. It also reads only `in` / `not in`: a rendered repr compared with `==`
    is a different and much rarer mistake.
  - arm 4 nominates a rendered repr even when the argument was a plain string
    all along. trigger/tests/test_log_watcher.py:1080 sets `event.src_path` to a
    string and would pass on either host; it is the same shape as the row three
    files over that does not, and telling them apart needs the producer.

WHAT WAS DROPPED IN THE PORT, NAMED RATHER THAN CARRIED. The original nominator
re-tested `isinstance(call.func, ast.Attribute)` at the top of BOTH detector
helpers, and its only caller had already filtered on exactly that - neither guard
could ever fail. Removing them changes no answer; the check now lives once, at the
walker, where the filter actually happens. The same version then re-tested
`isinstance(literal, ast.Constant)` on what the helpers returned, and both helpers
only ever returned a node the rooted-literal predicate had already accepted - and
that predicate opens with the same isinstance. It was always true. Here the helpers
return `Optional[ast.Constant]` so the type carries the fact, instead of a branch
that looks like a check and is really a decoration.

STDLIB ONLY - `ast`, `pathlib`, `typing`, and the pack's own corpus reader. That
constraint is the reason the pack exists and can be lifted onto any project.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "posix_literal"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Constructors whose first argument is a path. A `.resolve()` hanging off one of
#: these is pathlib's resolve and no other object's - which is what keeps a
#: branch-name resolver sharing the verb out of the results.
PATH_CONSTRUCTORS: frozenset = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "PosixPath", "WindowsPath"}
)

#: Module-level functions that normalise a path against process state.
RESOLVER_FUNCTIONS: frozenset = frozenset({"realpath", "abspath"})

#: What the receiver of a resolver function has to look like. `os.path`,
#: `posixpath` and `ntpath` all end in it; `registry`, `shutil` and `helper` do
#: not, and a `helper.abspath(...)` is somebody else's method.
RESOLVER_MODULE_SUFFIX: str = "path"

#: The path modules that name their dialect out loud. `os.path` is an ALIAS -
#: it is `posixpath` on one leg of the matrix and `ntpath` on the other, which
#: is the entire hazard. These two are not: `ntpath.abspath("/x")` returns the
#: same string on every host, because the module IS the answer to "which
#: platform". Convicting them convicts the fix.
DIALECT_MODULES: frozenset = frozenset({"ntpath", "posixpath", "macpath"})

#: The method whose receiver is read rather than whose name is trusted.
RESOLVE_METHOD: str = "resolve"

#: The finding vocabulary. Four species, one rule: a path claim that is only
#: true on the platform it was written on. POSIX-LITERAL is arms 1-2 (a rooted
#: literal put through a resolver); the other three are the reverse shape, a
#: Path rendered to text and compared with a forward-slashed literal.
SPECIES_POSIX_LITERAL: str = "POSIX-LITERAL"
SPECIES_RENDERED_PATH: str = "RENDERED-PATH"
SPECIES_RETURNED_PATH: str = "RETURNED-PATH"
SPECIES_REPR_HAYSTACK: str = "REPR-HAYSTACK"

#: WHICH SPECIES MOVE THE NUMBER. Three of the four: each of them is a defect
#: the checker can see whole, inside the unit. RETURNED-PATH is absent, and the
#: module docstring gives the measurement that put it there - it flags the same
#: AST shape whether production normalised the separator or not, and on the
#: first fleet run 27 of its 62 rows were seedgo's own tests reading a relpath
#: that `corpus._relpath` renders with `.as_posix()`. Correct, portable code.
SCORING_SPECIES: tuple = (SPECIES_POSIX_LITERAL, SPECIES_RENDERED_PATH, SPECIES_REPR_HAYSTACK)

#: How a compared value came to be text, split by WHO WROTE THE RENDERING DOWN.
#: The test did, in the first group - `str(p)`, an f-string, `%s` - so the test
#: owns the dialect and the row scores. The code under test did, in the second,
#: and whether it normalised is off-screen, so the row nominates.
WRITTEN_RENDERINGS: tuple = ("str()", "f-string", "%-format")
RETURNED_PROVENANCES: tuple = ("subscript", "attribute", "call result")

#: Characters a path SEGMENT is made of. Deliberately not `str.isalnum` - a
#: segment carries dots, dashes and underscores, and nothing else here does.
PATH_SEGMENT_CHARS: frozenset = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")

#: The separator arm 3 is about. Only the forward one: a literal spelled with a
#: backslash is already a Windows claim, which is arms 1-2's drive test.
POSIX_SEPARATOR: str = "/"

#: Text that is NOT a filesystem path however many slashes it holds. `://` and
#: a bare `@` between path characters are a URL and an scp-style remote; `::`
#: is a pytest nodeid, and pytest spells those posix on every platform, by
#: contract, which makes a nodeid assertion correct rather than a finding.
NON_PATH_MARKERS: tuple = ("://", "@", "::")

#: How long a trailing `.thing` may be and still read as a file extension. Five
#: covers `.py`, `.json`, `.local`; it does not cover `claude-3.5-sonnet`, which
#: is the model name this bound was measured against.
MAX_EXTENSION_LENGTH: int = 5

#: Builtins that turn an object into text. A Path handed to any of them comes
#: back in the HOST's dialect - that is the whole of arm 3.
RENDER_BUILTINS: frozenset = frozenset({"str", "repr", "format", "ascii"})

#: Name fragments that say an expression is holding a path. Read against a
#: variable, an attribute or a dict key - the three places a rendered relpath
#: is found sitting in the fleet.
PATHISH_NAME_TOKENS: tuple = ("path", "dir", "file", "relpath", "root", "src", "dest", "target", "location")

#: pathlib attributes and methods whose presence identifies the receiver as a
#: Path without having to follow where it came from.
PATH_ATTRIBUTES: frozenset = frozenset(
    {
        "parent",
        "parents",
        "name",
        "stem",
        "suffix",
        "suffixes",
        "relative_to",
        "joinpath",
        "resolve",
        "absolute",
        "with_name",
        "with_suffix",
    }
)

#: Fixture names whose value pytest creates. A path rooted at one of these was
#: derived, not written down - the same reading `host_state` uses.
SANDBOX_FIXTURES: frozenset = frozenset({"tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory"})

#: The spelling that ends the argument. `.as_posix()` says "posix on purpose",
#: and the rest name the separator instead of assuming one. Any of them inside
#: the comparison acquits the whole site.
POSIX_SPELLING_METHOD: str = "as_posix"
SEPARATOR_ACQUITTALS: frozenset = frozenset(
    {"os.sep", "os.path.sep", "os.path.join", "posixpath.join", "ntpath.join", "os.fspath", "os.path.normpath"}
)

#: String methods that read a value against a literal prefix or suffix. The
#: comparison operators are read structurally; these two are calls.
STRING_COMPARISON_METHODS: frozenset = frozenset({"startswith", "endswith"})

#: Mock attributes that hold a RECORD of a call rather than the call's
#: arguments. Rendering one of these runs its contents through `repr()`, which
#: is where a backslash separator doubles - the arm 4 defect.
MOCK_CALL_RECORDS: frozenset = frozenset(
    {"call_args", "call_args_list", "mock_calls", "await_args", "await_args_list", "method_calls"}
)

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# ANALYSIS
# =============================================================================


def is_rooted(text: str) -> bool:
    """True when a string starts at a filesystem root in either dialect.

    Split out of `rooted_literal` on 2026-09-08 with its answers unchanged,
    because arm 3 has to ask the same question about a SUBSTRING - the path run
    inside `"File: apps/something.py"` - and a node-shaped predicate cannot be
    asked about text. One definition of "rooted", read by both.

    Args:
        text: Any string.

    Returns:
        True for `/tmp`, `\\\\server` and `C:/tmp`; False for `tmp` and for the
        empty string.
    """
    if not text:
        return False
    if text[0] in ("/", "\\"):
        return True
    return len(text) > 2 and text[0].isalpha() and text[1] == ":" and text[2] in ("/", "\\")


def rooted_literal(node: ast.AST) -> Optional[ast.Constant]:
    """The node itself when it is a string literal that starts at a root.

    Args:
        node: Any AST node.

    Returns:
        The constant for `"/tmp"`, `"\\\\server"` and `"C:/tmp"`; None for
        `"tmp"`, for the empty string and for anything that is not a string.
    """
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    return node if is_rooted(node.value) else None


def _receiver_literal(func: ast.Attribute) -> Optional[ast.Constant]:
    """The rooted literal a `.resolve()` receiver was constructed from.

    Keyed on the RECEIVER and never on the method name: `Path("/tmp").resolve()`
    is pathlib, while `registry.resolve("@canary", ...)` is a branch-name lookup
    that happens to share a verb. Measured before choosing - the name test
    nominates six such sites fleet-wide and this one nominates none of them.

    Args:
        func: The attribute a call hangs off.

    Returns:
        The literal node, or None.
    """
    if func.attr != RESOLVE_METHOD:
        return None
    receiver = func.value
    if not isinstance(receiver, ast.Call) or not isinstance(receiver.func, ast.Name):
        return None
    if receiver.func.id not in PATH_CONSTRUCTORS or not receiver.args:
        return None
    return rooted_literal(receiver.args[0])


def _argument_literal(call: ast.Call, func: ast.Attribute) -> Optional[ast.Constant]:
    """The rooted literal an `os.path.realpath`-shaped call was handed.

    Args:
        call: The call node, read for its arguments.
        func: The attribute the call hangs off, read for the module it names.

    Returns:
        The literal node, or None.
    """
    if func.attr not in RESOLVER_FUNCTIONS or not call.args:
        return None
    module = corpus.dotted_name(func.value)
    if not module.endswith(RESOLVER_MODULE_SUFFIX):
        return None
    if module in DIALECT_MODULES:
        return None
    return rooted_literal(call.args[0])


def resolved_literals(unit: corpus.TestUnit) -> List[Tuple[str, int]]:
    """Every rooted literal this unit puts through a resolver.

    The public entry point for the rule's reading - the report lane and the tests
    both ask the question here rather than re-deriving it.

    Args:
        unit: One test unit.

    Returns:
        `(literal_text, lineno)` pairs, in source order. The line is the CALL's,
        because that is the line a reader has to go and look at.
    """
    found: List[Tuple[str, int]] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        literal = _receiver_literal(node.func)
        if literal is None:
            literal = _argument_literal(node, node.func)
        if literal is not None:
            found.append((str(literal.value), node.lineno))
    return found


# =============================================================================
# READING A LITERAL AS TEXT
#
# Arm 3 asks whether a string LOOKS like a filesystem path. Everything in this
# block reads characters and never the host - same premise as arms 1-2, so the
# answers are identical on every leg of a matrix.
# =============================================================================


def _path_runs(text: str) -> List[str]:
    """Maximal runs of path-segment characters and forward slashes.

    `"File: apps/something.py"` yields `["File:", "apps/something.py"]` - the
    colon and the space end a run - so a path embedded in a sentence is still
    read as a path. That is deliberate: two of the four rows this arm exists
    for are a rendered relpath with a `File: ` or `Dir: ` label in front.

    Args:
        text: The literal's value.

    Returns:
        The runs, in source order. Empty when the text holds no path character.
    """
    runs: List[str] = []
    current = ""
    for char in text:
        if char in PATH_SEGMENT_CHARS or char == POSIX_SEPARATOR:
            current += char
            continue
        if current:
            runs.append(current)
        current = ""
    if current:
        runs.append(current)
    return runs


def _carries_extension(segment: str) -> bool:
    """True when a segment ends in a plausible file extension.

    Bounded at `MAX_EXTENSION_LENGTH` and required to be alphabetic, which is
    what tells `gamma.py` from `claude-3.5-sonnet`: the tail of the model name
    is `5-sonnet`, and it is neither.
    """
    if "." not in segment:
        return False
    tail = segment.rsplit(".", 1)[1]
    return 0 < len(tail) <= MAX_EXTENSION_LENGTH and tail.isalpha()


def _reads_as_a_path(run: str) -> bool:
    """True when a run of path characters is evidence of a filesystem path.

    Two segments is the floor, and then ONE of three things has to be true: a
    trailing slash (`apps/handlers/`), a second separator (`src/aipass/prax`),
    or an extension on the last segment (`pkg/gamma.py`). Measured over 18
    branches, dropping this test costs 51 nominations and every one of them is
    correct code: a model name, a branch name, `50/s`, `150 lines/min`,
    `Owner/identity OK`, `temp/scratchpad`.
    """
    segments = [part for part in run.split(POSIX_SEPARATOR) if part]
    if len(segments) < 2:
        return False
    return run.endswith(POSIX_SEPARATOR) or run.count(POSIX_SEPARATOR) >= 2 or _carries_extension(segments[-1])


def path_run(text: str, allow_rooted: bool) -> Optional[str]:
    """The filesystem path spelled inside a string literal, or None.

    Acquits a URL, an scp-style remote and a pytest nodeid by marker, because
    none of those is a path the host gets to spell - pytest in particular
    guarantees a posix nodeid on every platform.

    Args:
        text: The literal's value.
        allow_rooted: False for arm 3, where a rooted literal belongs to arms
            1-2 and 497 of the 501 rooted sites in the fleet are data. True for
            arm 4, where the root is not the hazard and the separator is.

    Returns:
        The offending run, or None.
    """
    if any(marker in text for marker in NON_PATH_MARKERS):
        return None
    for run in _path_runs(text):
        if not allow_rooted and is_rooted(run):
            continue
        if _reads_as_a_path(run):
            return run
    return None


def relative_path_run(text: str) -> Optional[str]:
    """Arm 3's reading: the RELATIVE path spelled inside a literal, or None."""
    return path_run(text, allow_rooted=False)


def _literal_run(node: ast.AST) -> Optional[str]:
    """The relative path run of a node, when the node is a string literal."""
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    return relative_path_run(node.value)


# =============================================================================
# READING AN EXPRESSION AS A PATH
# =============================================================================


def _is_pathish_name(text: str) -> bool:
    """True when an identifier or dict key says it holds a path."""
    lowered = text.lower()
    return any(token in lowered for token in PATHISH_NAME_TOKENS)


def _pathish_call(node: ast.Call) -> bool:
    """True when a call constructs or manipulates a Path, or renders one."""
    tail = corpus.dotted_name(node.func).rsplit(".", 1)[-1]
    if tail in PATH_CONSTRUCTORS or tail in PATH_ATTRIBUTES:
        return True
    return any(pathish_expression(arg) for arg in node.args)


def _pathish_subscript(node: ast.Subscript) -> bool:
    """True when a subscript's KEY names a path, or its base is path-ish."""
    key = node.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str) and _is_pathish_name(key.value):
        return True
    return pathish_expression(node.value)


def pathish_expression(node: ast.AST) -> bool:
    """Does this expression look like it is holding a path?

    THE HONEST STATEMENT OF WHAT THIS IS. It is a reading of SPELLING, not a
    type inference - `Path(...)`, a `/` join, a `tmp_path` fixture, a pathlib
    attribute, or a name/attribute/key containing one of `PATHISH_NAME_TOKENS`.
    A path held in a variable called `x` is invisible to it, and a variable
    called `target` that holds a hostname is a false positive. It exists so the
    rendering arms (`str(x)`, an f-string, `%s`) fire on a path and not on every
    string in the fleet.

    Args:
        node: Any AST node.

    Returns:
        True when the spelling is evidence of a path.
    """
    if isinstance(node, ast.Call):
        return _pathish_call(node)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return pathish_expression(node.left) or isinstance(node.right, ast.Constant)
    if isinstance(node, ast.Attribute):
        return node.attr in PATH_ATTRIBUTES or _is_pathish_name(node.attr) or pathish_expression(node.value)
    if isinstance(node, ast.Name):
        return node.id in SANDBOX_FIXTURES or _is_pathish_name(node.id)
    if isinstance(node, ast.Subscript):
        return _pathish_subscript(node)
    if isinstance(node, ast.JoinedStr):
        return any(pathish_expression(part.value) for part in node.values if isinstance(part, ast.FormattedValue))
    return False


def _separator_is_spelled_out(node: ast.AST) -> bool:
    """True when the site names the separator instead of assuming one.

    `.as_posix()` anywhere, or `os.sep` / `os.path.join` / `os.fspath` by their
    dotted spelling. This is the acquittal a flagged site is rewritten INTO, so
    convicting it would convict the cure - the same reasoning that acquits
    `ntpath` and `posixpath` in arm 2.
    """
    for sub in ast.walk(node):
        if not isinstance(sub, (ast.Name, ast.Attribute)):
            continue
        dotted = corpus.dotted_name(sub)
        if dotted in SEPARATOR_ACQUITTALS or dotted.rsplit(".", 1)[-1] == POSIX_SPELLING_METHOD:
            return True
    return False


def _builds_a_path(unit: corpus.TestUnit) -> bool:
    """Does this unit construct a Path anywhere in its body?

    THE WEAKEST EVIDENCE THIS RULE USES, AND IT IS USED ON PURPOSE. A subscript
    into a result dict cannot tell a reader where its value came from, so when
    the key is not path-ish the arm falls back to asking whether the unit is
    working with paths at all. It is circumstantial. It is also what separates
    `bypassed[0]["name"] == "File: apps/something.py"`, in a unit that builds a
    whole tree under `tmp_path`, from a payload assertion in a unit that never
    touches the filesystem.
    """
    for node in ast.walk(unit.node):
        if isinstance(node, ast.arg) and node.arg in SANDBOX_FIXTURES:
            return True
        if isinstance(node, ast.Name) and node.id in SANDBOX_FIXTURES:
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PATH_CONSTRUCTORS:
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and _literal_operand(node.right):
            return True
    return False


def _literal_operand(node: ast.AST) -> bool:
    """True when a node is a plain string literal - a `/` join's right side."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


# =============================================================================
# ARM 3 - RENDERED-PATH
# =============================================================================


def _written_rendering(node: ast.AST) -> str:
    """The rendering the TEST wrote down, or "" when it wrote none.

    `str(p)`, an f-string over a path, `"%s" % p`. The dialect is chosen on the
    line the reader is looking at, by the test, which is what makes this half
    scoreable: nothing off-screen can make it right.

    Returns:
        `str()`, `f-string`, `%-format`, or "".
    """
    if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in RENDER_BUILTINS:
        return "str()" if node.args and pathish_expression(node.args[0]) else ""
    if isinstance(node, ast.JoinedStr):
        return "f-string" if pathish_expression(node) else ""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _literal_operand(node.left):
        return "%-format" if pathish_expression(node.right) else ""
    return ""


def _returned_value(node: ast.AST, builds_path: bool) -> str:
    """How a value CAME BACK from the code under test, or "".

    A dict subscript, an attribute, a call result. The string was rendered
    somewhere this file cannot read, so whether the producer normalised the
    separator is off-screen - which is exactly why these rows nominate instead
    of scoring.

    Args:
        node: The non-literal side of a comparison.
        builds_path: Whether the enclosing unit builds a Path at all - the
            fallback evidence when the spelling names no path.

    Returns:
        `subscript`, `attribute`, `call result`, or "".
    """
    if isinstance(node, ast.Subscript):
        return "subscript" if builds_path or _pathish_subscript(node) else ""
    if isinstance(node, ast.Attribute) and node.attr not in PATH_ATTRIBUTES:
        return "attribute" if builds_path or _is_pathish_name(node.attr) else ""
    if isinstance(node, ast.Call) and corpus.dotted_name(node.func) not in RENDER_BUILTINS:
        return "call result" if builds_path or _is_pathish_name(corpus.dotted_name(node.func)) else ""
    return ""


def _rendered_side(node: ast.AST, builds_path: bool) -> str:
    """How this expression came to be text, named, or "" when it did not.

    The written rendering is asked for FIRST. `str(entry["path"])` is both a
    subscript and a `str()`, and the `str()` is the honest reading: the test
    put the value through the renderer itself, so the test owns the dialect.
    """
    return _written_rendering(node) or _returned_value(node, builds_path)


def _species_for(provenance: str) -> str:
    """The species a provenance belongs to - scoring, or nominate-only."""
    return SPECIES_RENDERED_PATH if provenance in WRITTEN_RENDERINGS else SPECIES_RETURNED_PATH


def _rendered_partner(sides: List[ast.expr], subject: ast.AST, builds_path: bool) -> str:
    """How some OTHER side of this comparison came to be text, or ""."""
    for other in sides:
        if other is subject:
            continue
        rendering = _rendered_side(other, builds_path)
        if rendering:
            return rendering
    return ""


def _compare_rows(node: ast.Compare, builds_path: bool) -> List[Tuple[str, int, str]]:
    """Every rendered-path row in one comparison.

    Reads `==`, `!=`, `in` and `not in`. `is` is deliberately absent: a string
    compared with `is` is a different bug, and this rule is not it.
    """
    if not any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in node.ops):
        return []
    if _separator_is_spelled_out(node):
        return []
    sides: List[ast.expr] = [node.left] + list(node.comparators)
    rows: List[Tuple[str, int, str]] = []
    for side in sides:
        run = _literal_run(side)
        rendering = _rendered_partner(sides, side, builds_path) if run else ""
        if run and rendering:
            rows.append((run, node.lineno, rendering))
    return rows


def _string_method_rows(node: ast.Call, builds_path: bool) -> List[Tuple[str, int, str]]:
    """Every rendered-path row in a `startswith` / `endswith` call."""
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in STRING_COMPARISON_METHODS:
        return []
    if not node.args or _separator_is_spelled_out(node):
        return []
    run = _literal_run(node.args[0])
    if run is None:
        return []
    rendering = _rendered_side(node.func.value, builds_path)
    return [(run, node.lineno, rendering)] if rendering else []


def rendered_path_literals(unit: corpus.TestUnit) -> List[Tuple[str, int, str]]:
    """Every rendered path this unit compares with a forward-slashed literal.

    The public entry point for arm 3's reading, matching `resolved_literals`:
    the report lane and the tests ask the question here rather than re-deriving
    it.

    Args:
        unit: One test unit.

    Returns:
        `(path_run, lineno, rendering)` triples, in source order, deduped by
        line and run so a chained comparison is one row.
    """
    builds_path = _builds_a_path(unit)
    found: List[Tuple[str, int, str]] = []
    seen: Set[Tuple[str, int]] = set()
    for node in ast.walk(unit.node):
        for run, line, rendering in _rows_for_node(node, builds_path):
            if (run, line) in seen:
                continue
            seen.add((run, line))
            found.append((run, line, rendering))
    return found


def _rows_for_node(node: ast.AST, builds_path: bool) -> List[Tuple[str, int, str]]:
    """Arm 3's rows for one node - a comparison or a string-method call."""
    if isinstance(node, ast.Compare):
        return _compare_rows(node, builds_path)
    if isinstance(node, ast.Call):
        return _string_method_rows(node, builds_path)
    return []


# =============================================================================
# ARM 4 - REPR-HAYSTACK
# =============================================================================


def _render_targets(node: ast.AST) -> List[ast.expr]:
    """What an expression renders to text, or [] when it renders nothing."""
    if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in RENDER_BUILTINS:
        return list(node.args)
    if isinstance(node, ast.JoinedStr):
        return [part.value for part in ast.walk(node) if isinstance(part, ast.FormattedValue)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _literal_operand(node.left):
        return [node.right]
    return []


def _renders_a_call_record(node: ast.AST) -> str:
    """The mock call record this expression renders, by dotted spelling, or "".

    `str(warned.call_args)` answers `warned.call_args`. The record is what makes
    the site wrong: rendering it runs every argument through `repr()`, and a
    Windows path comes back with its separators doubled.
    """
    for target in _render_targets(node):
        for sub in ast.walk(target):
            if isinstance(sub, ast.Attribute) and sub.attr in MOCK_CALL_RECORDS:
                return corpus.dotted_name(sub)
    return ""


def _local_bindings(unit: corpus.TestUnit) -> Dict[str, ast.expr]:
    """First value bound to each plain local name in the unit.

    ONE HOP, FIRST BINDING ONLY. `reported = str(warned.call_args)` on one line
    and the assertion on the next is the shape in every one of the fleet's
    sites, and following further would mean tracking flow. A name rebound later
    keeps its first reading, which is the direction that under-reports.
    """
    bindings: Dict[str, ast.expr] = {}
    for node in ast.walk(unit.node):
        name = _bound_name(node)
        if name and name not in bindings and isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value:
            bindings[name] = node.value
    return bindings


def _bound_name(node: ast.AST) -> str:
    """The single plain name a statement assigns to, or ""."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return ""


def _pathish_needle(node: ast.AST) -> bool:
    """Is the thing being searched for a path?

    A literal is read as text and may be ROOTED here - unlike arm 3, where a
    rooted literal belongs to arms 1-2. Inside a rendered repr the root is not
    the hazard; the separator is, and `/some/core.log` carries one.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return path_run(node.value, allow_rooted=True) is not None
    return pathish_expression(node)


def _haystack_rows(node: ast.Compare, bindings: Dict[str, ast.expr]) -> List[Tuple[str, int, str]]:
    """Every repr-haystack row in one `in` / `not in` comparison."""
    if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
        return []
    if not _pathish_needle(node.left):
        return []
    needle = ast.unparse(node.left)
    rows: List[Tuple[str, int, str]] = []
    for haystack in node.comparators:
        record = _rendered_record(haystack, bindings)
        if record:
            rows.append((needle, node.lineno, record))
    return rows


def _rendered_record(node: ast.AST, bindings: Dict[str, ast.expr]) -> str:
    """The call record a haystack renders, following one local binding."""
    record = _renders_a_call_record(node)
    if record:
        return record
    if isinstance(node, ast.Name) and node.id in bindings:
        return _renders_a_call_record(bindings[node.id])
    return ""


def repr_haystack_needles(unit: corpus.TestUnit) -> List[Tuple[str, int, str]]:
    """Every path searched for inside a rendered mock call record.

    Args:
        unit: One test unit.

    Returns:
        `(needle_source, lineno, record)` triples, in source order.
    """
    bindings = _local_bindings(unit)
    found: List[Tuple[str, int, str]] = []
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Compare):
            found.extend(_haystack_rows(node, bindings))
    return found


def _finding(unit: corpus.TestUnit, line: int, text: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it."""
    return {
        "nodeid": unit.nodeid,
        "line": line,
        "species": SPECIES_POSIX_LITERAL,
        "literal": text,
        "reason": (
            f"rooted path literal {text!r} put through a resolver - a rooted literal is "
            f"DRIVE-RELATIVE under ntpath, so this line means something else on the other "
            f"half of the matrix"
        ),
    }


def _rendered_finding(unit: corpus.TestUnit, line: int, text: str, rendering: str) -> Dict:
    """One arm-3 row: a rendered Path compared with a slashed literal.

    The species follows the provenance, and so does the sentence. A rendering
    the TEST wrote down is a statement about this line; a value that came back
    from the code under test is a question about a producer this file cannot
    read, and it must not be phrased as an accusation.
    """
    species = _species_for(rendering)
    if species == SPECIES_RENDERED_PATH:
        reason = (
            f"path literal {text!r} compared against a value this test rendered from a Path "
            f"({rendering}) - str() of a Path spells the separator the HOST's way, so this "
            f"literal is only right on the leg of the matrix it was written on"
        )
    else:
        reason = (
            f"path literal {text!r} compared against a value returned by the code under test "
            f"({rendering}) - NOMINATION ONLY, not scored: whether the producer normalised the "
            f"separator is off-screen. Compare Path to Path, or as_posix() on both sides"
        )
    return {
        "nodeid": unit.nodeid,
        "line": line,
        "species": species,
        "literal": text,
        "rendering": rendering,
        "reason": reason,
    }


def _haystack_finding(unit: corpus.TestUnit, line: int, needle: str, record: str) -> Dict:
    """One arm-4 row: a path searched for inside a rendered call record."""
    return {
        "nodeid": unit.nodeid,
        "line": line,
        "species": SPECIES_REPR_HAYSTACK,
        "literal": needle,
        "record": record,
        "reason": (
            f"{needle} is searched for inside a rendered {record} - str() of a mock call "
            f"record runs its arguments through repr(), which DOUBLES a backslash separator, "
            f"so even a correctly built expected string is not in there. Assert on "
            f"{record}.args[n] or .kwargs instead, never on a rendered repr"
        ),
    }


def find_rooted_literals(scanned: corpus.Corpus) -> List[Dict]:
    """Every resolved rooted literal in the corpus, unit order preserved."""
    rows: List[Dict] = []
    for unit in scanned.units():
        for text, line in resolved_literals(unit):
            rows.append(_finding(unit, line, text))
    return rows


def find_rendered_paths(scanned: corpus.Corpus) -> List[Dict]:
    """Every rendered path compared with a slashed literal - arm 3."""
    rows: List[Dict] = []
    for unit in scanned.units():
        for text, line, rendering in rendered_path_literals(unit):
            rows.append(_rendered_finding(unit, line, text, rendering))
    return rows


def find_repr_haystacks(scanned: corpus.Corpus) -> List[Dict]:
    """Every path searched for inside a rendered call record - arm 4."""
    rows: List[Dict] = []
    for unit in scanned.units():
        for needle, line, record in repr_haystack_needles(unit):
            rows.append(_haystack_finding(unit, line, needle, record))
    return rows


def find_violations(scanned: corpus.Corpus) -> List[Dict]:
    """Every finding in the corpus, grouped by arm.

    ARM ORDER, NOT SOURCE ORDER, and that is the readable one: the four arms
    describe four different mistakes, and a reader working through a report
    wants all the resolver rows together and then all the rendering rows. The
    score does not care - it dedupes by nodeid either way.
    """
    return find_rooted_literals(scanned) + find_rendered_paths(scanned) + find_repr_haystacks(scanned)


def split_rows(rows: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """(scored, nominated), split by species and NOT deduped.

    NOT DEDUPED, WHICH IS WHERE THIS DIFFERS FROM `platform_oracle`, on purpose.
    Both lists carry every line, because a reader chasing a separator wants each
    one; the dedupe happens later, at `flagged_nodeids`, where the SCORE is
    computed. A unit with three rooted literals is three lines to fix and one
    unit to charge, and collapsing the list would lose the other two lines.

    A unit can appear in both lists. The second list is not a penalty - it is a
    place to look - so hiding a nomination behind a scored row would lose it.
    """
    scored = [row for row in rows if row["species"] in SCORING_SPECIES]
    nominated = [row for row in rows if row["species"] not in SCORING_SPECIES]
    return scored, nominated


def _nomination_check(nominated: List[Dict], total: int) -> Dict:
    """The nominations line: reported, never scored, always passed.

    PASSED TRUE AND OUTSIDE THE NUMBER. RETURNED-PATH flags the same AST shape
    whether the producer normalised or not, and the first fleet run measured 27
    of its 62 rows on seedgo alone as correct portable code - tests reading a
    relpath that `corpus._relpath` renders with `.as_posix()`. An arm that would
    convict correct code must not move a number. The first time a fleet watches
    its score drop for a test that was right, the score stops being read, and
    the arms that ARE sound stop being read with it.
    """
    units = flagged_nodeids(nominated)
    if not units:
        return {
            "name": "Path provenance nominations",
            "passed": True,
            "message": f"0/{total} test units carry a path-provenance nomination",
        }
    overflow = f" (+{len(units) - MAX_REPORTED} more)" if len(units) > MAX_REPORTED else ""
    return {
        "name": "Path provenance nominations",
        "passed": True,
        "message": (
            f"{len(units)}/{total} test units compare a path literal with a value RETURNED by the "
            f"code under test (reported only - not scored, not counted as failing): "
            + ", ".join(units[:MAX_REPORTED])
            + overflow
        ),
    }


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    THE SCORE IS PER UNIT, NOT PER FINDING. A unit resolving four rooted literals
    is one unit a reader has to go and look at; counting the findings would let a
    single loop-heavy test drive a project's score below zero, and a score that
    can go negative is one nobody believes twice.
    """
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


def _flagged_message(rows: List[Dict], units: List[str], total: int) -> str:
    """The check line, naming what was actually found rather than a guess.

    THE SENTENCE FOLLOWS THE SPECIES. A project flagged only by arms 1-2 gets
    the resolver sentence it has always had - the shape has not changed and the
    line should not either. The moment a rendering row is in the list, "put a
    rooted path literal through a resolver" would be describing a finding that
    is neither rooted nor resolved, so the line widens to what the four arms
    have in common: a path claim that is only true on one dialect.
    """
    species = {row["species"] for row in rows}
    if species == {SPECIES_POSIX_LITERAL}:
        head = f"{len(units)}/{total} test units put a rooted path literal through a resolver: "
    else:
        head = f"{len(units)}/{total} test units spell a path in one platform's dialect: "
    overflow = f" (+{len(units) - MAX_REPORTED} more)" if len(units) > MAX_REPORTED else ""
    return head + ", ".join(units[:MAX_REPORTED]) + overflow


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests hardcode one platform's root.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to
            be excused from. Wiring a bypass before the standard can fail would
            be granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory, violations and nominations. The nominate-only species is
        reported in its own check line, with passed True, and is excluded from
        both the score and the failing count. A project with no tests reports
        not_applicable rather than a number, because zero tests measured is not
        zero quality found.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. An earlier version of the reference check returned "no test files
    # found" before this ran, so a project whose ONLY test file had a syntax
    # error reported exactly what a project with no tests at all reports. A
    # broken file must never read as an absent one - that is the whole contract
    # `unparseable` exists to keep, and it was defeated on the one path where
    # nothing else could catch it. The ordering here is the fix, inherited.
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
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present "
                f"but unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Path dialect literals", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    scored, nominated = split_rows(find_violations(scanned))
    units = flagged_nodeids(scored)
    score = int(((total - len(units)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Path dialect literals",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units keep their path claims off a single dialect"
                if not units
                else _flagged_message(scored, units, total)
            ),
        },
        _nomination_check(nominated, total),
    ]

    checks.extend(unreadable)

    return {
        "passed": True,
        "score": score,
        "checks": checks,
        "standard": STANDARD_NAME.upper(),
        "advisory": True,
        "violations": scored,
        "nominations": nominated,
    }
