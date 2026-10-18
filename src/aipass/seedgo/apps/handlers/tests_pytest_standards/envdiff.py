# =================== AIPass ====================
# Name: envdiff.py
# Description: two-environment verdict diff - the width_coupling execution group
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-10-17
# =============================================

"""Run the suite twice under two named environments and diff the per-test verdicts.

The output is the set of nodeids whose verdict changes between a narrow and a wide
run: the width coupling itself, which a static rule only half catches. `run_axis()`
knows nothing about width; another axis is one more `*_variants()` beside it.
Verdicts never travel through the terminal: COLUMNS=40 trims pytest's own summary,
so an injected plugin writes JSONL, and its header records the width the child
actually resolved. Either variant failing refuses the axis, never a zero.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

GROUP = "width_coupling"

#: Published so a second axis on the same core is distinguishable in an artifact.
AXIS_WIDTH = "width"

#: 40 is where the canary fixture's coupling peaks; at 200 nothing observed wraps.
NARROW_COLUMNS = 40
WIDE_COLUMNS = 200

VARIANT_NARROW = "narrow"
VARIANT_WIDE = "wide"

#: Identical across variants so only the axis differs. `TERM` is a real name: Rich
#: treats `dumb`/`unknown` as a fixed 80x25 console and would ignore the axis.
SHARED_ENVIRONMENT: Dict[str, str] = {
    "TERM": "xterm-256color",
    "LINES": "24",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}

#: The plugin refuses to load without it, so a lost channel dies loudly, not as zero.
VERDICT_LOG_ENV = "AUDIT_TESTS_VERDICT_LOG"

#: Preferred over the tty size by `shutil` and Rich, which makes the axis work in a non-tty child.
COLUMNS_ENV = "COLUMNS"

PLUGIN_MODULE = "envdiff_verdict_plugin"
PLUGIN_FILENAME = f"{PLUGIN_MODULE}.py"
VERDICT_LOG_TEMPLATE = "verdicts_{variant}.jsonl"
WORKDIR_PREFIX = "audit_tests_envdiff_"

RECORD_HEADER = "header"
RECORD_REPORT = "report"
RECORD_COLLECT_ERROR = "collect_error"
RECORD_SESSION = "session"

PHASE_SETUP = "setup"
PHASE_CALL = "call"
PHASE_TEARDOWN = "teardown"

OUTCOME_PASSED = "passed"
OUTCOME_FAILED = "failed"
OUTCOME_SKIPPED = "skipped"

VERDICT_PASSED = "passed"
VERDICT_FAILED = "failed"
VERDICT_ERROR = "error"
VERDICT_SKIPPED = "skipped"
VERDICT_XFAILED = "xfailed"
VERDICT_XPASSED = "xpassed"

#: The only exit codes whose log is final; 2-5 leave a partial or empty log.
PYTEST_EXIT_OK = 0
PYTEST_EXIT_TESTS_FAILED = 1
COMPLETING_EXIT_CODES: Tuple[int, ...] = (PYTEST_EXIT_OK, PYTEST_EXIT_TESTS_FAILED)

#: `no:randomly` stops per-session reseeding from faking a divergence. The target's
#: own config stays in effect: overriding `addopts` would measure a suite nobody runs.
PYTEST_BASE_ARGS: Tuple[str, ...] = (
    "-B",
    "-m",
    "pytest",
)
PYTEST_TAIL_ARGS: Tuple[str, ...] = (
    "-p",
    PLUGIN_MODULE,
    "-p",
    "no:cacheprovider",
    "-p",
    "no:randomly",
    "-q",
    "--no-header",
    "--tb=no",
)

#: Per variant run, matching the adapter's T-BUDGET default; the axis costs two.
DEFAULT_BUDGET_SECONDS = 900

STDOUT_TAIL_CHARS = 2000

REFUSAL_OUTPUT_CHARS = 400
MAX_NAMED_COLLECT_ERRORS = 3

#: Caps the enumeration only, never the count; the document says when it truncated.
MAX_REPORTED_DIVERGENCES = 500

GROUP_TIER = "exec"
GROUP_KIND = "measure_only"
STATUS_MEASURED = "measured"
STATUS_NOT_APPLICABLE = "not_applicable"

NEXT_AXIS_NOTE = (
    "order_dependence is the same mechanism with a different knob: two variants that "
    "differ in test order rather than in COLUMNS, diffed by this identical core. It is "
    "the spine's own group and is still not_applicable: 'not built'. Building it adds "
    "an order_variants() beside width_variants() and changes nothing else here."
)

#: Published with every result, so a divergence count is not over-read.
WIDTH_AXIS_LIMITS: Tuple[str, ...] = (
    "Two widths are two points, not a sweep. A suite green at both 40 and 200 can "
    "still be coupled at some width in between, and this axis will call it clean.",
    "A divergence is measured once and never re-run. An ordinarily flaky test looks "
    "identical to a width-coupled one here; PYTHONHASHSEED and LINES are pinned "
    "across both runs to remove two known sources, but nothing confirms reproducibility.",
    "The verdict is pass/fail per nodeid. A test that passes at both widths while "
    "rendering visibly different output is invisible to this axis.",
    "The axis names WHICH nodeids flip, never WHY. It does not identify the assertion "
    "that wrapped, and it cannot tell a test that legitimately pins its own width "
    "from one that is simply insensitive to width.",
    "COLUMNS is honoured by whatever the target's own renderer consults. The header "
    "record proves the CHILD's stdlib terminal-size resolver saw the requested width; "
    "it does not prove every renderer inside the target asked that resolver.",
    "Windows is untested here. COLUMNS is not exported by cmd.exe or PowerShell, so "
    "no Windows developer has the environment this axis constructs; the variable is "
    "still honoured by shutil.get_terminal_size() and by Rich when a parent sets it, "
    "but a renderer calling the Win32 console API directly would ignore it. No "
    "measurement on Windows backs this paragraph.",
    "Nodeids are relative to pytest's rootdir. Both variants run the identical "
    "invocation from the identical cwd, so they share one rootdir - a run whose "
    "rootdir differed would make the whole subtraction meaningless and is refused.",
    "A target that pins COLUMNS itself - a conftest setting os.environ at import - "
    "makes the whole axis refuse rather than report a clean zero. That is the right "
    "answer and it is all-or-nothing: such a suite cannot be measured here at all, "
    "not even the part of it that never pinned anything. Measured on a probe target "
    "whose conftest set COLUMNS=120: both variants refused with the width they got.",
)

#: Not `SPECIFICATION`: `render_spec` stamps the STATIC tier on everything it renders,
#: and this is an execution group.
GROUP_SPECIFICATION: Dict[str, object] = {
    "rule": "a suite's verdicts must not depend on the terminal width it is rendered at",
    "mechanism": "run the suite twice, identical in everything but COLUMNS, and subtract the per-nodeid verdicts",
    "flags": [
        "a nodeid that passes at one width and fails at the other, in either direction",
        "a nodeid collected by one run and not the other (reported separately)",
    ],
    "limits": list(WIDTH_AXIS_LIMITS),
    "evidence": (
        "canary fixture tests/test_span.py: 25 of 56 nodeids flip between COLUMNS=40 "
        "and COLUMNS=200; the whole fixture tests/ tree: 45 of 141; seedgo's own "
        "4415-nodeid suite: 0 of 4415"
    ),
}


#: Loaded with `-p` inside a foreign copy, never imported here: stdlib-only, no aipass
#: import (Law M10). Outside `payload/`, so `execution_isolation()` does not check it.
VERDICT_PLUGIN_SOURCE = f'''"""Per-test verdict recorder. Stdlib only. Imports no aipass, ever."""

import json
import os
import shutil

_PATH = os.environ.get("{VERDICT_LOG_ENV}")
if not _PATH:
    raise RuntimeError(
        "{VERDICT_LOG_ENV} is unset - this plugin refuses to run without a sink, "
        "because a run with no verdict channel would report an entirely believable zero"
    )

_HANDLE = open(_PATH, "a", encoding="utf-8")


def _write(record):
    _HANDLE.write(json.dumps(record, sort_keys=True))
    _HANDLE.write("\\n")
    _HANDLE.flush()


def pytest_configure(config):
    _write(
        {{
            "rec": "{RECORD_HEADER}",
            "reported_columns": shutil.get_terminal_size().columns,
            "columns_env": os.environ.get("{COLUMNS_ENV}", ""),
            "rootdir": str(config.rootpath),
        }}
    )


def pytest_runtest_logreport(report):
    _write(
        {{
            "rec": "{RECORD_REPORT}",
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "xfail": hasattr(report, "wasxfail"),
        }}
    )


def pytest_collectreport(report):
    if report.failed:
        _write({{"rec": "{RECORD_COLLECT_ERROR}", "nodeid": report.nodeid}})


def pytest_sessionfinish(session, exitstatus):
    _write({{"rec": "{RECORD_SESSION}", "exitstatus": int(exitstatus)}})
    _HANDLE.close()
'''


class EnvDiffError(RuntimeError):
    """The axis could not be set up. Never raised for a suite that merely failed."""


@dataclass(frozen=True)
class Target:
    """Where and how to invoke pytest. Built by the caller, never by this module."""

    python: Path
    cwd: Path
    pythonpath: str
    test_arg: str

    def to_document(self) -> dict:
        """The artifact's invocation block."""
        return {
            "python": str(self.python),
            "cwd": str(self.cwd),
            "test_arg": self.test_arg,
        }


