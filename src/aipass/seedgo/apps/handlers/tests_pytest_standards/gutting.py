# =================== AIPass ====================
# Name: gutting.py
# Description: extreme mutation - the per-function pseudo-tested probe
# Version: 1.2.0
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

A SURVIVOR IS A SUPERSET OF PSEUDO-TESTED, AND THE DIFFERENCE IS COVERAGE -
WHICH ``SELECTION_COVERAGE`` NOW MEASURES. Descartes calls a method
pseudo-tested only when it is COVERED and its mutant survives; a method no test
ever executes is simply NOT COVERED, which is an ordinary coverage finding and
not this probe's news. The default ``SELECTION_FULL_SUITE`` mode runs no
coverage instrumentation and still cannot tell the two apart, and its limits
say so. ``selection=SELECTION_COVERAGE`` closes the gap: the baseline pass is
taken under coverage.py with per-test contexts, so a function whose body no
test executes is reported in its own ``uncovered`` bucket carrying
``reason: "no covering test"`` and NEVER appears in ``pseudo_tested``. They are
different findings - the first is a hole in the coverage, the second is a
missing oracle over code the suite really runs - and only the second is the
thing Descartes named. Measured on the c5a487e2 canary fixture: of three
full-suite survivors, two are uncovered and one is genuinely pseudo-tested.

TEST SELECTION IS A COST REDUCTION AND A DIFFERENT CLAIM, SO IT IS RECORDED
PER MUTANT. Gutting one function and running 4362 tests to watch none of them
notice is the cost problem that keeps this probe off a weekly cadence: seedgo
has 2091 probeable functions and a 101.9s suite, which is 35.6 projected hours
of full-suite campaign. ``SELECTION_COVERAGE`` runs, for each mutant, ONLY the
tests whose recorded coverage context executes that function's body - the
mutmut-3 strategy - and every mutant record carries ``selected_tests`` and
``selection_basis`` so a reader can see which claim it is looking at. A verdict
from nine tests is not the verdict from the whole suite, and a record that does
not say which one it is would be the conflation this lane exists to refuse.

THE SELECTION IS SOUND ONLY BECAUSE GUTTING TOUCHES NOTHING BUT A BODY. The
mutant keeps the original decorators, the def line and the signature byte for
byte, so a test that never enters the body cannot observe the mutation; the
tests that execute the body's lines are therefore the complete set that can
kill. That argument is what makes the reduction legitimate rather than merely
cheap, and it is exactly why this module refuses to rewrite signatures.

THREE COVERAGE CLASSES, AND THE MIDDLE ONE WAS FOUND BY RUNNING THIS. A body
line can carry a test context, no context at all, or no coverage record:

* Body lines carrying test contexts -> run those tests, basis
  ``covering_tests``.
* Body lines executed under coverage's EMPTY context -> the function ran
  outside any test phase, i.e. at import or collection time, and no nodeid can
  be attributed to it. Selecting nothing here would be a silent lie. Measured:
  the fixture's ``_find_real_caller`` runs only at import, has zero test
  contexts, and the full suite KILLS it with a TypeError. Recorded basis
  ``import_time_no_test_context`` and the WHOLE SUITE runs for that mutant.
* No coverage record on any body line -> nothing executes it, so nothing can
  kill it. That is a survivor with zero runs and ``reason: "no covering test"``,
  and it is free.

WHAT SELECTION CANNOT SEE, STATED BEFORE THE SAVING. coverage.py traces the
process it runs in. A test that exercises the target through a SUBPROCESS - the
fixture's own ``test_dead_cwd_imports.py`` does - contributes no context, so a
function reached only that way reads as "no covering test" when the full suite
would have killed it. The ``uncovered`` bucket is therefore a list to verify,
not a conclusion, and a source file absent from the coverage data altogether
(never imported, or dropped by an inherited ``omit``) falls back to the whole
suite under basis ``source_file_not_instrumented`` rather than being guessed at.
When the coverage map cannot be produced at all, the campaign REFUSES with the
reason; it never quietly runs the full suite and reports the cheap number as if
it were the same measurement.

