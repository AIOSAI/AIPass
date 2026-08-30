# =================== AIPass ====================
# Name: render_spec.py
# Description: renders a nominator's SPECIFICATION for the query surface
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
One renderer for every nominator's content file.

WHY THE CONTENT IS DERIVED AND NOT WRITTEN. A `*_content.py` maintained by
hand beside a `*_check.py` is two statements of the same rule that can
disagree, and the one a reader trusts is the prose. This campaign's whole
subject is claims nothing checks — a documentation file that says the rule
exempts `sys.platform` while the code stopped exempting it would be exactly
that, in the auditor's own pack.

So each nominator declares one `SPECIFICATION` dict and this module renders
it. The check and the content cannot drift, because there is only one of them.
The `.md` files are generated from the same dict by the same rule.
"""

from typing import Dict, List

RULE_WIDTH = 70


def _section(title: str, lines: List[str], bullet: str = "•") -> List[str]:
    """One titled block of bullets, or nothing when there is nothing to say."""
    if not lines:
        return []
    rendered = [f"[bold cyan]{title}[/bold cyan]", ""]
    for line in lines:
        rendered.append(f"  [dim]{bullet}[/dim] {line}")
    rendered.append("")
    return rendered


def render(name: str, specification: Dict[str, object]) -> str:
    """A nominator's specification as Rich-markup content."""
    species = list(specification.get("species", []))  # type: ignore[arg-type]
    lines: List[str] = [
        f"[bold red]{name.upper().replace('_', ' ')}[/bold red]",
        "",
        f"[bold cyan]RULE:[/bold cyan] {specification.get('rule', '')}",
        f"[bold cyan]SPECIES:[/bold cyan] {', '.join(species) or 'none declared'}",
        "[bold cyan]TIER:[/bold cyan] STATIC - nominates, never convicts (Law M1)",
        "",
        "─" * RULE_WIDTH,
        "",
    ]

    lines += _section("WHAT IT FLAGS", list(specification.get("flags", [])))  # type: ignore[arg-type]
    lines += _section("WHAT IT MUST NEVER FLAG", list(specification.get("exempts", [])))  # type: ignore[arg-type]
    lines += _section("WHAT IT CANNOT SEE", list(specification.get("limits", [])))  # type: ignore[arg-type]

    if specification.get("fix"):
        lines += [f"[bold cyan]THE FIX:[/bold cyan] {specification['fix']}", ""]
    if specification.get("evidence"):
        lines += [f"[bold cyan]MEASURED:[/bold cyan] {specification['evidence']}", ""]

    lines += [
        "─" * RULE_WIDTH,
        "",
        "[yellow]This group is NEVER SCORED.[/yellow] Law S7a forbids an unscored group from",
        "carrying a number, and Law M11 forbids acting on a nomination by deleting the",
        "test: a pin that reads like a tautology can be the last thing standing between",
        "a rename and a production hole.",
        "",
    ]
    return "\n".join(lines)


def render_markdown(name: str, specification: Dict[str, object]) -> str:
    """The same specification as a standards `.md` document."""
    species = list(specification.get("species", []))  # type: ignore[arg-type]
    title = name.replace("_", " ").title()
    lines = [
        f"# {title} (static nominator)",
        "**Status:** Active v1",
        "**Tier:** STATIC — nominates, never convicts (Law M1)",
        f"**Species:** {', '.join(species) or 'none declared'}",
        f"**Rule:** {specification.get('rule', '')}",
        "",
        "---",
        "",
        "## What it flags",
        "",
    ]
    lines += [f"- {line}" for line in specification.get("flags", [])]  # type: ignore[union-attr]
    lines += ["", "## What it must never flag", ""]
    lines += [f"- {line}" for line in specification.get("exempts", [])]  # type: ignore[union-attr]
    lines += ["", "## What it cannot see", ""]
    lines += [f"- {line}" for line in specification.get("limits", [])]  # type: ignore[union-attr]
    lines += [
        "",
        "## The fix",
        "",
        str(specification.get("fix", "")),
        "",
        "## Measured",
        "",
        str(specification.get("evidence", "")),
        "",
        "---",
        "",
        "## Why this group is never scored",
        "",
        "Law M1 splits the tiers: static **nominates**, execution **convicts**. A nomination",
        "says a test is suspect; it never says a test is worthless, and Law S7b closes the",
        "verdict vocabulary against the delete family for exactly that reason.",
        "",
        "Law M11 is the reason the rows carry a `deletion_safety` field that currently says",
        "`probed: false`. TAXONOMY corpus row 26 is the worked example: @daemon's",
        "`HANDLED_COMMANDS` membership tests read as tautologies and are the only pins on the",
        "name of a verb that, renamed, falls through and turns the fleet's scheduler off — with",
        "all 481 tests green. A checker that flagged those pins and got them deleted would have",
        "made the branch worse.",
        "",
        "## Why the static tier can never be retired",
        "",
        "Design section 4.2a-bis, CONTRACT 0. Mutation's unit of judgement is the **mutant**,",
        "not the **test**, so any healthy test on a symbol masks every weak one beside it.",
        "Measured: a MIRROR-EXPECT test survived a constant mutant while its spelled-out twin",
        "killed the same mutant — so nothing was reported at all. A per-mutant verdict cannot",
        "structurally name a per-test defect, whatever the execution tier grows into.",
        "",
    ]
    return "\n".join(lines)