@dataclass(frozen=True)
class Variant:
    """One named environment the suite is run under.

    `env` is layered over the parent environment: a suite stripped of PATH and HOME measures nothing real.
    """

    name: str
    env: Dict[str, str]
    description: str

    def to_document(self) -> dict:
        """The artifact's variant declaration."""
        return {"variant": self.name, "env": dict(self.env), "description": self.description}


@dataclass
class VariantRun:
    """What one run of one variant produced, including the ways it produced nothing."""

    variant: str
    description: str
    env: Dict[str, str] = field(default_factory=dict)
    verdicts: Dict[str, str] = field(default_factory=dict)
    collect_errors: List[str] = field(default_factory=list)
    returncode: Optional[int] = None
    elapsed_seconds: float = 0.0
    session_finished: bool = False
    reported_columns: Optional[int] = None
    rootdir: str = ""
    refused: bool = False
    reason: str = ""
    stdout_tail: str = ""

    @property
    def counts(self) -> Dict[str, int]:
        """Verdicts tallied by kind. Every kind is present, including the zeros."""
        tally = {
            VERDICT_PASSED: 0,
            VERDICT_FAILED: 0,
            VERDICT_ERROR: 0,
            VERDICT_SKIPPED: 0,
            VERDICT_XFAILED: 0,
            VERDICT_XPASSED: 0,
        }
        for verdict in self.verdicts.values():
            tally[verdict] = tally.get(verdict, 0) + 1
        return tally

    def to_document(self) -> dict:
        """The artifact's per-variant summary."""
        return {
            "variant": self.variant,
            "description": self.description,
            "env": dict(self.env),
            "counts": self.counts,
            "nodeid_count": len(self.verdicts),
            "collect_errors": list(self.collect_errors),
            "returncode": self.returncode,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "session_finished": self.session_finished,
            "reported_columns": self.reported_columns,
            "rootdir": self.rootdir,
            "refused": self.refused,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Divergence:
    """One nodeid whose verdict is not the same in both variants."""

    nodeid: str
    verdicts: Dict[str, str]

    def to_document(self) -> dict:
        """The artifact's divergence record."""
        return {"nodeid": self.nodeid, "verdicts": dict(self.verdicts)}


@dataclass(frozen=True)
class CollectionDelta:
    """One nodeid one variant collected and the other did not.

    A finding, never a silent drop: different collections are not one suite measured twice.
    """

    nodeid: str
    present_in: List[str]
    absent_from: List[str]
    verdict: str

    def to_document(self) -> dict:
        """The artifact's collection-delta record."""
        return {
            "nodeid": self.nodeid,
            "present_in": list(self.present_in),
            "absent_from": list(self.absent_from),
            "verdict": self.verdict,
        }


@dataclass
class AxisResult:
    """The whole two-run diff: both summaries, the deltas, and why it refused."""

    axis: str
    target: Optional[Target] = None
    runs: List[VariantRun] = field(default_factory=list)
    diverged: List[Divergence] = field(default_factory=list)
    collection_delta: List[CollectionDelta] = field(default_factory=list)
    compared_nodeids: int = 0
    refused: bool = False
    reason: str = ""
    elapsed_seconds: float = 0.0
    limits: List[str] = field(default_factory=list)

    @property
    def diverged_count(self) -> int:
        """The true count, never the length of the published list."""
        return len(self.diverged)

    def to_document(self) -> dict:
        """The measurement, as a plain dict. Applies no law and computes no score."""
        published = self.diverged[:MAX_REPORTED_DIVERGENCES]
        document = {
            "axis": self.axis,
            "variants": [run.to_document() for run in self.runs],
            "compared_nodeids": self.compared_nodeids,
            "diverged_count": self.diverged_count,
            "diverged": [item.to_document() for item in published],
            "diverged_truncated": len(published) < self.diverged_count,
            "collection_delta": [item.to_document() for item in self.collection_delta],
            "collection_delta_count": len(self.collection_delta),
            "refused": self.refused,
            "reason": self.reason,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "limits": list(self.limits),
        }
        if self.target is not None:
            document["invocation"] = self.target.to_document()
        return document


def width_variants(narrow: int = NARROW_COLUMNS, wide: int = WIDE_COLUMNS) -> Tuple[Variant, Variant]:
    """The two variants of the width axis: same everything, different COLUMNS.

    Raises EnvDiffError unless the widths are two distinct positives: coinciding ends report a confident zero.
    """
    if narrow < 1 or wide < 1:
        raise EnvDiffError(f"a terminal width must be positive: narrow={narrow}, wide={wide}")
    if narrow == wide:
        raise EnvDiffError(
            f"the narrow and wide variants are both {narrow} columns - an axis with one "
            f"point reports zero divergence for every suite on earth"
        )

    return (
        Variant(
            name=VARIANT_NARROW,
            env={COLUMNS_ENV: str(narrow)},
            description=f"the suite rendered at {narrow} columns, where wrapping is most likely",
        ),
        Variant(
            name=VARIANT_WIDE,
            env={COLUMNS_ENV: str(wide)},
            description=f"the suite rendered at {wide} columns, wide enough that nothing observed wraps",
        ),
    )


def expected_columns(variant: Variant) -> Optional[int]:
    """The width this variant asked the child for, or None when it asked for none.

    A non-numeric COLUMNS is "asked for nothing": a non-width axis may run through this core.
    """
    raw = variant.env.get(COLUMNS_ENV, "")
    if not raw.isdigit():
        return None
    return int(raw)


def run_axis(
    target: Target,
    variants: Sequence[Variant],
    *,
    workdir: Optional[Path] = None,
    budget_seconds: int = DEFAULT_BUDGET_SECONDS,
    axis: str = AXIS_WIDTH,
    limits: Sequence[str] = WIDTH_AXIS_LIMITS,
) -> AxisResult:
    """Run the suite once per variant and return the nodeids whose verdict differs.

    Refuses rather than shrinks: a bad variant gives `refused=True`, a reason, and no divergences.
    `workdir` is never the target's own tree.
    """
    _validate_variants(variants)

    started = time.monotonic()
    owned_workdir = workdir is None
    scratch = Path(tempfile.mkdtemp(prefix=WORKDIR_PREFIX)) if workdir is None else Path(workdir)

    try:
        runs = _run_all(target, variants, scratch, budget_seconds)
    finally:
        if owned_workdir:
            _remove_scratch(scratch)

    result = _assemble(axis, target, runs, limits)
    result.elapsed_seconds = time.monotonic() - started
    _record(result)
    return result


def _validate_variants(variants: Sequence[Variant]) -> None:
    """Two variants, two names. Anything else is a caller error, stated as one."""
    if len(variants) != 2:
        raise EnvDiffError(f"an axis compares exactly two variants, got {len(variants)}")
    if variants[0].name == variants[1].name:
        raise EnvDiffError(f"both variants are named '{variants[0].name}' - the diff would be unreadable")


def _run_all(
    target: Target,
    variants: Sequence[Variant],
    scratch: Path,
    budget_seconds: int,
) -> List[VariantRun]:
    """Install the verdict channel once, then run each variant through it."""
    plugin_dir = install_plugin(scratch)
    return [_run_variant(target, variant, scratch, plugin_dir, budget_seconds) for variant in variants]


def install_plugin(workdir: Path) -> Path:
    """Write the verdict-recording plugin into `workdir` and return its directory.

    Raises EnvDiffError if it cannot: a run without the verdict channel must not start.
    """
    directory = Path(workdir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / PLUGIN_FILENAME).write_text(VERDICT_PLUGIN_SOURCE, encoding="utf-8")
    except OSError as exc:
        raise EnvDiffError(f"could not write the verdict plugin into {directory}: {exc}") from exc
    return directory


def _child_environment(target: Target, variant: Variant, plugin_dir: Path, log_path: Path) -> Dict[str, str]:
    """The parent environment, plus the shared pins, plus this variant's axis.

    The plugin directory goes on the END of PYTHONPATH so it never shadows the target.
    """
    environment = dict(os.environ)
    environment.update(SHARED_ENVIRONMENT)
    environment.update(variant.env)
    environment[VERDICT_LOG_ENV] = str(log_path)
    environment["PYTHONPATH"] = os.pathsep.join([part for part in (target.pythonpath, str(plugin_dir)) if part])
    return environment


def _run_variant(
    target: Target,
    variant: Variant,
    scratch: Path,
    plugin_dir: Path,
    budget_seconds: int,
) -> VariantRun:
    """One variant's run, and every way it can come back with nothing to say."""
    run = VariantRun(variant=variant.name, description=variant.description, env=dict(variant.env))
    log_path = Path(scratch) / VERDICT_LOG_TEMPLATE.format(variant=variant.name)
    _clear_log(log_path)

    command = [str(target.python), *PYTEST_BASE_ARGS, target.test_arg, *PYTEST_TAIL_ARGS]
    environment = _child_environment(target, variant, plugin_dir, log_path)

    started = time.monotonic()
    completed = _launch(command, target, environment, budget_seconds, run)
    run.elapsed_seconds = time.monotonic() - started
    if completed is None:
        return run

    run.returncode = completed.returncode
    run.stdout_tail = (completed.stdout or "")[-STDOUT_TAIL_CHARS:]
    _absorb_log(run, log_path)
    _rule_on_run(run, variant)
    return run


def _launch(
    command: List[str],
    target: Target,
    environment: Dict[str, str],
    budget_seconds: int,
    run: VariantRun,
) -> "Optional[subprocess.CompletedProcess[str]]":
    """Run pytest, or mark the variant refused with the reason it never ran."""
    try:
        return subprocess.run(
            command,
            cwd=str(target.cwd),
            env=environment,
            capture_output=True,
            text=True,
            timeout=budget_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"[AUDIT-TESTS] variant '{run.variant}' exceeded its {budget_seconds}s budget")
        run.refused = True
        run.reason = (
            f"the {budget_seconds}s budget expired before the suite finished, so this variant "
            f"produced a partial log and no verdict from it is final (Law T-BUDGET)"
        )
        return None
    except OSError as exc:
        logger.warning(f"[AUDIT-TESTS] variant '{run.variant}' could not be launched: {exc}")
        run.refused = True
        run.reason = f"pytest could not be launched: {type(exc).__name__}: {exc}"
        return None


def _clear_log(log_path: Path) -> None:
    """Remove a stale log, loudly if it will not go.

    The plugin appends, so a leftover file would read as this run's verdicts.
    """
    try:
        log_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(f"[AUDIT-TESTS] stale verdict log {log_path} could not be removed: {exc}")


def _absorb_log(run: VariantRun, log_path: Path) -> None:
    """Read the verdict channel into the run, or say why there was nothing to read."""
    records = read_records(log_path)
    if not records:
        run.refused = True
        run.reason = (
            f"the verdict plugin wrote no records to {log_path.name} - it never loaded, so "
            f"nothing about this run's verdicts is known"
        )
        return

    header = _first(records, RECORD_HEADER)
    run.reported_columns = _as_optional_int(header.get("reported_columns"))
    run.rootdir = str(header.get("rootdir", ""))
    run.verdicts = collapse_verdicts(records)
    run.collect_errors = [
        str(record.get("nodeid", "")) for record in records if record.get("rec") == RECORD_COLLECT_ERROR
    ]
    run.session_finished = bool(_first(records, RECORD_SESSION))


def _rule_on_run(run: VariantRun, variant: Variant) -> None:
    """Decide whether this variant is entitled to contribute verdicts at all.

    Most-diagnostic first, so the reason names the earliest thing that went wrong.
    """
    if run.refused:
        return

    wanted = expected_columns(variant)
    if wanted is not None and run.reported_columns != wanted:
        run.refused = True
        run.reason = (
            f"the child resolved {run.reported_columns} columns after being asked for {wanted} - "
            f"the axis did not take effect in this environment, so any divergence measured "
            f"against it would be measuring something else"
        )
        return

    if not run.session_finished:
        run.refused = True
        run.reason = "the session never reached pytest_sessionfinish, so its verdicts are partial"
        return

    if run.returncode not in COMPLETING_EXIT_CODES:
        run.refused = True
        run.reason = (
            f"pytest exited {run.returncode}, which means the session did not simply pass or fail "
            f"(2 interrupted, 3 internal error, 4 usage error, 5 nothing collected): "
            f"{run.stdout_tail[-REFUSAL_OUTPUT_CHARS:].strip() or 'no output'}"
        )
        return

    if not run.verdicts:
        named = run.collect_errors[:MAX_NAMED_COLLECT_ERRORS]
        detail = ", ".join(named) or "no collection error was reported either"
        run.refused = True
        run.reason = f"the run executed no test at all - {detail}"


def read_records(log_path: Path) -> List[dict]:
    """Every well-formed JSONL record in a verdict log.

    A truncated final line is dropped, not raised: the missing session record refuses upstream.
    """
    path = Path(log_path)
    if not path.is_file():
        return []

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(f"[AUDIT-TESTS] verdict log {path} could not be read: {exc}")
        return []

    records: List[dict] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        record = _decode(line, path, number)
        if record is not None:
            records.append(record)
    return records


def _decode(line: str, path: Path, number: int) -> Optional[dict]:
    """One JSONL line as a dict, or None with a warning naming where it broke."""
    text = line.strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"[AUDIT-TESTS] verdict log {path.name} line {number} is not JSON: {exc}")
        return None
    if not isinstance(decoded, dict):
        logger.warning(f"[AUDIT-TESTS] verdict log {path.name} line {number} is not an object")
        return None
    return decoded


