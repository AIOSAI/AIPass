# =================== AIPass ====================
# Name: lowercase_name_content.py
# Description: Lowercase Name Standards Content Handler
# Version: 1.0.0
# Created: 2026-11-22
# Modified: 2026-11-22
# =============================================

"""Lowercase Name Standards Content Handler"""

from aipass.sentry.apps.handlers.json import json_handler


def get_lowercase_name_standards() -> str:
    """Return formatted lowercase_name standards content with Rich markup."""
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  The system speaks lowercase: an agent's name is stored in lowercase (owner, 2026-11-22).",
        "  Markdown is a document, not the runtime, and is never opened by this standard.",
        "",
        "[bold cyan]WHAT IT CHECKS (one finding fails the standard):[/bold cyan]",
        "  1. [red]Registry row[/red]: this branch's row in *_REGISTRY.json - a capital name or an",
        "     absolute path. Cure: drone @spawn sync-registry <registry> --lowercase",
        "  2. [red]Data files[/red]: .trinity/passport.json branch_info.branch_name,",
        "     artifacts/birth_certificate.json owner, DASHBOARD.local.json branch",
        "  3. [red]Code[/red] under apps/ and shared/: an agent name through .upper() / .title() /",
        "     .capitalize(), directly or via a local, into a dict, a subscript store or a path;",
        "     or a literal that is an agent name in capitals stored the same way",
        "  4. [red]Templates[/red]: {{BRANCHNAME}} (filled in capitals) in a non-markdown file under",
        "     templates/ - use {{BRANCH}}, which spawn fills in lowercase",
        "",
        "[bold cyan]WHAT IT LEAVES OUT:[/bold cyan]",
        "  - anything inside a print, console, logger or log_operation call: screens and logs",
        "  - a value that leaves the function before it is stored (a return, a call argument),",
        "    and what a call returns when a capital name is only its argument (a lookup key)",
        "  - [yellow]cannot tell apart[/yellow]: an in-memory map, a returned status dict or a palette",
        "    keyed by capital names reads as storage; waive the site with a row saying why",
        "  - a literal that is not a known agent name: its own folder, plus its registry's rows",
        "  - the project's own name (the registry file's stem, metadata.name)",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold], APPLIES_TO = [bold]production[/bold]",
        "  The checklist judges the code leg of the file being written; the audit runs every leg.",
        "  Bypass: a row with lines waives one code site and says why; the data legs take none.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Checker: lowercase_name_check.py  Doc: lowercase_name.md[/dim]",
    ]
    json_handler.log_operation("standard_content_queried", {"standard": "lowercase_name"})
    return "\n".join(lines)
