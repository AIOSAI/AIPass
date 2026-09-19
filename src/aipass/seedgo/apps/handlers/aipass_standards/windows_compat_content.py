# =================== AIPass ====================
# Name: windows_compat_content.py
# Description: Windows Compatibility Standards Content Handler
# Version: 1.1.0
# Created: 2026-05-10
# Modified: 2026-09-18
# =============================================

"""
Windows Compatibility Standards Content Handler

Provides formatted Windows Compatibility standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_windows_compat_standards() -> str:
    """Return formatted windows_compat standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Code must run on both Linux and Windows. POSIX-only APIs must be",
        "  guarded with [yellow]if sys.platform != 'win32'[/yellow] or wrapped in",
        "  [yellow]try/except ImportError[/yellow]. We ADD Windows code paths alongside",
        "  existing Linux code -- we NEVER change the Linux path.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Parses Python files with [dim]ast.parse()[/dim] and detects:",
        "",
        "  1. [red]Unguarded POSIX-only imports[/red]: fcntl, pwd, grp, termios, resource",
        "  2. [red]Unguarded POSIX-only constants[/red]: os.WNOHANG, signal.SIGPIPE",
        "  3. [red]Unguarded POSIX-only calls[/red]: os.fork, os.setpgid, os.killpg,",
        "     os.getpgid, os.waitpid",
        "  4. [red]os.kill() without OSError handling[/red]: Windows raises WinError 87",
        "",
        "  [yellow]Valid guards (checker recognizes):[/yellow]",
        "  - [dim]if sys.platform != 'win32':[/dim]",
        "  - [dim]if sys.platform == 'linux':[/dim]",
        "  - [dim]if os.name != 'nt':[/dim]  /  [dim]if os.name == 'posix':[/dim]",
        "  - [dim]try: import fcntl / except ImportError:[/dim]",
        "  - [dim]if hasattr(signal, 'SIGPIPE'):[/dim]",
        "  - [dim]try: os.kill(...) / except OSError:[/dim]",
        "",
        "  [yellow]Skips:[/yellow]",
        "  - [dim]__init__.py[/dim] files",
        "  - Non-.py files",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "",
        "  [red]Bad -- bare POSIX import:[/red]",
        "  [dim]import fcntl[/dim]",
        "  [dim]fcntl.flock(fd, fcntl.LOCK_EX)[/dim]",
        "",
        "  [red]Bad -- unguarded os.WNOHANG:[/red]",
        "  [dim]pid, _ = os.waitpid(-1, os.WNOHANG)[/dim]",
        "",
        "  [red]Bad -- os.kill without exception handling:[/red]",
        "  [dim]os.kill(pid, 0)  # WinError 87 on Windows[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "",
        "  [green]Good -- platform-guarded import:[/green]",
        '  [dim]if sys.platform == "win32":[/dim]',
        "  [dim]    import msvcrt[/dim]",
        "  [dim]else:[/dim]",
        "  [dim]    import fcntl[/dim]",
        "",
        "  [green]Good -- try/except import:[/green]",
        "  [dim]try:[/dim]",
        "  [dim]    import fcntl[/dim]",
        "  [dim]except ImportError:[/dim]",
        "  [dim]    fcntl = None[/dim]",
        "",
        "  [green]Good -- guarded POSIX constant:[/green]",
        '  [dim]if sys.platform != "win32":[/dim]',
        "  [dim]    pid, _ = os.waitpid(-1, os.WNOHANG)[/dim]",
        "",
        "  [green]Good -- os.kill with OSError catch:[/green]",
        "  [dim]try:[/dim]",
        "  [dim]    os.kill(pid, 0)[/dim]",
        "  [dim]except OSError:[/dim]",
        "  [dim]    return False[/dim]",
        "",
        "  [green]Good -- hasattr guard for signal constants:[/green]",
        '  [dim]if hasattr(signal, "SIGPIPE"):[/dim]',
        "  [dim]    signal.signal(signal.SIGPIPE, signal.SIG_DFL)[/dim]",
        "",
        "[bold cyan]ADVISORY (not scored) -- lock race:[/bold cyan]",
        "  [dim]os.open(path, O_CREAT | O_EXCL)[/dim] against a file still being deleted",
        "  raises [red]PermissionError[/red] on Windows, not FileExistsError (CI 35192484222).",
        "  Info line when the FileExistsError handler's try lets PermissionError escape,",
        "  or when a retry loop retries on exists but gives up on PermissionError.",
        "  [green]Fix:[/green] poll PermissionError inside the wait; raise once the wait is spent.",
        "  [dim]Detail: windows_compat.md (Advisory section)[/dim]",
        "",
        "[bold cyan]ADVISORY (not scored) -- mock repr path, tests/:[/bold cyan]",
        "  [dim]str(lock) in ' '.join(str(c) for c in m.call_args_list)[/dim] -- a call's repr",
        "  doubles each backslash, so a Windows path is never in it (CI 35416653326).",
        "  [green]Fix:[/green] compare against the args: [dim]str(arg) for c in ... for arg in c.args[/dim]",
        "",
        "[bold cyan]WHY BY SHAPE:[/bold cyan]",
        "  A Linux run cannot observe a state POSIX lacks (delete pending) or a",
        "  spelling it never makes (backslash). On a POSIX value the bug has no input,",
        "  so the test passes. Windows-only behaviour is pinned statically.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Checks every .py file in the branch individually via AST parsing",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  One check per file (Windows compat)",
        "  [green]100[/green] = no unguarded POSIX-only patterns found",
        "  [red]0[/red] = one or more unguarded patterns found",
        "  Reports up to 3 offending line numbers with descriptions",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] -- supports standard, file-level,",
        "  and line-level bypass rules",
        "",
        "  [dim]Example bypass entry:[/dim]",
        '  [dim]{{"file": "apps/daemon.py", "standard": "windows_compat",[/dim]',
        '  [dim] "reason": "Daemon is Linux-only by design"}}[/dim]',
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (windows_compat)[/dim]",
        "  [dim]Checker: windows_compat_check.py[/dim]",
        "  [dim]Windows CI: .github/workflows/windows-test.yml[/dim]",
        "  [dim]Issue: #326 (Input-X Windows platform report)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "windows_compat"})
    return "\n".join(lines)
