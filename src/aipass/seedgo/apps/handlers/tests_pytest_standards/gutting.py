# =================== AIPass ====================
# Name: gutting.py
# Description: extreme mutation - the per-function pseudo-tested probe
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""
Extreme mutation. One mutant per FUNCTION, the whole body replaced by a constant.

WHAT IT MEASURES. Gutting (Niedermayr, Juergens & Wagner, ICSE-CSED 2016;
Vera-Perez, Danglot, Monperrus & Baudry, EMSE 2018 - the Descartes engine)
replaces one function's ENTIRE body with ``return None``, leaves every other
byte of the tree alone, and runs the suite once. If the suite is still green,
no test's oracle noticed that function's behaviour disappearing - and if the
tests also EXECUTE it, that is Descartes' PSEUDO-TESTED. Descartes measured a
median of 10% of methods pseudo-tested across 19 Java projects. No Python tool
ships this, which is the whole reason this module exists. The execution half of
that definition needs coverage, which this module does not measure; the caveat
has its own section below and it is not a footnote.

WHAT IT IS NOT - CONTRACT 2, AND IT IS NOT NEGOTIABLE. Pseudo-testedness is a
property of a FUNCTION. The pack's ``scoped_survival`` group measures
module-granularity ORACLE SURVIVAL, which is a property of a TEST. Different
quantity, different denominator, different unit of blame. The pack's signed
design forbids conflating them: the per-function probe lands as a NEW group
under S3/S4's no-vanishing rule, never as a redefinition of that one. So this
module serves ``GROUP = "pseudo_tested"`` and touches nothing else, and no
number it produces may be named, reported or documented as oracle survival.
A survivor here says "no oracle watches this function"; it does not say which
test is to blame, and the two counts will not agree because they are not
counting the same things.

CONTRACT 1 - WHY EVERY KILL MUST CARRY ITS EXCEPTION CLASS. The pack's signed
contract 1 binds every group that executes a mutant: no mutant record may exist
without a ``kill_cause`` splitting the kill by exception class, AssertionError
versus everything else. On the first release that executes a mutant, an unsplit
kill record is a REFUSAL, not a rounding error.

The reason bites hardest for exactly this probe. Gutting returns ``None``, and
in Python the next caller to touch that ``None`` raises ``TypeError`` or
``AttributeError`` on contact. A suite can therefore post a near-perfect
gutting kill rate WITHOUT A SINGLE ASSERTION EVER FIRING, purely on duck-typing
collapse - the most flattering and least meaningful number the lane could
publish. So:

* A kill by ``AssertionError`` is STRONG evidence the function is tested. A
  test looked at what the function produced and said it was wrong.
* A kill by any other exception class is WEAK evidence. The suite noticed that
  the program stopped working, which is roughly what an import check notices.
  It says nothing about whether any oracle inspects the function's behaviour.
* A kill whose class could not be determined is recorded ``"unknown"`` and
  counted in its own THIRD bucket. It is never folded into either side. An
  honest unknown bucket is the requirement here; a guess is the violation.

READING THE CLASS OUT OF PYTEST IS ITSELF A MEASUREMENT PROBLEM, and both
traps were found by running this probe rather than by reading pytest's docs.
pytest drops the crash message from a short-summary line that does not fit the
terminal width, and a non-tty child reports 80 columns; and it strips the
leading ``AssertionError: `` from any REWRITTEN assert before printing it, in
every traceback style there is. Left alone, those two turn the assertion bucket
into the unknown bucket. The fixes are named constants below - a wide
``COLUMNS`` for the child, and the exact inverse of pytest's strip rule - and
the first campaign that ran without them is why they exist.

Every record carries the raw class in ``kill_exception`` alongside the bucket,
so a later reader can regrade the split without re-running anything. Note that
``pytest.fail()`` raises ``Failed`` and a ``pytest.raises`` mismatch raises
``Failed`` too: both are real oracles firing, and both land in the error bucket
because the contract says AssertionError versus everything else. The raw class
is in the record precisely so that caveat is auditable rather than lost.

MUTATE A COPY, NEVER A BRANCH. Every mutation in this module is written into a
copy of the target that the CALLER built and handed over. This is a measured
lesson from this branch, not a stylistic preference: mutants written onto a
live tree leak into any concurrent process that execs source from disk, and a
concurrent fleet audit once scored a phantom red off exactly that. Restoration
of the original bytes happens in a ``finally``, so a crash mid-campaign cannot
leave a mutated file behind either.

ONE CAMPAIGN PER COPY. The copy is exclusive for the duration - this module
takes no lock, and two campaigns sharing one copy corrupt each other. Measured
during this module's own calibration: a second campaign started against a copy
another was already mutating read a RED baseline and a spurious
``already_gutted`` skip, both of them artefacts of the other process's
in-flight mutant rather than facts about the tree. It is the same failure the
mutate-a-copy rule exists to prevent, one level down. Give each campaign its
own copy.

SKIPPING IS A MEASUREMENT. A probe that quietly drops half the tree and then
reports a rate is lying about its denominator. Every function this module
declines to mutate is recorded with a reason and published in the per-reason
counts, including the functions whose gutting would be a no-op (a body that is
already ``pass``) and the ones where gutting would be a DIFFERENT mutation than
intended (a generator, where removing ``yield`` changes the function's type
rather than its behaviour).

A SURVIVOR IS A SUPERSET OF PSEUDO-TESTED, AND THE DIFFERENCE IS COVERAGE.
Descartes calls a method pseudo-tested only when it is COVERED and its mutant
survives; a method no test ever executes is simply NOT COVERED, which is an
ordinary coverage finding and not this probe's news. This module runs no
coverage instrumentation, so it cannot tell the two apart: `pseudo_tested`
here means "gutting survivor", and on the calibration fixture one of three
survivors was covered-and-unnoticed while the other two were never executed at
all. Read the survivors against a coverage report before calling any of them
pseudo-tested. Closing that gap needs a coverage pass the caller supplies; it
is stated here rather than papered over.

WHAT A SURVIVOR DOES NOT PROVE. A surviving mutant may be an EQUIVALENT mutant:
a function that genuinely has no observable effect, in which case no test could
have caught it and the finding is about the function, not the suite. The probe
cannot tell those apart and does not try. It reports the survivor and leaves
the judgement to a reader, which is also what Descartes does.

