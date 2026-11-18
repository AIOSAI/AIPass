# =================== AIPass ====================
# Name: fixed_depth_path_content.py
# Description: Fixed Depth Path Standards Content Handler
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""Fixed Depth Path Standards Content Handler"""

from aipass.sentry.apps.handlers.json import json_handler


def get_fixed_depth_path_standards() -> str:
    """Return formatted fixed_depth_path standards content with Rich markup."""
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  AIPass ships as a wheel. Installed, a module sits in site-packages, not in a",
        "  checkout: a home found by climbing a fixed number of folders up from the file",
        "  is right in the repo and wrong on every installed machine.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  A climb -- .parents[n], .parent, os.path.dirname -- off __file__,",
        "  aipass.<x>.__file__ or find_spec('aipass...').origin, also through a name bound",
        "  to one (HERE = Path(__file__).parent; HERE.parents[4]), also into the files of the",
        "  SAME branch that import that name (the finding names where it was counted).",
        "  Each site is convicted:",
        "",
        "  1. [red]Leaves the package[/red]: the climb goes above src/aipass. On a wheel that",
        "     is site-packages or the interpreter's lib directory.",
        "  2. [red]Unshipped name[/red]: a climb joined to a dot name, logs, system_logs, *_json,",
        "     or a name the repo .gitignore lists there. The wheel never ships them: on a",
        "     wheel this state is written inside the installed package.",
        "",
        "[bold cyan]WHAT PASSES:[/bold cyan]",
        "  - a climb that stays inside src/aipass and names shipped files (templates, data)",
        "  - a climb from a parameter (Path(file).parents[3]) or through '..': not read",
        "  - a file outside src/aipass: not in the wheel",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  [green]Good -- the home from a resolver (env, registry walk):[/green]",
        "  [dim]HOME = Path(os.environ['AIPASS_HOME'])[/dim]",
        "  [green]Good -- package data next to the module:[/green]  [dim]Path(__file__).parent / 'data.json'[/dim]",
        "  [red]Bad:[/red]  [dim]REPO = Path(__file__).resolve().parents[5][/dim]",
        "  [red]Bad:[/red]  [dim]LOGS = Path(__file__).parents[3] / 'logs'[/dim]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold], APPLIES_TO = [bold]production[/bold]",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  One finding per site (line, enclosing function). [green]100[/green] = none,",
        "  [red]0[/red] = any unwaived site. A file Python cannot parse scores 0, unjudged.",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  A lines or functions rule in the owning branch's [dim].sentry/bypass.json[/dim],",
        "  with the reason; a rule with neither waives the whole file.",
        '  [dim]{{"file": "x.py", "standard": "fixed_depth_path", "lines": [20],[/dim]',
        '  [dim] "reason": "..."}}[/dim]',
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Checker: fixed_depth_path_check.py  Doc: fixed_depth_path.md[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "fixed_depth_path"})
    return "\n".join(lines)