WHAT A SURVIVOR DOES NOT PROVE. A surviving mutant may be an EQUIVALENT mutant:
a function that genuinely has no observable effect, in which case no test could
have caught it and the finding is about the function, not the suite. The probe
cannot tell those apart and does not try. It reports the survivor and leaves
the judgement to a reader, which is also what Descartes does.

NO ``check_module`` AND NO ``check_branch`` LIVE HERE. Their absence is the
shape gate that keeps this pack invisible to the audit's file-walk scoring
engine, exactly as in ``adapter.py``. A flag can be forgotten; a function that
does not exist cannot be called.

THIS FILE IS THE DISCOVERY, THE MUTATION, THE CAMPAIGN AND THE REPORT, AND
NOTHING ELSE ANY MORE. Three sections moved out on 2026-09-19, when the file
crossed the branch's 1500-line architecture cap: the record shapes into
``mutation_shapes``, the pytest invocation and its output parsing into
``mutation_runner``, and the coverage pass with its per-mutant test selection
into ``mutation_selection``. It was a relocation and it changed no rule, no
threshold and no number. The chain is strictly one-directional -
``mutation_shapes`` <- ``mutation_runner`` <- ``mutation_selection`` <- here -
and every name those three modules own is imported back below, because callers
have always reached them through ``gutting`` and a split must not move an
address.
"""

import ast
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from aipass.prax import logger

# The three modules below were split out of this file and every public name
# they own is imported back here. Callers have always reached these through
# `gutting.<name>` - `adapter.py` still does - so the split must not move an
# address. A name this file does not itself use carries the F401 waiver rather
# than being dropped.
from aipass.seedgo.apps.handlers.tests_pytest_standards.mutation_runner import (
    ASSERTION_EXCEPTION_NAME,  # noqa: F401  (re-exported)
    ASSERTION_REWRITE_PREFIX,  # noqa: F401  (re-exported)
    BASELINE_EXTRA_ARGS,  # noqa: F401  (re-exported)
    COUNT_PATTERN,  # noqa: F401  (re-exported)
    DEFAULT_BASELINE_TIMEOUT_SECONDS,  # noqa: F401  (re-exported)
    ERROR_MARKER_PATTERN,  # noqa: F401  (re-exported)
    EXCEPTION_HEAD_PATTERN,  # noqa: F401  (re-exported)
    KILL_CAUSE_ASSERTION,
    KILL_CAUSE_ERROR,
    KILL_CAUSE_UNKNOWN,
    LOG_TAG,
    NO_BYTECODE_ARG,  # noqa: F401  (re-exported)
    NO_BYTECODE_VALUE,  # noqa: F401  (re-exported)
    NO_BYTECODE_VAR,  # noqa: F401  (re-exported)
    PASSED_SUMMARY_PATTERN,  # noqa: F401  (re-exported)
    PYTEST_COMMON_ARGS,  # noqa: F401  (re-exported)
    PYTEST_EXIT_OK,
    PYTHONPATH_VAR,  # noqa: F401  (re-exported)
    PYTHON_ARGS,  # noqa: F401  (re-exported)
    SHORT_SUMMARY_PATTERN,  # noqa: F401  (re-exported)
    TB_LINE_PATTERN,  # noqa: F401  (re-exported)
    TERMINAL_WIDTH_VALUE,  # noqa: F401  (re-exported)
    TERMINAL_WIDTH_VAR,  # noqa: F401  (re-exported)
    TOTALS_LINE_PATTERN,  # noqa: F401  (re-exported)
    _run_pytest,
    baseline,
    classify_kill,
    parse_counts,
)
from aipass.seedgo.apps.handlers.tests_pytest_standards.mutation_selection import (
    BASIS_COVERING_TESTS,  # noqa: F401  (re-exported)
    BASIS_FILE_NOT_MEASURED,  # noqa: F401  (re-exported)
    BASIS_FULL_SUITE,
    BASIS_IMPORT_TIME_ONLY,  # noqa: F401  (re-exported)
    BASIS_MAP_REFUSED,  # noqa: F401  (re-exported)
    BASIS_NEAR_TOTAL,  # noqa: F401  (re-exported)
    BASIS_NO_COVERING_TEST,  # noqa: F401  (re-exported)
    BASIS_UNMAPPED_CONTEXT,  # noqa: F401  (re-exported)
    CONTEXT_PHASE_SEPARATOR,  # noqa: F401  (re-exported)
    COVERAGE_CONTEXT_ARG,  # noqa: F401  (re-exported)
    COVERAGE_DATA_NAME,  # noqa: F401  (re-exported)
    COVERAGE_FILE_VAR,  # noqa: F401  (re-exported)
    COVERAGE_MAP_NAME,  # noqa: F401  (re-exported)
    COVERAGE_READER_CODE,  # noqa: F401  (re-exported)
    COVERAGE_READER_TIMEOUT_SECONDS,  # noqa: F401  (re-exported)
    COVERAGE_REPORT_ARG,  # noqa: F401  (re-exported)
    COVERAGE_REQUEST_NAME,  # noqa: F401  (re-exported)
    COVERAGE_SOURCE_FLAG,  # noqa: F401  (re-exported)
    DEFAULT_SOURCE_DIRS,
    NODEID_SEPARATOR,  # noqa: F401  (re-exported)
    NO_TEST_CONTEXT,  # noqa: F401  (re-exported)
    REASON_BASELINE_NOT_GREEN,
    REASON_BUDGET_EXHAUSTED,
    REASON_COVERAGE_UNAVAILABLE,
    REASON_LAUNCH_FAILED,
    REASON_MUTANT_NOT_PARSEABLE,
    REASON_MUTANT_TIMEOUT,
    REASON_NOT_GUTTABLE,
    REASON_SOURCE_IO,
    SELECTION_FULL_SUITE_FRACTION,  # noqa: F401  (re-exported)
    SOURCE_ENCODING,
    STDOUT_TAIL_CHARS,
    coverage_baseline,
    select_tests,
    site_key,  # noqa: F401  (re-exported)
)
from aipass.seedgo.apps.handlers.tests_pytest_standards.mutation_shapes import (
    BaselineResult,
    CampaignResult,
    CoverageMap,
    DEFAULT_BUDGET_SECONDS,
    DEFAULT_MUTANT_TIMEOUT_SECONDS,
    FunctionSite,
    MutantResult,
    SELECTION_COVERAGE,
    SELECTION_FULL_SUITE,
    SELECTION_MODES,
    Selection,
    SuiteRun,
    SuiteTarget,
)

#: The group this module serves. NOT `scoped_survival` - see contract 2 above.
GROUP = "pseudo_tested"

MODULE_NAME = "gutting"

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

#: The survivor that cost nothing to find. Spelled exactly as the lane's
#: contract names it, because it is published verbatim in the mutant record.
REASON_NO_COVERING_TEST = "no covering test"

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

#: `-rfE` keeps the FAILED/ERROR short-summary lines, which is where the
#: exception class is read from. `--tb=line` is the fallback source for the
#: same class when the summary line is missing.
MUTANT_EXTRA_ARGS: tuple = ("--tb=line", "-rfE")

#: One failure already means KILLED, so there is nothing to learn from the rest
#: of the suite. `-x` is sound here and is measured rather than assumed - and
#: it does not cost the kill cause, because the short summary and the `--tb`
#: line for the one failure that stopped the run are both still printed.
STOP_FIRST_ARG = "-x"

#: Below this much remaining budget a mutant is not started at all. Starting
#: one with two seconds left produces a timeout that reads like a slow test.
MIN_MUTANT_SECONDS = 5


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


def _classify_run(
    site: FunctionSite, run: SuiteRun, base: BaselineResult, capped: bool, selection: Selection
) -> MutantResult:
    """Turn one mutant run into a verdict, kill_cause and selection included."""
    if run.timed_out:
        reason = REASON_BUDGET_EXHAUSTED if capped else REASON_MUTANT_TIMEOUT
        return MutantResult(
            site, OUTCOME_NOT_RUN, reason=reason, elapsed_seconds=run.elapsed_seconds, selection=selection
        )
    if run.launch_error is not None:
        return MutantResult(
            site,
            OUTCOME_NOT_RUN,
            reason=f"{REASON_LAUNCH_FAILED}: {run.launch_error}",
            elapsed_seconds=run.elapsed_seconds,
            selection=selection,
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
            selection=selection,
        )
    return MutantResult(
        site,
        OUTCOME_SURVIVED,
        elapsed_seconds=run.elapsed_seconds,
        returncode=run.returncode,
        note=_survivor_note(run, base, selection),
        selection=selection,
    )


def _survivor_note(run: SuiteRun, base: BaselineResult, selection: Selection) -> Optional[str]:
    """A warning when a green mutant ran fewer tests than it was given.

    A mutant that turns tests into skips exits 0 and would otherwise read as a
    clean survivor. The count is compared rather than assumed - and it is
    compared against THIS MUTANT'S expected count, not the baseline's. Under a
    reduced selection every mutant runs fewer tests than the baseline by
    design, so comparing to the baseline would stamp the warning on every
    selected survivor and the signal would mean nothing.
    """
    expected = base.passed if selection.runs_whole_suite else (selection.count or 0)
    passed = parse_counts(run.stdout).get("passed", 0)
    if passed >= expected:
        return None
    return f"green but only {passed} of the {expected} tests it was given passed - inspect before trusting"


def _probe_site(
    target: SuiteTarget,
    site: FunctionSite,
    base: BaselineResult,
    timeout_seconds: int,
    capped: bool,
    extra_args: Sequence[str],
    selection: Selection,
) -> MutantResult:
    """Write one mutant, run its tests, classify, restore the original bytes.

    Restoration is in a `finally`, so a crashed run, a keyboard interrupt or a
    failure inside the classifier can never leave a mutated file in the copy.
    """
    path = target.target_copy / site.relpath
    original, read_error = _read_source(path)
    if original is None:
        return MutantResult(
            site, OUTCOME_MUTATION_FAILED, reason=f"{REASON_SOURCE_IO}: {read_error}", selection=selection
        )

    mutant, mutation_error = _mutant_text(original, site)
    if mutant is None:
        return MutantResult(site, OUTCOME_MUTATION_FAILED, reason=mutation_error, selection=selection)

    try:
        path.write_text(mutant, encoding=SOURCE_ENCODING, newline="")
        run = _run_pytest(target, extra_args, timeout_seconds, test_args=selection.nodeids)
    finally:
        path.write_bytes(original)
    return _classify_run(site, run, base, capped, selection)


def _uncovered_survivor(site: FunctionSite, selection: Selection) -> MutantResult:
    """The survivor that cost nothing: no test executes this function's body.

    No pytest runs at all. This is a COVERAGE HOLE rather than a missing
    oracle, it is reported in its own bucket, and it is the half of Descartes'
    definition the full-suite mode has never been able to separate out.
    """
    return MutantResult(site, OUTCOME_SURVIVED, reason=REASON_NO_COVERING_TEST, selection=selection)


def _mutant_args(stop_on_first_failure: bool) -> Tuple[str, ...]:
    """The mutant run's extra arguments."""
    if not stop_on_first_failure:
        return MUTANT_EXTRA_ARGS
    return (*MUTANT_EXTRA_ARGS, STOP_FIRST_ARG)


