# =================== AIPass ====================
# Name: audit_tests.py
# Description: the audit-tests verb - execution-tier test quality measurement
# Version: 1.1.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""The `audit-tests` verb. Measures how much a test suite proves, by running it.

Exact-match claims only (a prefix on "audit" would swallow the audit verb in sorted
routing); once claimed every failure is caught here. A refusal leaves with its own
exit code; a failed score exits 0, because this lane advises and does not gate.
"""

from typing import Dict, List, NoReturn

from aipass.cli import console
from aipass.cli.apps.modules import error, success, warning
from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit_tests import refusal, render, runner
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.tests_pytest_standards import diff_scope
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.modules import CommandRefused

COMMANDS: tuple = ("audit-tests", "audit_tests")

#: One table read by both the parser and the did-you-mean, so they cannot drift (Law ARGV).
#: Never on by default: each costs whole extra suite executions.
OPT_IN_GROUP_FLAGS: Dict[str, str] = {
    "--pseudo-tested": "pseudo_tested",
    "--width-coupling": "width_coupling",
    "--statement-deletion": "statement_deletion",
}

#: Travels to `adapter.build_env()` and onto the EnvSpec that `nominate()` reads.
OPTION_EXECUTION_GROUPS = "execution_groups"

#: A scope over a campaign, not a campaign: alone it is refused, since it measures nothing.
DIFF_SCOPE_FLAG = "--diff-scope"

LANE_FLAGS: tuple = (
    "--budget",
    "--prove-refusal",
    "--symlink-siblings",
    "--no-tmpdir-allowance",
    DIFF_SCOPE_FLAG,
    *OPT_IN_GROUP_FLAGS,
    "--help",
    "-h",
)

#: The verb one keystroke away from this one, in the other direction.
SIBLING_VERBS: tuple = ("audit",)


def handle_command(command: str, args: List[str]) -> bool:
    """Claim `audit-tests` and run it. Returns True once claimed, always.

    An escaping exception would be reported by the router as an unknown command.
    """
    if command not in COMMANDS:
        return False

    if not args:
        print_introspection()
        return True

    if wants_help(None, args):
        _print_help()
        return True

    try:
        _run(args)
    except CommandRefused:
        # A refusal is not a crash: the generic handler below would replace its code with EXIT_UNPROVEN.
        raise
    except Exception as exc:
        logger.error(f"[AUDIT-TESTS] the lane failed: {type(exc).__name__}: {exc}")
        error(f"audit-tests failed: {type(exc).__name__}: {exc}")
        console.print("[dim]No artifact was written. This is a lane failure, not a measurement.[/dim]")
        # Exiting 0 here would report the crash as a run.
        raise CommandRefused(refusal.EXIT_UNPROVEN, "audit-tests")

    return True


def _run(args: List[str]) -> None:
    """Parse the arguments, run every target, print what happened."""
    argument, options, unrecognized = _parse(args)
    if unrecognized:
        # Before the missing-target message: the stray token may be the target, misspelt.
        _refuse_unknown_argument(unrecognized[0], args)
    if not argument:
        error("audit-tests needs a target: @branch, a directory, or 'aipass' for every citizen")
        raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, "audit-tests with no target")
    if options.get("scope_to_diff") and not options.get(OPTION_EXECUTION_GROUPS):
        error(f"{DIFF_SCOPE_FLAG} narrows a mutation campaign; on its own it measures nothing")
        console.print(f"[dim]add a group: {' '.join(sorted(OPT_IN_GROUP_FLAGS))}[/dim]")
        raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, f"{DIFF_SCOPE_FLAG} with no execution group")

    json_handler.log_operation("lane_invoked", {"target": argument, "options": sorted(options)})
    results, worst = runner.run(argument, options)
    _report(results, worst)
    if worst in refusal.REFUSAL_CODES:
        # Refusals only: EXIT_SCORED_FAILED stays 0, this lane advises.
        raise CommandRefused(worst, argument)


def _refuse_unknown_argument(token: str, args: List[str]) -> NoReturn:
    """Refuse a token this verb never claimed, print the fix, and carry the code out (Law ARGV)."""
    refused = refusal.refusal_for_unknown_argument(
        token,
        refusal.suggested_command(token, "audit-tests", args, LANE_FLAGS, SIBLING_VERBS),
        "audit-tests",
    )
    error(refused.stdout_line())
    console.print(f"[dim]law: {refused.law}   exit code: {refused.code}[/dim]")
    for line in refused.detail:
        console.print(f"  [dim]{line}[/dim]")
    raise CommandRefused(refused.code, token)


def _parse(args: List[str]) -> tuple:
    """Split the argument list into `(target, options, unrecognized)`.

    Unknown tokens are collected in the one loop that knows what the verb accepts (Law ARGV).
    """
    options: dict = {}
    unrecognized: List[str] = []
    target = ""
    index = 0

    while index < len(args):
        token = args[index]
        if token == "--budget":
            # A trailing bare '--budget' keeps the default: the flag is known, only its value is missing.
            options["budget_seconds"] = _as_int(args[index + 1] if index + 1 < len(args) else "")
            index += 2
            continue
        if token == "--prove-refusal":
            options["prove_refusal"] = True
            index += 1
            continue
        if token == "--symlink-siblings":
            options["symlink_siblings"] = True
            index += 1
            continue
        if token == "--no-tmpdir-allowance":
            options["no_tmpdir_allowance"] = True
            index += 1
            continue
        if token == DIFF_SCOPE_FLAG or token.startswith(f"{DIFF_SCOPE_FLAG}="):
            # The ref is attached (`=HEAD~1`), never positional, so it cannot swallow the target.
            options["scope_to_diff"] = True
            _, _, ref = token.partition("=")
            options["diff_scope_ref"] = ref or None
            index += 1
            continue
        if token in OPT_IN_GROUP_FLAGS:
            # Append, not assign: two flags ask for both campaigns.
            _request_execution_group(options, OPT_IN_GROUP_FLAGS[token])
            index += 1
            continue
        if not token.startswith("-"):
            # One target per run; `aipass` is the fleet form.
            if target:
                unrecognized.append(token)
            else:
                target = token
            index += 1
            continue
        unrecognized.append(token)
        index += 1

    return target, options, unrecognized


def _request_execution_group(options: dict, group: str) -> None:
    """Add one opt-in execution group to the request, once."""
    requested = options.setdefault(OPTION_EXECUTION_GROUPS, [])
    if group not in requested:
        requested.append(group)


def _as_int(raw: str) -> int:
    """A budget in seconds, or the default when the token is not a number."""
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"[AUDIT-TESTS] --budget {raw!r} is not a number; using the default")
        return runner.DEFAULT_BUDGET_SECONDS


def _report(results: list, worst: int) -> None:
    """Print each target's full report, then the fleet summary.

    A fleet gets one line per target: full reports would scroll the first ones off the screen.
    """
    if len(results) == 1:
        result = results[0]
        render.render_target(result.document, str(result.path))
    else:
        console.print()
        for result in results:
            _summary_line(result)

    console.print()
    console.print(f"[dim]worst exit code: {worst} (a shell hint - the artifact carries the verdict)[/dim]")

    scored = [r for r in results if not r.refused]
    if scored:
        console.print("[dim]hygiene is the only scored group. SCORED is not GATING: this blocks nothing.[/dim]")
        console.print("[dim]Every other group reports not_applicable with a reason, never 0.[/dim]")
        if len(results) > 1:
            _print_nomination_totals(scored)
            _print_blind_spots(scored)


def _summary_line(result) -> None:
    """One target's line, styled by what happened to it."""
    if result.refused:
        error(result.summary_line())
    elif result.document.get("groups", {}).get("hygiene", {}).get("score") == 100:
        success(result.summary_line())
    else:
        warning(result.summary_line())


