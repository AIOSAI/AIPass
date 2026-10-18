# =================== AIPass ====================
# Name: verify.py
# Description: Plan Verification Module
# Version: 0.1.0
# Created: 2026-03-18
# Modified: 2026-10-17
# =============================================

"""
Plan Verification Module
"""

import subprocess
import json
import os
import sys
from typing import List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help
from aipass.memory.apps.handlers.repo_root import module_file

# ChromaDB runs in the memory venv's python, in a subprocess.
_HANDLERS_DIR = module_file(__file__).parent.parent / "handlers"
CHROMA_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "storage" / "chroma_subprocess.py"

_MEMORY_ROOT = module_file(__file__).parents[2]
_MEMORY_VENV_PYTHON = _MEMORY_ROOT / ".venv" / "bin" / "python"


def _get_memory_python() -> str:
    """Get the Python executable for memory ML operations."""
    env_override = os.environ.get("AIPASS_MEMORY_PYTHON")
    if env_override:
        return env_override
    if _MEMORY_VENV_PYTHON.exists():
        return str(_MEMORY_VENV_PYTHON)
    return sys.executable


def handle_command(command: str, args: List[str]) -> bool:
    """Handle verify commands: no args introspects, a help flag prints help, else check the plan."""
    # The entry point may send a bare help flag as the command.
    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command == "verify":
        if not args:
            print_introspection()
            return True

        # Bare `help` counts only in the first slot: a plan label is free text.
        if wants_help(args):
            print_help()
            return True

        plan_label = args[0]
        _verify_plan(plan_label)
        return True

    return False


def _check_plan_subprocess(plan_label: str) -> dict:
    """Check plan vectorization via chroma_subprocess: success, found, count, source_files."""
    python_path = _get_memory_python()
    input_data = json.dumps(
        {
            "operation": "check_plan",
            "plan_label": plan_label,
        }
    )

    try:
        result = subprocess.run(
            [python_path, str(CHROMA_SUBPROCESS_SCRIPT)], input=input_data, capture_output=True, text=True, timeout=60
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Subprocess failed"}

        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.warning("[verify] Plan check subprocess timed out")
        return {"success": False, "error": "Check operation timed out"}
    except json.JSONDecodeError as e:
        logger.warning(f"[verify] Invalid JSON from plan check subprocess: {e}")
        return {"success": False, "error": f"Invalid JSON response: {e}"}
    except Exception as e:
        logger.error(f"[verify] Plan check subprocess failed: {e}")
        return {"success": False, "error": str(e)}


def is_plan_vectorized(plan_label: str) -> dict:
    """Check if a plan has been vectorized in ChromaDB (programmatic API for other modules)."""
    return _check_plan_subprocess(plan_label)


def _verify_plan(plan_label: str) -> None:
    """Verify a plan's vectorization status and display the result."""
    result = _check_plan_subprocess(plan_label)

    if not result.get("success"):
        error(result.get("error", "Unknown error"))
        json_handler.log_operation("verify_plan", {"plan_label": plan_label, "success": False})
        return

    found = result.get("found", False)
    count = result.get("count", 0)

    console.print()
    if found:
        console.print(f"  Plan {plan_label}: [green]Vectorized[/green] ({count} chunks)")
    else:
        warning(f"Plan {plan_label}: NOT vectorized")
    console.print()

    json_handler.log_operation(
        "verify_plan",
        {
            "plan_label": plan_label,
            "found": found,
            "count": count,
            "success": True,
        },
    )


def _discover_handlers() -> dict[str, list[str]]:
    """Map each handler directory to its .py files (excluding __init__.py)."""
    handlers_dir = module_file(__file__).parent.parent / "handlers"
    result: dict[str, list[str]] = {}
    if not handlers_dir.exists():
        return result
    for d in sorted(handlers_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("__"):
            continue
        py_files = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix == ".py" and f.name != "__init__.py")
        if py_files:
            result[d.name] = py_files
    return result


def print_introspection() -> None:
    """Display module introspection info (seedgo standard)."""
    console.print()
    console.print("[bold cyan]verify Module[/bold cyan]")
    console.print("Checks whether a plan has been vectorized in ChromaDB")
    console.print()

    handlers = _discover_handlers()
    console.print("[yellow]Connected Handlers:[/yellow]")
    if handlers:
        for dir_name, files in handlers.items():
            file_list = ", ".join(files)
            console.print(f"  [cyan]handlers/{dir_name}/[/cyan]  [dim]{file_list}[/dim]")
    else:
        console.print("  [dim]No handlers found[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory verify FPLAN-0126[/green]     [dim]# Check if plan is vectorized[/dim]")
    console.print("  [green]drone @memory verify --help[/green]         [dim]# Full usage guide[/dim]")
    console.print()


def print_help() -> None:
    """Display verify module help."""
    console.print()
    console.print("[bold cyan]Verify Module - Plan Vectorization Check[/bold cyan]")
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory verify <plan_label>")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  [cyan]verify <plan_label>[/cyan]   Check if a plan is vectorized in ChromaDB")
    console.print("  [cyan]help[/cyan]                  Show this help message")
    console.print()
    console.print("[bold]EXAMPLES:[/bold]")
    console.print("  [dim]drone @memory verify FPLAN-0126[/dim]")
    console.print("  [dim]drone @memory verify HPLAN-0001[/dim]")
    console.print()
    console.print("[bold]HOW IT WORKS:[/bold]")
    console.print("  1. Query the flow_plans ChromaDB collection")
    console.print("  2. Filter entries by source_file metadata matching the plan label")
    console.print("  3. Report vectorization status and chunk count")
    console.print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        handle_command("verify", [])
        sys.exit(0)

    if sys.argv[1] in ("--help", "-h", "help"):
        handle_command("verify", ["--help"])
        sys.exit(0)

    command = sys.argv[1]
    if not handle_command(command, sys.argv[2:]):
        error(f"Unknown command: {command}", suggestion="Run 'drone @memory verify --help' for available commands")
        sys.exit(1)
