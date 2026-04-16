# =================== AIPass ====================
# Name: central_writer.py
# Description: AI_MAIL Central File Writer
# Version: 1.0.0
# Created: 2025-11-27
# Modified: 2025-11-27
# =============================================

"""
Central Writer Handler

Aggregates branch inbox stats and writes to AI_MAIL.central.json.
This file serves as AI_MAIL's API output for AIPASS dashboard integration.

Architecture:
- Scans all .ai_mail.local/inbox.json files across the system
- Calculates per-branch unread/total message counts
- Writes aggregated stats to AI_CENTRAL/AI_MAIL.central.json (under repo root)
"""

# CRITICAL: Use importlib to bypass local json/ directory and get stdlib json
import sys
import importlib.util

# Remove current directory from sys.path temporarily to import stdlib json
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


# =============================================================================
# CONSTANTS
# =============================================================================

_REPO_ROOT = find_repo_root()
AI_CENTRAL_DIR = _REPO_ROOT / ".ai_central"
CENTRAL_FILE = AI_CENTRAL_DIR / "AI_MAIL.central.json"
BRANCH_REGISTRY = _REPO_ROOT / "AIPASS_REGISTRY.json"


# =============================================================================
# CORE FUNCTIONS
# =============================================================================


def find_all_inbox_files() -> List[Path]:
    """
    Find all inbox.json files in .ai_mail.local directories.

    Scans the repo root directory for .ai_mail.local/inbox.json files.
    Excludes backup directories to avoid counting archived data.

    Returns:
        List of Path objects to inbox.json files

    Raises:
        OSError: If filesystem scan fails
    """
    inbox_files = []

    # Search pattern: any directory ending in .ai_mail.local containing inbox.json
    for ai_mail_dir in _REPO_ROOT.rglob(".ai_mail.local"):
        # Skip backup/archive directories (but NOT backup branch itself)
        path_str = str(ai_mail_dir)
        if ".backup" in path_str or ".archive" in path_str or "/backups/" in path_str:
            continue

        inbox_path = ai_mail_dir / "inbox.json"
        if inbox_path.exists() and inbox_path.is_file():
            inbox_files.append(inbox_path)

    return inbox_files


def extract_branch_name(inbox_path: Path) -> str:
    """
    Extract branch name from inbox.json path.

    Given: .../seedgo/.ai_mail.local/inbox.json
    Returns: SEEDGO

    Given: .../prax/.ai_mail.local/inbox.json
    Returns: PRAX

    Args:
        inbox_path: Path to inbox.json file

    Returns:
        Uppercase branch name
    """
    # Parent of .ai_mail.local is the branch directory
    branch_dir = inbox_path.parent.parent
    branch_name = branch_dir.name.upper()

    return branch_name


def read_inbox_stats(inbox_path: Path) -> Tuple[int, int]:
    """
    Read unread and total message counts from inbox.json.

    Args:
        inbox_path: Path to inbox.json file

    Returns:
        Tuple of (unread_count, total_messages)

    Raises:
        FileNotFoundError: If inbox.json doesn't exist
        json.JSONDecodeError: If inbox.json is malformed
        KeyError: If required fields are missing
    """
    with open(inbox_path, "r", encoding="utf-8") as f:
        inbox_data = stdlib_json.load(f)

    unread = inbox_data.get("unread_count", 0)
    total = inbox_data.get("total_messages", 0)

    return (unread, total)


def get_valid_branch_names() -> set:
    """
    Load valid branch names from AIPASS_REGISTRY.json.

    Returns:
        Set of uppercase branch names that are registered in the system.

    Raises:
        FileNotFoundError: If AIPASS_REGISTRY.json doesn't exist
        json.JSONDecodeError: If AIPASS_REGISTRY.json is malformed
    """
    with open(BRANCH_REGISTRY, "r", encoding="utf-8") as f:
        registry_data = stdlib_json.load(f)

    return {branch["name"].upper() for branch in registry_data.get("branches", [])}