def _print_nomination_totals(scored: list) -> None:
    """The static tier's totals per species group, across every target.

    Printed even at zero: a tier that prints nothing looks like a tier that did not run.
    """
    totals: dict = {}
    for result in scored:
        for name in result.document.get("group_list", []):
            group = result.document.get("groups", {}).get(name, {})
            if group.get("kind") != "nominate_only" or group.get("status") != "measured":
                continue
            totals[name] = totals.get(name, 0) + int(group.get("nomination_count", 0))

    if not totals:
        return

    console.print()
    console.print("[bold cyan]Static tier[/bold cyan] [dim](nominations - never scored, never verdicts: Law M1)[/dim]")
    for name in sorted(totals):
        console.print(f"  [dim]{name:34} {totals[name]} nomination(s)[/dim]")


def _print_blind_spots(scored: list) -> None:
    """State what the gate could not see, beside the number it produced.

    Law S8: a bare 100 reads as clean; beside the unwatched counts it reads as none seen.
    """
    for result in scored:
        coverage = result.document.get("groups", {}).get("hygiene", {}).get("gate_coverage", {})
        if not coverage:
            continue
        children = coverage.get("child_processes_spawned", 0)
        databases = coverage.get("sqlite3_connections", {}).get("file_backed", 0)
        if children or databases:
            warning(
                f"{result.target.name}: {children} child process(es) and {databases} file-backed "
                f"sqlite3 handle(s) wrote where this gate cannot follow"
            )


