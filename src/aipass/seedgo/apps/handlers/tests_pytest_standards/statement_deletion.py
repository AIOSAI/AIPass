# =================== AIPass ====================
# Name: statement_deletion.py
# Description: delete one statement at a time and report which deletions the suite does not notice
# Version: 1.1.0
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
import re
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

#: HEADROOM, BECAUSE THE SUBSET IS SOMETIMES THE WHOLE SUITE. The ceiling above
#: was argued from "a run over a SUBSET cannot legitimately outlast the whole
#: suite" — true, and it does not hold when selection has no coverage entry for
#: a statement and falls back to running everything. Then the mutant's honest
#: cost IS the baseline and a ceiling of exactly the baseline loses a coin toss.
#:
#: Measured, canary a36f500a (devpulse r5_lane.json): baseline 19s, ceiling 19s,
#: and the only two `not_run / mutant_timeout` of 153 were the only two with
#: `selection_basis: unmapped_test_context` — store.py:82 `super().__init__` and
#: kv.py:247 `logger.warning`. Both auditors deleted the log line by hand in
#: under a suite's time. Five further mutants landed at 10.1-14.8s and survived
#: the wall by luck.
#:
#: A hang is unbounded and a slow mutant is about one baseline, so doubling
#: separates them and costs at most one extra baseline on a true hang.
HANG_TIMEOUT_BASELINE_MULTIPLIER = 2


def hang_timeout(baseline_seconds: float) -> int:
    """The per-mutant ceiling for this target, from its own baseline."""
    scaled = int(baseline_seconds * HANG_TIMEOUT_BASELINE_MULTIPLIER)
    return max(HANG_TIMEOUT_FLOOR_SECONDS, scaled or HANG_TIMEOUT_FLOOR_SECONDS)


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
    ARID_SOLE_RETURN_NONE: (
        "`return None` in tail position — reaching the end of its block already ends the "
        "function, so there is nothing left to skip. A guard clause is NOT this: see `_walk_block`"
    ),
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


def _arid_reason_for(node: ast.stmt, ends_the_function: bool) -> Optional[str]:
    """Why deleting this statement could not change behaviour, or None.

    `ends_the_function` is the whole guard on the `return` case: see
    `_walk_block`. The first cut passed `is_last`, computed per BLOCK, which
    made every guard clause arid.
    """
    if _is_bare_string(node):
        return ARID_DOCSTRING
    if isinstance(node, ast.Pass):
        return ARID_PASS
    if _is_ellipsis(node):
        return ARID_ELLIPSIS
    if ends_the_function and _is_return_none(node):
        return ARID_SOLE_RETURN_NONE
    return None


#: Nodes that open a fresh scope. `_walk_block` does NOT descend into these.
#:
#: `discover_statements` finds functions with `ast.walk`, which reaches every
#: nested `def` and every method on its own, so descending here as well emitted
#: each nested statement TWICE — once under the outer function's qualname and
#: once under its own. Measured on a two-level fixture: 6 sites for 4 lines.
#: Found here, not in the round-5 report; it inflates any denominator built on
#: the site count and pays to run the same mutant twice.
_SCOPE_NODES: tuple = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

#: Loop nodes whose `body` re-enters: reaching the end of one starts the next
#: iteration, so a deleted `return` there does not end the function.
_LOOP_NODES: tuple = (ast.For, ast.AsyncFor, ast.While)


def _child_block_exits(node: ast.stmt, name: str, parent_exits: bool) -> bool:
    """Whether reaching the end of `node.<name>` ends the enclosing function.

    Reached only when `node` is itself the last statement of a block that ends
    the function, so `parent_exits` already carries the outer answer. Three
    blocks take it away again:

      loop `body`      the next iteration runs — deleting a `return` there
                       continues the loop instead of leaving the function
      `finalbody`      falling off a `finally` resumes the pending return or
                       re-raises the pending exception; a `return` there
                       SWALLOWS both, so deleting it is never a no-op
      `try` body with  an `else` runs when the try completes normally, so
      an `else`        falling off the try body runs code a `return` skipped
    """
    if not parent_exits:
        return False
    if name == "body" and isinstance(node, _LOOP_NODES):
        return False
    if name == "finalbody":
        return False
    if name == "body" and isinstance(node, ast.Try) and node.orelse:
        return False
    return True


def _is_deletable_kind(node: ast.stmt) -> bool:
    """Simple statement only. A compound header would be branch deletion."""
    return isinstance(node, DELETABLE_NODES)


