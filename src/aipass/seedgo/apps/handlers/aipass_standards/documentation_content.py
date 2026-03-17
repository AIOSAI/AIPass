# =================== AIPass ====================
# Name: documentation_content.py
# Description: Documentation Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Documentation Standards Content Handler

Condensed documentation standards verified against actual codebase.
Truth-checked 2025-11-13 against spawn and seedgo production code.
"""

from aipass.seedgo.apps.handlers.json import json_handler

def get_documentation_standards() -> str:
    """Return formatted documentation standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]WHY DOCUMENT?[/bold cyan]",
        "  • AI agents need metadata for context extraction",
        "  • Humans need quick file understanding without reading code",
        "  • Consistency = predictability = faster development",
        "",
        "─" * 70,
        "",
        "[bold cyan]REQUIRED: AIPass HEADER (Every Python file)[/bold cyan]",
        "",
        "  [dim]# =================== AIPass ====================[/dim]",
        "  [dim]# Name: filename.py[/dim]",
        "  [dim]# Description: Brief description of the file[/dim]",
        "  [dim]# Version: 1.0.0[/dim]",
        "  [dim]# Created: YYYY-MM-DD[/dim]",
        "  [dim]# Modified: YYYY-MM-DD[/dim]",
        "  [dim]# =============================================[/dim]",
        "",
        "[yellow]KEY RULES:[/yellow]",
        "  1. AIPass block = AI-scannable metadata",
        "  2. Name must match the actual filename",
        "  3. Version uses semantic versioning (X.Y.Z)",
        "  4. Created/Modified use ISO date format (YYYY-MM-DD)",
        "",
        "─" * 70,
        "",
        "[bold cyan]REQUIRED: MODULE DOCSTRING[/bold cyan]",
        "",
        "  [dim]\"\"\"",
        "  Module Title",
        "",
        "  Brief purpose description.",
        "  Key features or workflow if needed.",
        "",
        "  Usage examples (optional).",
        "  \"\"\"[/dim]",
        "",
        "[yellow]RULES:[/yellow]",
        "  • Goes right after AIPass block",
        "  • Tells WHAT the file does (not HOW)",
        "  • Keep brief - details go in function docstrings",
        "",
        "─" * 70,
        "",
        "[bold cyan]FUNCTION DOCSTRINGS (Google-style)[/bold cyan]",
        "",
        "  [dim]def function_name(arg: Type) -> ReturnType:",
        "      \"\"\"",
        "      One-line summary",
        "",
        "      Args:",
        "          arg: Description of parameter",
        "",
        "      Returns:",
        "          Description of return value",
        "",
        "      Raises:",
        "          Exception: When raised (optional)",
        "      \"\"\"[/dim]",
        "",
        "[yellow]RULES:[/yellow]",
        "  • Type hints REQUIRED on all functions",
        "  • Args/Returns/Raises sections for clarity",
        "  • Skip Raises if using error handler decorators",
        "",
        "─" * 70,
        "",
        "[bold cyan]IMPORT ORGANIZATION[/bold cyan]",
        "",
        "  [bold]Order:[/bold]",
        "  1. Standard library imports",
        "  2. Third-party imports",
        "  3. Internal imports ([dim]from aipass.{module}...[/dim])",
        "",
        "─" * 70,
        "",
        "[bold cyan]SECTION SEPARATORS[/bold cyan]",
        "",
        "  [dim]# =============================================================================[/dim]",
        "  [dim]# SECTION NAME[/dim]",
        "  [dim]# =============================================================================[/dim]",
        "",
        "  Common sections: CONSTANTS, FILE OPERATIONS, HELPER FUNCTIONS",
        "",
        "─" * 70,
        "",
        "[bold cyan]INLINE COMMENTS (use sparingly)[/bold cyan]",
        "",
        "  [bold]Good:[/bold] Explain WHY, not WHAT",
        "  [dim]# Memory file suffixes to check (JSON format)[/dim]",
        "  [dim]memory_suffixes = [\".json\", \".local.json\"][/dim]",
        "",
        "  [bold]Bad:[/bold] Obvious narration",
        "  [dim]# Set x to 5[/dim]",
        "  [dim]x = 5[/dim]",
        "",
        "[yellow]REMEMBER:[/yellow] Good code documents itself. Comments are last resort.",
        "",
        "─" * 70,
        "",
        "[bold cyan]VERIFICATION:[/bold cyan]",
        "  Standards verified against actual production code:",
        "  • [dim]src/aipass/*/apps/ (all module entry points)[/dim]",
        "",
        "[bold cyan]FULL REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (documentation)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "documentation"})
    return "\n".join(lines)