def print_introspection() -> None:
    """What this verb is, shown when it is called with no arguments."""
    console.print()
    console.print("[bold cyan]audit-tests[/bold cyan] — execution-tier test quality")
    console.print()
    console.print("  Runs a target's suite inside a COPY, under a filesystem write gate,")
    console.print("  and refuses to publish anything unless a planted canary proves the")
    console.print("  gate could have fired.")
    console.print()
    console.print("[yellow]Groups[/yellow]")
    console.print("  hygiene            the only SCORED group - 100 or 0, never a percentage")
    console.print("  oracle_execution   not built; reports not_applicable with a reason")
    console.print("  order_dependence   not built; reports not_applicable with a reason")
    console.print("  ai_advisory        nominate-only, never scored")
    console.print()
    console.print("[yellow]Opt-in groups[/yellow] [dim](BUILT; they cost wall clock, so you have to ask)[/dim]")
    console.print("  pytest.pseudo_tested    --pseudo-tested    one mutant per function; hours on a branch")
    console.print("  pytest.width_coupling   --width-coupling   the suite at two widths, verdicts diffed")
    console.print("  pytest.statement_deletion --statement-deletion  one statement removed at a time")
    console.print()
    console.print("[dim]Unasked-for, both report not_applicable saying they are AVAILABLE, not unbuilt.[/dim]")
    console.print("[dim]SCORED is not GATING: this blocks nothing at launch.[/dim]")
    console.print("[dim]Run 'drone @seedgo audit-tests --help' for usage.[/dim]")
    console.print()


def _print_help() -> None:
    """The verb's own help."""
    console.print()
    console.print("[bold cyan]audit-tests[/bold cyan] — execution-tier test quality")
    console.print()
    console.print("  drone @seedgo audit-tests @branch          measure one branch")
    console.print("  drone @seedgo audit-tests <directory>      measure any directory")
    console.print("  drone @seedgo audit-tests aipass           measure every citizen")
    console.print()
    console.print("[yellow]Options[/yellow]")
    console.print("  --budget <seconds>        wall-clock budget per target (Law T-BUDGET)")
    console.print("  --prove-refusal           run with the gate OFF; the run must REFUSE")
    console.print("  --symlink-siblings        faster, and stamps m10_complete: false")
    console.print("  --no-tmpdir-allowance     treat TMPDIR writes as violations too")
    console.print("  --width-coupling          run the suite at two widths and diff the verdicts")
    console.print("  --pseudo-tested           gut one function at a time; HOURS on a real branch")
    console.print("  --statement-deletion      delete one statement at a time; the most expensive group")
    console.print("  --diff-scope[=<ref>]      narrow the mutants to CHANGED LINES; needs a group")
    console.print()
    console.print("[dim]All three opt-in groups are BUILT. They are off by default because they cost[/dim]")
    console.print("[dim]whole extra suite runs, not because anything about them is unfinished.[/dim]")
    console.print("[dim]--diff-scope is a SCOPE, not a group: it probes the changed lines of the[/dim]")
    console.print("[dim]working tree, or of the commit <ref> names. A clean diff-scoped run says[/dim]")
    console.print("[dim]nothing about the statements it did not probe - every limit it has travels[/dim]")
    console.print(
        f"[dim]in the artifact ({len(diff_scope.SCOPE_LIMITS)} of them today), including that the working-tree[/dim]"
    )
    console.print("[dim]form sees the CALLER's branch only, so cross-branch scoping takes a ref.[/dim]")
    console.print("[dim]The suite runs against a COPY. Nothing writes to the real target.[/dim]")
    console.print("[dim]A run that cannot prove its own gate can fire publishes NOTHING.[/dim]")
    console.print()