def collapse_verdicts(records: Iterable[dict]) -> Dict[str, str]:
    """Per-nodeid verdicts, collapsed from pytest's three per-test phase reports.

    One combining rule for both variants, so a residual tally disagreement cannot fake a divergence.
    """
    verdicts: Dict[str, str] = {}
    for record in records:
        if record.get("rec") != RECORD_REPORT:
            continue
        nodeid = str(record.get("nodeid", ""))
        verdict = _phase_verdict(record)
        if nodeid and verdict:
            verdicts[nodeid] = verdict
    return verdicts


def _phase_verdict(record: dict) -> str:
    """What one phase report implies, or "" when that phase implies nothing."""
    phase = record.get("when")
    outcome = str(record.get("outcome", ""))
    xfail = bool(record.get("xfail"))

    if phase == PHASE_SETUP:
        return _setup_verdict(outcome, xfail)
    if phase == PHASE_CALL:
        return _call_verdict(outcome, xfail)
    if phase == PHASE_TEARDOWN and outcome == OUTCOME_FAILED:
        return VERDICT_ERROR
    return ""


def _setup_verdict(outcome: str, xfail: bool) -> str:
    """A setup phase speaks only when it failed or skipped the test outright."""
    if outcome == OUTCOME_FAILED:
        return VERDICT_ERROR
    if outcome == OUTCOME_SKIPPED:
        return VERDICT_XFAILED if xfail else VERDICT_SKIPPED
    return ""


