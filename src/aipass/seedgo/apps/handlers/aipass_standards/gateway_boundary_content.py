# =================== AIPass ====================
# Name: gateway_boundary_content.py
# Description: Gateway Boundary Standards Content Handler
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""
Gateway Boundary Standards Content Handler

Provides formatted gateway boundary standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_gateway_boundary_standards() -> str:
    """Return formatted gateway_boundary standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A branch may write its OWN storage. It may ask another branch to write",
        "  theirs, through that branch's door. What it may NOT do is reach into",
        "  another branch's storage and write it by hand.",
        "",
        '  [dim]Patrick, 2026-08-17: "@api should be only doing api calls.',
        '  api is api thats it."[/dim]',
        "",
        "[bold cyan]WHY IT MATTERS:[/bold cyan]",
        "  A hand-written copy of someone else's write semantics is a MIRROR, and",
        "  a mirror drifts. It does not drift through neglect - it drifts the first",
        "  time either side is fixed. The measured case: @api's settings.py was",
        "  audited and hardened so an unreadable file raises instead of reading as",
        "  blank; @baud's settings.rs still reads every error as blank, which its",
        "  own doc comment forbids in words. The audit that improved one half is",
        "  what separated the two halves.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  A write whose TARGET PATH resolves into another branch's storage.",
        "",
        "  1. [red]Owned filenames[/red]: writing a file whose name is a constant",
        "     another branch already declares (e.g. 'aipass-hooks-muted' belongs",
        "     to @hooks, who expose it as [cyan]drone @hooks hooksound on|off[/cyan]).",
        "  2. [red]Private storage roots[/red]: writing under .seedgo/, .daemon/,",
        "     .spawn/, .flow/ or .ai_mail.local/ when you are not the owner and the",
        "     file shows no sign of routing through one.",
        "",
        "[bold cyan]HOW THE WRITE IS BOUND TO THE PATH:[/bold cyan]",
        "  The check tracks which names are assigned from a foreign path literal,",
        "  propagates through helpers that RETURN one, and then flags only write",
        "  calls whose target derives from that name. Mentioning another branch's",
        "  path is not a violation. READING their file is not a violation. The",
        "  write and the foreign path must be the SAME path.",
        "",
        "[bold cyan]FALSE-POSITIVE GUARDS (each measured, not assumed):[/bold cyan]",
        "  - [dim]AIPASS_REGISTRY.json / passport.json[/dim] are NOT owned names:",
        "    every branch locates and reads them by design. Including them flagged",
        "    47 files across 13 branches, all readers.",
        "  - [dim].trinity/[/dim] is not a foreign root: every branch writes its own.",
        "  - [dim].claude/ and .aipass/[/dim] are SHARED namespaces, not private",
        "    storage - branches correctly create their own file inside them.",
        "  - [dim]str.replace()[/dim] is not a filesystem write. Only os.replace is.",
        "  - [dim]Tests[/dim] are out of scope (APPLIES_TO = production).",
        "",
        "[bold cyan]THE FIX:[/bold cyan]",
        "  Call the owner's door. If no door exists, ASK THE OWNER FOR ONE and say",
        "  so in the code until it arrives - a documented absence is honest, a",
        "  silent hand-written copy is not.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  100 = no cross-branch storage writes. Each violation costs 25.",
    ]
    json_handler.log_operation("gateway_boundary_standards_served", {"lines": len(lines)})
    return "\n".join(lines)
