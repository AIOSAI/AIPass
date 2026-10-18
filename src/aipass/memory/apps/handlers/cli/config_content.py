# =================== AIPass ====================
# Name: config_content.py
# Description: Config-verb content handler - the help page and limit blocks as lines, never printed
# Version: 1.0.0
# Created: 2026-09-16
# Modified: 2026-10-17
# =============================================

"""
Config Verb Content Handler

Lines of Rich markup for ``modules/rollover_config.py`` to print; handlers may not
print and the module must stay under 600 lines. Every number and name is passed in
so nothing is copied here to drift.
"""

from typing import Any, Iterable, Mapping

from aipass.memory.apps.handlers.json import json_handler


def fmt_count(value: object) -> str:
    """Render a limit for display — an absent limit says so, never shows 0."""
    return "unset" if value is None else str(value)


def defaults_lines(
    defaults: Mapping[str, Any], display_types: Iterable[str], read_only_types: Iterable[str]
) -> list[str]:
    """The global default limits block."""
    read_only = set(read_only_types)
    lines = ["[bold]DEFAULTS[/bold] [dim](drone @memory config set-default <type> <count>)[/dim]"]
    for entry_type in display_types:
        row = defaults.get(entry_type, {})
        cap = row.get("auto_compact_cap")
        suffix = "" if cap is None else f"  [dim]auto_compact_cap {cap} (read-only)[/dim]"
        if entry_type in read_only:
            suffix = "  [dim](read-only in v1)[/dim]"
        lines.append(f"  [cyan]{entry_type:<14}[/cyan] {fmt_count(row.get('count'))}{suffix}")
    lines.append("")
    return lines


def overrides_lines(overrides: Mapping[str, Any], display_types: Iterable[str]) -> list[str]:
    """Every branch whose effective limits deviate from the defaults."""
    if not overrides:
        return ["[green]>[/green] All branches at defaults — no per-branch overrides", ""]

    types = list(display_types)
    lines = [f"[bold]OVERRIDES[/bold] [dim]({len(overrides)} branch(es) deviating from defaults)[/dim]"]
    for branch, limits in overrides.items():
        lines.append(f"  [bold]@{branch}[/bold]")
        for entry_type in types:
            row = limits.get(entry_type, {})
            if not row.get("is_override"):
                continue
            lines.append(
                f"    [cyan]{entry_type:<14}[/cyan] {fmt_count(row.get('count'))} "
                f"[yellow][OVERRIDE][/yellow] [dim](default {fmt_count(row.get('default_count'))})[/dim]"
            )
    lines.append("")
    return lines


def branch_limits_lines(
    branch: str, limits: Mapping[str, Any], display_types: Iterable[str], read_only_types: Iterable[str]
) -> list[str]:
    """One branch's EFFECTIVE limits, each marked default-or-override.

    Markers are UPPERCASE: Rich reads `[default]` as a style name and deletes it.
    """
    read_only = set(read_only_types)
    lines = [f"[bold]@{branch}[/bold] [dim](effective limits — what the rollover engine applies)[/dim]", ""]
    for entry_type in display_types:
        row = limits.get(entry_type, {})
        marker = "[yellow][OVERRIDE][/yellow]" if row.get("is_override") else "[green][DEFAULT][/green]"
        lines.append(
            f"  [cyan]{entry_type:<14}[/cyan] {fmt_count(row.get('count')):<6} {marker} "
            f"[dim](default {fmt_count(row.get('default_count'))}, resolved from {row.get('source')})[/dim]"
        )
        cap = row.get("auto_compact_cap")
        if cap is not None:
            lines.append(f"                 [dim]auto_compact_cap {cap} — read-only in v1[/dim]")
        if entry_type in read_only:
            lines.append("                 [dim]read-only in v1 — the todo roll reads it, config set does not[/dim]")
    lines.append("")
    lines.append("[dim]Change with: drone @memory config set @" + branch + " sessions <count>[/dim]")
    lines.append("")
    return lines


def help_lines(min_count: int, max_count: int, ceilings: Mapping[str, Any]) -> list[str]:
    """The config-verb help page below its title panel.

    ceilings are the LIVE per-type ceilings, so BOUNDS never contradicts the refusal.
    """
    json_handler.log_operation("config_help_content", {"ceilings": len(ceilings)})
    lines = [
        "[bold]USAGE:[/bold]",
        "  drone @memory config get                        Defaults + branches that deviate",
        "  drone @memory config get @<branch>              One branch's effective limits",
        "  drone @memory config set @<branch> <type> <n>   Override one branch",
        "  drone @memory config set-default <type> <n>     Change the global default",
        "",
        "[bold]--json — THE MACHINE SURFACE:[/bold]",
        "  Every verb above takes [cyan]--json[/cyan] in ANY slot; it is stripped before",
        "  positional parsing, so `set @b sessions 12 --json` parses like `set @b sessions 12`.",
        "  Exactly ONE JSON document reaches stdout — no panels, no banners, no Rich.",
        "  A help flag OUTRANKS it: `set ... --help --json` prints this page and writes nothing.",
        "",
        "  Every payload carries [cyan]ok[/cyan] and [cyan]verb[/cyan]. [cyan]ok[/cyan] is the signal,",
        "  because refusals exit 0 — a refusal is [cyan]ok: false[/cyan] plus [cyan]error[/cyan] and",
        "  [cyan]suggestion[/cyan], carrying the SAME sentences the human path prints.",
        "",
        "[bold]ENTRY TYPES:[/bold]",
        "  [cyan]sessions[/cyan]        local.json -> sessions",
        "  [cyan]key_learnings[/cyan]   local.json -> key_learnings",
        "  [cyan]observations[/cyan]    observations.json -> observations",
        "  [cyan]todos[/cyan]           local.json -> todos  [dim](count shown by get, read-only in v1)[/dim]",
        "",
        f"[bold]BOUNDS:[/bold] a whole number, {min_count}-{max_count} inclusive — AND under its ceiling",
        f"  {min_count - 1} would roll over every entry immediately; past {max_count} rollover is defeated entirely.",
        "  The ceiling is lower and is PER TYPE and PER FILE: a keep-count multiplies an entry cap,",
        "  so the file it fills must still fit its budget. At the counts the other types hold:",
    ]
    for entry_type, row in ceilings.items():
        lines.append(
            f"    [cyan]{entry_type:<14}[/cyan] at most {row['ceiling']:<4}"
            f" [dim]{row['file_key']} budget {row['budget_chars']:,} chars[/dim]"
        )
    lines += [
        "  Raise one type and its co-tenants' ceilings drop. Budgets: memory.config.json",
        "  entry_limits.file_budgets; the refusal names the ceiling and the worst case it measured.",
        "",
        "[bold]EFFECTIVE LIMITS:[/bold]",
        "  Resolution is per FILE KEY, not per entry type — exactly what the",
        "  rollover engine does. Once per_branch -> <branch> -> local exists,",
        "  the default local block is never consulted for that branch again.",
        "  A value is marked [yellow][OVERRIDE][/yellow] when it differs from the default,",
        "  [green][DEFAULT][/green] when it matches.",
        "",
        "[bold]SET-DEFAULT DOES NOT PUSH:[/bold]",
        "  set-default writes defaults only and leaves per_branch untouched.",
        "  drone @memory rollover push stays the one explicit fleet-wide reset.",
        "",
        "[bold]READ-ONLY:[/bold] auto_compact_cap and the todos count are displayed but not settable in v1.",
        "",
    ]
    return lines