def aggregate_branch_stats() -> Dict[str, Dict[str, int]]:
    """
    Aggregate inbox stats for all branches.

    Scans all branch inbox files and compiles per-branch statistics.
    Only includes branches that are registered in AIPASS_REGISTRY.json.

    Returns:
        Dict mapping branch names to their stats:
        {
            "SEEDGO": {"unread": 5, "total": 8},
            "DRONE": {"unread": 0, "total": 3}
        }

    Raises:
        OSError: If filesystem operations fail
        json.JSONDecodeError: If any inbox.json is malformed
    """
    branch_stats = {}

    inbox_files = find_all_inbox_files()
    valid_branches = get_valid_branch_names()

    for inbox_path in inbox_files:
        try:
            branch_name = extract_branch_name(inbox_path)

            # Skip branches not in BRANCH_REGISTRY
            if branch_name not in valid_branches:
                continue

            unread, total = read_inbox_stats(inbox_path)

            branch_stats[branch_name] = {"unread": unread, "total": total}
        except (FileNotFoundError, stdlib_json.JSONDecodeError, KeyError) as e:
            # Skip branches with missing/malformed inbox files
            # Continue processing other branches
            logger.warning("[central] Skipping branch inbox %s: %s", inbox_path, e)
            continue
        except Exception as e:
            # Handler tier 3: raise unexpected errors for caller to handle
            raise RuntimeError(f"Failed to process {inbox_path}: {e}") from e

    return branch_stats


def calculate_system_totals(branch_stats: Dict[str, Dict[str, int]]) -> Dict[str, int]:
    """
    Calculate system-wide totals from branch stats.

    Args:
        branch_stats: Per-branch statistics

    Returns:
        Dict with total_unread and total_messages:
        {"total_unread": 5, "total_messages": 11}
    """
    total_unread = sum(stats["unread"] for stats in branch_stats.values())
    total_messages = sum(stats["total"] for stats in branch_stats.values())

    return {"total_unread": total_unread, "total_messages": total_messages}


def build_central_data(branch_stats: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
    """
    Build complete central.json data structure.

    Args:
        branch_stats: Per-branch statistics

    Returns:
        Complete data structure ready for JSON serialization
    """
    system_totals = calculate_system_totals(branch_stats)

    return {
        "service": "ai_mail",
        "last_updated": datetime.now().date().isoformat(),  # Date only - avoids phantom git changes
        "branch_stats": branch_stats,
        "system_totals": system_totals,
    }


def write_central_file(data: Dict[str, Any]) -> None:
    """
    Write data to AI_MAIL.central.json.

    Args:
        data: Complete central file data structure

    Raises:
        OSError: If file write fails
        PermissionError: If insufficient permissions
    """
    # Ensure AI_CENTRAL directory exists
    AI_CENTRAL_DIR.mkdir(parents=True, exist_ok=True)

    with open(CENTRAL_FILE, "w", encoding="utf-8") as f:
        stdlib_json.dump(data, f, indent=2, ensure_ascii=False)


# =============================================================================
# PUBLIC API
# =============================================================================


def update_central() -> Dict[str, Any]:
    """
    Update AI_MAIL.central.json with current branch inbox stats.

    This is the primary public function for updating central statistics.
    Should be called whenever mail is sent/received to keep dashboard in sync.

    Process:
    1. Scans all branch .ai_mail.local/inbox.json files
    2. Aggregates unread and total message counts per branch
    3. Calculates system-wide totals
    4. Writes results to AI_CENTRAL/AI_MAIL.central.json (under repo root)

    Returns:
        The data written to central file (for logging/verification)

    Raises:
        OSError: If filesystem operations fail
        json.JSONDecodeError: If any inbox.json is malformed
        PermissionError: If insufficient permissions to write central file

    Example:
        >>> from ai_mail.apps.handlers.central_writer import update_central
        >>> stats = update_central()
        >>> print(stats["system_totals"]["total_unread"])
        5
    """
    json_handler.log_operation("update_central", {"target": str(CENTRAL_FILE)})

    # Aggregate statistics from all branches
    branch_stats = aggregate_branch_stats()

    # Build complete data structure
    central_data = build_central_data(branch_stats)

    # Write to central file
    write_central_file(central_data)

    return central_data


# =============================================================================
# CLI TEST HARNESS
# =============================================================================

if __name__ == "__main__":
    # Handler tier 3: no CLI imports in main code
    # Test harness can import CLI libraries for display
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

        # Display results in table
        table = Table(title="Branch Mail Statistics")
        table.add_column("Branch", style="cyan", no_wrap=True)
        table.add_column("Unread", justify="right", style="yellow")
        table.add_column("Total", justify="right", style="blue")

        for branch, data in sorted(stats["branch_stats"].items()):
            table.add_row(branch, str(data["unread"]), str(data["total"]))

        # Add totals row
        table.add_section()
        table.add_row(
            "[bold]SYSTEM TOTALS[/bold]",
            f"[bold yellow]{stats['system_totals']['total_unread']}[/bold yellow]",
            f"[bold blue]{stats['system_totals']['total_messages']}[/bold blue]",
        )

        console.print(table)
        console.print()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise
