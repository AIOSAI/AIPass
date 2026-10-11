# =================== AIPass ====================
# Name: mutation_shapes.py
# Description: the records every stage of a gutting campaign exchanges
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""
The record shapes a gutting campaign hands from one stage to the next.

WHY THIS IS ITS OWN MODULE. ``gutting.py`` crossed the branch's 1500-line
architecture cap, so the probe was split along the lines its own section
banners already drew. These dataclasses are the BOTTOM of that split: they own
the campaign's vocabulary - a discovered function, how to invoke the target's
suite, one run's raw output, the baseline verdict, one mutant's test selection,
the coverage map and the finished campaign - and they depend on nothing else in
the pack. ``mutation_runner``, ``mutation_selection`` and ``gutting`` all
import from here and nothing here imports back, which is what keeps the split
acyclic.

The contracts travel with the shapes and are unchanged by the move: a baseline
that is not green is a REFUSAL rather than a zero, a ``Selection`` of None, of
``()`` and of a populated tuple are three different claims, and a
``MutantResult`` never exists without the ``kill_cause`` field contract 1
requires. The relocation changed no rule and no number.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

#: SELECTION MODES. `full_suite` is the default and is the behaviour every
#: number published before this release describes; `coverage_context` is the
#: opt-in reduction and is never chosen implicitly.
SELECTION_FULL_SUITE = "full_suite"
SELECTION_COVERAGE = "coverage_context"
SELECTION_MODES: tuple = (SELECTION_FULL_SUITE, SELECTION_COVERAGE)

DEFAULT_MUTANT_TIMEOUT_SECONDS = 300
DEFAULT_BUDGET_SECONDS = 1800


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
class Selection:
    """Which tests one mutant runs, and on what grounds.

    `nodeids` is None for "the whole suite", an EMPTY tuple for "nothing can
    kill this, do not start pytest at all", and a populated tuple for a reduced
    run. The three are deliberately distinct: a green whole-suite run and a
    green nine-test run are different claims, and a zero-test survivor is not a
    claim about the suite's oracles at all.
    """

    basis: str
    nodeids: Optional[Tuple[str, ...]] = None

    @property
    def runs_whole_suite(self) -> bool:
        """True when this mutant is measured against every test there is."""
        return self.nodeids is None

    @property
    def count(self) -> Optional[int]:
        """How many tests were selected, or None for the whole suite."""
        return None if self.nodeids is None else len(self.nodeids)


@dataclass(frozen=True)
class CoverageMap:
    """Which tests execute each function's body, measured in the baseline pass.

    A map that could not be built carries `refusal_reason` and no numbers. The
    campaign publishes that refusal; it never falls back to the full suite
    while continuing to call the run a coverage-selected campaign.
    """

    by_function: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    import_time_only: FrozenSet[str] = frozenset()
    unmapped: FrozenSet[str] = frozenset()
    unmeasured_files: FrozenSet[str] = frozenset()
    total_tests: int = 0
    elapsed_seconds: float = 0.0
    refusal_reason: Optional[str] = None

    def to_document(self) -> dict:
        """The map's shape as a plain record, without the nodeid lists."""
        selected = [len(ids) for ids in self.by_function.values()]
        return {
            "functions_mapped": len(self.by_function),
            "tests_selected_total": sum(selected),
            "total_tests": self.total_tests,
            "import_time_only": len(self.import_time_only),
            "unmapped_contexts": len(self.unmapped),
            "unmeasured_files": len(self.unmeasured_files),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "refusal_reason": self.refusal_reason,
        }


@dataclass(frozen=True)
class MutantResult:
    """One gutted function, and what the suite did about it.

    `kill_cause` is present on EVERY record, killed or not, because contract 1
    forbids a mutant record without it. For a survivor or an unrun mutant it is
    None, which is a statement that no kill happened - not a missing field.

    `selection` is present for the same reason one level up: a verdict read off
    a reduced test set is a different claim from a verdict read off the whole
    suite, so every record says which it is and how many tests stood behind it.
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
    selection: Optional[Selection] = None

    def to_document(self) -> dict:
        """The mutant as a plain record.

        Returns:
            A JSON-safe dict carrying the kill_cause split required by
            contract 1, the raw exception class behind it, and the test
            selection this verdict was read from. `selected_tests` is None when
            the whole suite ran - `selection_basis` says which whole-suite case
            that was.
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
            "selected_tests": self.selection.count if self.selection is not None else None,
            "selection_basis": self.selection.basis if self.selection is not None else None,
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
    selection_mode: str = SELECTION_FULL_SUITE
    coverage_map: Optional[CoverageMap] = None
