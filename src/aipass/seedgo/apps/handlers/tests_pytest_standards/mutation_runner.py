# =================== AIPass ====================
# Name: mutation_runner.py
# Description: runs the target's pytest and reads the verdict out of its output
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""
The pytest subprocess, and everything read back out of what it printed.

WHY THIS IS ITS OWN MODULE. Split out of ``gutting.py`` on the day that file
crossed the branch's 1500-line architecture cap; this is the section its
``EXECUTION`` banner already marked, moved whole. It owns one job: build the
fixed invocation, run it under a wall-clock ceiling, and turn the bytes that
come back into counts, passing nodeids, the contract-1 kill split and the
baseline verdict. It knows nothing about mutation, coverage or campaigns, and
it imports only ``mutation_shapes``.

THE OUTPUT PARSING IS ITSELF A MEASUREMENT, WHICH IS WHY IT LIVES BESIDE THE
INVOCATION. Both traps this module works around were found by running the probe
rather than by reading pytest's docs - the terminal width that truncates a
short-summary line out of its exception class, and the ``AssertionError: ``
prefix pytest strips from every rewritten assert - and the constants that fix
them sit here next to the patterns that depend on them. The full reasoning is
in ``gutting``'s module docstring, which remains the probe's specification.
"""

import os
import re
import subprocess
import time
from typing import Dict, List, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards.mutation_shapes import BaselineResult, SuiteRun, SuiteTarget

LOG_TAG = "[AUDIT-TESTS]"

#: Contract 1 buckets.
KILL_CAUSE_ASSERTION = "assertion"
KILL_CAUSE_ERROR = "error"
KILL_CAUSE_UNKNOWN = "unknown"
ASSERTION_EXCEPTION_NAME = "AssertionError"

#: The invocation. Fixed shape, serial, no plugin autoload surprises. `-B` and
#: `-p no:cacheprovider` are not tidiness: a suite reading a `.pyc` of a body
#: that no longer exists measures a tree that does not exist either.
NO_BYTECODE_ARG = "-B"
PYTHON_ARGS: tuple = (NO_BYTECODE_ARG, "-m", "pytest")
PYTEST_COMMON_ARGS: tuple = ("-p", "no:cacheprovider", "-q", "--no-header")

#: `-rA` lists every PASSED nodeid, which is how the baseline captures the
#: passing set under `-q` without giving up the quiet output.
BASELINE_EXTRA_ARGS: tuple = ("--tb=line", "-rA")

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
# EXECUTION
# =============================================================================


def _pytest_command(target: SuiteTarget, test_args: Sequence[str], extra_args: Sequence[str]) -> List[str]:
    """The serial pytest invocation for one run.

    `test_args` is the whole suite's path for a full run and an explicit list
    of nodeids for a selected one. Both forms are relative to `target.cwd`,
    which is the form pytest's own short-summary lines print.
    """
    return [str(target.python), *PYTHON_ARGS, *test_args, *PYTEST_COMMON_ARGS, *extra_args]


def _pytest_environment(target: SuiteTarget, extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The caller's PYTHONPATH laid over the current environment.

    The isolated env is built elsewhere. All this does is point the child at
    the PYTHONPATH it was handed and forbid bytecode, so a mutant can never be
    shadowed by a `.pyc` of the body it replaced.
    """
    environment = dict(os.environ)
    environment[PYTHONPATH_VAR] = target.pythonpath
    environment[NO_BYTECODE_VAR] = NO_BYTECODE_VALUE
    environment[TERMINAL_WIDTH_VAR] = TERMINAL_WIDTH_VALUE
    if extra_env:
        environment.update(extra_env)
    return environment


def _run_pytest(
    target: SuiteTarget,
    extra_args: Sequence[str],
    timeout_seconds: int,
    *,
    test_args: Optional[Sequence[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> SuiteRun:
    """One pytest subprocess, with a wall-clock ceiling.

    Args:
        target: Where and how to run the suite.
        extra_args: Run-specific arguments appended to the fixed command.
        timeout_seconds: Ceiling for this single run.
        test_args: Explicit nodeids to run; the whole suite when None.
        extra_env: Environment entries this run needs on top of the standard
            ones, such as the coverage pass's data-file location.

    Returns:
        The raw run. A timeout and a launch failure are both returned as
        recorded states, never raised, because both are measurements about the
        mutant rather than crashes of the campaign.
    """
    started = time.monotonic()
    selected = (target.test_arg,) if test_args is None else test_args
    try:
        completed = subprocess.run(
            _pytest_command(target, selected, extra_args),
            cwd=str(target.cwd),
            env=_pytest_environment(target, extra_env),
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
    return _baseline_from_run(_run_pytest(target, BASELINE_EXTRA_ARGS, timeout_seconds), timeout_seconds)


def _baseline_from_run(run: SuiteRun, timeout_seconds: int) -> BaselineResult:
    """Read one unmutated run's output into a baseline, refusal included."""
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
