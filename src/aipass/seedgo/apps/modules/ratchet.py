# =================== AIPass ====================
# Name: ratchet.py
# Description: the execution ratchet - pick one branch a week, probe it, record the point
# Version: 1.1.0
# Created: 2026-10-12
# Modified: 2026-10-18
# =============================================

"""
The `ratchet` verb (DPLAN-0405, FPLAN-9994 phase 1).

seedgo's `.daemon/schedule.json` runs `ratchet run` as a COMMAND job (no wake, no model): the probe is deterministic.

No hand-off dispatch, `verify`, `trend`, mail or slices yet: their absence is not a decision.

THE SERIES IS THE CLOCK, never the artifact - see `handlers/ratchet/series.py`.
"""

import time
from typing import List, Optional, Tuple

from aipass.cli import console
from aipass.cli.apps.modules import error, success, warning
from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit_tests import artifact, laws, refusal, runner
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.ratchet import pick, series
from aipass.seedgo.apps.modules import CommandRefused

COMMANDS: tuple = ("ratchet",)

SUBCOMMANDS: tuple = ("pick", "run", "record")

#: The command job's own timeout (3600) sits above this plus the suite runs.
DEFAULT_BUDGET_SECONDS = 1800

PROBE_GROUP = "pseudo_tested"

#: A week whose target could not be measured is still a point on the series: the reason is
#: in the line, and only a lane that could not run exits non-zero.
RECORDED_STATUSES: tuple = ("measured", "not_applicable")


def handle_command(command: str, args: List[str]) -> bool:
    """Claim `ratchet` and run it. Returns True once claimed, always."""
    if command not in COMMANDS:
        return False

    if not args:
        print_introspection()
        return True

    if wants_help(None, args):
        _print_help()
        return True

    try:
        _dispatch(args)
    except CommandRefused:
        raise
    except Exception as exc:
        logger.error(f"[RATCHET] the ratchet failed: {type(exc).__name__}: {exc}")
        error(f"ratchet failed: {type(exc).__name__}: {exc}")
        console.print("[dim]No series line was written.[/dim]")
        raise CommandRefused(refusal.EXIT_UNPROVEN, "ratchet")

    return True


def _dispatch(args: List[str]) -> None:
    """Route the subcommand, refusing anything this verb does not know."""
    sub, rest = args[0], args[1:]
    if sub == "pick" and not rest:
        _pick()
        return
    if sub == "run":
        _run(_parse_budget(rest))
        return
    if sub == "record" and len(rest) == 1 and rest[0].startswith("@"):
        _record(rest[0])
        return

    error(f"ratchet does not know '{' '.join(args)}' - it takes {', '.join(SUBCOMMANDS)}")
    console.print("[dim]Run 'drone @seedgo ratchet --help' for usage.[/dim]")
    raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, sub)


def _parse_budget(rest: List[str]) -> int:
    """`--budget <seconds>` or nothing. Anything else is refused by name."""
    if not rest:
        return DEFAULT_BUDGET_SECONDS
    if len(rest) == 2 and rest[0] == "--budget" and rest[1].isdigit() and int(rest[1]) > 0:
        return int(rest[1])

    error(f"ratchet run takes only '--budget <seconds>', got '{' '.join(rest)}'")
    raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, " ".join(rest))


def _branch_names() -> List[str]:
    """Every citizen the audit-tests lane can resolve, as the registry spells it."""
    return sorted(runner.branch_paths())


def _pick() -> None:
    """Print the next branch, the reason, and the standings it was read from."""
    lines = series.read()
    names = _branch_names()
    chosen, reason = pick.choose(names, lines)

    console.print()
    console.print(f"[bold cyan]next probe:[/bold cyan] {chosen}  [dim]{reason}[/dim]")
    console.print()
    for name, date in pick.standings(names, lines):
        console.print(f"  [cyan]{name:<12}[/cyan] {date[:10] if date else '[dim]never[/dim]'}")
    console.print()
    console.print(f"[dim]{len(lines)} line(s) in {series.series_path()}. Nothing was run.[/dim]")


def _run(budget: int) -> None:
    """Pick, probe, archive, append. The probe's refusal still writes its line."""
    lines = series.read()
    chosen, reason = pick.choose(_branch_names(), lines)
    json_handler.log_operation("ratchet_run_started", {"branch": chosen, "budget_seconds": budget})

    console.print()
    console.print(f"[bold cyan]ratchet:[/bold cyan] probing {chosen}  [dim]{reason}[/dim]")
    console.print(f"[dim]audit-tests @{chosen} --pseudo-tested, campaign budget {budget}s[/dim]")

    started = time.time()
    document, code = _probe(chosen, budget)
    line = _write_point(document, chosen, series.TRIGGER_WEEKLY, reason)

    _print_point(line, time.time() - started)
    if code in refusal.REFUSAL_CODES or line["status"] not in RECORDED_STATUSES:
        raise CommandRefused(code if code in refusal.REFUSAL_CODES else refusal.EXIT_UNPROVEN, chosen)