def _body_blocks(node: ast.stmt, parent_exits: bool) -> List[Tuple[List[ast.stmt], bool]]:
    """Every statement list hanging off a compound statement, each with its
    own answer to "does reaching the end of this block end the function".

    A nested `def`/`lambda`/`class` yields nothing: `discover_statements`
    reaches those through `ast.walk` already, and descending twice double-counts.
    """
    if isinstance(node, _SCOPE_NODES):
        return []
    blocks: List[Tuple[List[ast.stmt], bool]] = []
    for name in ("body", "orelse", "finalbody"):
        block = getattr(node, name, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            blocks.append((block, _child_block_exits(node, name, parent_exits)))
    for handler in getattr(node, "handlers", []) or []:
        if isinstance(handler, ast.ExceptHandler) and handler.body:
            blocks.append((handler.body, parent_exits))
    for case in getattr(node, "cases", []) or []:
        if getattr(case, "body", None):
            blocks.append((case.body, parent_exits))
    return blocks


def _walk_block(
    block: Sequence[ast.stmt],
    *,
    relpath: str,
    function_qualname: str,
    lines: Sequence[str],
    out: List[StatementSite],
    block_exits_function: bool = True,
) -> None:
    """Collect deletable statements in this block, then recurse into compounds.

    `block_exits_function` is the tail-position answer for THIS block: True
    when reaching its end ends the enclosing function. Only then is a trailing
    bare `return` the same thing as falling off the end.

    THE DEFECT THIS PARAMETER CURES (devpulse, round 5, canary a36f500a). The
    first cut asked `index == len(block) - 1` and nothing else, so a `return`
    last in an `if` body was declared arid — which is the definition of a
    guard clause, and the species this operator exists to probe. `kv.py:238`,
    the `return` after `kv refused: --json is only for list`, was filtered out
    before it was ever probed; deleting it leaves the suite green while
    `kv --json FILE set K V` prints the refusal, exits 2, AND writes the pair.
    13 statements on that tree were skipped under the old reason.

    Measured here, the same filter was wrong about three more shapes the
    report did not name: a `return` last in a LOOP body (deleting it continues
    the loop), last in a `finally` (deleting it stops swallowing the pending
    return or exception), and last in a `try` body that has an `else`.
    """
    sole = len(block) == 1
    for index, node in enumerate(block):
        is_last = index == len(block) - 1
        ends_the_function = is_last and block_exits_function
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
                arid_reason=_arid_reason_for(node, ends_the_function),
            )
            out.append(site)

        for inner, inner_exits in _body_blocks(node, ends_the_function):
            _walk_block(
                inner,
                relpath=relpath,
                function_qualname=function_qualname,
                lines=lines,
                out=out,
                block_exits_function=inner_exits,
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


# =============================================================================
# THE CONVICTION LINE
# =============================================================================

#: WHAT WOULD OBSERVE THIS STATEMENT, by the shape of the statement itself.
#:
#: The brief's boundary, verbatim: "A scored check that says 'unobserved
#: statement at aligner.py:87, log_operation table_refused, reached by 20
#: tests, none read the trail' teaches. A percentage does not."
#:
#: So the survivor list is not the product — the sentence is. Each pattern
#: names the assertion that WOULD have killed the mutant, because a builder
#: told only that something is unobserved has to invent the cure themselves,
#: and the round-5 trail gap survived five rounds of exactly that.
#:
#: Matched on the statement's own source line, most specific first. A shape
#: nobody has a sentence for falls through to the generic clause rather than
#: guessing, which is why the last entry matches everything.
OBSERVATION_CLAUSES: Tuple[Tuple[str, str], ...] = (
    (
        r"^json_handler\.log_operation\(\s*['\"](?P<name>[^'\"]+)",
        "an assertion reading the operations trail for '{name}'",
    ),
    (r"^logger\.(?P<level>debug|info|warning|error|critical)\(", "an assertion on the captured log record at {level}"),
    (r"^(console\.print|print)\(\s*\)", "an assertion that the blank separator line is present in captured output"),
    (r"^(console\.print|print)\(", "an assertion on captured stdout containing this line"),
    (r"^(error|_refuse)\(", "an assertion on the refusal reason AND on the exit code"),
    (r"^return\s*$", "an assertion that the call refuses AND that the work it guards did not happen"),
    (r"^(?P<target>[A-Za-z_][\w.]*)\s*(?::[^=]+)?=\s*", "an assertion reaching the branch that reads '{target}'"),
    (r"^(?P<callee>[A-Za-z_][\w.]*)\(", "an assertion on the effect of {callee}()"),
    (r"", "an assertion that reads the effect of this statement"),
)


def _outermost_callee(line: str) -> Optional[str]:
    """The function a call statement actually calls, or None.

    Regex alone reads the FIRST identifier, which is the wrong one the moment
    a call is chained: `Path(temp_name).unlink(missing_ok=True)` is a call to
    `unlink`, and `super().__init__(reason)` to `__init__`. Naming `Path()` in
    a conviction sends the builder to assert on the wrong thing, so the line
    is parsed and the regex kept only for what will not parse.
    """
    try:
        node = ast.parse(line.strip(), mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def observation_clause(source_line: str) -> str:
    """The sentence naming what would have killed this mutant."""
    line = (source_line or "").strip()
    for pattern, clause in OBSERVATION_CLAUSES:
        match = re.match(pattern, line)
        if not match:
            continue
        fields = match.groupdict()
        if "callee" in fields:
            fields["callee"] = _outermost_callee(line) or fields["callee"]
        return clause.format(**fields) if fields else clause
    return OBSERVATION_CLAUSES[-1][1]


def conviction_line(result: StatementResult) -> str:
    """One survivor, in the sentence a builder can act on.

    The count of covering tests is the part that makes it a conviction rather
    than a coverage note: a statement NO test reaches is a coverage fact and
    never appears here, while one that 20 tests execute and none observe is a
    claim about the assertions, which is the species.
    """
    site = result.site
    reached = result.selected_tests
    reach = f"reached by {reached} test{'s' if reached != 1 else ''}" if reached else "reached by the whole suite"
    return (
        f"unobserved statement at {site.relpath}:{site.lineno}, "
        f"{site.source_line.strip()[:CONVICTION_STATEMENT_CHARS]}, "
        f"{reach}, none observe it — {observation_clause(site.source_line)} would"
    )


#: How much of the statement the line quotes before it stops. A conviction is
#: read in a terminal beside others; the address is what a builder navigates by.
CONVICTION_STATEMENT_CHARS = 60


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
        "convictions": [conviction_line(r) for r in observed],
        "convictions_note": (
            "One sentence per UNOBSERVED survivor — a statement at least one test executes and no "
            "test observes. Statements with no covering test are a coverage fact and are counted "
            "separately in `survived_no_covering_test`, never convicted here."
        ),
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
        document.update(_cost_breakdown(campaign, executed))
    json_handler.log_operation("statement_deletion_summarised", {"executed": len(executed)})
    return document


def _cost_breakdown(campaign: StatementCampaign, executed: Sequence[StatementResult]) -> dict:
    """Fixed setup and marginal per-mutant cost, split.

    THE DEFECT THIS REPLACES (devpulse, 2026-09-20). `seconds_per_mutant` was
    the GROUP's elapsed time divided by the mutant count, which silently folds
    one-time setup — env copy, baseline, coverage map — into a number named
    "per mutant". Measured on devpulse: 278.72s over 2 mutants published
    139.36, while the two mutants' own clocks read 0.98s and 1.58s and the
    other 276.16s was setup. I reported that 139 as a per-mutant floor and it
    reached the owner as a projection; it was arithmetic on my own bad metric.

    The honest model is `setup + N x marginal`, so both travel, and the median
    travels beside the mean because a deletion campaign's tail is long: canary
    read a 0.74s median against a 2.14s mean with one mutant at 15.13s.
    """
    own = sorted(result.elapsed_seconds for result in executed)
    mutant_total = sum(own)
    middle = len(own) // 2
    median = own[middle] if len(own) % 2 else (own[middle - 1] + own[middle]) / 2
    return {
        "setup_seconds": round(max(0.0, campaign.elapsed_seconds - mutant_total), 2),
        "mutant_seconds_total": round(mutant_total, 2),
        "seconds_per_mutant_mean": round(mutant_total / len(own), 2),
        "seconds_per_mutant_median": round(median, 2),
        "seconds_per_mutant_max": round(own[-1], 2),
        "cost_model": (
            "elapsed = setup_seconds + sum(mutant_seconds). `setup_seconds` is one-time per run "
            "(env copy, baseline, coverage map) and does NOT scale with the mutant count, so a "
            "cost projection multiplies the MARGINAL figures and adds setup once. Dividing total "
            "elapsed by the mutant count reads as a per-mutant floor and is not one."
        ),
    }
