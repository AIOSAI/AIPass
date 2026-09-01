# =================== AIPass ====================
# Name: imports_content.py
# Description: Import Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Import Standards Content Handler

Provides formatted import standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_imports_standards() -> str:
    """Return formatted import standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]STANDARD IMPORT ORDER:[/bold cyan]",
        "",
        "[bold]1. Infrastructure[/bold]",
        "   • AIPASS_ROOT = Path(__file__).resolve().parents[N]",
        "   • Use package-relative paths (no sys.path hacks in pip packages)",
        "",
        "[bold]2. Standard library[/bold]",
        "   • Grouped by category, alphabetical",
        "   • json, datetime, typing, pathlib, etc.",
        "",
        "[bold]3. Prax logger (nearly always)[/bold]",
        "   • [dim]from aipass.prax.apps.modules.logger import system_logger as logger[/dim]",
        "",
        "[bold]4. Services (CLI, etc.)[/bold]",
        "   • [dim]from aipass.cli.apps.modules import console, header, success[/dim]",
        "",
        "[bold]5. Internal handlers[/bold]",
        "   • [dim]from aipass.seedgo.apps.handlers.json import json_handler[/dim]",
        "",
        "[yellow]RULE:[/yellow] Infrastructure → Stdlib → Prax → Services → Internal",
        "",
        "[bold cyan]COMPLETE PATTERN:[/bold cyan]",
        "  [dim]import sys[/dim]",
        "  [dim]from pathlib import Path[/dim]",
        "",
        "  [dim]import json[/dim]",
        "  [dim]from datetime import datetime[/dim]",
        "  [dim]from typing import Dict, List, Optional[/dim]",
        "",
        "  [dim]from aipass.prax.apps.modules.logger import system_logger as logger[/dim]",
        "  [dim]from aipass.cli.apps.modules import console, header[/dim]",
        "  [dim]from aipass.seedgo.apps.handlers.json import json_handler[/dim]",
        "",
        "[bold cyan]CRITICAL RULES:[/bold cyan]",
        "  [yellow]✓[/yellow] Path(__file__).resolve().parents[N] - NEVER hardcode paths",
        "  [yellow]✓[/yellow] Absolute imports - NO relative imports (...)",
        "  [yellow]✓[/yellow] Handlers CANNOT import modules (independence)",
        "  [yellow]✓[/yellow] Services before internal (Prax, CLI, then handlers)",
        "",
        "[bold cyan]HANDLER INDEPENDENCE:[/bold cyan]",
        "  Handlers import handlers ✓",
        "  Handlers import services ✓",
        "  Handlers import modules ✗ [dim](BREAKS INDEPENDENCE)[/dim]",
        "",
        "[bold cyan]SERVICE INVOCATION - CONTEXT REQUIREMENTS:[/bold cyan]",
        "",
        "[bold]Context-Independent Services (work anywhere):[/bold]",
        "  • Prax logger - import and use from any location",
        "  • CLI services - import and use from any location",
        "",
        "[bold]Context-Dependent Services (PWD detection):[/bold]",
        "  • [yellow]AI_MAIL[/yellow] - requires calling from branch directory",
        "  • Uses PWD to detect sender identity (@seedgo, @drone, etc.)",
        "  • Auto-generates config at [branch]/seedgo_json/user_config.json",
        "",
        "[bold]Best Practice - Use Drone:[/bold]",
        '  [dim]subprocess.run(["drone", "email", "send", "@recipient", "Subject", "Message"])[/dim]',
        "  • Drone handles PWD detection automatically",
        "",
        "[bold]Direct Invocation (Advanced):[/bold]",
        '  [dim]subprocess.run(["drone", "@ai_mail", "send", ...],[/dim]',
        "  [dim]                cwd=str(branch_dir))  # Force correct working directory[/dim]",
        "  • Must use cwd= parameter for PWD detection to work",
        "",
        "[yellow]KEY:[/yellow] AI_MAIL walks up from CWD to find .trinity/passport.json for branch identity",
        "",
        "[bold cyan]DEMONSTRATION:[/bold cyan]",
        "  [dim]src/aipass/seedgo/apps/standards/aipass/modules/ (reference modules)[/dim]",
        "  [dim]src/aipass/cli/apps/modules/ (CLI service examples)[/dim]",
        "",
        "[bold cyan]IMPORT-TIME CAPTURE -- THE REDIRECT SEAM:[/bold cyan]",
        "  A value captured at import cannot be redirected later. Resolve at CALL",
        "  time: [bold]the last dot must be resolved at call time[/bold] for a patch to reach",
        "  a consumer. [dim]import pkg; pkg.x() is patchable -- from pkg import x is not.[/dim]",
        "  [yellow]![/yellow]  NECESSARY, NOT SUFFICIENT. If the call-time resolver compares",
        "     against a reference captured at import and derived from the SAME env",
        "     var, the seam is dead again -- the stale value looks like a deliberate",
        "     override and wins for the rest of the process.",
        "     [bold]A reference that is itself derived from the thing you are[/bold]",
        "     [bold]detecting cannot detect it.[/bold] [dim](@daemon via @prax, 2026-08-31)[/dim]",
        "  [yellow]![/yellow]  EVIDENCE SHAPE: a per-branch green does not clear this class.",
        "     [dim]Pin it in a SUBPROCESS -- export the var, import, assert the anchor[/dim]",
        "     [dim]is the real tree. In-process the property is unobservable by[/dim]",
        "     [dim]construction: the import already happened. @prax's suite was green[/dim]",
        "     [dim]from the branch dir and red from the repo root, on import-order luck.[/dim]",
        "  [yellow]![/yellow]  MOCKING A RE-EXPORTED OBJECT: patch the CONSUMING module's name",
        '     [dim]-- patch("<consumer module>.logger"). Patching upstream of a binding[/dim]',
        "     [dim]never reaches past it, and aipass/prax/__init__ re-exports by[/dim]",
        "     [dim]binding, so the copy is taken twice. Five fleet techniques measured[/dim]",
        "     [dim]against a real consumer by object identity: all five reach nothing.[/dim]",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (imports)[/dim]",
        "",
        "─" * 70,
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "imports"})
    return "\n".join(lines)