NO ``check_module`` AND NO ``check_branch`` LIVE HERE. Their absence is the
shape gate that keeps this pack invisible to the audit's file-walk scoring
engine, exactly as in ``adapter.py``. A flag can be forgotten; a function that
does not exist cannot be called.
"""

import ast
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from aipass.prax import logger

#: The group this module serves. NOT `scoped_survival` - see contract 2 above.
GROUP = "pseudo_tested"

MODULE_NAME = "gutting"
LOG_TAG = "[AUDIT-TESTS]"

#: Production source roots inside a target copy. Tests are never gutted.
DEFAULT_SOURCE_DIRS: tuple = ("apps",)

#: Directory names that are never production source. Any dot-directory is
#: excluded on top of this list, which covers `.venv`, `.git` and `.archive`.
EXCLUDED_DIR_NAMES: tuple = (
    "__pycache__",
    "tests",
    "test",
    "docs",
    "node_modules",
    "site-packages",
)

SOURCE_GLOB = "*.py"
SOURCE_ENCODING = "utf-8"

#: The mutation itself. One statement, at the body's own indentation.
GUT_STATEMENT = "return None"
DEFAULT_NEWLINE = "\n"

#: Skip reasons. Every one of these is published with a count; none of them is
#: a quiet drop.
REASON_TRIVIAL_BODY = "trivial_body"
REASON_ALREADY_GUTTED = "already_gutted"
REASON_GENERATOR = "generator"
REASON_ABSTRACT = "abstract_method"
REASON_OVERLOAD = "typing_overload"
REASON_PROPERTY_MUTATOR = "property_mutator"
REASON_INLINE_BODY = "inline_body"
REASON_NO_BODY_RANGE = "no_body_range"
REASON_UNPARSABLE_SOURCE = "unparsable_source"
REASON_DUNDER_INIT = "dunder_init"

#: Not-run reasons. A mutant that never ran is never a survivor and never a
#: kill; it is an unmeasured function and says so.
REASON_BASELINE_NOT_GREEN = "baseline_not_green"
REASON_BUDGET_EXHAUSTED = "budget_exhausted"
REASON_MUTANT_TIMEOUT = "mutant_timeout"
REASON_NOT_GUTTABLE = "not_guttable"
REASON_MUTANT_NOT_PARSEABLE = "mutant_not_parseable"
REASON_SOURCE_IO = "source_io_error"
REASON_LAUNCH_FAILED = "pytest_launch_failed"

#: Decorator trailing names that mean the body is not a behaviour to remove.
SKIP_DECORATOR_REASONS: Dict[str, str] = {
    "abstractmethod": REASON_ABSTRACT,
    "abstractproperty": REASON_ABSTRACT,
    "overload": REASON_OVERLOAD,
    "setter": REASON_PROPERTY_MUTATOR,
    "deleter": REASON_PROPERTY_MUTATOR,
}

DUNDER_INIT_NAME = "__init__"

#: Outcomes. `mutation_failed` is deliberately distinct from `killed`: a mutant
#: that could not be written is not evidence about the suite.
OUTCOME_SURVIVED = "survived"
OUTCOME_KILLED = "killed"
OUTCOME_SKIPPED = "skipped"
OUTCOME_NOT_RUN = "not_run"
OUTCOME_MUTATION_FAILED = "mutation_failed"

#: Contract 1 buckets.
KILL_CAUSE_ASSERTION = "assertion"
KILL_CAUSE_ERROR = "error"
KILL_CAUSE_UNKNOWN = "unknown"
ASSERTION_EXCEPTION_NAME = "AssertionError"

#: The invocation. Fixed shape, serial, no plugin autoload surprises. `-B` and
#: `-p no:cacheprovider` are not tidiness: a suite reading a `.pyc` of a body
#: that no longer exists measures a tree that does not exist either.
PYTHON_ARGS: tuple = ("-B", "-m", "pytest")
PYTEST_COMMON_ARGS: tuple = ("-p", "no:cacheprovider", "-q", "--no-header")

#: `-rA` lists every PASSED nodeid, which is how the baseline captures the
#: passing set under `-q` without giving up the quiet output.
BASELINE_EXTRA_ARGS: tuple = ("--tb=line", "-rA")

#: `-rfE` keeps the FAILED/ERROR short-summary lines, which is where the
#: exception class is read from. `--tb=line` is the fallback source for the
#: same class when the summary line is missing.
MUTANT_EXTRA_ARGS: tuple = ("--tb=line", "-rfE")

#: One failure already means KILLED, so there is nothing to learn from the rest
#: of the suite. `-x` is sound here and is measured rather than assumed - and
#: it does not cost the kill cause, because the short summary and the `--tb`
#: line for the one failure that stopped the run are both still printed.
STOP_FIRST_ARG = "-x"

PYTHONPATH_VAR = "PYTHONPATH"
NO_BYTECODE_VAR = "PYTHONDONTWRITEBYTECODE"
NO_BYTECODE_VALUE = "1"

#: MEASURED, NOT DECORATIVE. pytest appends the crash message to a short-summary
#: line only if the whole line fits the terminal width, and a non-tty child gets
#: 80 columns. Real nodeids are longer than that on their own, so every FAILED
#: line arrived stripped of its exception class and the first campaign posted
#: four honest `unknown` kills that were all AssertionError underneath. Widening
#: the child's reported terminal is what makes the class readable at all.
TERMINAL_WIDTH_VAR = "COLUMNS"
TERMINAL_WIDTH_VALUE = "300"

DEFAULT_BASELINE_TIMEOUT_SECONDS = 900
DEFAULT_MUTANT_TIMEOUT_SECONDS = 300
DEFAULT_BUDGET_SECONDS = 1800

#: Below this much remaining budget a mutant is not started at all. Starting
#: one with two seconds left produces a timeout that reads like a slow test.
MIN_MUTANT_SECONDS = 5

STDOUT_TAIL_CHARS = 2000
PYTEST_EXIT_OK = 0

SHORT_SUMMARY_PATTERN = re.compile(r"^(?:FAILED|ERROR)\s+(?P<nodeid>\S+)(?:\s+-\s+(?P<detail>.*))?$")
PASSED_SUMMARY_PATTERN = re.compile(r"^PASSED\s+(?P<nodeid>\S+)")
EXCEPTION_HEAD_PATTERN = re.compile(r"^(?P<exc>[A-Za-z_][A-Za-z0-9_.]*)\s*(?::|$)")
TB_LINE_PATTERN = re.compile(r"^.+?:\d+:\s+(?P<detail>\S.*)$")
ERROR_MARKER_PATTERN = re.compile(r"^E\s+(?P<detail>\S.*)$")

#: THE SECOND MEASURED TRAP, AND THE WORSE ONE. pytest renders a crash message
#: through `ExceptionInfo.exconly(tryshort=True)`, which strips the leading
#: `AssertionError: ` from a REWRITTEN assert - so `assert 1 == 2` reaches every
#: output mode with no class name on it at all. Reading that as "class unknown"
#: would dump the single most important bucket into the unknown pile in every
#: run. pytest only sets that strip text when the exception IS an AssertionError
#: whose message begins `assert`, so the inverse rule is exact rather than a
#: guess: a detail that starts with a bare `assert` is an AssertionError.
ASSERTION_REWRITE_PREFIX = "assert"
COUNT_PATTERN = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")
TOTALS_LINE_PATTERN = re.compile(r"\bin\s+\d+(?:\.\d+)?s\b")


# =============================================================================
# SHAPES
# =============================================================================


@dataclass(frozen=True)
class FunctionSite:
    """One `def` or `async def` in the target's production source.

    `skip_reason` is None for a site that will be probed and a recorded reason
    for one that will not. A site is never dropped from the list; declining to
    mutate it is part of the measurement.
    """

    relpath: str
    qualname: str
    lineno: int
    end_lineno: int
    is_async: bool
    body_line_count: int
    body_lineno: int = 0
    body_col_offset: int = 0
    skip_reason: Optional[str] = None

    def to_document(self) -> dict:
        """The site as a plain record.

        Returns:
            A JSON-safe dict naming the function and where it lives.
        """
        return {
            "relpath": self.relpath,
            "qualname": self.qualname,
            "lineno": self.lineno,
            "end_lineno": self.end_lineno,
            "is_async": self.is_async,
            "body_line_count": self.body_line_count,
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True)
class SuiteTarget:
    """How to run the target copy's suite, entirely as supplied by the caller.

    This module builds NO environment and imports NO target code. The isolated
    env is the caller's job (`envcopy` does it for this pack); everything here
    is a subprocess invocation over values handed in.
    """

    python: Path
    cwd: Path
    pythonpath: str
    test_arg: str
    target_copy: Path


@dataclass(frozen=True)
class SuiteRun:
    """One pytest invocation's raw result."""

    returncode: Optional[int]
    stdout: str
    stderr: str
    elapsed_seconds: float
    timed_out: bool = False
    launch_error: Optional[str] = None