def _call_verdict(outcome: str, xfail: bool) -> str:
    """The call phase, where an xfail marker inverts the plain reading."""
    if xfail and outcome in (OUTCOME_SKIPPED, OUTCOME_FAILED):
        return VERDICT_XFAILED
    if xfail and outcome == OUTCOME_PASSED:
        return VERDICT_XPASSED
    return {
        OUTCOME_PASSED: VERDICT_PASSED,
        OUTCOME_FAILED: VERDICT_FAILED,
        OUTCOME_SKIPPED: VERDICT_SKIPPED,
    }.get(outcome, "")


def _assemble(
    axis: str,
    target: Target,
    runs: List[VariantRun],
    limits: Sequence[str],
) -> AxisResult:
    """Turn two runs into the result, refusing whenever the subtraction is unsound."""
    result = AxisResult(axis=axis, target=target, runs=runs, limits=list(limits))

    blocked = [run for run in runs if run.refused]
    if blocked:
        result.refused = True
        result.reason = "; ".join(f"variant '{run.variant}': {run.reason}" for run in blocked)
        return result

    first, second = runs[0], runs[1]
    if first.rootdir and second.rootdir and first.rootdir != second.rootdir:
        result.refused = True
        result.reason = (
            f"the two runs resolved different pytest rootdirs ({first.rootdir} and "
            f"{second.rootdir}), so their nodeids are not the same names for the same tests"
        )
        return result

    result.diverged = _diverged(first, second)
    result.collection_delta = _collection_delta(first, second)
    result.compared_nodeids = len(set(first.verdicts) & set(second.verdicts))
    return result


