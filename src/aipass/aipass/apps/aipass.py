# =================== AIPass ====================
# Name: aipass.py
# Description: AIPASS branch entry point — thin command router
# Version: 0.5.2
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""
AIPASS Branch - Main Orchestrator
"""

import os
import sys
import importlib
import importlib.metadata
from pathlib import Path
from typing import List, Any

# Windows streams default to cp1252 and cannot encode Rich's glyphs; PYTHONUTF8 only
# reaches child interpreters, so the live streams are reconfigured too (as drone/cli.py).
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")  # for child subprocesses
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.cli.apps.modules import console, error, resolve_exit, warning
from aipass.prax import logger

try:
    import tomllib  # type: ignore[import-not-found]  # Python 3.11+, absent on 3.10
except ModuleNotFoundError:  # pragma: no cover — Python 3.10
    try:
        import tomli as tomllib  # type: ignore[no-redef]

        logger.info("[AIPASS] tomllib unavailable (Python 3.10), using tomli")
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]
        logger.info("[AIPASS] tomllib/tomli unavailable, pyproject version read disabled")


_PUBLIC_COMMANDS = {
    "adopt": "Turn an existing projects/ directory into a full project",
    "baud": "Install the baud phone face from a release",
    "doctor": "System health — structure, registry, hooks, tests",
    "handoff": "Launch your CLI in a new session",
    "help": "README-backed Q&A — ask about any branch",
    "init": "Guided setup — 'init run' walks the 10 stages, resumable",
    "install": "One-command bootstrap — clone, setup.sh, hooks, welcome chat",
    "new": "Create a project inside AIPass",
    "profile": "Show/edit user profile",
    "read": "View a branch README, rendered in the terminal",
    "trust": "Trust registry — enroll/revoke projects",
    "feedback": "Toggle the feedback reminder on/off",
}


def _pyproject_version(start: Path) -> str | None:
    """Version from the repo's own pyproject.toml, walking up from `start`.

    Editable installs freeze metadata at install time; the repo tree is the live version.
    """
    if tomllib is None:
        logger.info("[AIPASS] tomllib/tomli unavailable, skipping pyproject version read")
        return None

    for parent in start.resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.exists():
            continue
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            logger.warning(f"[AIPASS] Could not parse {pyproject}: {e}")
            continue
        project = data.get("project", {})
        # Name guard: nested projects carry their own pyproject — keep walking
        if project.get("name") == "aipass" and project.get("version"):
            return str(project["version"])
    return None


def _installed_version() -> str:
    """``importlib.metadata.version("aipass")``, unchanged.

    A seam: the test stands in an install with no metadata here, not process-wide.
    """
    return importlib.metadata.version("aipass")


def _resolve_version() -> str:
    """Live version — repo pyproject.toml first, installed metadata as fallback."""
    version = _pyproject_version(Path(__file__))
    if version:
        return version
    try:
        return _installed_version()
    except importlib.metadata.PackageNotFoundError:
        logger.info("[AIPASS] No repo pyproject.toml and no package metadata, version unknown")
        return "unknown"


MODULES_DIR = Path(__file__).parent / "modules"


_import_failures: dict[str, Exception] = {}


def _import_module(name: str) -> Any:
    """``importlib.import_module(name)``, unchanged.

    A seam: every real module has handle_command, so the test reaches the skip branch here.
    """
    return importlib.import_module(name)


def discover_modules() -> List[Any]:
    """Auto-discover modules in modules/ directory."""
    modules = []
    _import_failures.clear()

    if not MODULES_DIR.exists():
        return modules

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = f"aipass.aipass.apps.modules.{file_path.stem}"

        try:
            module = _import_module(module_name)
            if hasattr(module, "handle_command"):
                modules.append(module)
        except Exception as e:
            logger.error(f"[AIPASS] Failed to load module {module_name}: {e}")
            _import_failures[file_path.stem] = e

    return modules


def print_introspection(modules: List[Any] | None = None) -> None:
    """Bare invocation — title, purpose, public commands, --help pointer."""
    console.print()
    console.print("[bold cyan]AIPASS — Concierge & Setup[/bold cyan]")
    console.print("[dim]The friendly front door for AIPass. Setup, diagnostics, documentation, project creation.[/dim]")
    console.print()

    if modules is None:
        modules = discover_modules()

    commands = []
    for module in modules:
        name = getattr(module, "COMMAND", None)
        if name and name in _PUBLIC_COMMANDS:
            commands.append((name, _PUBLIC_COMMANDS[name]))
    commands.sort()

    if commands:
        console.print("[yellow]Commands:[/yellow]")
        for name, desc in commands:
            console.print(f"  [green]{name:16}[/green] [dim]{desc}[/dim]")
        console.print()

    console.print("[dim]Run 'aipass --help' for usage and examples[/dim]")
    console.print()


def print_help(modules: List[Any] | None = None) -> None:
    """Full help — usage, commands, examples."""
    console.print()
    console.print("[bold cyan]AIPASS — Concierge & Setup[/bold cyan]")
    console.print("[dim]The friendly front door for AIPass. Setup, diagnostics, documentation, project creation.[/dim]")
    console.print()

    console.print("[yellow]Usage:[/yellow]")
    console.print("  [green]aipass[/green] [dim]<command>[/dim] [dim]\\[options][/dim]")
    console.print("  [green]aipass[/green]                       [dim]Show commands[/dim]")
    console.print("  [green]aipass[/green] [dim]<command>[/dim] [dim]--help[/dim]     [dim]Help for a command[/dim]")
    console.print()

    console.print("[yellow]Commands:[/yellow]")
    console.print("  [green]baud install[/green]                 [dim]Install the baud phone face from a release[/dim]")
    console.print("  [green]baud status[/green]                  [dim]Installed phone face, where @api points[/dim]")
    console.print(
        "  [green]doctor[/green]                       [dim]System health — structure, registry, hooks, tests[/dim]"
    )
    console.print("  [green]doctor --fix[/green]                 [dim]Remediation report with repair commands[/dim]")
    console.print("  [green]doctor --fix --json[/green]          [dim]The remediation report as JSON[/dim]")
    console.print("  [green]doctor --cross-os[/green]            [dim]Cross-OS pre-flight check[/dim]")
    console.print(
        "  [green]feedback[/green] [dim]\\[on|off][/dim]            [dim]Toggle the feedback reminder pulse[/dim]"
    )
    console.print(
        "  [green]handoff[/green] [dim]\\[launch][/dim]             [dim]Launch your CLI in a new session[/dim]"
    )
    console.print("  [green]help <question>[/green]              [dim]Search branch documentation (Q&A)[/dim]")
    console.print("  [green]init run[/green]                     [dim]The 10-stage guided setup, resumable[/dim]")
    console.print("  [green]install[/green]                      [dim]Bootstrap — clone, setup.sh, hooks, chat[/dim]")
    console.print("  [green]new <name>[/green]                   [dim]Create a project inside AIPass[/dim]")
    console.print(
        "  [green]adopt <name>[/green]                 "
        "[dim]Turn an existing projects/ directory into a full project[/dim]"
    )
    console.print("  [green]profile[/green]                      [dim]Show/edit user profile[/dim]")
    console.print(
        "  [green]read <branch>[/green]                [dim]View a branch README, rendered in the terminal[/dim]"
    )
    console.print(
        "  [green]trust[/green] [dim]\\[path][/dim]                 "
        "[dim]Trust registry — show it, or enroll a project[/dim]"
    )
    console.print("  [green]revoke <path>[/green]                [dim]Remove a project from the trust registry[/dim]")
    console.print("  [green]--version[/green]                    [dim]Show version[/dim]")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  [green]aipass doctor[/green]                       [dim]Check system health[/dim]")
    console.print("  [green]aipass help what does drone do[/green]      [dim]Search documentation[/dim]")
    console.print("  [green]aipass new myapp --template python[/green]  [dim]Create a Python project[/dim]")
    console.print("  [green]aipass adopt myapp --dry-run[/green]        [dim]Preview adopting projects/myapp[/dim]")
    console.print("  [green]aipass init run[/green]                     [dim]Start guided setup[/dim]")
    console.print()


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module.

    Raises on a crash (False means not found); main() logs it, a log call here could mask it.
    """
    for module in modules:
        if module.handle_command(command, args):
            return True
    return False