@dataclass(frozen=True)
class BaselineResult:
    """The unmutated suite, and whether it can support a verdict at all.

    A target whose baseline is not green CANNOT BE MEASURED by this probe: a
    mutant is killed when the suite goes red, so a suite that is already red
    kills every mutant for free and survivorship means nothing. That state
    returns `refusal_reason` and never a number - it is a refusal, not a zero.
    """

    green: bool
    passed: int
    failed: int
    errors: int
    skipped: int
    passing_nodeids: Tuple[str, ...]
    elapsed_seconds: float
    returncode: Optional[int]
    refusal_reason: Optional[str] = None

    def to_document(self) -> dict:
        """The baseline as a plain record.

        Returns:
            A JSON-safe dict, including the refusal reason when there is one.
        """
        return {
            "green": self.green,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "passing_nodeids": len(self.passing_nodeids),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "returncode": self.returncode,
            "refusal_reason": self.refusal_reason,
        }


@dataclass(frozen=True)
class MutantResult:
    """One gutted function, and what the suite did about it.

    `kill_cause` is present on EVERY record, killed or not, because contract 1
    forbids a mutant record without it. For a survivor or an unrun mutant it is
    None, which is a statement that no kill happened - not a missing field.
    """

    site: FunctionSite
    outcome: str
    kill_cause: Optional[str] = None
    kill_exception: Optional[str] = None
    first_failing_nodeid: Optional[str] = None
    reason: Optional[str] = None
    elapsed_seconds: float = 0.0
    returncode: Optional[int] = None
    note: Optional[str] = None

    def to_document(self) -> dict:
        """The mutant as a plain record.

        Returns:
            A JSON-safe dict carrying the kill_cause split required by
            contract 1 plus the raw exception class behind it.
        """
        return {
            "relpath": self.site.relpath,
            "qualname": self.site.qualname,
            "lineno": self.site.lineno,
            "outcome": self.outcome,
            "kill_cause": self.kill_cause,
            "kill_exception": self.kill_exception,
            "first_failing_nodeid": self.first_failing_nodeid,
            "reason": self.reason,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "returncode": self.returncode,
            "note": self.note,
        }


@dataclass
class CampaignResult:
    """Everything one campaign produced, before it is summarised."""

    baseline: BaselineResult
    results: List[MutantResult] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    budget_seconds: int = DEFAULT_BUDGET_SECONDS
    mutant_timeout_seconds: int = DEFAULT_MUTANT_TIMEOUT_SECONDS
    stopped_on_first_failure: bool = True


# =============================================================================
# DISCOVERY
# =============================================================================


def _is_excluded_dir(name: str) -> bool:
    """True when a path component is never production source."""
    return name.startswith(".") or name in EXCLUDED_DIR_NAMES


def iter_source_files(target_copy: Path, source_dirs: Sequence[str] = DEFAULT_SOURCE_DIRS) -> List[Path]:
    """Every production `.py` file under the target copy's source roots.

    Args:
        target_copy: Root of the COPY of the target tree.
        source_dirs: Directory names under the copy that hold production code.

    Returns:
        Sorted absolute paths, with test, cache, archive and dot-directories
        removed.
    """
    files: List[Path] = []
    for name in source_dirs:
        root = target_copy / name
        if not root.is_dir():
            logger.info(f"{LOG_TAG} no source root {name} under {target_copy}")
            continue
        files += [path for path in root.rglob(SOURCE_GLOB) if _keeps_path(path, target_copy)]
    return sorted(set(files))