def _diverged(first: VariantRun, second: VariantRun) -> List[Divergence]:
    """Every nodeid both runs executed and disagreed about."""
    shared = sorted(set(first.verdicts) & set(second.verdicts))
    return [
        Divergence(
            nodeid=nodeid,
            verdicts={first.variant: first.verdicts[nodeid], second.variant: second.verdicts[nodeid]},
        )
        for nodeid in shared
        if first.verdicts[nodeid] != second.verdicts[nodeid]
    ]


def _collection_delta(first: VariantRun, second: VariantRun) -> List[CollectionDelta]:
    """Every nodeid exactly one run had. Reported, never dropped."""
    deltas: List[CollectionDelta] = []
    for owner, other in ((first, second), (second, first)):
        for nodeid in sorted(set(owner.verdicts) - set(other.verdicts)):
            deltas.append(
                CollectionDelta(
                    nodeid=nodeid,
                    present_in=[owner.variant],
                    absent_from=[other.variant],
                    verdict=owner.verdicts[nodeid],
                )
            )
    return deltas


def measure_width_coupling(
    target: Target,
    *,
    narrow: int = NARROW_COLUMNS,
    wide: int = WIDE_COLUMNS,
    workdir: Optional[Path] = None,
    budget_seconds: int = DEFAULT_BUDGET_SECONDS,
) -> AxisResult:
    """The width axis, end to end. One call for an adapter to wire."""
    variants = width_variants(narrow=narrow, wide=wide)
    return run_axis(
        target,
        variants,
        workdir=workdir,
        budget_seconds=budget_seconds,
        axis=AXIS_WIDTH,
        limits=WIDTH_AXIS_LIMITS,
    )


