# =================== AIPass ====================
# Name: host_portability_content.py
# Description: Host Portability Standards Content Handler
# Version: 1.7.0
# Created: 2026-09-12
# Modified: 2026-11-14
# =============================================

"""
Host Portability Standards Content Handler

Provides formatted Host Portability standards content.
Module orchestrates, handler implements.
"""

from aipass.sentry.apps.handlers.json import json_handler


def get_host_portability_standards() -> str:
    """Return formatted host_portability standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Code must run on every Linux host it is handed: a container, a CI",
        "  runner, another Python, a sandbox. Each arm below is an assumption",
        "  about the author's own seat that another host does not share.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Parses every [dim]apps/[/dim], [dim]tests/[/dim] and [dim]lib/[/dim] Python file",
        "  with [dim]ast.parse()[/dim]. All arms SCORE.",
        "",
        "  [red]ARM B -- assumed non-portable binary[/red]",
        "     A [dim]subprocess.run/Popen/check_output/call/check_call[/dim] whose",
        "     argv[0] is a bare literal in the curated list:",
        "     [dim]tmux, systemctl, loginctl, sysctl, gnome-terminal,[/dim]",
        "     [dim]xfce4-terminal, konsole, xterm[/dim].",
        "     A missing binary raises [yellow]FileNotFoundError[/yellow] out of exec,",
        "     so [dim]check=False[/dim] does NOT help.",
        "",
        "  [red]ARM D -- a direct pathlib.Path subclass (the host's Python)[/red]",
        "     [dim]class X(Path)[/dim] or [dim]class X(PurePath)[/dim] with no [dim]_flavour[/dim]:",
        "     [yellow]AttributeError _flavour[/yellow] on 3.10 and 3.11, fine on 3.12+.",
        "     A concrete flavour ([dim]PurePosixPath[/dim]) is acquitted.",
        "",
        "  [red]ARM E -- a resolved path compared with one taken as given[/red]",
        "     In one function, [dim]==[/dim] / [dim]!=[/dim] / [dim]in x.parents[/dim] /",
        "     [dim]relative_to[/dim] / [dim]is_relative_to[/dim] / [dim]startswith[/dim] with one side",
        "     through [dim].resolve()[/dim] or [dim]os.path.realpath[/dim] and the other from",
        "     [dim]Path.home()[/dim], [dim]Path.cwd()[/dim], [dim]os.getcwd()[/dim] or [dim]tempfile[/dim] as given.",
        "     Followed through same-function names, [dim]/[/dim], [dim].parent[/dim], [dim]str()[/dim],",
        "     and same-file helpers (hooks loader: aipass_home -> _absolute -> resolve).",
        "     A home or temp dir reached through a symlink makes the two differ. Cure: resolve both.",
        "",
        "  [red]ARM F -- git's config emptied with no commit email (file-local)[/red]",
        "     A file naming [dim]GIT_CONFIG_GLOBAL[/dim] or [dim]GIT_CONFIG_NOSYSTEM[/dim] also names",
        "     [dim]GIT_AUTHOR_EMAIL[/dim] and [dim]GIT_COMMITTER_EMAIL[/dim], or a [dim]user.email[/dim].",
        "     A runner has no email to auto-detect: [yellow]git commit exits 128[/yellow].",
        "",
        "  [red]ARM G -- a stdlib import newer than pyproject's requires-python floor[/red]",
        "     [dim]import tomllib[/dim] (3.11) under a 3.10 floor: its except branch runs only on",
        "     the floor's CI lane. Acquitted when the same try/if imports [dim]tomli[/dim].",
        "",
        "  [red]ARM H -- a .git existence test an empty directory passes (product code)[/red]",
        '     [dim](x / ".git").exists()[/dim] / [dim].is_dir()[/dim]: a sandbox mounts an empty .git',
        "     in each writable root. Acquitted when the function reads .git/HEAD or lists .git.",
        "     Cure: [dim]m.is_file() or (m.is_dir() and any(m.iterdir()))[/dim].",
        "",
        "  [yellow]Valid guards for Arm B (checker recognizes):[/yellow]",
        "  - [dim]try: ... except OSError / FileNotFoundError / Exception:[/dim]",
        "  - [dim]with pytest.raises(FileNotFoundError):[/dim] (or OSError) -- the",
        "    missing binary raises what the test expects",
        "  - [dim]shutil.which('tmux')[/dim] in the same function",
        "",
        "  [yellow]Deliberately NOT guards:[/yellow]",
        "  - [dim]check=False[/dim] on a subprocess call (wrong failure mode)",
        "",
        "  [yellow]Skips:[/yellow]",
        "  - dynamic argv[0] (a variable, an f-string, a starred element) -- the",
        "    invisible spelling is usually the CURE",
        "  - portable binaries: [dim]git, bash, sh, drone, python3, sleep, gh,[/dim]",
        "    [dim]ps, lsof, pgrep, npm, ruff[/dim]",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "",
        "  [red]Bad -- a binary that is not everywhere:[/red]",
        '  [dim]subprocess.run(["tmux", "kill-session", "-t", name], check=False)[/dim]',
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "",
        "  [green]Good -- probe the binary first:[/green]",
        '  [dim]if not shutil.which("tmux"):[/dim]',
        "  [dim]    return False[/dim]",
        '  [dim]subprocess.run(["tmux", "kill-session", "-t", name], check=False)[/dim]',
        "",
        "  [green]Good -- catch the exec failure:[/green]",
        "  [dim]try:[/dim]",
        '  [dim]    subprocess.run(["systemctl", "--user", "enable", unit])[/dim]',
        "  [dim]except (OSError, subprocess.SubprocessError) as exc:[/dim]",
        '  [dim]    logger.info("systemctl unavailable: %s", exc)[/dim]',
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Corpus is [bold]apps/, tests/ AND lib/[/bold] -- the per-file lane never",
        "  enters tests/, most failures this exists to prevent were tests,",
        "  and skills keeps its seven built-in skills in lib/",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  [bold]clean files / total files x 100[/bold] -- the same number the",
        "  all_files lane produces by averaging a 100-or-0 per file",
        "  [green]100[/green] = no unguarded host assumptions anywhere",
        "  Reports up to 3 offending file:line rows with descriptions",
        "  A second [dim]passed: True[/dim] line counts the binary calls that ALREADY",
        "  carry a guard -- context, never scored",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].sentry/bypass.json[/dim] -- supports standard, file-level,",
        "  and line-level bypass rules",
        "",
        "  [dim]Example bypass entry:[/dim]",
        '  [dim]{{"file": "apps/handlers/systemd_unit.py", "standard": "host_portability",[/dim]',
        '  [dim] "reason": "systemd integration, needs systemctl by design"}}[/dim]',
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: sentry standards pack (host_portability)[/dim]",
        "  [dim]Checker: host_portability_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "host_portability"})
    return "\n".join(lines)
