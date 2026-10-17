# =================== AIPass ====================
# Name: shadow_cycle.py
# Description: the weekly shadow cycle - three fleet measurements, one document, one mail
# Version: 1.0.0
# Created: 2026-09-02
# Modified: 2026-10-17
# =============================================

"""
The `shadow-cycle` verb. Runs the three weekly measurement passes back to back
and mails ONE screen of headline counts and artifact paths.

Three passes in one run are a cross-section; taken a week apart they are unrelated readings.
`run` is required: the cycle walks every branch three times, and a bare call only describes a verb.
The mail is an email, never a dispatch (a weekly reading must not wake a citizen), and carries artifact paths.
The fleet container comes from `inventory`, never re-derived: the registry is machine-local, absent on a fresh checkout.
"""

import time
from typing import List, Tuple

from aipass.cli import console
from aipass.cli.apps.modules import error, success
from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit import discovery
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.audit_tests import refusal
from aipass.seedgo.apps.modules import CommandRefused
from aipass.seedgo.apps.handlers.shadow_cycle import cycle, mail, score
from aipass.seedgo.apps.handlers.test_inventory import report, roots, twins
from aipass.seedgo.apps.modules import inventory

#: Never a prefix: `route_command` takes the first truthy module, so a prefix claim swallows other verbs.
COMMANDS: tuple = ("shadow-cycle", "shadow_cycle")

FLAGS: tuple = ("--no-mail", "--help", "-h")

RUN_TOKEN = "run"

#: The one thing about this cycle a future ruling is expected to change.
SHADOW_PACK = "pytest_quality"

RECIPIENT = "@devpulse"


def handle_command(command: str, args: List[str]) -> bool:
    """Claim `shadow-cycle` and run it. Returns True once claimed, always.

    An exception escaping here is swallowed by the router as an unknown command, so a broken verb would look uninstalled.
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
        logger.error(f"[SHADOW_CYCLE] the cycle failed: {type(exc).__name__}: {exc}")
        error(f"shadow-cycle failed: {type(exc).__name__}: {exc}")
        console.print("[dim]No cycle document was published and no mail was sent.[/dim]")
        raise CommandRefused(refusal.EXIT_UNPROVEN, "shadow-cycle")

    return True


def _run(args: List[str]) -> None:
    """Parse, run the three passes, publish the document, mail the screen."""
    wants_run, no_mail, unrecognized = _parse(args)
    if unrecognized:
        error(f"shadow-cycle does not know the option '{unrecognized}' - it accepts {', '.join(FLAGS)}")
        return
    if not wants_run:
        _refuse_bare_flags()
        return

    json_handler.log_operation("shadow_cycle_invoked", {"pack": SHADOW_PACK, "mail": not no_mail})

    started = time.time()
    scored = _score_pass()
    measured = _inventory_pass()
    twinned = _twins_pass()

    document = cycle.build(scored, measured, twinned, time.time() - started)
    published = cycle.publish(document)
    body = cycle.one_screen(document)

    _report(document, body, published)
    _deliver(document, body, no_mail)


def _score_pass() -> dict:
    """Pass 1 - the v5 shadow score over every registered branch."""
    console.print()
    console.print(f"[bold cyan]1/3[/bold cyan] [dim]scoring {SHADOW_PACK} over the fleet - shadow, gates nothing[/dim]")
    branches = discovery.discover_branches()
    console.print(f"[dim]{len(branches)} branches, one checker pack, no threshold[/dim]")
    return score.run(SHADOW_PACK, branches, cycle.score_artifact_path(SHADOW_PACK), on_branch=_score_line)


def _inventory_pass() -> dict:
    """Pass 2 - the ranked test inventory over the whole fleet.

    `inventory._measure` is called, not copied: a second spelling would be a second definition of the inventory.
    """
    console.print()
    console.print("[bold cyan]2/3[/bold cyan] [dim]the ranked test inventory[/dim]")
    root = roots.resolve(roots.FLEET_ARGUMENT)
    built = inventory._measure(root)
    return cycle.inventory_block(built.summary, report.publish(built))


def _twins_pass() -> dict:
    """Pass 3 - cross-branch twins over the directory the branches live in."""
    console.print()
    console.print("[bold cyan]3/3[/bold cyan] [dim]cross-branch twins, keyed on shape[/dim]")
    container = inventory._fleet_container()
    console.print(f"[dim]walking {container}[/dim]")
    built = twins.build(container)
    return cycle.twins_block(built, twins.publish(built))


def _deliver(document: dict, body: str, no_mail: bool) -> None:
    """Email the one screen, or say plainly that nothing was sent."""
    if no_mail:
        console.print(f"[dim]--no-mail: nothing was sent. {RECIPIENT} would have received the screen above.[/dim]")
        return

    if mail.send(RECIPIENT, cycle.subject(document), body):
        success(f"emailed to {RECIPIENT}")
        return

    error(f"the cycle ran and published, but the email to {RECIPIENT} did not go out")
    console.print("[dim]Every artifact above is on disk. Check the prax log for the send failure.[/dim]")


def _parse(args: List[str]) -> Tuple[bool, bool, str]:
    """Whether to run, whether to stay quiet, and the first token nobody claimed."""
    wants_run = False
    no_mail = False

    for token in args:
        if token == RUN_TOKEN:
            wants_run = True
            continue
        if token == "--no-mail":
            no_mail = True
            continue
        return wants_run, no_mail, token

    return wants_run, no_mail, ""


def _score_line(result: dict) -> None:
    """One branch's shadow score, printed as it lands."""
    average = result.get("average", 0)
    style = "green" if average >= score.ATTENTION_BELOW else "yellow"
    console.print(f"  [cyan]{result['branch']['name']:<12}[/cyan] [{style}]{average:>3}%[/{style}]")