def group_document(result: AxisResult) -> dict:
    """The `width_coupling` group, as the artifact publishes it.

    Law S1: a refused axis is `not_applicable` with a reason, never a zero; `score` stays None.
    """
    measured = not result.refused
    document: Dict[str, object] = {
        "tier": GROUP_TIER,
        "kind": GROUP_KIND,
        "status": STATUS_MEASURED if measured else STATUS_NOT_APPLICABLE,
        "reason": result.reason,
        "score": None,
        "rule": GROUP_SPECIFICATION["rule"],
        "mechanism": GROUP_SPECIFICATION["mechanism"],
        "next_axis": NEXT_AXIS_NOTE,
    }
    document.update(result.to_document())
    return document


def not_applicable_document(reason: str) -> dict:
    """The group when the axis never ran at all. Law S1, stated once."""
    return {
        "tier": GROUP_TIER,
        "kind": GROUP_KIND,
        "status": STATUS_NOT_APPLICABLE,
        "reason": reason,
        "score": None,
        "axis": AXIS_WIDTH,
        "rule": GROUP_SPECIFICATION["rule"],
        "mechanism": GROUP_SPECIFICATION["mechanism"],
        "next_axis": NEXT_AXIS_NOTE,
        "variants": [],
        "compared_nodeids": 0,
        "diverged_count": 0,
        "diverged": [],
        "collection_delta": [],
        "limits": list(WIDTH_AXIS_LIMITS),
    }