def _log_crash(message: str) -> None:
    """Log the crash being handled, with its traceback; never raise from the log itself.

    A handler that raises from its own logging (an unwritable log home) hides the user's error.
    """
    try:
        logger.error(message, exc_info=True)
    except OSError as exc:
        warning(f"(this crash could not be written to the log: {exc})")


def main():
    """Main entry point - routes commands or shows help.

    Exit codes: 0 clean; 2 a module reported through error(); 1 unknown command, crash
    or load failure. No success path returns 1.
    """
    modules = discover_modules()
    args = sys.argv[1:]

    if len(args) > 0 and args[0] in ["--version", "-V"]:
        console.print(f"aipass {_resolve_version()}")
        return 0

    if not args:
        print_introspection(modules)
        return 0

    if args[0] in ("--help", "-h"):
        print_help(modules)
        return 0

    command = args[0]
    remaining = args[1:] if len(args) > 1 else []

    # --help in ANY position answers before dispatch: a help probe must never run the
    # verb (`aipass trust <dir> --help` would enroll the dir).
    if any(a in ("--help", "-h") for a in remaining):
        for module in modules:
            if module.handle_command(command, ["--help"]):
                return 0
        console.print(f"Unknown command: {command}")
        return 1

    # A module that reports through error() and returns True failed: resolve_exit makes it 2.
    try:
        if route_command(command, remaining, modules):
            return resolve_exit(True)
    except Exception as e:
        error(f"'{command}' crashed: {e}")
        _log_crash(f"[AIPASS] '{command}' traceback")
        return 1

    if command.startswith("@"):
        console.print(f"{command} is a drone routing target, not an aipass command.")
        console.print("aipass is your front-door CLI; drone is the agent router — two separate tools.")
        console.print()
        console.print(f"  Reach an agent:   drone {command} ...   ·  drone systems")
        console.print("  aipass commands:  aipass --help")
        return 1

    for stem, err in _import_failures.items():
        if command in (stem, stem.replace("_", "")):
            error(f"'{command}' failed to load: {err}")
            return 1

    # Multi-word plain input reads as a question; anything with flags stays Unknown command.
    if remaining and not command.startswith("-") and all(not a.startswith("-") for a in remaining):
        question = [command, *remaining]
        console.print(f"[dim]No command '{command}' — answering as: aipass help {' '.join(question)}[/dim]")
        try:
            if route_command("help", question, modules):
                return resolve_exit(True)
        except Exception as e:
            error(f"help crashed: {e}")
            _log_crash("[AIPASS] catch-all help traceback")
            return 1

    console.print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
