# =================== AIPass ====================
# Name: inventory.py
# Description: the test-inventory verb - a ranked static report over every test
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
The `test-inventory` verb. Lists every test function in a tree and ranks them
for READING, never for removal.

    drone @seedgo test-inventory aipass          every citizen, one tree
    drone @seedgo test-inventory @backup         one branch
    drone @seedgo test-inventory .               any directory
    drone @seedgo test-inventory aipass --top 40 a longer reading queue

WHY THE FILE IS NOT CALLED `test_inventory.py`. `python_files` collects
`test_*.py`, and `testpaths` includes `src`, so a production module under that
name is imported by pytest on every collection of the fleet. One such module
already exists in this branch and it is a wart, not a precedent worth
extending. The verb keeps its name; the file does not take it.

WHAT THIS VERB IS NOT. It runs nothing, times nothing, and covers nothing - it
reads source and version-control history. It is phase A of the test-governance
plan and it sits OUTSIDE the audit-tests lane on purpose: the lane's Law S7a
refuses a scored non-hygiene group, and that law is right. Folding a ranked
inventory into the lane is a governance decision for phase D, taken with the
fleet-wide distribution in hand - which is the thing this verb produces.

CLAIMING IS EXACT MATCH ONLY. `route_command()` takes the first module
returning truthy in sorted-name order, so a prefix claim would swallow verbs
this module knows nothing about.
"""

import time
from typing import List, Tuple

from aipass.cli import console
from aipass.cli.apps.modules import error, success
from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit import discovery
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.test_inventory import collection, exclusions, history, report, roots, shape

#: Exact tokens this module claims. Never a prefix match.
COMMANDS: tuple = ("test-inventory", "test_inventory")

#: Every option this verb accepts.
FLAGS: tuple = ("--top", "--help", "-h")

#: How many rows the reading queue shows when nobody says otherwise.
DEFAULT_TOP = 15


def handle_command(command: str, args: List[str]) -> bool:
    """Claim `test-inventory` and run it. Returns True once claimed, always.

    The unconditional True is the safety property: an exception escaping here
    is swallowed by the router and reported to the user as an unknown command,
    so a broken verb would look like a verb that was never installed.
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
        logger.error(f"[INVENTORY] the verb failed: {type(exc).__name__}: {exc}")
        error(f"test-inventory failed: {type(exc).__name__}: {exc}")
        console.print("[dim]Nothing was published. This is a tool failure, not a measurement.[/dim]")

    return True


def _run(args: List[str]) -> None:
    """Resolve the target, walk it, publish, and print what happened."""
    argument, top, unrecognized = _parse(args)
    if unrecognized:
        error(f"test-inventory does not know the option '{unrecognized}' - it accepts {', '.join(FLAGS)}")
        return

    root = roots.resolve(argument, _branch_paths())
    json_handler.log_operation("test_inventory_invoked", {"target": argument, "root": str(root.path)})

    started = time.time()
    inventory = _measure(root)
    paths = report.publish(inventory)
    _report(root, inventory, paths, time.time() - started, top)


def _measure(root: roots.Root) -> report.Inventory:
    """The four static passes, in the order each one's input becomes available."""
    console.print(f"[dim]walking {root.path} ({root.resolved_from})[/dim]")
    found = collection.collect(root.path)

    console.print(f"[dim]{len(found.functions)} test functions in {len(found.files)} files, reading exclusions[/dim]")
    statuses = exclusions.classify(root.path, found.files, found.rules.norecursedirs)

    console.print("[dim]one blame per file, in parallel[/dim]")
    blames = history.blame_files(root.path, found.files)

    return report.build(root.path, found, statuses, blames, history.now_seconds())


def _parse(args: List[str]) -> Tuple[str, int, str]:
    """The target, the queue length, and the first token nobody claimed."""
    argument = ""
    top = DEFAULT_TOP
    index = 0

    while index < len(args):
        token = args[index]
        if token == "--top" and index + 1 < len(args):
            top = _positive_int(args[index + 1], top)
            index += 2
            continue
        if token.startswith("-"):
            return argument, top, token
        argument = argument or token
        index += 1

    return argument or roots.FLEET_ARGUMENT, top, ""


def _positive_int(token: str, fallback: int) -> int:
    """A positive integer, or the fallback when the token is not one."""
    return int(token) if token.isdigit() and int(token) > 0 else fallback


def _branch_paths() -> dict:
    """Registered branch name to path, for `@branch` targets."""
    return {branch["name"]: branch["path"] for branch in discovery.discover_branches(include_private=True)}


