# =================== AIPass ====================
# Name: statement_deletion.py
# Description: delete one statement at a time and report which deletions the suite does not notice
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""One statement at a time, not the whole body.

WHY THIS EXISTS. `gutting` replaces a whole function body with `return None`
and asks whether any test notices. That finds a function nothing observes, but
it cannot find a STATEMENT nothing observes inside a function that is otherwise
well tested — the body has other work in it, so gutting the whole thing is
killed by the other work and the unobserved statement is never isolated.

The species, three-instanced before this module was written (devpulse,
DPLAN-0352 round 2):

  round 0 A3   the deletable code was the caller's guard, not the callee body
  round 1 row 3 a documented operation trail with no test reading it
  round 3       extreme mutation left exactly one green of fourteen: `_refuse`
                reduced to a bare `raise`, which deletes the trail call

In one sentence: **code that is documented as doing something, that executes,
that no test observes, and that whole-body gutting cannot isolate.**

STATEMENT LEVEL, NOT BRANCH LEVEL. Deleting an `if`/`for`/`while`/`try` node
deletes its whole block, which is branch deletion and a different, harder
operator (round 0's A3 shape). This module recurses INTO compound statements
and only ever deletes a SIMPLE statement, so a compound header is never the
mutation. That boundary is the brief's, and it is enforced in
`_is_deletable_kind` rather than left to reviewer discipline.

COST IS THE GOVERNING CONSTRAINT. There are many more statements than
functions, so this operator inherits `mutation_selection`'s coverage map or it
does not run at all. It goes further than `gutting` does: gutting selects the
tests covering the whole FUNCTION, while a statement only needs the tests that
cover ITS OWN LINES, which is a strictly smaller set. The map's child reducer
already ranges over `body_lineno..end_lineno`, so a per-statement span needs no
change there — the narrowing is free.

ARID NODES ARE DECLARED HERE, NOT TRIAGED LATER. A survivor list nobody can
triage is worse than no operator (the brief, and round 3's mutmut run where
`"utf-8"` to `"UTF-8"` and `None` flag values padded the survivor list until a
50.9% score understated the suite badly). Every suppression in `ARID_REASONS`
is a statement whose deletion CANNOT change behaviour, each with the reason it
cannot; nothing is suppressed for being noisy, and the counts are published.

WHAT IS DELIBERATELY NOT SUPPRESSED: logging, telemetry and operation-trail
calls. Those look arid and are exactly the species this operator was built to
find. Suppressing them would have suppressed all three sightings.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.tests_pytest_standards import gutting
from aipass.seedgo.apps.handlers.tests_pytest_standards.mutation_runner import (
    PYTEST_EXIT_OK,
    _run_pytest,
    classify_kill,
)
from aipass.seedgo.apps.handlers.tests_pytest_standards.mutation_selection import (
    DEFAULT_SOURCE_DIRS,
    coverage_baseline,
    select_tests,
)
from aipass.seedgo.apps.handlers.tests_pytest_standards.mutation_shapes import (
    BaselineResult,
    CoverageMap,
    FunctionSite,
    Selection,
    SuiteTarget,
)

GROUP = "statement_deletion"

MODULE_NAME = "statement_deletion"

SOURCE_ENCODING = "utf-8"
DEFAULT_NEWLINE = "\n"

#: What replaces a statement that was the only one in its block. Deleting the
#: last statement of a block is a SyntaxError, not a mutant, so the block keeps
#: a body and loses its behaviour — which is the mutation we meant.
EMPTY_BLOCK_FILLER = "pass"

#: Outcomes, spelled exactly as `gutting` spells them so one reader serves both.
OUTCOME_SURVIVED = gutting.OUTCOME_SURVIVED
OUTCOME_KILLED = gutting.OUTCOME_KILLED
OUTCOME_SKIPPED = gutting.OUTCOME_SKIPPED
OUTCOME_NOT_RUN = gutting.OUTCOME_NOT_RUN
OUTCOME_MUTATION_FAILED = gutting.OUTCOME_MUTATION_FAILED

#: DELETION MAKES NON-TERMINATING MUTANTS, AND GUTTING DOES NOT. Removing a
#: loop variable's advance (`index += 1`, `frame = frame.f_back`) leaves a
#: `while` that never exits, and no test can fail a suite that never returns.
#: Measured on fixture three with gutting's inherited 300s timeout: 7 of 108
#: mutants took 95% of the entire campaign's wall clock, and the other 101
#: averaged 0.71s. The timeout, not the mutant count, was the cost.
#:
#: So the ceiling is the target's OWN baseline rather than a fixed number: a
#: run over a SUBSET of the suite cannot legitimately outlast the whole suite,
#: and scaling by the target's own measurement is the lesson from projecting
#: gutting's cost by a rate instead of by its suite.
HANG_TIMEOUT_FLOOR_SECONDS = 10


def hang_timeout(baseline_seconds: float) -> int:
    """The per-mutant ceiling for this target, from its own baseline."""
    return max(HANG_TIMEOUT_FLOOR_SECONDS, int(baseline_seconds) or HANG_TIMEOUT_FLOOR_SECONDS)


REASON_NO_COVERING_TEST = gutting.REASON_NO_COVERING_TEST
REASON_BUDGET_EXHAUSTED = gutting.REASON_BUDGET_EXHAUSTED
REASON_MUTANT_NOT_PARSEABLE = gutting.REASON_MUTANT_NOT_PARSEABLE

#: ARID NODES — a statement whose deletion cannot change behaviour. Each key is
#: published with a count, and each value is the reason it cannot, so the list
#: is reviewable rather than a denylist of things somebody found annoying.
ARID_DOCSTRING = "docstring"
ARID_PASS = "pass_statement"
ARID_ELLIPSIS = "ellipsis_body"
ARID_SOLE_RETURN_NONE = "returns_none_already"

ARID_REASONS: Dict[str, str] = {
    ARID_DOCSTRING: "a bare string expression is evaluated and discarded, at any point in a body",
    ARID_PASS: "`pass` is defined as doing nothing, so removing it removes nothing",
    ARID_ELLIPSIS: "a bare `...` expression is the same no-op as `pass`",
    ARID_SOLE_RETURN_NONE: "`return None` at the end of a body is what falling off the end already does",
}

#: Non-arid skip reasons — the statement is real, but this operator cannot make
#: a sound mutant of it. Counted separately from arid nodes on purpose: an arid
#: node is a statement we CHOSE not to mutate, these are ones we COULD not.
REASON_COMPOUND_HEADER = "compound_header_is_branch_deletion"
REASON_NO_LINE_RANGE = "no_line_range"
REASON_UNPARSABLE_SOURCE = gutting.REASON_UNPARSABLE_SOURCE

#: Simple statements this operator will delete. A compound statement
#: (If/For/While/With/Try/Match) is NOT here: deleting one is branch deletion.
#: `Return`, `Raise`, `Break` and `Continue` are here because deleting one is a
#: statement deletion whose effect on control flow is exactly the point —
#: round 3's single survivor was a deleted trail call beside a `raise`.
DELETABLE_NODES: tuple = (
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.Return,
    ast.Raise,
    ast.Delete,
    ast.Assert,
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
    ast.Break,
    ast.Continue,
    ast.Pass,
)


@dataclass(frozen=True)
class StatementSite:
    """One deletable statement, addressed the way the coverage map addresses.

    `relpath`, `qualname`, `body_lineno` and `end_lineno` carry the STATEMENT's
    own span rather than the function's, because that is what makes the test
    selection narrower than gutting's. `function_qualname` keeps the owning
    function for the report, which is how a reader finds it.
    """

    relpath: str
    qualname: str
    function_qualname: str
    lineno: int
    end_lineno: int
    body_lineno: int
    body_col_offset: int
    kind: str
    is_sole_statement: bool
    source_line: str
    skip_reason: Optional[str] = None
    arid_reason: Optional[str] = None

    @property
    def body_line_count(self) -> int:
        """Lines this statement spans."""
        return max(0, self.end_lineno - self.body_lineno + 1)

    def as_function_site(self) -> FunctionSite:
        """The shape `mutation_selection` reads, spanning this statement only.

        The map keys on `relpath::qualname:lineno` and reduces coverage over
        `body_lineno..end_lineno`, so handing it the statement's span asks
        "which tests execute THESE lines" instead of "which tests execute the
        function". Nothing in the reducer changes; the span is the whole ask.
        """
        return FunctionSite(
            relpath=self.relpath,
            qualname=self.qualname,
            lineno=self.lineno,
            end_lineno=self.end_lineno,
            is_async=False,
            body_line_count=self.body_line_count,
            body_lineno=self.body_lineno,
            body_col_offset=self.body_col_offset,
        )


@dataclass(frozen=True)
class StatementResult:
    """One statement mutant's verdict."""

    site: StatementSite
    outcome: str
    kill_cause: Optional[str] = None
    kill_exception: Optional[str] = None
    first_failing_nodeid: Optional[str] = None
    reason: Optional[str] = None
    elapsed_seconds: float = 0.0
    returncode: Optional[int] = None
    selection_basis: Optional[str] = None
    selected_tests: Optional[int] = None


@dataclass(frozen=True)
class StatementCampaign:
    """Everything one campaign measured."""

    baseline: Optional[BaselineResult]
    results: List[StatementResult] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    budget_seconds: int = 0
    mutant_timeout_seconds: int = 0
    coverage_map: Optional[CoverageMap] = None
    refusal_reason: Optional[str] = None


# =============================================================================
# DISCOVERY
# =============================================================================


def _is_bare_string(node: ast.stmt) -> bool:
    """Whether this is a bare string expression, wherever it sits.

    Not just position 0. A string literal alone on a line evaluates and is
    discarded at ANY point in a body, so deleting it cannot change behaviour
    there either — only the leading one also binds `__doc__`. The first cut
    tested `index == 0` and a mutant that dropped the position check survived,
    because dropping it is not a defect: the narrower rule was simply less
    true than the code it was judging.
    """
    if not isinstance(node, ast.Expr):
        return False
    return isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _is_ellipsis(node: ast.stmt) -> bool:
    """Whether this is a bare `...` expression."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant):
        return False
    return node.value.value is Ellipsis


def _is_return_none(node: ast.stmt) -> bool:
    """Whether this is `return` or `return None`."""
    if not isinstance(node, ast.Return):
        return False
    if node.value is None:
        return True
    return isinstance(node.value, ast.Constant) and node.value.value is None


def _arid_reason_for(node: ast.stmt, is_last: bool) -> Optional[str]:
    """Why deleting this statement could not change behaviour, or None."""
    if _is_bare_string(node):
        return ARID_DOCSTRING
    if isinstance(node, ast.Pass):
        return ARID_PASS
    if _is_ellipsis(node):
        return ARID_ELLIPSIS
    if is_last and _is_return_none(node):
        return ARID_SOLE_RETURN_NONE
    return None


def _is_deletable_kind(node: ast.stmt) -> bool:
    """Simple statement only. A compound header would be branch deletion."""
    return isinstance(node, DELETABLE_NODES)


def _body_blocks(node: ast.stmt) -> List[List[ast.stmt]]:
    """Every statement list hanging off a compound statement."""
    blocks: List[List[ast.stmt]] = []
    for name in ("body", "orelse", "finalbody"):
        block = getattr(node, name, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            blocks.append(block)
    for handler in getattr(node, "handlers", []) or []:
        if isinstance(handler, ast.ExceptHandler) and handler.body:
            blocks.append(handler.body)
    for case in getattr(node, "cases", []) or []:
        if getattr(case, "body", None):
            blocks.append(case.body)
    return blocks


def _walk_block(
    block: Sequence[ast.stmt],
    *,
    relpath: str,
    function_qualname: str,
    lines: Sequence[str],
    out: List[StatementSite],
) -> None:
    """Collect deletable statements in this block, then recurse into compounds."""
    sole = len(block) == 1
    for index, node in enumerate(block):
        is_last = index == len(block) - 1
        lineno = getattr(node, "lineno", 0)
        end_lineno = getattr(node, "end_lineno", 0) or lineno
        source_line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""

        if _is_deletable_kind(node):
            site = StatementSite(
                relpath=relpath,
                qualname=f"{function_qualname}@{lineno}",
                function_qualname=function_qualname,
                lineno=lineno,
                end_lineno=end_lineno,
                body_lineno=lineno,
                body_col_offset=getattr(node, "col_offset", 0),
                kind=type(node).__name__,
                is_sole_statement=sole,
                source_line=source_line,
                skip_reason=None if lineno else REASON_NO_LINE_RANGE,
                arid_reason=_arid_reason_for(node, is_last),
            )
            out.append(site)

        for inner in _body_blocks(node):
            _walk_block(
                inner,
                relpath=relpath,
                function_qualname=function_qualname,
                lines=lines,
                out=out,
            )


def discover_statements(
    target_copy: Path,
    *,
    source_dirs: Sequence[str] = DEFAULT_SOURCE_DIRS,
) -> List[StatementSite]:
    """Every deletable statement under `target_copy`, arid ones included.

    Arid statements are RETURNED, carrying their reason, exactly as `gutting`
    returns skipped functions: a list that quietly drops half the tree and then
    reports a rate is lying about its denominator.
    """
    sites: List[StatementSite] = []
    for path in gutting.iter_source_files(target_copy, source_dirs=source_dirs):
        relpath = path.relative_to(target_copy).as_posix()
        try:
            source = path.read_text(encoding=SOURCE_ENCODING)
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, ValueError) as e:
            logger.info("statement_deletion: cannot read %s: %s", relpath, e)
            sites.append(
                StatementSite(
                    relpath=relpath,
                    qualname=relpath,
                    function_qualname=relpath,
                    lineno=0,
                    end_lineno=0,
                    body_lineno=0,
                    body_col_offset=0,
                    kind="Module",
                    is_sole_statement=False,
                    source_line="",
                    skip_reason=REASON_UNPARSABLE_SOURCE,
                )
            )
            continue

        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            _walk_block(
                node.body,
                relpath=relpath,
                function_qualname=node.name,
                lines=lines,
                out=sites,
            )
    return sites


# =============================================================================
# MUTATION
# =============================================================================


def delete_statement(source: str, site: StatementSite) -> Optional[str]:
    """`source` with this statement removed, or None when it cannot be.

    A text splice over the statement's own line range, never `ast.unparse`:
    unparsing rewrites the whole file, so a kill would no longer be
    attributable to the deletion. The same reasoning as `gutting.gut_source`,
    and the same reason the signature and decorators stay byte-identical —
    that invariant is what makes coverage-based test selection sound.
    """
    lines = source.splitlines(keepends=True)
    start = site.body_lineno - 1
    end = site.end_lineno - 1
    if start < 0 or end >= len(lines) or start > end:
        return None

    if site.is_sole_statement:
        first_line = lines[start]
        newline = first_line[len(first_line.rstrip("\r\n")) :] or DEFAULT_NEWLINE
        indent = " " * site.body_col_offset
        replacement = f"{indent}{EMPTY_BLOCK_FILLER}{newline}"
        return "".join([*lines[:start], replacement, *lines[end + 1 :]])

    return "".join([*lines[:start], *lines[end + 1 :]])


def _mutant_text(source: str, site: StatementSite) -> Tuple[Optional[str], Optional[str]]:
    """The mutant, compiled before it is written. `(text, failure_reason)`."""
    mutant = delete_statement(source, site)
    if mutant is None:
        return None, REASON_NO_LINE_RANGE
    try:
        compile(mutant, site.relpath, "exec")
    except (SyntaxError, ValueError) as e:
        # An engine bug must never reach the suite as a perfect kill, so the
        # mutant is compiled before it is written and the failure is named.
        logger.info("statement_deletion: %s:%s did not compile after deletion: %s", site.relpath, site.lineno, e)
        return None, REASON_MUTANT_NOT_PARSEABLE
    return mutant, None


def probeable(sites: Sequence[StatementSite]) -> List[StatementSite]:
    """The statements a campaign will actually run — not arid, not skipped."""
    return [s for s in sites if s.skip_reason is None and s.arid_reason is None]


# =============================================================================
# CAMPAIGN
# =============================================================================


def _selection_for(site: StatementSite, coverage_map: CoverageMap) -> Selection:
    """Which tests can reach THIS statement."""
    return select_tests(site.as_function_site(), coverage_map)


def _probe(
    target: SuiteTarget,
    site: StatementSite,
    selection: Selection,
    timeout_seconds: int,
) -> StatementResult:
    """Write the mutant, run the selected tests, restore the file."""
    path = target.target_copy / site.relpath
    try:
        original = path.read_bytes()
        source = original.decode(SOURCE_ENCODING)
    except (OSError, UnicodeDecodeError) as e:
        return StatementResult(site=site, outcome=OUTCOME_MUTATION_FAILED, reason=f"cannot read source: {e}")

    mutant, failure = _mutant_text(source, site)
    if mutant is None:
        return StatementResult(site=site, outcome=OUTCOME_MUTATION_FAILED, reason=failure)

    extra_args = [*gutting.MUTANT_EXTRA_ARGS, gutting.STOP_FIRST_ARG]
    try:
        path.write_text(mutant, encoding=SOURCE_ENCODING, newline="")
        run = _run_pytest(
            target,
            extra_args,
            timeout_seconds,
            test_args=selection.nodeids,
        )
    finally:
        path.write_bytes(original)

    selected = None if selection.nodeids is None else len(selection.nodeids)
    if run.timed_out:
        return StatementResult(
            site=site,
            outcome=OUTCOME_NOT_RUN,
            reason="mutant_timeout",
            elapsed_seconds=run.elapsed_seconds,
            selection_basis=selection.basis,
            selected_tests=selected,
        )
    if run.launch_error:
        return StatementResult(
            site=site,
            outcome=OUTCOME_NOT_RUN,
            reason=f"pytest_launch_failed: {run.launch_error}",
            elapsed_seconds=run.elapsed_seconds,
            selection_basis=selection.basis,
            selected_tests=selected,
        )
    if run.returncode != PYTEST_EXIT_OK:
        cause, exception, nodeid = classify_kill(run.stdout, run.stderr)
        return StatementResult(
            site=site,
            outcome=OUTCOME_KILLED,
            kill_cause=cause,
            kill_exception=exception,
            first_failing_nodeid=nodeid,
            elapsed_seconds=run.elapsed_seconds,
            returncode=run.returncode,
            selection_basis=selection.basis,
            selected_tests=selected,
        )
    return StatementResult(
        site=site,
        outcome=OUTCOME_SURVIVED,
        elapsed_seconds=run.elapsed_seconds,
        returncode=run.returncode,
        selection_basis=selection.basis,
        selected_tests=selected,
    )


def run_campaign(
    target: SuiteTarget,
    sites: Sequence[StatementSite],
    *,
    budget_seconds: int = gutting.DEFAULT_BUDGET_SECONDS,
    mutant_timeout_seconds: Optional[int] = None,
    source_dirs: Sequence[str] = DEFAULT_SOURCE_DIRS,
) -> StatementCampaign:
    """One instrumented baseline, then one selected run per live statement.

    The baseline is the coverage run: under coverage selection a caller cannot
    hand in a baseline taken some other way, because the map and the baseline
    have to come from the same execution or the selection is about a different
    tree.
    """
    import time

    started = time.monotonic()
    live = probeable(sites)
    function_sites = [s.as_function_site() for s in live]
    base, coverage_map = coverage_baseline(target, function_sites, source_dirs=source_dirs)

    refusal = None
    if coverage_map.refusal_reason is not None:
        refusal = coverage_map.refusal_reason
    elif not base.green:
        refusal = base.refusal_reason

    if refusal is not None:
        return StatementCampaign(
            baseline=base,
            results=[StatementResult(site=s, outcome=OUTCOME_NOT_RUN, reason=refusal) for s in live],
            elapsed_seconds=time.monotonic() - started,
            budget_seconds=budget_seconds,
            mutant_timeout_seconds=mutant_timeout_seconds or HANG_TIMEOUT_FLOOR_SECONDS,
            coverage_map=coverage_map,
            refusal_reason=refusal,
        )

    ceiling = mutant_timeout_seconds or hang_timeout(base.elapsed_seconds)
    results: List[StatementResult] = []
    for index, site in enumerate(live):
        elapsed = time.monotonic() - started
        remaining = budget_seconds - elapsed
        if remaining < gutting.MIN_MUTANT_SECONDS:
            results += [
                StatementResult(site=s, outcome=OUTCOME_NOT_RUN, reason=REASON_BUDGET_EXHAUSTED) for s in live[index:]
            ]
            break

        selection = _selection_for(site, coverage_map)
        if selection.nodeids is not None and not selection.nodeids:
            results.append(
                StatementResult(
                    site=site,
                    outcome=OUTCOME_SURVIVED,
                    reason=REASON_NO_COVERING_TEST,
                    selection_basis=selection.basis,
                    selected_tests=0,
                )
            )
            continue

        timeout = min(ceiling, int(remaining))
        results.append(_probe(target, site, selection, timeout))

    return StatementCampaign(
        baseline=base,
        results=results,
        elapsed_seconds=time.monotonic() - started,
        budget_seconds=budget_seconds,
        mutant_timeout_seconds=ceiling,
        coverage_map=coverage_map,
    )


# =============================================================================
# REPORT
# =============================================================================


def _count_by(values: Sequence[Optional[str]]) -> Dict[str, int]:
    """A count per distinct non-None value."""
    counts: Dict[str, int] = {}
    for value in values:
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    return counts


#: A function needs at least this many executed mutants before "every one of
#: them survived" says anything. One statement surviving out of one is a
#: statement finding; it is not evidence about the function.
ROLLUP_MIN_STATEMENTS = 2


def _survivor_rollup(campaign: StatementCampaign) -> dict:
    """Collapse whole-function survivor blocks into one row each.

    MEASURED, not guessed: canary's round-4 tree returned 230 survivors and
    188 of them - 82% - were statements inside `print_help` and
    `print_introspection`, two functions `pseudo_tested` already convicts
    whole. Listing them one statement at a time buries the other 42 behind a
    cause that a cheaper operator already reported at the right altitude.

    This is a REPORTING collapse and never a suppression: every mutant is
    still in `mutants[]` with its own verdict. Nothing is dropped, and the
    denominator is published beside the rollup.
    """
    per_function: Dict[Tuple[str, str], List[StatementResult]] = {}
    for result in campaign.results:
        if result.outcome not in (OUTCOME_SURVIVED, OUTCOME_KILLED):
            continue
        key = (result.site.relpath, result.site.function_qualname)
        per_function.setdefault(key, []).append(result)

    wholly: List[dict] = []
    by_function: List[dict] = []
    rolled_up = 0
    for (relpath, qualname), results in sorted(per_function.items()):
        survived = [r for r in results if r.outcome == OUTCOME_SURVIVED]
        if not survived:
            continue
        row = {
            "file": relpath,
            "function": qualname,
            "statements": len(survived),
            "of_executed": len(results),
            "first_line": min(r.site.lineno for r in survived),
        }
        by_function.append(row)
        if len(survived) == len(results) and len(results) >= ROLLUP_MIN_STATEMENTS:
            rolled_up += len(survived)
            wholly.append({k: v for k, v in row.items() if k != "of_executed"})

    by_function.sort(key=lambda row: (-row["statements"], row["file"], row["first_line"]))
    survivors = len([r for r in campaign.results if r.outcome == OUTCOME_SURVIVED])
    return {
        "functions_wholly_unobserved": wholly,
        "statements_rolled_up": rolled_up,
        "survivors_total": survivors,
        "survivors_after_rollup": survivors - rolled_up,
        "survivors_by_function": by_function,
        "means": (
            "Every executed statement in `functions_wholly_unobserved` survived its own deletion, so the "
            "finding is the FUNCTION and the whole-body operator is its right reporter. Read "
            "`survivors_after_rollup` as the statement-level list this operator was built for, and "
            "`survivors_by_function` as that list at one row per function: `statements` of `of_executed` "
            "unobserved. A row where those two differ is the species - the observed statements protect "
            "the whole body from the gutting operator while the rest go unread."
        ),
    }


def summarize(campaign: StatementCampaign, sites: Sequence[StatementSite]) -> dict:
    """The group document. Every denominator is published beside its rate."""
    survivors = [r for r in campaign.results if r.outcome == OUTCOME_SURVIVED]
    observed = [r for r in survivors if r.reason != REASON_NO_COVERING_TEST]
    executed = [r for r in campaign.results if r.outcome in (OUTCOME_SURVIVED, OUTCOME_KILLED)]

    document = {
        "group": GROUP,
        "statements_total": len(sites),
        "statements_arid": len([s for s in sites if s.arid_reason is not None]),
        "statements_skipped": len([s for s in sites if s.skip_reason is not None]),
        "statements_probeable": len(probeable(sites)),
        "statements_executed": len(executed),
        "arid_by_reason": _count_by([s.arid_reason for s in sites]),
        "arid_reasons_declared": dict(ARID_REASONS),
        "skipped_by_reason": _count_by([s.skip_reason for s in sites]),
        "killed": len([r for r in campaign.results if r.outcome == OUTCOME_KILLED]),
        "survived": len(survivors),
        "survived_unobserved": len(observed),
        "survived_no_covering_test": len(survivors) - len(observed),
        "survivor_rollup": _survivor_rollup(campaign),
        "not_run": len([r for r in campaign.results if r.outcome == OUTCOME_NOT_RUN]),
        "mutation_failed": len([r for r in campaign.results if r.outcome == OUTCOME_MUTATION_FAILED]),
        "elapsed_seconds": round(campaign.elapsed_seconds, 2),
        "budget_seconds": campaign.budget_seconds,
        "mutant_timeout_seconds": campaign.mutant_timeout_seconds,
        "refusal_reason": campaign.refusal_reason,
        "mutants": [
            {
                "file": r.site.relpath,
                "function": r.site.function_qualname,
                "line": r.site.lineno,
                "kind": r.site.kind,
                "statement": r.site.source_line,
                "outcome": r.outcome,
                "kill_cause": r.kill_cause,
                "kill_exception": r.kill_exception,
                "first_failing_nodeid": r.first_failing_nodeid,
                "reason": r.reason,
                "selection_basis": r.selection_basis,
                "selected_tests": r.selected_tests,
                "elapsed_seconds": round(r.elapsed_seconds, 2),
            }
            for r in campaign.results
        ],
        "limits": [
            "A surviving deletion may be an equivalent mutant. The declared arid list removes the "
            "statements that CANNOT change behaviour; it does not prove the rest can.",
            "Statement level only. A compound statement is never deleted, so a dead branch is out of "
            "reach of this operator by construction - that is branch deletion and a different build.",
            "Selection is per statement, so a mutant is judged only by the tests that execute its own "
            "lines. A test that would have caught it without executing it cannot.",
            "A deletion that removes a loop variable's advance does not terminate, and no suite can fail "
            "a run that never returns. Those arrive as not_run/mutant_timeout, capped at the target's own "
            "baseline duration - they are reported as unmeasured, never counted as survivors.",
            "`survivor_rollup` collapses a function whose every executed statement survived into one row, "
            "because that is a function-level finding wearing statement-level clothes. It is a reporting "
            "collapse and never a suppression: every mutant is still in `mutants[]` with its own verdict.",
        ],
    }
    if campaign.elapsed_seconds and executed:
        document["seconds_per_mutant"] = round(campaign.elapsed_seconds / len(executed), 2)
    json_handler.log_operation("statement_deletion_summarised", {"executed": len(executed)})
    return document