def _keeps_path(path: Path, target_copy: Path) -> bool:
    """True when no directory component of `path` is excluded."""
    try:
        relative = path.relative_to(target_copy)
    except ValueError:
        return False
    return not any(_is_excluded_dir(part) for part in relative.parts[:-1])


def _decorator_trailing_names(node: ast.AST) -> List[str]:
    """The last dotted component of each decorator on a function."""
    names: List[str] = []
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute):
            names.append(target.attr)
        elif isinstance(target, ast.Name):
            names.append(target.id)
    return names


def _strip_docstring(body: List[ast.stmt]) -> List[ast.stmt]:
    """The body with a leading docstring removed."""
    if not body:
        return body
    first = body[0]
    is_string = (
        isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)
    )
    return body[1:] if is_string else body


def _body_shape_reason(node: ast.AST) -> Optional[str]:
    """A skip reason when gutting this body would change nothing.

    Gutting a body that is already a docstring, `pass`, `...`, `return` or
    `return None` produces a mutant identical in behaviour to the original, so
    it survives by construction and a survivor would mean nothing at all.
    """
    body = _strip_docstring(list(getattr(node, "body", [])))
    if not body:
        return REASON_TRIVIAL_BODY
    if len(body) > 1:
        return None
    statement = body[0]
    if isinstance(statement, ast.Pass):
        return REASON_TRIVIAL_BODY
    if _is_ellipsis(statement):
        return REASON_TRIVIAL_BODY
    if _is_bare_none_return(statement):
        return REASON_ALREADY_GUTTED
    return None


def _is_ellipsis(statement: ast.stmt) -> bool:
    """True for a bare `...` statement."""
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


def _is_bare_none_return(statement: ast.stmt) -> bool:
    """True for `return` or `return None`."""
    if not isinstance(statement, ast.Return):
        return False
    if statement.value is None:
        return True
    return isinstance(statement.value, ast.Constant) and statement.value.value is None


def _contains_yield(node: ast.AST) -> bool:
    """True when this function's OWN body yields.

    Nested functions and lambdas are not descended into: a generator defined
    inside an ordinary function does not make the outer one a generator.
    """
    stack: List[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack += list(ast.iter_child_nodes(current))
    return False


def _decorator_reason(node: ast.AST) -> Optional[str]:
    """A skip reason drawn from the function's decorators."""
    for name in _decorator_trailing_names(node):
        reason = SKIP_DECORATOR_REASONS.get(name)
        if reason is not None:
            return reason
    return None


def _skip_reason_for(node: ast.AST, lines: List[str], skip_dunder_init: bool) -> Optional[str]:
    """The reason this function will not be gutted, or None to probe it."""
    decorator_reason = _decorator_reason(node)
    if decorator_reason is not None:
        return decorator_reason
    if skip_dunder_init and getattr(node, "name", "") == DUNDER_INIT_NAME:
        return REASON_DUNDER_INIT
    if _contains_yield(node):
        return REASON_GENERATOR
    shape_reason = _body_shape_reason(node)
    if shape_reason is not None:
        return shape_reason
    return _body_range_reason(node, lines)


def _body_range_reason(node: ast.AST, lines: List[str]) -> Optional[str]:
    """A skip reason when the body has no replaceable line range.

    A body written on the signature's own line (`def f(): return 1`) cannot be
    replaced by whole lines without rewriting the signature, and rewriting the
    signature is exactly what this module refuses to do.
    """
    body = list(getattr(node, "body", []))
    end_lineno = getattr(node, "end_lineno", None)
    if not body or end_lineno is None or getattr(body[0], "lineno", None) is None:
        return REASON_NO_BODY_RANGE
    first = body[0]
    if first.lineno > len(lines) or end_lineno > len(lines):
        return REASON_NO_BODY_RANGE
    if lines[first.lineno - 1][: first.col_offset].strip():
        return REASON_INLINE_BODY
    return None


def _qualname(stack: Sequence[str], name: str) -> str:
    """`Class.method` or `outer.inner` or a bare function name."""
    return ".".join([*stack, name])


def _site_from_node(
    # Narrow, not `ast.AST`: this reads `.name` and `.lineno`, which a bare AST
    # does not have. The loose annotation let four type errors through the
    # per-file checklist and the branch audit caught them.
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    relpath: str,
    stack: Sequence[str],
    lines: List[str],
    skip_init: bool,
) -> FunctionSite:
    """Build one `FunctionSite`, skip reason included."""
    body = list(getattr(node, "body", []))
    first_lineno = getattr(body[0], "lineno", node.lineno) if body else node.lineno
    end_lineno = getattr(node, "end_lineno", None) or first_lineno
    return FunctionSite(
        relpath=relpath,
        qualname=_qualname(stack, node.name),
        lineno=node.lineno,
        end_lineno=end_lineno,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        body_line_count=max(0, end_lineno - first_lineno + 1),
        body_lineno=first_lineno,
        body_col_offset=getattr(body[0], "col_offset", 0) if body else 0,
        skip_reason=_skip_reason_for(node, lines, skip_init),
    )


def _walk_for_sites(
    node: ast.AST, relpath: str, stack: List[str], lines: List[str], skip_init: bool
) -> List[FunctionSite]:
    """Every function defined at or below `node`, methods and nested defs alike."""
    sites: List[FunctionSite] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            sites += _walk_for_sites(child, relpath, [*stack, child.name], lines, skip_init)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sites.append(_site_from_node(child, relpath, stack, lines, skip_init))
            sites += _walk_for_sites(child, relpath, [*stack, child.name], lines, skip_init)
        else:
            sites += _walk_for_sites(child, relpath, stack, lines, skip_init)
    return sites


def _sites_in_file(path: Path, target_copy: Path, skip_dunder_init: bool) -> List[FunctionSite]:
    """The function sites in one file, or a single unparsable-source record.

    A file that will not parse contributes exactly ONE skip record rather than
    an unknown number of silently missing functions, so the hole it leaves in
    the denominator is visible in the per-reason counts.
    """
    relpath = path.relative_to(target_copy).as_posix()
    try:
        source = path.read_text(encoding=SOURCE_ENCODING)
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(f"{LOG_TAG} {relpath} could not be read: {type(exc).__name__}: {exc}")
        return [_unparsable_site(relpath)]

    try:
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, ValueError) as exc:
        logger.warning(f"{LOG_TAG} {relpath} could not be parsed: {type(exc).__name__}: {exc}")
        return [_unparsable_site(relpath)]

    return _walk_for_sites(tree, relpath, [], source.splitlines(), skip_dunder_init)