# =============================================================================
# DISPLAY
# =============================================================================


def _report(root: roots.Root, inventory: report.Inventory, paths: dict, elapsed: float, top: int) -> None:
    """Print the counts, the reading queue, and where the rows went."""
    summary = inventory.summary
    corpus = summary["corpus_definition"]
    shapes = summary["assertion_shape"]

    success(f"test-inventory: {len(inventory.rows)} test functions over {root.name} in {elapsed:.1f}s")
    console.print()
    console.print("[bold cyan]Corpus[/bold cyan]")
    console.print(f"  {corpus['functions_found']} functions in {corpus['files_matched']} files")
    console.print(
        f"  [green]{corpus['functions_that_run']}[/green] run · {corpus['functions_that_never_run']} never do"
    )
    console.print(f"  config: {corpus['config_source']}")
    console.print()
    console.print("[bold cyan]Assertion shape[/bold cyan]")
    for name in (shape.SHAPE_NONE, shape.SHAPE_MOCK_ONLY, shape.SHAPE_REAL):
        console.print(f"  {name:<10} {shapes['counts'].get(name, 0)}")
    console.print(
        f"  [dim]of the assertion-free rows, {shapes['none_with_delegated_oracle']} call a check-shaped "
        f"helper and {shapes['none_with_no_check_of_any_kind']} check nothing at all[/dim]"
    )
    console.print()
    console.print("[bold cyan]Authorship[/bold cyan]")
    for bucket, count in sorted(summary["authorship"]["buckets"].items()):
        console.print(f"  {bucket:<14} {count}")
    console.print()
    _print_queue(summary["top_review_priority"][:top])
    console.print()
    console.print(f"[dim]rows    : {paths['rows']}[/dim]")
    console.print(f"[dim]summary : {paths['summary']}[/dim]")
    console.print(f"[dim]readable: {paths['readable']}[/dim]")
    console.print()
    console.print("[bold cyan]What the score means[/bold cyan]")
    console.print(f"  [dim]{summary['ranking']['means']}[/dim]")


def _print_queue(queue: List[dict]) -> None:
    """The highest review priorities, in order."""
    console.print("[bold cyan]Read these first[/bold cyan]")
    for position, row in enumerate(queue, start=1):
        console.print(
            f"  {position:>3}. [yellow]{row['review_priority']:.3f}[/yellow] "
            f"{row['assertion_shape']:<10} {row['nodeid']}"
        )


def _print_help() -> None:
    """What the verb does, what it refuses to do, and how to call it."""
    console.print()
    console.print("[bold cyan]seedgo test-inventory[/bold cyan] - every test function, ranked for READING")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  drone @seedgo test-inventory aipass            every citizen, one tree")
    console.print("  drone @seedgo test-inventory @backup           one branch")
    console.print("  drone @seedgo test-inventory .                 any directory")
    console.print("  drone @seedgo test-inventory aipass --top 40   a longer reading queue")
    console.print()
    console.print("[yellow]Measures[/yellow]")
    console.print("  assertion shape (NONE / MOCK_ONLY / REAL), age and author from blame,")
    console.print("  how many tests share the file and the class, and identically-shaped siblings.")
    console.print()
    console.print("[yellow]Refuses[/yellow]")
    console.print("  it runs no tests, measures no coverage, and issues no verdict.")
    console.print("  the score orders a reading queue and authorises nothing.")
    console.print()


def print_introspection() -> None:
    """What this verb is, shown when it is called with no arguments."""
    console.print()
    console.print("[bold cyan]test-inventory[/bold cyan] — every test function, ranked for READING")
    console.print()
    console.print("  Walks a tree statically and publishes one row per test function:")
    console.print("  assertion shape, age, author, neighbours, and a composite priority")
    console.print("  with every component left visible so a reader can re-sort it.")
    console.print()
    console.print("[yellow]Columns[/yellow]")
    console.print("  assertion_shape    NONE / MOCK_ONLY / REAL — the one published signal")
    console.print("  age_days           from one blame per file; a LOWER bound, never exact")
    console.print("  author_bucket      a declared table; unknown names go to OTHER, not human")
    console.print("  twins_in_class     identically-shaped siblings — marked WEAK in every row")
    console.print("  review_priority    a reading order. It authorises nothing.")
    console.print()
    console.print("[dim]Phase A of the test-governance plan: static only, outside the audit-tests lane.[/dim]")
    console.print("[dim]Run 'drone @seedgo test-inventory --help' for usage.[/dim]")
    console.print()
