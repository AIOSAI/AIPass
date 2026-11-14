# =================== AIPass ====================
# Name: host_coupled_oracle_content.py
# Description: Host Coupled Oracle Standards Content Handler
# Version: 1.1.0
# Created: 2026-10-26
# Modified: 2026-11-14
# =============================================

"""
Host Coupled Oracle Standards Content Handler

Provides formatted Host Coupled Oracle standards content.
Module orchestrates, handler implements.
"""

from aipass.sentry.apps.handlers.json import json_handler


def get_host_coupled_oracle_standards() -> str:
    """Return formatted host_coupled_oracle standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test's expected value must hold on every host CI runs it on. A hooks",
        "  test passed on the seat and went [red]red in CI[/red]: it read its own",
        "  process title, which pytest-xdist rewrites.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "",
        "  [red]Its own process title[/red]",
        "     [dim]os.getpid()[/dim] or [dim]os.getppid()[/dim] handed to a callee named for",
        "     the command line: args, argv, cmdline, command, title, proctitle.",
        "",
        "  [yellow]Acquits:[/yellow]",
        "  - [dim]is_pid_alive(os.getpid())[/dim]: a liveness probe reads no title",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  [dim]args = cc_sessions.process_args(os.getpid())[/dim]",
        "  [dim]assert 'python' in args[0][/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  [green]Start a child and read ITS pid:[/green]",
        "  [dim]child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])[/dim]",
        "  [dim]assert 'python' in process_args(child.pid)[0][/dim]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Corpus is [bold]tests/ and lib/*/tests/[/bold]",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  [bold]clean test files / total test files x 100[/bold]",
        "  Reports up to 3 offending file:line rows with descriptions",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].sentry/bypass.json[/dim] -- supports standard, file-level,",
        "  and line-level bypass rules",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: sentry standards pack (host_coupled_oracle)[/dim]",
        "  [dim]Checker: host_coupled_oracle_check.py[/dim]",
        "  [dim]Sibling: host_portability (one file's host reads)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "host_coupled_oracle"})
    return "\n".join(lines)