def _unparsable_site(relpath: str) -> FunctionSite:
    """The one record a file stands in for when its functions cannot be listed."""
    return FunctionSite(
        relpath=relpath,
        qualname="<module>",
        lineno=1,
        end_lineno=1,
        is_async=False,
        body_line_count=0,
        skip_reason=REASON_UNPARSABLE_SOURCE,
    )


def discover_functions(
    target_copy: Path,
    *,
    source_dirs: Sequence[str] = DEFAULT_SOURCE_DIRS,
    skip_dunder_init: bool = False,
) -> List[FunctionSite]:
    """Every function in the target copy's production source, with skip reasons.

    `skip_dunder_init` defaults to False on purpose. Whether gutting `__init__`
    breaks import rather than behaviour is a question to MEASURE on a given
    tree, not to assume; leaving it on by default keeps the denominator honest
    and lets the campaign report what those mutants actually did.

    Args:
        target_copy: Root of the COPY of the target tree. Never a live branch.
        source_dirs: Production source roots to walk under the copy.
        skip_dunder_init: Record `__init__` as skipped instead of probing it.

    Returns:
        Every discovered site in file then line order, including the ones that
        will be skipped - each carrying its own reason.
    """
    sites: List[FunctionSite] = []
    for path in iter_source_files(target_copy, source_dirs):
        sites += _sites_in_file(path, target_copy, skip_dunder_init)
    logger.info(f"{LOG_TAG} discovered {len(sites)} functions under {target_copy}")
    return sites


# =============================================================================
# MUTATION
# =============================================================================


def gut_source(source: str, site: FunctionSite) -> Optional[str]:
    """The module source with one function's body replaced by `return None`.

    Line ranges plus the original text, never `ast.unparse`. Unparsing rewrites
    the WHOLE file - quotes, spacing, comments gone - so every mutant would
    differ from the original in a thousand irrelevant ways and a kill would no
    longer be attributable to the gutting. Here the signature, the decorators,
    the def line and every other byte of the file survive untouched. The same
    replacement is correct for `async def`: the coroutine still awaits to None.

    Args:
        source: The unmutated module text.
        site: The function to gut, carrying its own body line range.

    Returns:
        The mutated source, or None when the site cannot be gutted safely.
    """
    if site.skip_reason is not None:
        return None
    lines = source.splitlines(keepends=True)
    start = site.body_lineno - 1
    end = site.end_lineno - 1
    if start < 0 or end < start or end >= len(lines):
        logger.warning(f"{LOG_TAG} {site.relpath}:{site.lineno} body range is outside the file")
        return None

    first_line = lines[start]
    indent = first_line[: site.body_col_offset]
    if indent.strip():
        logger.warning(f"{LOG_TAG} {site.relpath}:{site.lineno} body does not start its own line")
        return None

    newline = first_line[len(first_line.rstrip("\r\n")) :] or DEFAULT_NEWLINE
    replacement = f"{indent}{GUT_STATEMENT}{newline}"
    return "".join([*lines[:start], replacement, *lines[end + 1 :]])


# =============================================================================
# EXECUTION
# =============================================================================


def _pytest_command(target: SuiteTarget, extra_args: Sequence[str]) -> List[str]:
    """The serial pytest invocation for one run."""
    return [str(target.python), *PYTHON_ARGS, target.test_arg, *PYTEST_COMMON_ARGS, *extra_args]


def _pytest_environment(target: SuiteTarget) -> Dict[str, str]:
    """The caller's PYTHONPATH laid over the current environment.

    The isolated env is built elsewhere. All this does is point the child at
    the PYTHONPATH it was handed and forbid bytecode, so a mutant can never be
    shadowed by a `.pyc` of the body it replaced.
    """
    environment = dict(os.environ)
    environment[PYTHONPATH_VAR] = target.pythonpath
    environment[NO_BYTECODE_VAR] = NO_BYTECODE_VALUE
    environment[TERMINAL_WIDTH_VAR] = TERMINAL_WIDTH_VALUE
    return environment


def _run_pytest(target: SuiteTarget, extra_args: Sequence[str], timeout_seconds: int) -> SuiteRun:
    """One pytest subprocess, with a wall-clock ceiling.

    Args:
        target: Where and how to run the suite.
        extra_args: Run-specific arguments appended to the fixed command.
        timeout_seconds: Ceiling for this single run.

    Returns:
        The raw run. A timeout and a launch failure are both returned as
        recorded states, never raised, because both are measurements about the
        mutant rather than crashes of the campaign.
    """
    started = time.monotonic()
    try:
        completed = subprocess.run(
            _pytest_command(target, extra_args),
            cwd=str(target.cwd),
            env=_pytest_environment(target),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"{LOG_TAG} a suite run exceeded its {timeout_seconds}s ceiling in {target.cwd}")
        return SuiteRun(None, "", "", time.monotonic() - started, timed_out=True)
    except OSError as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.warning(f"{LOG_TAG} pytest could not be launched in {target.cwd}: {detail}")
        return SuiteRun(None, "", "", time.monotonic() - started, launch_error=detail)

    return SuiteRun(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        elapsed_seconds=time.monotonic() - started,
    )


def _totals_line(stdout: str) -> str:
    """The pytest totals line, or the whole output when it cannot be found."""
    for line in reversed(stdout.splitlines()):
        if TOTALS_LINE_PATTERN.search(line):
            return line
    return stdout