def _unrun(
    sites: Sequence[FunctionSite], reason: str, selector: Callable[[FunctionSite], Selection]
) -> List[MutantResult]:
    """Mark a run of sites as never executed, with the reason attached."""
    return [MutantResult(site, OUTCOME_NOT_RUN, reason=reason, selection=selector(site)) for site in sites]


def _full_suite_selector(site: FunctionSite) -> Selection:
    """The selector every full-suite campaign uses: one basis, every test."""
    del site
    return Selection(BASIS_FULL_SUITE)


def _build_selector(
    target: SuiteTarget,
    sites: Sequence[FunctionSite],
    selection_mode: str,
    source_dirs: Sequence[str],
    baseline_result: Optional[BaselineResult],
) -> Tuple[BaselineResult, Optional[CoverageMap], Callable[[FunctionSite], Selection]]:
    """The baseline, the map when one was asked for, and the per-site selector."""
    if selection_mode != SELECTION_COVERAGE:
        base = baseline_result if baseline_result is not None else baseline(target)
        return base, None, _full_suite_selector

    base, coverage_map = coverage_baseline(target, sites, source_dirs=source_dirs)

    def selector(site: FunctionSite) -> Selection:
        """This site's covering tests, read off the map taken at baseline."""
        return select_tests(site, coverage_map)

    return base, coverage_map, selector