def _refuse_bare_flags() -> None:
    """Say why nothing happened, and print the two commands that do happen."""
    error(f"shadow-cycle needs the word '{RUN_TOKEN}' - it walks the fleet three times and mails a report")
    console.print(f"  [green]drone @seedgo shadow-cycle {RUN_TOKEN}[/green]            [dim]the cycle, mailed[/dim]")
    console.print(
        f"  [green]drone @seedgo shadow-cycle {RUN_TOKEN} --no-mail[/green]  [dim]the cycle, printed only[/dim]"
    )


def _report(document: dict, body: str, published) -> None:
    """Print exactly what the recipient will read, then the caveats.

    The body prints verbatim, without markup, so console and inbox show one screen; the caveats follow because
    a terminal has room for them. soft_wrap is on for the body alone: each line ends in a path that must copy whole.
    """
    console.print()
    success(f"shadow cycle complete in {document['elapsed_seconds']:.0f}s")
    console.print()
    console.print(body, markup=False, highlight=False, soft_wrap=True)
    console.print()
    console.print("[bold cyan]Caveats[/bold cyan]")
    for caveat in document["caveats"]:
        console.print(f"  [dim]{caveat}[/dim]")
    console.print()
    console.print(f"[dim]document: {published}[/dim]")


def _print_help() -> None:
    """What the verb does, what it refuses to do, and how to call it."""
    console.print()
    console.print("[bold cyan]seedgo shadow-cycle[/bold cyan] - the three weekly measurements, in one pass")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  drone @seedgo shadow-cycle                 what the cycle is")
    console.print("  drone @seedgo shadow-cycle run             run it, email the screen")
    console.print("  drone @seedgo shadow-cycle run --no-mail   run it, send nothing")
    console.print()
    console.print("[yellow]Passes[/yellow]")
    console.print(f"  1. the {SHADOW_PACK} pack over every branch - SHADOW, it gates nothing")
    console.print("  2. the ranked test inventory - one row per test function")
    console.print("  3. cross-branch twins - identities sharing a name AND a shape")
    console.print()
    console.print("[yellow]Mails[/yellow]")
    console.print(f"  one screen to {RECIPIENT}: the headline counts and the artifact PATHS.")
    console.print("  an email, never a dispatch - a weekly reading must not wake anyone.")
    console.print()
    console.print("[yellow]Refuses[/yellow]")
    console.print("  it deletes nothing, merges nothing and issues no verdict.")
    console.print("  the score in pass 1 is a series to diff, not a threshold to pass.")
    console.print()


def print_introspection() -> None:
    """What this verb is, shown when it is called with no arguments."""
    console.print()
    console.print("[bold cyan]shadow-cycle[/bold cyan] - three fleet measurements, one screen")
    console.print()
    console.print("  Runs the weekly cadence in one pass and publishes a joining")
    console.print("  document naming which three runs belong to the same week.")
    console.print()
    console.print("[yellow]Passes[/yellow]")
    console.print(f"  shadow score   the {SHADOW_PACK} pack, fleet-wide, SCORING AND NOT GATING")
    console.print("  inventory      every test function, ranked for READING")
    console.print("  twins          cross-branch shape identities, and the merge residue")
    console.print()
    console.print("[yellow]Publishes[/yellow]")
    console.print(f"  {cycle.document_path()}")
    console.print(f"  plus each pass's own artifact, and one email to {RECIPIENT}")
    console.print()
    console.print("[dim]Nothing here gates anything. Run 'drone @seedgo shadow-cycle --help' for usage.[/dim]")
    console.print()
