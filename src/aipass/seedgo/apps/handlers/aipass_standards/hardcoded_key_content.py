# =================== AIPass ====================
# Name: hardcoded_key_content.py
# Description: Hardcoded Key Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Hardcoded Key Standards Content Handler

Provides formatted Hardcoded Key standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_hardcoded_key_standards() -> str:
    """Return formatted hardcoded_key standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  API keys and secrets must [bold red]never[/bold red] appear as string",
        "  literals in source code. Use environment variables or config files.",
        "  A single leaked key can compromise an entire service.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Scans every .py file for known API key prefixes inside quotes.",
        "  Detected providers:",
        "",
        "  [yellow]Provider prefixes:[/yellow]",
        "  - OpenRouter: [dim]sk-or-v1-...[/dim]",
        "  - OpenAI: [dim]sk-proj-...[/dim]",
        "  - Anthropic: [dim]sk-ant-...[/dim]",
        "  - Google: [dim]AIza...[/dim]",
        "  - AWS: [dim]AKIA...[/dim]",
        "  - GitHub: [dim]ghp_... / gho_... / ghs_...[/dim]",
        "  - Slack: [dim]xoxb-... / xoxp-...[/dim]",
        "  - Generic: [dim]key-...[/dim] (16+ chars after prefix)",
        "",
        "  [yellow]Smart filtering -- these are NOT flagged:[/yellow]",
        "  - Comment lines ([dim]# sk-or-v1-...[/dim])",
        "  - Docstring regions (triple-quoted blocks)",
        "  - Placeholder values ([dim]your_key_here, xxx, example, placeholder, ...[/dim])",
        "  - Placeholder suffixes ([dim]...-example, ...-test, ...-placeholder[/dim])",
        "  - Lines with example context words ([dim]example, template, sample, demo[/dim])",
        "  - Regex compilation contexts ([dim]re.compile(...)[/dim])",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  Any key-like string literal that passes all filters is a violation.",
        "",
        "  [red]Bad:[/red]",
        '  [dim]API_KEY = "sk-or-v1-abc123real456key789"[/dim]',
        '  [dim]client = OpenAI(api_key="sk-proj-actual-secret-key-here123")[/dim]',
        "",
        "  [green]Good -- use environment variables:[/green]",
        "  [dim]import os[/dim]",
        '  [dim]API_KEY = os.environ["OPENROUTER_API_KEY"][/dim]',
        "",
        "  [green]Good -- use config files:[/green]",
        '  [dim]config = json.loads(Path("config.json").read_text(encoding="utf-8"))[/dim]',
        '  [dim]API_KEY = config["api_key"][/dim]',
        "",
        "  Violation message example:",
        "  [dim]Found 2 hardcoded key(s) on lines 15, 42[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  1. Move the key to an environment variable or .env file",
        '  2. Replace the literal with [dim]os.environ["KEY_NAME"][/dim]',
        "  3. Add the .env file to .gitignore if not already present",
        "  4. Rotate the exposed key immediately -- it is compromised",
        "  5. Re-run the audit to confirm zero violations",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Runs against every .py file in the branch. Skips __init__.py.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Single check per file: [green]pass[/green] (0 keys found) or [red]fail[/red] (any keys found)",
        "  Score: 100 if passed, 0 if failed",
        "  Threshold: score >= 75 to pass overall",
        "  Line-level bypass filtering is supported -- bypassed lines are",
        "  excluded before counting violations.",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Add an entry to [dim].seedgo/bypass.json[/dim]:",
        '  [dim]{"standard": "hardcoded_key", "file": "path/to/file.py"}[/dim]',
        "  Or bypass specific lines:",
        '  [dim]{"standard": "hardcoded_key", "file": "file.py", "lines": [15]}[/dim]',
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (hardcoded_key)[/dim]",
        "  [dim]Checker: hardcoded_key_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "hardcoded_key"})
    return "\n".join(lines)
