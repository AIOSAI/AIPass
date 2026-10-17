# =================== AIPass ====================
# Name: mutation_selection.py
# Description: the coverage pass and the per-mutant test selection it feeds
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-10-17
# =============================================

"""The instrumented baseline pass, and which tests one mutant is allowed to run.

Above ``mutation_runner``, below ``gutting``; ``gutting``'s docstring is the specification.
"""

import json
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards.mutation_runner import (
    BASELINE_EXTRA_ARGS,
    DEFAULT_BASELINE_TIMEOUT_SECONDS,
    LOG_TAG,
    NO_BYTECODE_ARG,
    PYTEST_EXIT_OK,
    _baseline_from_run,
    _pytest_environment,
    _run_pytest,
)
from aipass.seedgo.apps.handlers.tests_pytest_standards.mutation_shapes import (
    BaselineResult,
    CoverageMap,
    FunctionSite,
    Selection,
    SuiteTarget,
)

DEFAULT_SOURCE_DIRS: tuple = ("apps",)

SOURCE_ENCODING = "utf-8"

#: A mutant that never ran is neither survivor nor kill: an unmeasured function.
REASON_BASELINE_NOT_GREEN = "baseline_not_green"
REASON_COVERAGE_UNAVAILABLE = "coverage_map_unavailable"
REASON_BUDGET_EXHAUSTED = "budget_exhausted"
REASON_MUTANT_TIMEOUT = "mutant_timeout"
REASON_NOT_GUTTABLE = "not_guttable"
REASON_MUTANT_NOT_PARSEABLE = "mutant_not_parseable"
REASON_SOURCE_IO = "source_io_error"
REASON_LAUNCH_FAILED = "pytest_launch_failed"

#: Every mutant record carries one: "the suite stayed green" means something different per basis.
BASIS_FULL_SUITE = "full_suite"
BASIS_COVERING_TESTS = "covering_tests"
BASIS_NO_COVERING_TEST = "no_covering_test"
BASIS_IMPORT_TIME_ONLY = "import_time_no_test_context"
BASIS_UNMAPPED_CONTEXT = "unmapped_test_context"
BASIS_FILE_NOT_MEASURED = "source_file_not_instrumented"
BASIS_NEAR_TOTAL = "selection_covers_most_of_suite"
BASIS_MAP_REFUSED = "coverage_map_refused"

#: Above this share the whole suite runs, under its own basis, never disguised as a selection.
SELECTION_FULL_SUITE_FRACTION = 0.9

COVERAGE_SOURCE_FLAG = "--cov"
COVERAGE_CONTEXT_ARG = "--cov-context=test"
COVERAGE_REPORT_ARG = "--cov-report="
COVERAGE_FILE_VAR = "COVERAGE_FILE"

#: Beside the run cwd, never inside the target copy, which holds only the measured tree.
COVERAGE_DATA_NAME = ".gutting_coverage"
COVERAGE_REQUEST_NAME = ".gutting_coverage_request.json"
COVERAGE_MAP_NAME = ".gutting_coverage_map.json"
COVERAGE_READER_TIMEOUT_SECONDS = 600

#: pytest-cov contexts are `<nodeid>|<phase>`; all phases fold onto one nodeid.
CONTEXT_PHASE_SEPARATOR = "|"

#: Import/collection time: the one class where selecting nothing would be wrong.
NO_TEST_CONTEXT = ""

#: Always slash-separated; `os.sep` here would be a Windows bug Linux never surfaces.
NODEID_SEPARATOR = "/"

#: Runs under the TARGET's interpreter, whose coverage wrote the file (another version
#: reads it silently wrong); reduces in the child so no line map crosses the pipe.
COVERAGE_READER_CODE = """
import json
import sys
from pathlib import Path

request = json.loads(Path(sys.argv[1]).read_text())
output = Path(sys.argv[2])
separator = request["phase_separator"]
no_test_context = request["no_test_context"]


def refuse(detail):
    output.write_text(json.dumps({"error": detail}))
    raise SystemExit(0)


try:
    import coverage
except ImportError as exc:
    refuse("coverage is not importable by the target interpreter: %s" % exc)

data = coverage.CoverageData(basename=request["data_file"])
try:
    data.read()
except Exception as exc:
    # Every failure here is a refusal the parent must publish, so it is turned
    # into a recorded reason rather than a traceback nobody reads.
    refuse("the coverage data could not be read: %s: %s" % (type(exc).__name__, exc))

root = Path(request["target_copy"])
by_relpath = {}
for measured in data.measured_files():
    try:
        relative = Path(measured).relative_to(root).as_posix()
    except ValueError:
        continue
    by_relpath[relative] = data.contexts_by_lineno(measured)

functions = {}
for key, relpath, first, last in request["sites"]:
    lines = by_relpath.get(relpath)
    if lines is None:
        functions[key] = {"measured": False, "contexts": [], "import_time": False}
        continue
    contexts = set()
    import_time = False
    for number in range(first, last + 1):
        for context in lines.get(number, ()):
            if context == no_test_context:
                import_time = True
            else:
                contexts.add(context.rsplit(separator, 1)[0])
    functions[key] = {"measured": True, "contexts": sorted(contexts), "import_time": import_time}

output.write_text(json.dumps({"files": sorted(by_relpath), "functions": functions}))
"""