def parse_counts(stdout: str) -> Dict[str, int]:
    """The pass/fail/error/skip counts from a pytest run.

    Args:
        stdout: The run's standard output.

    Returns:
        A dict keyed `passed`, `failed`, `error`, `skipped` and friends. A
        missing key means pytest printed no such count.
    """
    counts: Dict[str, int] = {}
    for amount, label in COUNT_PATTERN.findall(_totals_line(stdout)):
        counts[label.rstrip("s") if label.startswith("error") else label] = int(amount)
    return counts


def _passing_nodeids(stdout: str) -> Tuple[str, ...]:
    """Every nodeid pytest reported as PASSED under `-rA`."""
    found = [match.group("nodeid") for match in map(PASSED_SUMMARY_PATTERN.match, stdout.splitlines()) if match]
    return tuple(found)


def _detail_from_summary(lines: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
    """The crash message and nodeid from the first FAILED/ERROR summary line."""
    for line in lines:
        match = SHORT_SUMMARY_PATTERN.match(line.strip())
        if match is None:
            continue
        return (match.group("detail") or "").strip() or None, match.group("nodeid")
    return None, None


def _detail_from_traceback(lines: Sequence[str]) -> Optional[str]:
    """The crash message from an `E` marker or a `--tb=line` location line."""
    for pattern in (ERROR_MARKER_PATTERN, TB_LINE_PATTERN):
        for line in lines:
            match = pattern.match(line.rstrip())
            if match is not None:
                return match.group("detail").strip()
    return None


def _cause_from_detail(detail: str) -> Tuple[str, Optional[str]]:
    """The contract-1 bucket and the exception class behind one crash message."""
    first_word = detail.split(":", 1)[0].split()[0] if detail.split() else ""
    if first_word == ASSERTION_REWRITE_PREFIX:
        return KILL_CAUSE_ASSERTION, ASSERTION_EXCEPTION_NAME
    head = EXCEPTION_HEAD_PATTERN.match(detail)
    if head is None:
        return KILL_CAUSE_UNKNOWN, None
    short_name = head.group("exc").rsplit(".", 1)[-1]
    cause = KILL_CAUSE_ASSERTION if short_name == ASSERTION_EXCEPTION_NAME else KILL_CAUSE_ERROR
    return cause, short_name


def classify_kill(stdout: str, stderr: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Split one kill by exception class, as contract 1 requires.

    An `AssertionError` means a test looked at what the function produced and
    said it was wrong. Any other class usually means the gutted `None` reached
    a caller that could not use it, which is the duck-typing collapse this
    split exists to expose. A class that cannot be read from pytest's output is
    reported `unknown` and counted on its own; it is never guessed into either
    side.

    A crash message beginning with a bare `assert` is an AssertionError whose
    class name pytest stripped on the way out - see ASSERTION_REWRITE_PREFIX.
    That is a rule pytest's own behaviour makes exact, not an inference.

    Args:
        stdout: The mutant run's standard output.
        stderr: The mutant run's standard error.

    Returns:
        `(kill_cause, exception_class_or_None, first_failing_nodeid_or_None)`.
    """
    lines = stdout.splitlines() + stderr.splitlines()
    detail, nodeid = _detail_from_summary(lines)
    if detail is None:
        detail = _detail_from_traceback(lines)
    if detail is None:
        return KILL_CAUSE_UNKNOWN, None, nodeid

    cause, exception_name = _cause_from_detail(detail)
    return cause, exception_name, nodeid


def baseline(target: SuiteTarget, *, timeout_seconds: int = DEFAULT_BASELINE_TIMEOUT_SECONDS) -> BaselineResult:
    """Run the unmutated suite once and decide whether it can carry a verdict.

    A RED BASELINE IS A REFUSAL, NOT A ZERO. A mutant is killed when the suite
    goes red; against a suite that is already red every mutant is killed for
    free and every survivor is an accident of ordering. There is no number to
    report in that world, so this returns `green=False` with a `refusal_reason`
    and the campaign publishes the refusal instead of a rate.

    Args:
        target: Where and how to run the suite.
        timeout_seconds: Ceiling for the single baseline run.

    Returns:
        The baseline counts, the passing nodeids, and a refusal reason when the
        suite cannot support a measurement.
    """
    run = _run_pytest(target, BASELINE_EXTRA_ARGS, timeout_seconds)
    counts = parse_counts(run.stdout)
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0)
    errors = counts.get("error", 0)
    refusal = _baseline_refusal(run, passed, failed, errors, timeout_seconds)
    if refusal is not None:
        logger.warning(f"{LOG_TAG} gutting refused: {refusal}")
    return BaselineResult(
        green=refusal is None,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=counts.get("skipped", 0),
        passing_nodeids=_passing_nodeids(run.stdout),
        elapsed_seconds=run.elapsed_seconds,
        returncode=run.returncode,
        refusal_reason=refusal,
    )


def _baseline_refusal(run: SuiteRun, passed: int, failed: int, errors: int, timeout_seconds: int) -> Optional[str]:
    """The sentence explaining why this baseline cannot be measured, or None."""
    if run.timed_out:
        return f"the unmutated suite did not finish within {timeout_seconds}s, so no mutant verdict can be trusted"
    if run.launch_error is not None:
        return f"pytest could not be launched for the unmutated suite ({run.launch_error})"
    if failed or errors:
        return (
            f"the unmutated suite is already red ({failed} failed, {errors} error), so gutting verdicts are meaningless"
        )
    if run.returncode != PYTEST_EXIT_OK:
        tail = run.stdout.strip().splitlines()[-1:] or [""]
        return f"the unmutated suite exited {run.returncode} rather than 0 ({tail[0][:160]})"
    if passed == 0:
        return "the unmutated suite reported no passing tests, so there is no oracle for a mutant to escape"
    return None


# =============================================================================
# CAMPAIGN
# =============================================================================


def _read_source(path: Path) -> Tuple[Optional[bytes], Optional[str]]:
    """The file's bytes, or a recorded reason why they could not be read."""
    try:
        return path.read_bytes(), None
    except OSError as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.warning(f"{LOG_TAG} could not read {path}: {detail}")
        return None, detail


def _mutant_text(original: bytes, site: FunctionSite) -> Tuple[Optional[str], Optional[str]]:
    """The gutted source text, or a recorded reason why there is none.

    The mutant is compiled before it is written. A mutant that will not parse
    would take the suite down with a `SyntaxError` and read as a perfect kill,
    which would be a measurement of this module's bug rather than of the
    target's tests.
    """
    try:
        source = original.decode(SOURCE_ENCODING)
    except UnicodeDecodeError as exc:
        return None, f"{REASON_SOURCE_IO}: {exc}"

    mutant = gut_source(source, site)
    if mutant is None:
        return None, REASON_NOT_GUTTABLE

    try:
        compile(mutant, site.relpath, "exec")
    except (SyntaxError, ValueError) as exc:
        logger.warning(f"{LOG_TAG} mutant of {site.relpath}::{site.qualname} does not parse: {exc}")
        return None, REASON_MUTANT_NOT_PARSEABLE
    return mutant, None


def _classify_run(site: FunctionSite, run: SuiteRun, base: BaselineResult, capped: bool) -> MutantResult:
    """Turn one mutant run into a verdict, kill_cause included."""
    if run.timed_out:
        reason = REASON_BUDGET_EXHAUSTED if capped else REASON_MUTANT_TIMEOUT
        return MutantResult(site, OUTCOME_NOT_RUN, reason=reason, elapsed_seconds=run.elapsed_seconds)
    if run.launch_error is not None:
        return MutantResult(
            site,
            OUTCOME_NOT_RUN,
            reason=f"{REASON_LAUNCH_FAILED}: {run.launch_error}",
            elapsed_seconds=run.elapsed_seconds,
        )
    if run.returncode != PYTEST_EXIT_OK:
        cause, exception_name, nodeid = classify_kill(run.stdout, run.stderr)
        return MutantResult(
            site,
            OUTCOME_KILLED,
            kill_cause=cause,
            kill_exception=exception_name,
            first_failing_nodeid=nodeid,
            elapsed_seconds=run.elapsed_seconds,
            returncode=run.returncode,
            note=run.stdout.strip()[-STDOUT_TAIL_CHARS:] if cause == KILL_CAUSE_UNKNOWN else None,
        )
    return MutantResult(
        site,
        OUTCOME_SURVIVED,
        elapsed_seconds=run.elapsed_seconds,
        returncode=run.returncode,
        note=_survivor_note(run, base),
    )


def _survivor_note(run: SuiteRun, base: BaselineResult) -> Optional[str]:
    """A warning when a green mutant ran fewer tests than the baseline did.

    A mutant that turns tests into skips exits 0 and would otherwise read as a
    clean survivor. The count is compared rather than assumed.
    """
    passed = parse_counts(run.stdout).get("passed", 0)
    if passed >= base.passed:
        return None
    return f"green but only {passed} of the baseline's {base.passed} tests passed - inspect before trusting"


def _probe_site(
    target: SuiteTarget,
    site: FunctionSite,
    base: BaselineResult,
    timeout_seconds: int,
    capped: bool,
    extra_args: Sequence[str],
) -> MutantResult:
    """Write one mutant, run the suite, classify, restore the original bytes.

    Restoration is in a `finally`, so a crashed run, a keyboard interrupt or a
    failure inside the classifier can never leave a mutated file in the copy.
    """
    path = target.target_copy / site.relpath
    original, read_error = _read_source(path)
    if original is None:
        return MutantResult(site, OUTCOME_MUTATION_FAILED, reason=f"{REASON_SOURCE_IO}: {read_error}")

    mutant, mutation_error = _mutant_text(original, site)
    if mutant is None:
        return MutantResult(site, OUTCOME_MUTATION_FAILED, reason=mutation_error)

    try:
        path.write_text(mutant, encoding=SOURCE_ENCODING, newline="")
        run = _run_pytest(target, extra_args, timeout_seconds)
    finally:
        path.write_bytes(original)
    return _classify_run(site, run, base, capped)


def _mutant_args(stop_on_first_failure: bool) -> Tuple[str, ...]:
    """The mutant run's extra arguments."""
    if not stop_on_first_failure:
        return MUTANT_EXTRA_ARGS
    return (*MUTANT_EXTRA_ARGS, STOP_FIRST_ARG)


def _unrun(sites: Sequence[FunctionSite], reason: str) -> List[MutantResult]:
    """Mark a run of sites as never executed, with the reason attached."""
    return [MutantResult(site, OUTCOME_NOT_RUN, reason=reason) for site in sites]


def run_campaign(
    target: SuiteTarget,
    sites: Sequence[FunctionSite],
    *,
    budget_seconds: int = DEFAULT_BUDGET_SECONDS,
    mutant_timeout_seconds: int = DEFAULT_MUTANT_TIMEOUT_SECONDS,
    stop_on_first_failure: bool = True,
    baseline_result: Optional[BaselineResult] = None,
) -> CampaignResult:
    """Gut every probeable function in turn, one suite run each.

    The campaign is serial and bounded twice over: `mutant_timeout_seconds`
    caps one suite run, `budget_seconds` caps the whole campaign. On expiry the
    remaining sites are recorded `not_run` with `budget_exhausted` and the
    summary reports what was completed - a partial campaign never becomes a
    whole-tree number.

    Args:
        target: Where and how to run the suite, over a COPY of the tree.
        sites: Everything `discover_functions` found, skips included.
        budget_seconds: Wall-clock ceiling for the entire campaign.
        mutant_timeout_seconds: Wall-clock ceiling for one mutant's suite run.
        stop_on_first_failure: Pass `-x`; one failure already means KILLED.
        baseline_result: A baseline already measured by the caller, if any.

    Returns:
        The campaign, baseline included, ready for `summarize`.
    """
    started = time.monotonic()
    base = baseline_result if baseline_result is not None else baseline(target)
    skipped = [MutantResult(site, OUTCOME_SKIPPED, reason=site.skip_reason) for site in sites if site.skip_reason]
    probeable = [site for site in sites if site.skip_reason is None]

    if not base.green:
        logger.warning(f"{LOG_TAG} campaign refused on {len(probeable)} functions: {base.refusal_reason}")
        results = skipped + _unrun(probeable, REASON_BASELINE_NOT_GREEN)
        return CampaignResult(
            base, results, time.monotonic() - started, budget_seconds, mutant_timeout_seconds, stop_on_first_failure
        )

    extra_args = _mutant_args(stop_on_first_failure)
    results = skipped + _drive(target, probeable, base, started, budget_seconds, mutant_timeout_seconds, extra_args)
    elapsed = time.monotonic() - started
    logger.info(f"{LOG_TAG} gutting campaign finished in {elapsed:.1f}s over {len(probeable)} functions")
    return CampaignResult(base, results, elapsed, budget_seconds, mutant_timeout_seconds, stop_on_first_failure)


def _drive(
    target: SuiteTarget,
    probeable: Sequence[FunctionSite],
    base: BaselineResult,
    started: float,
    budget_seconds: int,
    mutant_timeout_seconds: int,
    extra_args: Sequence[str],
) -> List[MutantResult]:
    """Walk the probeable sites under the campaign's wall-clock budget."""
    results: List[MutantResult] = []
    for index, site in enumerate(probeable):
        remaining = budget_seconds - (time.monotonic() - started)
        if remaining < MIN_MUTANT_SECONDS:
            logger.warning(f"{LOG_TAG} budget exhausted with {len(probeable) - index} functions unprobed")
            return results + _unrun(probeable[index:], REASON_BUDGET_EXHAUSTED)
        ceiling = min(mutant_timeout_seconds, int(remaining))
        results.append(_probe_site(target, site, base, ceiling, ceiling < mutant_timeout_seconds, extra_args))
    return results


# =============================================================================
# SUMMARY
# =============================================================================


def _count_reasons(results: Sequence[MutantResult], outcome: str) -> Dict[str, int]:
    """Per-reason counts for one outcome."""
    counts: Dict[str, int] = {}
    for result in results:
        if result.outcome != outcome:
            continue
        key = result.reason or "unrecorded"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _count_causes(results: Sequence[MutantResult], cause: str) -> int:
    """How many kills carried this kill_cause."""
    return sum(1 for result in results if result.outcome == OUTCOME_KILLED and result.kill_cause == cause)


def _limits(campaign: CampaignResult, survivors: Sequence[MutantResult], unknown: int) -> List[str]:
    """Plain-sentence caveats that travel with the numbers."""
    sentences = [
        "A kill by AssertionError is strong evidence the function is tested; a kill by any other "
        "exception class is weak evidence, because gutting returns None and the next caller to "
        "touch that None raises on contact whether or not any oracle is watching.",
        "pytest.fail() and a pytest.raises mismatch both raise Failed, not AssertionError, so a real "
        "oracle firing through either one is counted in killed_by_error. The raw class is in each "
        "record's kill_exception so the split can be regraded without re-running.",
        "A surviving mutant may be an equivalent mutant - a function with no observable effect, which "
        "no test could have caught. This probe reports the survivor and does not judge equivalence.",
        "Survivors are a SUPERSET of pseudo-tested functions. Descartes calls a function pseudo-tested "
        "only when tests cover it and the mutant still survives; a function no test executes is merely "
        "uncovered. No coverage was measured here, so read this list against a coverage report before "
        "calling any entry pseudo-tested.",
        "This is pseudo-testedness, a property of a function. It is not the scoped_survival group's "
        "oracle survival, which is a property of a test, and the two counts are not comparable.",
        "Every mutation was written into a copy of the target and the original bytes were restored in "
        "a finally block; no branch tree was mutated.",
    ]
    if unknown:
        sentences.append(
            f"{unknown} kills could not be attributed to an exception class and are counted in "
            "killed_by_unknown rather than being assigned to either side."
        )
    if campaign.stopped_on_first_failure:
        sentences.append(
            "Mutant runs used -x, so a killed mutant's suite stopped at its first failure. The kill "
            "cause is still read from that failure; the remaining tests were not run and no mutant "
            "carries a full pass/fail tally."
        )
    if any(result.note for result in survivors):
        sentences.append(
            "At least one survivor ran fewer passing tests than the baseline. A mutant that turns "
            "tests into skips exits 0 and reads as green; those records carry a note."
        )
    return sentences


def summarize(campaign: CampaignResult) -> dict:
    """The campaign as a publishable record.

    Args:
        campaign: A finished campaign.

    Returns:
        A JSON-safe dict. `killed_by_assertion`, `killed_by_error` and
        `killed_by_unknown` are reported separately and there is deliberately
        no combined total: contract 1 exists to make that ratio visible, and a
        single kill count would hide exactly the thing it was written to show.
    """
    results = campaign.results
    survivors = [result for result in results if result.outcome == OUTCOME_SURVIVED]
    probed = [result for result in results if result.outcome in (OUTCOME_SURVIVED, OUTCOME_KILLED)]
    unrun_reasons = _count_reasons(results, OUTCOME_NOT_RUN)
    unrun_reasons.update(_count_reasons(results, OUTCOME_MUTATION_FAILED))
    unknown = _count_causes(results, KILL_CAUSE_UNKNOWN)
    elapsed = campaign.elapsed_seconds

    return {
        "group": GROUP,
        "functions_total": len(results),
        "functions_probed": len(probed),
        "skipped": {
            "total": sum(1 for r in results if r.outcome == OUTCOME_SKIPPED),
            "by_reason": _count_reasons(results, OUTCOME_SKIPPED),
        },
        "pseudo_tested": [
            {"relpath": r.site.relpath, "qualname": r.site.qualname, "lineno": r.site.lineno, "note": r.note}
            for r in survivors
        ],
        "killed_by_assertion": _count_causes(results, KILL_CAUSE_ASSERTION),
        "killed_by_error": _count_causes(results, KILL_CAUSE_ERROR),
        "killed_by_unknown": unknown,
        "not_run": {"total": sum(unrun_reasons.values()), "by_reason": unrun_reasons},
        "baseline": campaign.baseline.to_document(),
        "elapsed_seconds": round(elapsed, 3),
        "seconds_per_mutant": round(elapsed / len(probed), 3) if probed else None,
        "budget_seconds": campaign.budget_seconds,
        "stopped_on_first_failure": campaign.stopped_on_first_failure,
        "mutants": [result.to_document() for result in results],
        "limits": _limits(campaign, survivors, unknown),
    }
