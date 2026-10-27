# =================== AIPass ====================
# Name: host_coupled_oracle_content.py
# Description: Host Coupled Oracle Standards Content Handler
# Version: 1.0.0
# Created: 2026-10-26
# Modified: 2026-10-26
# =============================================

"""
Host Coupled Oracle Standards Content Handler

Provides formatted Host Coupled Oracle standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_host_coupled_oracle_standards() -> str:
    """Return formatted host_coupled_oracle standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test's expected value must hold on every host CI runs it on. Two hooks",
        "  tests passed on the seat and went [red]red in CI[/red]: one read its own",
        "  process title, which pytest-xdist rewrites; one counted [dim]subprocess.run[/dim]",
        "  calls down a path that reads /proc on Linux and runs [dim]ps[/dim] on macOS.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "",
        "  [red]1. Its own process title[/red]",
        "     [dim]os.getpid()[/dim] or [dim]os.getppid()[/dim] handed to a callee named for",
        "     the command line: args, argv, cmdline, command, title, proctitle.",
        "",
        "  [red]2. An exact command count across a platform fork[/red]",
        "     [dim]<mock>.call_count == N[/dim] (literal N > 0) on a mock bound by",
        "     [dim]with patch('...subprocess.run') as mock[/dim] or [dim]patch.object(x.subprocess, 'run')[/dim],",
        "     when the test reaches (6 hops, production only) a function that BOTH",
        "     branches on [dim]sys.platform[/dim] / [dim]os.name[/dim] / [dim]platform.system()[/dim]",
        "     (or a module-level name bound to one) AND runs a subprocess.",
        "",
        "  [yellow]Acquits:[/yellow]",
        "  - a skip mark that reads the platform on the test, its class or [dim]pytestmark[/dim]",
        "  - a platform read inside the test (the expectation follows the host)",
        "  - a platform gate that runs nothing: a fixture pins it, the count holds",
        "  - [dim]is_pid_alive(os.getpid())[/dim]: a liveness probe reads no title",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  [dim]args = cc_sessions.process_args(os.getpid())[/dim]",
        "  [dim]assert 'python' in args[0][/dim]",
        "",
        "  [dim]with patch('subprocess.run', side_effect=OSError) as ps:[/dim]",
        "  [dim]    assert resolve_session_pid() is None[/dim]",
        "  [dim]assert ps.call_count == 1      # 2 on darwin[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  [green]Start a child and read ITS pid:[/green]",
        "  [dim]child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])[/dim]",
        "  [dim]assert 'python' in process_args(child.pid)[0][/dim]",
        "",
        "  [green]Count only the call the test is about, or follow the platform:[/green]",
        "  [dim]assert [c for c in ps.call_args_list if c.args[0][0] == 'ps'][/dim]",
        "  [dim]assert ps.call_count == (1 if sys.platform.startswith('linux') else 2)[/dim]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Corpus is [bold]tests/ and lib/*/tests/[/bold]; production is read through the",
        "  tests' own imports under the package root",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  [bold]clean test files / total test files x 100[/bold]",
        "  Reports up to 3 offending file:line rows with descriptions",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] -- supports standard, file-level,",
        "  and line-level bypass rules",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (host_coupled_oracle)[/dim]",
        "  [dim]Checker: host_coupled_oracle_check.py[/dim]",
        "  [dim]Sibling: host_portability (one file's host reads; this follows the call)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "host_coupled_oracle"})
    return "\n".join(lines)