def _coverage_refusal(base: BaselineResult, coverage_map: Optional[CoverageMap]) -> Optional[str]:
    """The sentence explaining why a coverage-selected campaign cannot run."""
    if coverage_map is None:
        return None
    if coverage_map.refusal_reason is not None:
        return coverage_map.refusal_reason
    if not base.green:
        return f"{REASON_COVERAGE_UNAVAILABLE}: {base.refusal_reason}"
    return None


def run_campaign(
    target: SuiteTarget,
    sites: Sequence[FunctionSite],
    *,
    budget_seconds: int = DEFAULT_BUDGET_SECONDS,
    mutant_timeout_seconds: int = DEFAULT_MUTANT_TIMEOUT_SECONDS,
    stop_on_first_failure: bool = True,
    baseline_result: Optional[BaselineResult] = None,
    selection: str = SELECTION_FULL_SUITE,
    source_dirs: Sequence[str] = DEFAULT_SOURCE_DIRS,
) -> CampaignResult:
    """Gut every probeable function in turn and run the tests that can kill it.

    The campaign is serial and bounded twice over: `mutant_timeout_seconds`
    caps one suite run, `budget_seconds` caps the whole campaign. On expiry the
    remaining sites are recorded `not_run` with `budget_exhausted` and the
    summary reports what was completed - a partial campaign never becomes a
    whole-tree number.

    `selection` DEFAULTS TO THE FULL SUITE, which is the behaviour every number
    this group has published so far describes. `SELECTION_COVERAGE` opts into
    the reduction: the baseline is taken under coverage.py with per-test
    contexts and each mutant runs only the tests that execute its body. That is
    a cheaper campaign and a different claim, so it is never selected
    implicitly and every mutant record carries the basis it was judged on. When
    the map cannot be built the campaign REFUSES rather than running the full
    suite while still calling itself coverage-selected.

    Args:
        target: Where and how to run the suite, over a COPY of the tree.
        sites: Everything `discover_functions` found, skips included.
        budget_seconds: Wall-clock ceiling for the entire campaign.
        mutant_timeout_seconds: Wall-clock ceiling for one mutant's suite run.
        stop_on_first_failure: Pass `-x`; one failure already means KILLED.
        baseline_result: A baseline already measured by the caller, if any.
            Ignored under `SELECTION_COVERAGE`, whose baseline must be the
            instrumented run that produced the map.
        selection: One of `SELECTION_MODES`.
        source_dirs: Production roots under the copy, instrumented for the map.

    Returns:
        The campaign, baseline included, ready for `summarize`.
    """
    started = time.monotonic()
    if selection not in SELECTION_MODES:
        raise ValueError(f"selection must be one of {SELECTION_MODES}, not {selection!r}")

    base, coverage_map, selector = _build_selector(target, sites, selection, source_dirs, baseline_result)
    skipped = [
        MutantResult(site, OUTCOME_SKIPPED, reason=site.skip_reason, selection=selector(site))
        for site in sites
        if site.skip_reason
    ]
    probeable = [site for site in sites if site.skip_reason is None]
    refusal = _coverage_refusal(base, coverage_map) or (None if base.green else base.refusal_reason)

    if refusal is not None:
        logger.warning(f"{LOG_TAG} campaign refused on {len(probeable)} functions: {refusal}")
        reason = REASON_COVERAGE_UNAVAILABLE if coverage_map is not None else REASON_BASELINE_NOT_GREEN
        results = skipped + _unrun(probeable, reason, selector)
        return CampaignResult(
            base,
            results,
            time.monotonic() - started,
            budget_seconds,
            mutant_timeout_seconds,
            stop_on_first_failure,
            selection,
            coverage_map,
        )

    extra_args = _mutant_args(stop_on_first_failure)
    driven = _drive(target, probeable, base, started, budget_seconds, mutant_timeout_seconds, extra_args, selector)
    elapsed = time.monotonic() - started
    logger.info(f"{LOG_TAG} gutting campaign finished in {elapsed:.1f}s over {len(probeable)} functions")
    return CampaignResult(
        base,
        skipped + driven,
        elapsed,
        budget_seconds,
        mutant_timeout_seconds,
        stop_on_first_failure,
        selection,
        coverage_map,
    )


