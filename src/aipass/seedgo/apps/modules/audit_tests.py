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
from aipass.seedgo.apps.handlers.audit_tests import runner
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.json import json_handler

#: Exact tokens this module claims. Never a prefix match.
COMMANDS: tuple = ("audit-tests", "audit_tests")


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
    argument, options = _parse(args)
    if not argument:
        error("audit-tests needs a target: @branch, a directory, or 'aipass' for every citizen")
        return

    json_handler.log_operation("lane_invoked", {"target": argument, "options": sorted(options)})
    results, worst = runner.run(argument, options)
    _report(results, worst)


def _parse(args: List[str]) -> tuple:
    """Split the argument list into `(target, options)`."""
    options: dict = {}
    target = ""
    index = 0

    while index < len(args):
        token = args[index]
        if token == "--budget" and index + 1 < len(args):
            options["budget_seconds"] = _as_int(args[index + 1])
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
        if not token.startswith("-") and not target:
            target = token
        index += 1

    return target, options


def _as_int(raw: str) -> int:
    """A budget in seconds, or the default when the token is not a number."""
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"[AUDIT-TESTS] --budget {raw!r} is not a number; using the default")
        return runner.DEFAULT_BUDGET_SECONDS


def _report(results: list, worst: int) -> None:
    """Print one line per target, then the run's own caveats.

    A per-target line prints for EVERY target regardless of the fleet code, so
    the single number is never the only signal. A refusal prints its law and
    its reason, because a refusal nobody can act on is barely better than a
    wrong number.
    """
    console.print()
    for result in results:
        if result.refused:
            error(result.summary_line())
        elif result.document.get("groups", {}).get("hygiene", {}).get("score") == 100:
            success(result.summary_line())
        else:
            warning(result.summary_line())

    console.print()
    console.print(f"[dim]worst exit code: {worst} (a shell hint - the artifact carries the verdict)[/dim]")

    scored = [r for r in results if not r.refused]
    if scored:
        console.print("[dim]hygiene is the only scored group. SCORED is not GATING: this blocks nothing.[/dim]")
        console.print("[dim]Every other group reports not_applicable with a reason, never 0.[/dim]")
        _print_blind_spots(scored)


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
