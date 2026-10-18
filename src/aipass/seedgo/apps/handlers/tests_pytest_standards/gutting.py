# =================== AIPass ====================
# Name: gutting.py
# Description: extreme mutation - the per-function pseudo-tested probe
# Version: 1.2.0
# Created: 2026-09-19
# Modified: 2026-10-17
# =============================================

"""Extreme mutation. One mutant per FUNCTION, the whole body replaced by a constant.

Contract 2: pseudo-testedness is a property of a FUNCTION; no number here may be
named oracle survival (`scoped_survival`, a property of a TEST). Contract 1: every
kill carries `kill_cause` (assertion / error / unknown, never folded), because a
gutted `None` raises TypeError on contact and flatters the kill rate. Mutants go
into a caller-built copy, one campaign per copy (no lock), restored in a `finally`.
Coverage selection is sound only because gutting touches nothing but the body; a
subprocess-only test contributes no context, so `uncovered` is a list to verify.
`mutation_shapes`, `mutation_runner` and `mutation_selection` names are re-exported
here because callers reach them through `gutting`.
"""

import ast
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from aipass.prax import logger

# Re-exported: callers reach these as `gutting.<name>`; unused names carry the F401 waiver.
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

#: NOT `scoped_survival` - see contract 2 above.
GROUP = "pseudo_tested"

MODULE_NAME = "gutting"

#: Any dot-directory is excluded on top of this list.
EXCLUDED_DIR_NAMES: tuple = (
    "__pycache__",
    "tests",
    "test",
    "docs",
    "node_modules",
    "site-packages",
)

SOURCE_GLOB = "*.py"

GUT_STATEMENT = "return None"
DEFAULT_NEWLINE = "\n"

#: Every skip reason is published with a count; none is a quiet drop.
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

#: Published verbatim in the mutant record; spelled as the lane's contract names it.
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

#: `mutation_failed` is not `killed`: a mutant that could not be written is no evidence.
OUTCOME_SURVIVED = "survived"
OUTCOME_KILLED = "killed"
OUTCOME_SKIPPED = "skipped"
OUTCOME_NOT_RUN = "not_run"
OUTCOME_MUTATION_FAILED = "mutation_failed"

#: `-rfE` short-summary lines carry the exception class; `--tb=line` is the fallback.
MUTANT_EXTRA_ARGS: tuple = ("--tb=line", "-rfE")

#: One failure already means KILLED; the stopping failure's kill cause is still printed.
STOP_FIRST_ARG = "-x"

#: A mutant started with two seconds left times out like a slow test.
MIN_MUTANT_SECONDS = 5


def _is_excluded_dir(name: str) -> bool:
    """True when a path component is never production source."""
    return name.startswith(".") or name in EXCLUDED_DIR_NAMES


def iter_source_files(target_copy: Path, source_dirs: Sequence[str] = DEFAULT_SOURCE_DIRS) -> List[Path]:
    """Every production `.py` file under the target copy's source roots."""
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

    Such a mutant survives by construction, so its survivor would mean nothing.
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

    Nested functions are not descended into: an inner generator does not make the outer one.
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

    An inline body (`def f(): return 1`) would need the signature rewritten, which this refuses.
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
    # Narrow, not `ast.AST`: this reads `.name` and `.lineno`, which a bare AST lacks.
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

    One skip record per unparsable file, so its hole in the denominator is visible.
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

    `skip_dunder_init` is False by default: whether gutting `__init__` breaks import is measured.
    """
    sites: List[FunctionSite] = []
    for path in iter_source_files(target_copy, source_dirs):
        sites += _sites_in_file(path, target_copy, skip_dunder_init)
    logger.info(f"{LOG_TAG} discovered {len(sites)} functions under {target_copy}")
    return sites


def gut_source(source: str, site: FunctionSite) -> Optional[str]:
    """The module source with one function's body replaced by `return None`.

    Line ranges, never `ast.unparse`: every other byte survives, so a kill stays attributable.
    Correct for `async def` too: the coroutine still awaits to None.
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

    Compiled before writing: a SyntaxError mutant would read as a perfect kill.
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

    Compared against this mutant's expected count, not the baseline's, which selection lowers.
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
    """Write one mutant, run its tests, classify, restore the original bytes."""
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

    A coverage hole, not a missing oracle; reported in its own bucket.
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

    On budget expiry the rest are `not_run` with `budget_exhausted`: a partial campaign is
    never a whole-tree number. `selection` defaults to the full suite; `SELECTION_COVERAGE`
    refuses rather than silently falling back when the map cannot be built, and ignores
    `baseline_result` because its baseline must be the instrumented run.
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

    Only the coverage mode can separate uncovered from pseudo-tested, so the sentence differs.
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

    No combined kill total: contract 1 exists to make the split visible. `pseudo_tested` and
    `uncovered` are separate lists, neither a subset of the other.
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
        # `no covering test` survivors ran no pytest, so executed is published beside judged.
        "functions_executed": len(probed) - len(uncovered),
        "skipped": {
            "total": sum(1 for r in results if r.outcome == OUTCOME_SKIPPED),
            "by_reason": _count_reasons(results, OUTCOME_SKIPPED),
        },
        "pseudo_tested": [_survivor_document(r) for r in unwatched],
        "uncovered": {
            # An empty list under `measured: true` must mean "looked, found none".
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