STDOUT_TAIL_CHARS = 2000


def site_key(site: FunctionSite) -> str:
    """The stable identity of one function across the map and the campaign.

    The line number is in the key: a qualname defined twice in a file would share one selection.
    """
    return f"{site.relpath}::{site.qualname}:{site.lineno}"


def _coverage_args(target: SuiteTarget, source_dirs: Sequence[str]) -> List[str]:
    """The `--cov` arguments naming the copy's production roots."""
    args = [f"{COVERAGE_SOURCE_FLAG}={target.target_copy / name}" for name in source_dirs]
    return [*args, COVERAGE_CONTEXT_ARG, COVERAGE_REPORT_ARG]


def _read_coverage_child(target: SuiteTarget, sites: Sequence[FunctionSite]) -> Tuple[Optional[dict], Optional[str]]:
    """Reduce the coverage data to per-function context sets, in a child.

    Returns `(payload, refusal_reason)`; exactly one is set.
    """
    request_path = target.cwd / COVERAGE_REQUEST_NAME
    map_path = target.cwd / COVERAGE_MAP_NAME
    request = {
        "data_file": str(target.cwd / COVERAGE_DATA_NAME),
        "target_copy": str(target.target_copy),
        "phase_separator": CONTEXT_PHASE_SEPARATOR,
        "no_test_context": NO_TEST_CONTEXT,
        "sites": [[site_key(site), site.relpath, site.body_lineno, site.end_lineno] for site in sites],
    }
    try:
        request_path.write_text(json.dumps(request), encoding=SOURCE_ENCODING)
    except OSError as exc:
        return None, f"the coverage request could not be written to {request_path}: {type(exc).__name__}: {exc}"

    failure = _launch_coverage_reader(target, request_path, map_path)
    if failure is not None:
        return None, failure

    try:
        payload = json.loads(map_path.read_text(encoding=SOURCE_ENCODING))
    except (OSError, ValueError) as exc:
        return None, f"the coverage map at {map_path} could not be read: {type(exc).__name__}: {exc}"

    error = payload.get("error")
    return (None, error) if error else (payload, None)


