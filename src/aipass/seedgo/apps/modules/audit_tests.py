# =================== AIPass ====================
# Name: audit_tests.py
# Description: the audit-tests verb - execution-tier test quality measurement
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The `audit-tests` verb. Measures how much a test suite proves, by running it.

CLAIMING IS EXACT MATCH ONLY, and never a prefix. `route_command()` takes the
first module returning truthy and iterates in sorted-name order, where
`audit_tests.py` sorts BEFORE `standards_audit.py` — so a prefix claim on
"audit" would silently swallow the audit verb entirely.

CLAIM BEFORE YOU WORK. `route_command()` catches any exception a module raises
and continues to the next module; if nothing claims, the user is told "Unknown
command". A crash in this lane would therefore be INDISTINGUISHABLE FROM THE
VERB NOT EXISTING. So the command is recognised, the claim is set, and
everything after it is wrapped — this function returns True unconditionally
once it has claimed.

    drone @seedgo audit-tests @backup             one branch
    drone @seedgo audit-tests .                   the current directory
    drone @seedgo audit-tests /path/to/project    not an aipass branch at all
    drone @seedgo audit-tests aipass              every citizen
    drone @seedgo audit-tests @backup --budget 300
    drone @seedgo audit-tests @backup --prove-refusal    canary point C

THE EXIT CODE IS A SHELL CONVENIENCE, NEVER THE VERDICT. `seedgo.py` returns 0
whenever a route returns truthy, and drone flattens non-zero to a boolean, so
a consumer reading only the exit code CANNOT tell a refusal from a pass. The
artifact's `status` field and the `REFUSED:` line printed here are the
load-bearing signals.
"""

from typing import List

from aipass.cli import console
from aipass.cli.apps.modules import error, success, warning
from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit_tests import refusal, render, runner
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.json import json_handler

#: Exact tokens this module claims. Never a prefix match.
COMMANDS: tuple = ("audit-tests", "audit_tests")

#: Every option this verb accepts, for the did-you-mean a stray token gets.
LANE_FLAGS: tuple = (
    "--budget",
    "--prove-refusal",
    "--symlink-siblings",
    "--no-tmpdir-allowance",
    "--help",
    "-h",
)

#: The verb one keystroke away from this one, in the other direction.
SIBLING_VERBS: tuple = ("audit",)


def handle_command(command: str, args: List[str]) -> bool:
    """Claim `audit-tests` and run it. Returns True once claimed, always.

    The unconditional True is the whole safety property: an exception escaping
    here would be swallowed by the router and reported to the user as an
    unknown command, so a broken lane would look like a lane that was never
    installed.
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
    except Exception as exc:
        logger.error(f"[AUDIT-TESTS] the lane failed: {type(exc).__name__}: {exc}")
        error(f"audit-tests failed: {type(exc).__name__}: {exc}")
        console.print("[dim]No artifact was written. This is a lane failure, not a measurement.[/dim]")

    return True


def _run(args: List[str]) -> None:
    """Parse the arguments, run every target, print what happened."""
    argument, options, unrecognized = _parse(args)
    if unrecognized:
        # Before the missing-target message, because a token nobody read is the
        # more specific fact: it may well BE the target, misspelt.
        _refuse_unknown_argument(unrecognized[0], args)
        return
    if not argument:
        error("audit-tests needs a target: @branch, a directory, or 'aipass' for every citizen")
        return

    json_handler.log_operation("lane_invoked", {"target": argument, "options": sorted(options)})
    results, worst = runner.run(argument, options)
    _report(results, worst)


def _refuse_unknown_argument(token: str, args: List[str]) -> None:
    """Refuse a token this verb never claimed, and print the fix (Law ARGV).

    The same five lines as the audit verb's, deliberately: display belongs to
    the verb, and a handler that printed for both would be a handler carrying a
    console. The rule they share is the refusal vocabulary, not the rendering.
    """
    refused = refusal.refusal_for_unknown_argument(
        token,
        refusal.suggested_command(token, "audit-tests", args, LANE_FLAGS, SIBLING_VERBS),
        "audit-tests",
    )
    error(refused.stdout_line())
    console.print(f"[dim]law: {refused.law}   exit code: {refused.code}[/dim]")
    for line in refused.detail:
        console.print(f"  [dim]{line}[/dim]")


def _parse(args: List[str]) -> tuple:
    """Split the argument list into `(target, options, unrecognized)`.

    The third element is Law ARGV's whole mechanism: unknown tokens are
    COLLECTED HERE, in the one loop that already knows what this verb accepts,
    rather than screened by a second list that could drift out of step with it.
    A token this loop does not claim is a token nobody claimed.
    """
    options: dict = {}
    unrecognized: List[str] = []
    target = ""
    index = 0

    while index < len(args):
        token = args[index]
        if token == "--budget":
            # A trailing '--budget' with nothing after it keeps the default and
            # says so, rather than being refused as an argument nobody knows —
            # the flag IS known; only its value is missing.
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
        if not token.startswith("-"):
            # One target per run: `runner.run()` takes a single argument, so a
            # second bare word names nothing. `aipass` is the fleet form.
            if target:
                unrecognized.append(token)
            else:
                target = token
            index += 1
            continue
        unrecognized.append(token)
        index += 1

    return target, options, unrecognized


def _as_int(raw: str) -> int:
    """A budget in seconds, or the default when the token is not a number."""
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"[AUDIT-TESTS] --budget {raw!r} is not a number; using the default")
        return runner.DEFAULT_BUDGET_SECONDS


def _report(results: list, worst: int) -> None:
    """Print each target's full report, then the fleet summary.

    ONE TARGET GETS THE FULL RENDER; A FLEET GETS ONE LINE EACH. Eighteen full
    reports scroll the first seventeen off the screen, and a summary a reader
    cannot see is a summary that did not happen. Either way the per-target line
    prints for EVERY target regardless of the fleet code, so the single number
    is never the only signal a caller has.
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
            # The single-target path already printed every group with its own
            # count, so repeating the totals here would say the same thing
            # twice on one screen. A fleet run has no such render and needs it.
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

    Printed even when the total is zero, and SAYING it is zero. A tier that
    prints nothing when it finds nothing is indistinguishable from a tier that
    did not run, which is Law S1 applied to the terminal.
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

    Law S8 in its rendered form. A score of 100 printed alone reads as "this
    suite is clean"; printed beside the count of child processes and sqlite
    handles nobody watched, it reads as what it is — no violation SEEN.
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
    console.print()
    console.print("[dim]The suite runs against a COPY. Nothing writes to the real target.[/dim]")
    console.print("[dim]A run that cannot prove its own gate can fire publishes NOTHING.[/dim]")
    console.print()
