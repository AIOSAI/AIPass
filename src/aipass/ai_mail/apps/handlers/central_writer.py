# =================== AIPass ====================
# Name: central_writer.py
# Description: AI_MAIL Central File Writer
# Version: 1.2.0
# Created: 2025-11-27
# Modified: 2026-10-17
# =============================================

"""
Central Writer Handler

Aggregates branch inbox stats into AI_MAIL.central.json for the dashboard.
"""

# Load stdlib json via importlib: the local handlers/json/ package shadows it on sys.path.
import os
import sys
import importlib.util

_saved_path = sys.path.copy()
sys.path = [p for p in sys.path if "handlers" not in p]
spec = importlib.util.find_spec("json")
if spec is None or spec.loader is None:
    raise ImportError("Failed to find stdlib json module")
stdlib_json = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stdlib_json)
sys.path = _saved_path

from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


_REPO_ROOT = find_repo_root()
AI_CENTRAL_DIR = _REPO_ROOT / ".ai_central"
CENTRAL_FILE = AI_CENTRAL_DIR / "AI_MAIL.central.json"

# Archive/output subtrees pruned from the walk, matched as exact path components (a substring hid real branches).
# Never reuse seedgo's skip list: it names .ai_mail.local, which this walk must find.
EXCLUDED_DIR_NAMES = frozenset({".backup", ".archive", "backups", "dropbox", "docs.local", "artifacts", "system_logs"})
BRANCH_REGISTRY = _REPO_ROOT / "AIPASS_REGISTRY.json"


def _raise_walk_error(err: OSError) -> None:
    """os.walk's onerror hook: a directory it cannot list is raised, not skipped.

    A stale central file is honest; counts over a partly unread tree are not.
    """
    raise err


def find_all_inbox_files() -> List[Path]:
    """Find all inbox.json files in .ai_mail.local directories.

    Prunes excluded subtrees, not results: this runs on every delivery, and a full walk times out broadcasts.
    """
    inbox_files = []

    for dirpath, dirnames, _filenames in os.walk(_REPO_ROOT, onerror=_raise_walk_error):
        # Mutating dirnames in place is what stops os.walk descending.
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]

        if ".ai_mail.local" not in dirnames:
            continue

        inbox_path = Path(dirpath) / ".ai_mail.local" / "inbox.json"
        if inbox_path.is_file():
            inbox_files.append(inbox_path)

    return inbox_files


def extract_branch_name(inbox_path: Path) -> str:
    """Extract branch name from inbox.json path."""
    branch_dir = inbox_path.parent.parent
    branch_name = branch_dir.name.upper()

    return branch_name


def read_inbox_stats(inbox_path: Path) -> Tuple[int, int]:
    """Read unread and total message counts from inbox.json."""
    with open(inbox_path, "r", encoding="utf-8") as f:
        inbox_data = stdlib_json.load(f)

    unread = inbox_data.get("unread_count", 0)
    total = inbox_data.get("total_messages", 0)

    return (unread, total)


def get_valid_branch_names() -> set:
    """Load valid branch names from AIPASS_REGISTRY.json."""
    with open(BRANCH_REGISTRY, "r", encoding="utf-8") as f:
        registry_data = stdlib_json.load(f)

    return {branch["name"].upper() for branch in registry_data.get("branches", [])}


def aggregate_branch_stats() -> Dict[str, Dict[str, int]]:
    """Aggregate inbox stats for all branches."""
    branch_stats = {}

    inbox_files = find_all_inbox_files()
    valid_branches = get_valid_branch_names()

    for inbox_path in inbox_files:
        try:
            branch_name = extract_branch_name(inbox_path)

            if branch_name not in valid_branches:
                continue

            unread, total = read_inbox_stats(inbox_path)

            branch_stats[branch_name] = {"unread": unread, "total": total}
        except (FileNotFoundError, stdlib_json.JSONDecodeError, KeyError) as e:
            logger.warning("[central] Skipping branch inbox %s: %s", inbox_path, e)
            continue
        except Exception as e:
            raise RuntimeError(f"Failed to process {inbox_path}: {e}") from e

    return branch_stats


def calculate_system_totals(branch_stats: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    """Calculate system-wide totals from branch stats."""
    total_unread = sum(stats["unread"] for stats in branch_stats.values())
    total_messages = sum(stats["total"] for stats in branch_stats.values())

    return {"total_unread": total_unread, "total_messages": total_messages}


def build_central_data(branch_stats: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
    """Build complete central.json data structure."""
    system_totals = calculate_system_totals(branch_stats)

    return {
        "service": "ai_mail",
        "last_updated": datetime.now().date().isoformat(),  # Date only - avoids phantom git changes
        "branch_stats": branch_stats,
        "system_totals": system_totals,
    }


def write_central_file(data: Dict[str, Any]) -> None:
    """Write data to AI_MAIL.central.json."""
    AI_CENTRAL_DIR.mkdir(parents=True, exist_ok=True)

    with open(CENTRAL_FILE, "w", encoding="utf-8") as f:
        stdlib_json.dump(data, f, indent=2, ensure_ascii=False)


def update_central() -> Dict[str, Any]:
    """Update AI_MAIL.central.json with current branch inbox stats."""
    json_handler.log_operation("update_central", {"target": str(CENTRAL_FILE)})

    branch_stats = aggregate_branch_stats()

    central_data = build_central_data(branch_stats)

    write_central_file(central_data)

    return central_data


if __name__ == "__main__":
    # Only the test harness may import CLI libraries.
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    console.print()
    console.print(Panel.fit("[bold cyan]AI_MAIL Central Writer[/bold cyan]", border_style="bright_blue"))
    console.print()

    try:
        console.print("[yellow]Scanning branches...[/yellow]")
        stats = update_central()

        console.print(f"[green]Updated:[/green] {CENTRAL_FILE}")
        console.print()

        table = Table(title="Branch Mail Statistics")
        table.add_column("Branch", style="cyan", no_wrap=True)
        table.add_column("Unread", justify="right", style="yellow")
        table.add_column("Total", justify="right", style="blue")

        for branch, data in sorted(stats["branch_stats"].items()):
            table.add_row(branch, str(data["unread"]), str(data["total"]))

        table.add_section()
        table.add_row(
            "[bold]SYSTEM TOTALS[/bold]",
            f"[bold yellow]{stats['system_totals']['total_unread']}[/bold yellow]",
            f"[bold blue]{stats['system_totals']['total_messages']}[/bold blue]",
        )

        console.print(table)
        console.print()

    except Exception as e:
        from aipass.cli.apps.modules import error as cli_error

        cli_error(f"Error: {e}")
        raise
