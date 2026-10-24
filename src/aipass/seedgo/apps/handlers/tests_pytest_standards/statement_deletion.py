# =================== AIPass ====================
# Name: statement_deletion.py
# Description: delete one statement at a time and report which deletions the suite does not notice
# Version: 1.1.1
# Created: 2026-09-20
# Modified: 2026-10-24
# =============================================

"""One statement at a time, not the whole body.

`gutting` cannot isolate an unobserved STATEMENT inside an otherwise tested
function. This finds code that is documented as doing something, executes, and
no test observes. Only SIMPLE statements are deleted (a compound header is branch
deletion, enforced in `_is_deletable_kind`). Cost needs `mutation_selection`'s
coverage map, narrowed to the statement's own lines. Every arid suppression is a
statement whose deletion cannot change behaviour; logging, telemetry and trail
calls are never suppressed, they are the species this operator finds.
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

#: Fills a block whose only statement was deleted: an empty block is a SyntaxError, not a mutant.
EMPTY_BLOCK_FILLER = "pass"

#: Outcomes, spelled exactly as `gutting` spells them so one reader serves both.
OUTCOME_SURVIVED = gutting.OUTCOME_SURVIVED
OUTCOME_KILLED = gutting.OUTCOME_KILLED
OUTCOME_SKIPPED = gutting.OUTCOME_SKIPPED
OUTCOME_NOT_RUN = gutting.OUTCOME_NOT_RUN
OUTCOME_MUTATION_FAILED = gutting.OUTCOME_MUTATION_FAILED

#: Deleting a loop advance (`index += 1`) makes a mutant that never returns, so the
#: hang ceiling scales with the target's own baseline rather than a fixed number.
HANG_TIMEOUT_FLOOR_SECONDS = 10

#: An unmapped statement runs the whole suite, so its honest cost IS one baseline;
#: doubling separates a slow mutant from a hang at the cost of one extra baseline.
HANG_TIMEOUT_BASELINE_MULTIPLIER = 2


def hang_timeout(baseline_seconds: float) -> int:
    """The per-mutant ceiling for this target, from its own baseline."""
    scaled = int(baseline_seconds * HANG_TIMEOUT_BASELINE_MULTIPLIER)
    return max(HANG_TIMEOUT_FLOOR_SECONDS, scaled or HANG_TIMEOUT_FLOOR_SECONDS)


REASON_NO_COVERING_TEST = gutting.REASON_NO_COVERING_TEST
REASON_BUDGET_EXHAUSTED = gutting.REASON_BUDGET_EXHAUSTED
REASON_MUTANT_NOT_PARSEABLE = gutting.REASON_MUTANT_NOT_PARSEABLE

#: Arid nodes: deletion cannot change behaviour. Each is published with a count and its reason.
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

#: Real statements this operator cannot mutate soundly; counted apart from arid (chose not vs could not).
REASON_COMPOUND_HEADER = "compound_header_is_branch_deletion"
REASON_NO_LINE_RANGE = "no_line_range"
REASON_UNPARSABLE_SOURCE = gutting.REASON_UNPARSABLE_SOURCE

#: No compound statement here: deleting one is branch deletion. Control-flow statements
#: are here because their effect on control flow is exactly the point.
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

    The span is the statement's own, which narrows test selection below gutting's.
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
        """The shape `mutation_selection` reads, spanning this statement only."""
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


def _is_bare_string(node: ast.stmt) -> bool:
    """Whether this is a bare string expression, wherever it sits.

    Any position: a lone string literal is discarded anywhere; only the leading one binds `__doc__`.
    """
    if not isinstance(node, ast.Expr):
        return False
    return isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _arid_reason_for(node: ast.stmt, ends_the_function: bool) -> Optional[str]:
    """Why deleting this statement could not change behaviour, or None.

    `ends_the_function` is the whole guard on the `return` case; see `_walk_block`.
    """
    if _is_bare_string(node):
        return ARID_DOCSTRING
    if isinstance(node, ast.Pass):
        return ARID_PASS
    if gutting._is_ellipsis(node):
        return ARID_ELLIPSIS
    if ends_the_function and gutting._is_bare_none_return(node):
        return ARID_SOLE_RETURN_NONE
    return None


#: Not descended into: `discover_statements` reaches nested defs via `ast.walk`, so
#: descending here too would emit each nested statement twice.
_SCOPE_NODES: tuple = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

#: Loop nodes whose `body` re-enters: reaching the end of one starts the next
#: iteration, so a deleted `return` there does not end the function.
_LOOP_NODES: tuple = (ast.For, ast.AsyncFor, ast.While)


def _child_block_exits(node: ast.stmt, name: str, parent_exits: bool) -> bool:
    """Whether reaching the end of `node.<name>` ends the enclosing function.

    A loop `body`, a `finalbody`, and a `try` body with an `else` each take that answer
    away: deleting a `return` there continues, un-swallows, or runs the `else`.
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

    `block_exits_function`: a trailing bare `return` equals falling off the end only
    when the block's end ends the function; a `return` last in an `if` is a guard clause.
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

    Arid statements are returned with their reason, so the denominator stays honest.
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