def _drive(
    target: SuiteTarget,
    probeable: Sequence[FunctionSite],
    base: BaselineResult,
    started: float,
    budget_seconds: int,
    mutant_timeout_seconds: int,
    extra_args: Sequence[str],
    selector: Callable[[FunctionSite], Selection],
) -> List[MutantResult]:
    """Walk the probeable sites under the campaign's wall-clock budget."""
    results: List[MutantResult] = []
    for index, site in enumerate(probeable):
        selection = selector(site)
        if selection.count == 0:
            results.append(_uncovered_survivor(site, selection))
            continue
        remaining = budget_seconds - (time.monotonic() - started)
        if remaining < MIN_MUTANT_SECONDS:
            logger.warning(f"{LOG_TAG} budget exhausted with {len(probeable) - index} functions unprobed")
            return results + _unrun(probeable[index:], REASON_BUDGET_EXHAUSTED, selector)
        ceiling = min(mutant_timeout_seconds, int(remaining))
        capped = ceiling < mutant_timeout_seconds
        results.append(_probe_site(target, site, base, ceiling, capped, extra_args, selection))
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


def _count_bases(results: Sequence[MutantResult]) -> Dict[str, int]:
    """How many mutants were judged on each selection basis."""
    counts: Dict[str, int] = {}
    for result in results:
        basis = result.selection.basis if result.selection is not None else BASIS_FULL_SUITE
        counts[basis] = counts.get(basis, 0) + 1
    return counts