def _record(argument: str) -> None:
    """Record the probe already sitting in a branch's artifact, once."""
    target = runner.resolve_targets(argument)[0]
    path = artifact.artifact_path(target)
    document = artifact.load_previous(target)
    if document is None:
        error(f"no audit-tests artifact for {target.name} at {path}")
        raise CommandRefused(refusal.EXIT_NO_UNITS, argument)

    if not series.campaign_ran(document):
        group = series.campaign_group(document) or {}
        error(f"{path.name} holds no pseudo-tested campaign: {group.get('reason') or 'the group is absent'}")
        raise CommandRefused(refusal.EXIT_NO_UNITS, argument)

    run_id = str((document.get("provenance") or {}).get("run_id") or "")
    if series.holds_run(run_id, series.read()):
        warning(f"run {run_id} for {target.name} is already in the series - nothing written")
        return

    line = _write_point(document, target.name, series.TRIGGER_RECORD, f"recorded from {path.name}")
    _print_point(line, None)


def _probe(branch: str, budget: int) -> Tuple[dict, int]:
    """Run the audit-tests lane on one branch with the campaign opted in."""
    options = {"execution_groups": [PROBE_GROUP], "budget_seconds": budget}
    target = runner.resolve_targets(f"@{branch}")[0]
    try:
        result = runner.run_target(target, options)
    except laws.LawViolation as exc:
        logger.error(f"[RATCHET] the {branch} artifact was unlawful and not written: {exc}")
        return {"status": "refused", "refusal": {"reason": f"artifact unlawful: {exc}"}}, refusal.EXIT_UNPROVEN
    return result.document, result.code


def _write_point(document: dict, branch: str, trigger: str, reason: str) -> dict:
    """Archive the artifact and append its series line."""
    run_id = str((document.get("provenance") or {}).get("run_id") or "")
    archived = series.archive(document, branch, run_id) if run_id else None
    line = series.build_line(document, branch=branch, trigger=trigger, pick_reason=reason, archived=archived)
    series.append(line)
    return line


def _print_point(line: dict, elapsed: Optional[float]) -> None:
    """One probe, as the series now holds it."""
    console.print()
    took = f" in {elapsed:.0f}s" if elapsed is not None else ""
    if line["status"] == "measured":
        probed = line["functions_probed"]
        success(f"{line['branch']}: {line['open_survivors']} open survivor(s) of {probed} probed{took}")
    elif line["status"] in RECORDED_STATUSES:
        warning(f"{line['branch']}: probe {line['status']}{took} - {line['reason'] or 'no reason given'}")
    else:
        error(f"{line['branch']}: probe {line['status']}{took} - {line['reason'] or 'no reason given'}")
    console.print(f"  [dim]pseudo-tested[/dim] {len(line['pseudo_tested'])}")
    console.print(f"  [dim]uncovered    [/dim] {len(line['uncovered'])}")
    console.print(f"  [dim]crash-only   [/dim] {len(line['crash_only'])}")
    console.print(f"  [dim]archive      [/dim] {line['archive']}")
    console.print(f"  [dim]series       [/dim] {series.series_path()}")


def _print_help() -> None:
    """Usage, and what this phase does not do yet."""
    console.print()
    console.print("[bold cyan]seedgo ratchet[/bold cyan] - one branch a week, probed and recorded")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  drone @seedgo ratchet pick                the next branch and why; runs nothing")
    console.print("  drone @seedgo ratchet run                 pick, probe (--pseudo-tested), record")
    console.print("  drone @seedgo ratchet run --budget <s>    campaign ceiling, default 1800")
    console.print("  drone @seedgo ratchet record @branch      record the probe already in its artifact")
    console.print()
    console.print("[yellow]Writes[/yellow]")
    console.print(f"  {series.series_path()}  one line per probe, never rewritten")
    console.print(f"  {series.ARTIFACT_DIR / series.ARCHIVE_DIRNAME}  the artifact behind each line")
    console.print()
    console.print("[yellow]Not yet[/yellow]")
    console.print("  hand-off, verify, trend and the Sunday mail - FPLAN-9994 phases 2 to 4")
    console.print()


def print_introspection() -> None:
    """What this verb is, shown when it is called with no arguments."""
    console.print()
    console.print("[bold cyan]ratchet[/bold cyan] - the execution ratchet (DPLAN-0405)")
    console.print()
    console.print("  Picks the branch probed least recently, guts its functions one at a")
    console.print("  time, and appends the survivors to a series nothing rewrites.")
    console.print()
    console.print(f"[yellow]Subcommands[/yellow]  {', '.join(SUBCOMMANDS)}")
    console.print(f"[yellow]Series[/yellow]       {series.series_path()}")
    console.print()
    console.print("[dim]Run 'drone @seedgo ratchet --help' for usage.[/dim]")
    console.print()
