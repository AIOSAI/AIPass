# =================== AIPass ====================
# Name: shadow_cycle.py
# Description: the weekly shadow cycle - three fleet measurements, one document, one mail
# Version: 1.0.0
# Created: 2026-09-02
# Modified: 2026-09-02
# =============================================

"""
The `shadow-cycle` verb. Runs the three weekly measurement passes back to back
and mails ONE screen of headline counts and artifact paths.

    drone @seedgo shadow-cycle              what the cycle is
    drone @seedgo shadow-cycle run          the full cycle, emailed to @devpulse
    drone @seedgo shadow-cycle run --no-mail  the full cycle, printed and not sent

THE THREE PASSES, AND WHY THEY TRAVEL TOGETHER.

  1. THE V5 SHADOW SCORE. The `pytest_quality` pack over every branch. It is a
     SHADOW pack by its own declaration - it scores and gates nothing - and the
     reason to run it weekly is that a shadow number is only useful as a SERIES
     to diff against the calibrated v4 triage.
  2. THE RANKED TEST INVENTORY. One row per test function, ordered for reading.
  3. THE CROSS-BRANCH TWIN CENSUS, with the residue block: what a merge keyed on
     FILENAME would destroy.

Three numbers taken a week apart are three unrelated readings; three numbers
taken in one pass are a cross-section. That is the whole argument for one verb.

WHY IT WILL NOT RUN ON A BARE INVOCATION. `run` is required. This verb walks
every branch three times and takes minutes, and the seedgo introspection
standard reserves the no-argument call for describing a verb rather than firing
it. A cycle that started because someone typed the name to see what it was is
a cycle nobody asked for.

THE MAIL IS AN EMAIL, NEVER A DISPATCH - a weekly reading must not wake a
citizen at whatever hour the daemon fires. It carries the artifact PATHS; the
reports themselves run to tens of megabytes and belong on disk.

WHERE THE FLEET CONTAINER COMES FROM. `inventory` already owns that question
and answers it off the imported `aipass` package rather than the registry,
because the registry is machine-local and a fresh checkout has none - a second
derivation here is exactly the defect that turned the board red on PR #751.
This verb reuses that function; it does not re-derive it.
"""

import time
from typing import List, Tuple

from aipass.cli import console
from aipass.cli.apps.modules import error, success
from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit import discovery
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.shadow_cycle import cycle, mail, score
from aipass.seedgo.apps.handlers.test_inventory import report, roots, twins
from aipass.seedgo.apps.modules import inventory

#: Exact tokens this module claims. Never a prefix match - `route_command`
#: takes the first module returning truthy, so a prefix claim would swallow
#: verbs this module knows nothing about.
COMMANDS: tuple = ("shadow-cycle", "shadow_cycle")

#: Every option this verb accepts.
FLAGS: tuple = ("--no-mail", "--help", "-h")

#: The word that starts the cycle. Required - see the module docstring.
RUN_TOKEN = "run"

#: The pack measured in shadow. Named here because it is the ONE thing about
#: this cycle that a future ruling is expected to change.
SHADOW_PACK = "pytest_quality"

#: Who receives the one-screen summary.
RECIPIENT = "@devpulse"


def handle_command(command: str, args: List[str]) -> bool:
    """Claim `shadow-cycle` and run it. Returns True once claimed, always.

    The unconditional True is the safety property: an exception escaping here is
    swallowed by the router and reported to the user as an unknown command, so a
    broken verb would look like a verb that was never installed.
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

    `inventory._measure` is called rather than copied: it names the four static
    passes and their order, and a second spelling of that sequence here would be
    a second definition of what the inventory IS.
    """
    console.print()
    console.print("[bold cyan]2/3[/bold cyan] [dim]the ranked test inventory[/dim]")
    root = roots.resolve(roots.FLEET_ARGUMENT)
    built = inventory._measure(root)
    return cycle.inventory_block(built.summary, report.publish(built))


def _twins_pass() -> dict:
    """Pass 3 - cross-branch twins over the directory the branches live in.

    The container is READ OFF THE SOURCE TREE by `inventory._fleet_container`,
    never re-derived and never taken from the registry: the registry is
    gitignored, so on a fresh checkout a second derivation answers nothing,
    falls back to the repo root, and publishes "0 twins over 0 branches" as a
    success. That is not a hypothetical - it is what turned PR #751 red.
    """
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


# =============================================================================
# DISPLAY
# =============================================================================


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

    The body is printed VERBATIM and without markup so the console and the
    inbox cannot show two different screens; the caveats follow it because they
    are what the document refuses to be published without, and a reader at a
    terminal has room for them where one screen of mail does not.

    soft_wrap is on for the body alone: every line in it ends in an artifact
    PATH, and a path folded at the console width is a path nobody can
    double-click or copy in one go.
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