def _selection_document(campaign: CampaignResult, results: Sequence[MutantResult]) -> dict:
    """What test set the campaign's verdicts were read from, and how big it was."""
    selected = [r.selection.count for r in results if r.selection is not None and r.selection.count is not None]
    coverage_map = campaign.coverage_map
    return {
        "mode": campaign.selection_mode,
        "by_basis": _count_bases(results),
        "tests_selected_total": sum(selected),
        "whole_suite_runs": sum(1 for r in results if r.selection is not None and r.selection.runs_whole_suite),
        "coverage_map": coverage_map.to_document() if coverage_map is not None else None,
    }


def _selection_limits(campaign: CampaignResult) -> List[str]:
    """The caveats that belong to the selection, not to gutting itself."""
    if not _coverage_was_measured(campaign):
        refused = campaign.coverage_map.refusal_reason if campaign.coverage_map is not None else None
        sentences = [
            "No function's coverage was measured, so the uncovered bucket is empty because nothing "
            "looked, not because there is nothing there."
        ]
        if refused is None:
            sentences.append(
                "Every mutant here was measured against the WHOLE suite, so no verdict is a reduced-set verdict."
            )
            return sentences
        sentences.append(
            f"A coverage-selected campaign was asked for and REFUSED: {refused}. No mutant was run "
            "and no verdict was produced; the full suite was not silently substituted."
        )
        return sentences
    return [
        "Each mutant ran only the tests whose coverage context executes its body, so every verdict is "
        "a reduced-set verdict. The count and the basis are on each record; a basis other than "
        "covering_tests means the map could not narrow that one and the whole suite ran instead.",
        "The selection is sound because gutting replaces a body and nothing else: a test that never "
        "enters the body cannot observe the mutation. It is bounded by what coverage.py can see, and "
        "coverage.py traces one process - a test that exercises the target through a SUBPROCESS "
        "contributes no context, so the uncovered bucket is a list to verify rather than a conclusion.",
        "Functions whose body runs only at import or collection time carry no test context at all. "
        "Those are recorded import_time_no_test_context and measured against the whole suite, because "
        "selecting nothing for them would turn a killable mutant into a free survivor.",
        "Each selection is kept in the baseline's collection order so that -x stops on the same test "
        "the full suite would stop on and the kill_cause split is reproduced rather than reshuffled. "
        "Sorting a selection any other way moves kills between the assertion and error buckets while "
        "leaving the kill itself intact, which was measured before it was fixed.",
    ]


def _coverage_was_measured(campaign: CampaignResult) -> bool:
    """True only when a coverage map was actually built for this campaign."""
    coverage_map = campaign.coverage_map
    return coverage_map is not None and coverage_map.refusal_reason is None