def delete_statement(source: str, site: StatementSite) -> Optional[str]:
    """`source` with this statement removed, or None when it cannot be.

    A text splice, never `ast.unparse`: the rest of the file stays byte-identical, which
    keeps a kill attributable and coverage selection sound.
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
        # Compiled before writing: an engine bug must never reach the suite as a perfect kill.
        logger.info("statement_deletion: %s:%s did not compile after deletion: %s", site.relpath, site.lineno, e)
        return None, REASON_MUTANT_NOT_PARSEABLE
    return mutant, None


def probeable(sites: Sequence[StatementSite]) -> List[StatementSite]:
    """The statements a campaign will actually run — not arid, not skipped."""
    return [s for s in sites if s.skip_reason is None and s.arid_reason is None]


def _selection_for(site: StatementSite, coverage_map: CoverageMap) -> Selection:
    """Which tests can reach THIS statement."""
    return select_tests(site.as_function_site(), coverage_map)


def _probe(
    target: SuiteTarget,
    site: StatementSite,
    selection: Selection,
    timeout_seconds: int,
    capped: bool = False,
) -> StatementResult:
    """Write the mutant, run the selected tests, restore the file.

    `capped`: the remaining budget, not the hang ceiling, set this timeout.
    """
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
            reason=REASON_BUDGET_EXHAUSTED if capped else gutting.REASON_MUTANT_TIMEOUT,
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

    The baseline is the coverage run: map and baseline must come from one execution.
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
        results.append(_probe(target, site, selection, timeout, capped=timeout < ceiling))

    return StatementCampaign(
        baseline=base,
        results=results,
        elapsed_seconds=time.monotonic() - started,
        budget_seconds=budget_seconds,
        mutant_timeout_seconds=ceiling,
        coverage_map=coverage_map,
    )


def _count_by(values: Sequence[Optional[str]]) -> Dict[str, int]:
    """A count per distinct non-None value."""
    counts: Dict[str, int] = {}
    for value in values:
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    return counts


#: One survivor out of one is a statement finding, not evidence about the function.
ROLLUP_MIN_STATEMENTS = 2


#: The assertion that would have killed each mutant, by statement shape. Matched most
#: specific first; the last entry matches everything so nothing is guessed.
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

    Parsed, not regexed: a regex reads the first identifier of a chained call.
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

    A statement no test reaches is a coverage fact and never appears here.
    """
    site = result.site
    reached = result.selected_tests
    reach = f"reached by {reached} test{'s' if reached != 1 else ''}" if reached else "reached by the whole suite"
    return (
        f"unobserved statement at {site.relpath}:{site.lineno}, "
        f"{site.source_line.strip()[:CONVICTION_STATEMENT_CHARS]}, "
        f"{reach}, none observe it — {observation_clause(site.source_line)} would"
    )


CONVICTION_STATEMENT_CHARS = 60


def _survivor_rollup(campaign: StatementCampaign) -> dict:
    """Collapse whole-function survivor blocks into one row each.

    A reporting collapse, never a suppression: every mutant stays in `mutants[]`.
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

    Elapsed over mutant count folds one-time setup into "per mutant"; the honest model
    is `setup + N x marginal`, with the median beside the mean for the long tail.
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