def _launch_coverage_reader(target: SuiteTarget, request_path: Path, map_path: Path) -> Optional[str]:
    """Run the reader child. Returns a refusal reason, or None on success."""
    command = [str(target.python), NO_BYTECODE_ARG, "-c", COVERAGE_READER_CODE, str(request_path), str(map_path)]
    try:
        completed = subprocess.run(
            command,
            cwd=str(target.cwd),
            env=_pytest_environment(target),
            capture_output=True,
            text=True,
            timeout=COVERAGE_READER_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"the coverage reader could not run: {type(exc).__name__}: {exc}"

    if completed.returncode != PYTEST_EXIT_OK:
        return f"the coverage reader exited {completed.returncode}: {completed.stderr.strip()[:STDOUT_TAIL_CHARS]}"
    return None


def _nodeid_resolver(passing_nodeids: Sequence[str]) -> Callable[[str], Optional[str]]:
    """Map a coverage context's nodeid onto one pytest can be handed.

    coverage records rootdir-relative nodeids; pytest takes invocation-relative ones. The prefix
    is recovered from the run's own passing set so it cannot drift.
    """
    exact = set(passing_nodeids)
    by_suffix: Dict[str, List[str]] = {}
    for nodeid in passing_nodeids:
        _, _, tail = nodeid.partition(NODEID_SEPARATOR)
        while tail:
            by_suffix.setdefault(tail, []).append(nodeid)
            _, _, tail = tail.partition(NODEID_SEPARATOR)

    def resolve(raw: str) -> Optional[str]:
        """The runnable nodeid for one raw context, or None when ambiguous."""
        if raw in exact:
            return raw
        candidates = by_suffix.get(raw, [])
        return candidates[0] if len(candidates) == 1 else None

    return resolve


def _map_from_payload(
    payload: dict, base: BaselineResult, sites: Sequence[FunctionSite], elapsed: float
) -> CoverageMap:
    """Turn the child's per-function context sets into a runnable map.

    Each selection keeps the baseline's collection order: under `-x` another order can stop on
    a different first failure and move the kill between contract-1 buckets.
    """
    resolve = _nodeid_resolver(base.passing_nodeids)
    order = {nodeid: position for position, nodeid in enumerate(base.passing_nodeids)}
    measured_files = set(payload.get("files", []))
    functions: dict = payload.get("functions", {})

    by_function: Dict[str, Tuple[str, ...]] = {}
    import_time_only: List[str] = []
    unmapped: List[str] = []
    for site in sites:
        key = site_key(site)
        entry = functions.get(key)
        if entry is None:
            unmapped.append(key)
            continue
        resolved = [resolve(raw) for raw in entry.get("contexts", [])]
        if any(nodeid is None for nodeid in resolved):
            unmapped.append(key)
            continue
        found = {nodeid for nodeid in resolved if nodeid is not None}
        by_function[key] = tuple(sorted(found, key=lambda nodeid: order.get(nodeid, len(order))))
        if not by_function[key] and entry.get("import_time"):
            import_time_only.append(key)

    unmeasured = {site.relpath for site in sites if site.relpath not in measured_files}
    if unmeasured:
        logger.warning(f"{LOG_TAG} {len(unmeasured)} source files carry no coverage data and fall back to the suite")
    return CoverageMap(
        by_function=by_function,
        import_time_only=frozenset(import_time_only),
        unmapped=frozenset(unmapped),
        unmeasured_files=frozenset(unmeasured),
        total_tests=len(base.passing_nodeids),
        elapsed_seconds=elapsed,
    )


def coverage_baseline(
    target: SuiteTarget,
    sites: Sequence[FunctionSite],
    *,
    source_dirs: Sequence[str] = DEFAULT_SOURCE_DIRS,
    timeout_seconds: int = DEFAULT_BASELINE_TIMEOUT_SECONDS,
) -> Tuple[BaselineResult, CoverageMap]:
    """Take the baseline and the per-test coverage map in ONE pytest run.

    The baseline is the instrumented one; a refusal is never converted into a full-suite
    campaign behind the caller's back.
    """
    extra_env = {COVERAGE_FILE_VAR: str(target.cwd / COVERAGE_DATA_NAME)}
    args = [*BASELINE_EXTRA_ARGS, *_coverage_args(target, source_dirs)]
    run = _run_pytest(target, args, timeout_seconds, extra_env=extra_env)
    base = _baseline_from_run(run, timeout_seconds)
    if not base.green:
        reason = f"{REASON_COVERAGE_UNAVAILABLE}: {base.refusal_reason}"
        return base, CoverageMap(elapsed_seconds=run.elapsed_seconds, refusal_reason=reason)

    payload, failure = _read_coverage_child(target, sites)
    if payload is not None and not payload.get("files"):
        # coverage.py reads an absent or empty data file as a valid dataset of nothing.
        failure = f"the coverage pass produced no data for any file under {target.target_copy}"
        payload = None
    if payload is None:
        logger.warning(f"{LOG_TAG} gutting refused: {failure}")
        refusal = f"{REASON_COVERAGE_UNAVAILABLE}: {failure}"
        return base, CoverageMap(elapsed_seconds=run.elapsed_seconds, refusal_reason=refusal)

    built = _map_from_payload(payload, base, sites, run.elapsed_seconds)
    logger.info(f"{LOG_TAG} coverage map built for {len(built.by_function)} functions in {run.elapsed_seconds:.1f}s")
    return base, built


def select_tests(site: FunctionSite, coverage_map: CoverageMap) -> Selection:
    """The tests one mutant runs, and the basis that has to travel with them.

    A refused map must never answer "no covering test".
    """
    key = site_key(site)
    if coverage_map.refusal_reason is not None:
        return Selection(BASIS_MAP_REFUSED)
    if site.relpath in coverage_map.unmeasured_files:
        return Selection(BASIS_FILE_NOT_MEASURED)
    if key in coverage_map.unmapped:
        return Selection(BASIS_UNMAPPED_CONTEXT)

    nodeids = coverage_map.by_function.get(key, ())
    if not nodeids:
        if key in coverage_map.import_time_only:
            return Selection(BASIS_IMPORT_TIME_ONLY)
        return Selection(BASIS_NO_COVERING_TEST, ())
    if len(nodeids) >= coverage_map.total_tests * SELECTION_FULL_SUITE_FRACTION:
        return Selection(BASIS_NEAR_TOTAL)
    return Selection(BASIS_COVERING_TESTS, nodeids)