def _superset_sentence(campaign: CampaignResult) -> str:
    """How far this campaign got towards Descartes' own definition.

    The full-suite mode still cannot separate an uncovered function from a
    pseudo-tested one and must say so. The coverage mode can, and says that
    instead - the sentence changes because the measurement changed.
    """
    if not _coverage_was_measured(campaign):
        return (
            "Survivors are a SUPERSET of pseudo-tested functions. Descartes calls a function pseudo-tested "
            "only when tests cover it and the mutant still survives; a function no test executes is merely "
            "uncovered. No coverage was measured here, so read this list against a coverage report before "
            "calling any entry pseudo-tested."
        )
    return (
        "Coverage was measured, so the two halves of Descartes' definition are separated: pseudo_tested "
        "holds survivors whose bodies the suite really executes, and the uncovered bucket holds the "
        "functions no test reaches at all. The first is a missing oracle, the second is a coverage hole, "
        "and only the first is pseudo-testedness."
    )


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
        _superset_sentence(campaign),
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

        `pseudo_tested` and `uncovered` are SEPARATE lists and neither is a
        subset of the other. A function no test executes is a coverage hole; a
        function the tests execute and no oracle watches is a missing oracle.
        Folding them together is the confusion this group exists to undo.

    Returns:
        A JSON-safe dict. `killed_by_assertion`, `killed_by_error` and
        `killed_by_unknown` are reported separately and there is deliberately
        no combined total: contract 1 exists to make that ratio visible, and a
        single kill count would hide exactly the thing it was written to show.
    """
    results = campaign.results
    survivors = [result for result in results if result.outcome == OUTCOME_SURVIVED]
    uncovered = [result for result in survivors if result.reason == REASON_NO_COVERING_TEST]
    unwatched = [result for result in survivors if result.reason != REASON_NO_COVERING_TEST]
    probed = [result for result in results if result.outcome in (OUTCOME_SURVIVED, OUTCOME_KILLED)]
    unrun_reasons = _count_reasons(results, OUTCOME_NOT_RUN)
    unrun_reasons.update(_count_reasons(results, OUTCOME_MUTATION_FAILED))
    unknown = _count_causes(results, KILL_CAUSE_UNKNOWN)
    elapsed = campaign.elapsed_seconds

    return {
        "group": GROUP,
        "functions_total": len(results),
        "functions_probed": len(probed),
        # A `no covering test` survivor is a decided verdict that started no
        # pytest at all, so the count of functions actually EXECUTED as mutants
        # is published next to the count of functions judged.
        "functions_executed": len(probed) - len(uncovered),
        "skipped": {
            "total": sum(1 for r in results if r.outcome == OUTCOME_SKIPPED),
            "by_reason": _count_reasons(results, OUTCOME_SKIPPED),
        },
        "pseudo_tested": [_survivor_document(r) for r in unwatched],
        "uncovered": {
            # False whenever nothing looked - the full-suite mode, and equally
            # a coverage campaign whose map was refused. An empty list under
            # `measured: true` must mean "looked, found none".
            "measured": _coverage_was_measured(campaign),
            "total": len(uncovered),
            "functions": [_survivor_document(r) for r in uncovered],
        },
        "killed_by_assertion": _count_causes(results, KILL_CAUSE_ASSERTION),
        "killed_by_error": _count_causes(results, KILL_CAUSE_ERROR),
        "killed_by_unknown": unknown,
        "not_run": {"total": sum(unrun_reasons.values()), "by_reason": unrun_reasons},
        "baseline": campaign.baseline.to_document(),
        "selection": _selection_document(campaign, results),
        "elapsed_seconds": round(elapsed, 3),
        "seconds_per_mutant": round(elapsed / len(probed), 3) if probed else None,
        "budget_seconds": campaign.budget_seconds,
        "stopped_on_first_failure": campaign.stopped_on_first_failure,
        "mutants": [result.to_document() for result in results],
        "limits": _limits(campaign, survivors, unknown) + _selection_limits(campaign),
    }


def _survivor_document(result: MutantResult) -> dict:
    """One survivor as it is published, selection and reason attached."""
    return {
        "relpath": result.site.relpath,
        "qualname": result.site.qualname,
        "lineno": result.site.lineno,
        "reason": result.reason,
        "selected_tests": result.selection.count if result.selection is not None else None,
        "selection_basis": result.selection.basis if result.selection is not None else None,
        "note": result.note,
    }
