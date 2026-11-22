# =================== AIPass ====================
# Name: lowercase_name_content.py
# Description: Lowercase Name Standards Content Handler
# Version: 2.0.0
# Created: 2026-11-22
# Modified: 2026-11-22
# =============================================

"""Lowercase Name Standards Content Handler"""

from aipass.sentry.apps.handlers.json import json_handler


def get_lowercase_name_standards() -> str:
    """Return formatted lowercase_name standards content with Rich markup."""
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  The system speaks lowercase: an agent's name is lowercase wherever it runs - stored,",
        "  printed, logged or labelled (owner, 2026-11-22). Markdown is never opened.",
        "",
        "[bold cyan]WHAT IT CHECKS (one finding fails the standard):[/bold cyan]",
        "  1. [red]Registry row[/red]: this branch's row in *_REGISTRY.json - a capital name or an",
        "     absolute path. Cure: drone @spawn sync-registry <registry> --lowercase",
        "  2. [red]Data files[/red]: .trinity/passport.json branch_info.branch_name,",
        "     artifacts/birth_certificate.json owner, DASHBOARD.local.json branch",
        "  3. [red]Code[/red] under apps/ and shared/:",
        "     - .upper() / .title() / .capitalize() on a branch, agent, citizen, sender,",
        "       recipient, owner or caller expression (a case-fold for a comparison is exempt)",
        "     - a string literal word in all capitals whose lowercase is an agent name:",
        "       in a log tag or a banner: 'NAME AUDIT' where NAME is an agent - write 'name audit'",
        "  Agent names: the branch's own folder plus its registry's rows, read at check time.",
        "",
        "[bold cyan]NAMES THAT ARE ALSO WORDS:[/bold cyan]",
        "  cli, api, flow, hooks, memory, trigger, aipass count only in a name position:",
        "  a tag, an @address, an =value, the whole literal, or a banner head 'NAME v1.0'",
        "",
        "[bold cyan]WHAT IT LEAVES OUT:[/bold cyan]",
        "  - comments and docstrings: prose for the reader, not runtime output",
        "  - Title Case ('Sentry'), and capitals made another way (str.upper(x), name.upper())",
        "  - a common-word name outside a name position ('HOOKS BROKEN:')",
        "  - words joined by _ are one token: AI_MAIL_REGISTRY.json, AGENT_AIPASS are legal",
        "  - a clean checkout with no registry knows only the branch's own name",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold], APPLIES_TO = [bold]production[/bold]",
        "  The checklist judges the code leg of the file being written; the audit runs every leg.",
        "  Bypass: a row with lines waives one code site; the rule is drawn so none is needed.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Checker: lowercase_name_check.py  Doc: lowercase_name.md[/dim]",
    ]
    json_handler.log_operation("standard_content_queried", {"standard": "lowercase_name"})
    return "\n".join(lines)