def _first(records: List[dict], kind: str) -> dict:
    """The first record of a kind, or an empty dict when the run never wrote one."""
    for record in records:
        if record.get("rec") == kind:
            return record
    return {}


def _as_optional_int(value: object) -> Optional[int]:
    """An int when the child reported one, None when it reported something else."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _remove_scratch(scratch: Path) -> None:
    """Delete a scratch directory this module created, and only one it created.

    The M10 boundary: it refuses anything that is not a directory this module named.
    """
    path = Path(scratch)
    if not path.is_dir() or not path.name.startswith(WORKDIR_PREFIX):
        logger.warning(f"[AUDIT-TESTS] refusing to remove an unrecognised scratch directory: {path}")
        return
    try:
        shutil.rmtree(path)
    except OSError as exc:
        logger.warning(f"[AUDIT-TESTS] scratch directory {path} could not be removed: {exc}")


def _record(result: AxisResult) -> None:
    """Log the axis outcome where an operator can find it after the fact."""
    payload = {
        "axis": result.axis,
        "refused": result.refused,
        "reason": result.reason,
        "diverged_count": result.diverged_count,
        "collection_delta_count": len(result.collection_delta),
        "compared_nodeids": result.compared_nodeids,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
    }
    json_handler.log_operation(f"envdiff_{result.axis}_axis", payload)

    if result.refused:
        logger.warning(f"[AUDIT-TESTS] {GROUP} refused on the {result.axis} axis: {result.reason}")
        return
    logger.info(
        f"[AUDIT-TESTS] {GROUP}: {result.diverged_count} of {result.compared_nodeids} nodeids "
        f"changed verdict across the {result.axis} axis in {result.elapsed_seconds:.1f}s"
    )
