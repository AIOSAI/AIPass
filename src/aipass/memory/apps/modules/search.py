# =================== AIPass ====================
# Name: search.py
# Description: Search Orchestration Module
# Version: 0.5.0
# Created: 2025-11-27
# Modified: 2026-03-15
# =============================================

"""
Search Orchestration Module

Coordinates semantic search workflow by calling handlers in sequence:
1. Encode query text to embedding (vector/embedder)
2. Search Chroma collections (storage/chroma via subprocess)
3. Format and display results (Rich panels)

Purpose:
    Thin orchestration layer - no business logic implementation.
    All domain logic lives in handlers.
"""

import sys
from pathlib import Path
from typing import List

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.memory.apps.handlers.json.json_handler import log_operation

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# Handler imports
from aipass.memory.apps.handlers.search.query_executor import (
    execute_search as _handler_execute_search,
)


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle search commands with seedgo-compliant introspection.

    Routing:
        search (no args)          -> print_introspection()
        search --help/-h/help     -> print_help()
        search <query> [options]  -> execute query

    Backward-compatible top-level commands (routed from entry point):
        --help, -h, help          -> print_help()

    Args:
        command: Command name
        args: Additional arguments (query text, options)

    Returns:
        True if command handled, False otherwise
    """
    # Top-level help (backward compat — entry point may send these)
    if command in ('--help', '-h', 'help'):
        print_help()
        return True

    if command == 'search':
        # No args → introspection (seedgo standard)
        if not args:
            print_introspection()
            return True

        # --help / -h / help → full help
        if args[0] in ('--help', '-h', 'help'):
            print_help()
            return True

        # Parse arguments
        query_parts = []
        branch = None
        memory_type = None
        n_results = 5

        i = 0
        while i < len(args):
            if args[i] == '--branch' and i + 1 < len(args):
                branch = args[i + 1]
                i += 2
            elif args[i] == '--type' and i + 1 < len(args):
                memory_type = args[i + 1]
                i += 2
            elif args[i] == '--n' and i + 1 < len(args):
                try:
                    n_results = int(args[i + 1])
                except ValueError:
                    error(f"Invalid number: {args[i + 1]}")
                    return True
                i += 2
            else:
                query_parts.append(args[i])
                i += 1

        query = ' '.join(query_parts)
        if not query:
            error("Search query required")
            return True

        show_search_results(query, branch=branch, memory_type=memory_type, n_results=n_results)
        return True

    return False


def print_help() -> None:
    """Display search module help"""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Search Module - Semantic Memory Search[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  python3 -m aipass.memory.apps.modules.search search <query> [options]")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  [cyan]search <query>[/cyan]     Search across all memory collections")
    console.print("  [cyan]help[/cyan]                Show this help message")
    console.print()
    console.print("[bold]OPTIONS:[/bold]")
    console.print("  [cyan]--branch BRANCH[/cyan]    Filter by branch (e.g., SEED, CLI)")
    console.print("  [cyan]--type TYPE[/cyan]        Filter by memory type (observations, local)")
    console.print("  [cyan]--n N[/cyan]              Number of results (default: 5)")
    console.print()
    console.print("[bold]EXAMPLES:[/bold]")
    console.print("  # Search all branches")
    console.print("  [dim]drone @memory search \"performance patterns\"[/dim]")
    console.print()
    console.print("  # Search specific branch")
    console.print("  [dim]drone @memory search \"registry bugs\" --branch SEED[/dim]")
    console.print()
    console.print("  # Search specific memory type")
    console.print("  [dim]drone @memory search \"collaboration\" --type observations --n 10[/dim]")
    console.print()
    console.print("[bold]HOW IT WORKS:[/bold]")
    console.print("  1. Convert query to 384-dim embedding (all-MiniLM-L6-v2)")
    console.print("  2. Search ChromaDB collections for similar vectors")
    console.print("  3. Display top N most relevant memories")
    console.print()


# =============================================================================
# SEARCH RESULTS DISPLAY
# =============================================================================

def show_search_results(
    query: str,
    branch: str | None = None,
    memory_type: str | None = None,
    n_results: int = 5
) -> bool:
    """
    Execute semantic search via handler and display results with Rich.

    Args:
        query: Search query text
        branch: Optional branch filter
        memory_type: Optional memory type filter
        n_results: Number of results to return

    Returns:
        True if search successful, False otherwise
    """
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Memory - Semantic Search[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    console.print()

    # Display query info
    console.print(f"[cyan]Query:[/cyan] {query}")
    if branch:
        console.print(f"[cyan]Branch:[/cyan] {branch}")
    if memory_type:
        console.print(f"[cyan]Type:[/cyan] {memory_type}")
    console.print()

    console.print("[dim]Encoding query...[/dim]")
    console.print("[dim]Searching collections...[/dim]")

    # Delegate to handler
    result = _handler_execute_search(
        query=query,
        branch=branch,
        memory_type=memory_type,
        n_results=n_results
    )

    if not result['success']:
        error(result.get('error', 'Unknown error'))
        return False

    collections_searched = result.get('collections_searched', 0)
    total_results = result.get('total_results', 0)
    filtered_results = result.get('results', [])

    # Display summary
    console.print(f"[green]>[/green] Found {total_results} results in {collections_searched} collections")
    console.print()

    if not filtered_results and total_results == 0:
        warning("No matching memories found", details="Try different search terms, broader query without filters, or check if memories have been rolled over (drone @memory status)")
        return True

    if not filtered_results:
        warning("No relevant memories found", details="Results found but none relevant enough (>40% similarity). Try more specific search terms.")
        return True

    for i, item in enumerate(filtered_results, 1):
        collection = item.get('collection', 'unknown')
        document = item.get('document', '')
        metadata = item.get('metadata', {})
        similarity = item.get('similarity', 0)

        # Parse collection name
        parts = collection.split('_')
        branch_name = parts[0].upper() if parts else 'UNKNOWN'
        mem_type = parts[1] if len(parts) > 1 else 'unknown'

        # Build metadata display
        meta_lines = []
        if 'timestamp' in metadata:
            meta_lines.append(f"[dim]Time:[/dim] {metadata['timestamp']}")
        if 'source' in metadata:
            meta_lines.append(f"[dim]Source:[/dim] {metadata['source']}")

        meta_text = " | ".join(meta_lines) if meta_lines else ""

        # Create panel for each result
        panel_title = f"Result {i} - {branch_name} ({mem_type}) - Similarity: {similarity:.2%}"

        panel_content = document
        if meta_text:
            panel_content += f"\n\n{meta_text}"

        console.print(Panel(
            panel_content,
            title=panel_title,
            title_align="left",
            border_style="cyan" if similarity > 0.7 else "blue" if similarity > 0.5 else "dim"
        ))

    console.print()
    log_operation("search_query", {"query": query, "results": len(filtered_results)})
    return True


# =============================================================================
# INTROSPECTION
# =============================================================================

def _discover_handlers() -> dict[str, list[str]]:
    """Auto-discover handler directories and their Python files.

    Scans the handlers/ directory relative to this module.

    Returns:
        Dict mapping handler directory name to list of .py filenames
        (excluding __init__.py and __pycache__).
    """
    handlers_dir = Path(__file__).resolve().parent.parent / "handlers"
    result: dict[str, list[str]] = {}
    if not handlers_dir.exists():
        return result
    for d in sorted(handlers_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("__"):
            continue
        py_files = sorted(
            f.name for f in d.iterdir()
            if f.is_file() and f.suffix == ".py" and f.name != "__init__.py"
        )
        if py_files:
            result[d.name] = py_files
    return result


def print_introspection() -> None:
    """Display module introspection info (seedgo standard).

    Called when 'search' is invoked with no arguments.
    Shows module identity, connected handlers, and next-step hints.
    """
    console.print()
    console.print("[bold cyan]search Module[/bold cyan]")
    console.print("Orchestrates semantic search across memory collections via vector embeddings and ChromaDB")
    console.print()

    # Connected handlers (auto-discovered)
    handlers = _discover_handlers()
    console.print("[yellow]Connected Handlers:[/yellow]")
    if handlers:
        for dir_name, files in handlers.items():
            file_list = ", ".join(files)
            console.print(f"  [cyan]handlers/{dir_name}/[/cyan]  [dim]{file_list}[/dim]")
    else:
        console.print("  [dim]No handlers found[/dim]")
    console.print()

    # Next-step hints
    console.print("[yellow]Next:[/yellow]")
    console.print('  [green]drone @memory search "your query"[/green]              [dim]# Semantic search[/dim]')
    console.print('  [green]drone @memory search "query" --branch SEED[/green]     [dim]# Filter by branch[/dim]')
    console.print("  [green]drone @memory search --help[/green]                    [dim]# Full usage guide[/dim]")
    console.print()


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    # No args → introspection (seedgo standard)
    if len(sys.argv) < 2:
        handle_command('search', [])
        sys.exit(0)

    # --help → full help
    if sys.argv[1] in ('--help', '-h', 'help'):
        handle_command('search', ['--help'])
        sys.exit(0)

    # Execute command via handle_command
    command = sys.argv[1]
    if not handle_command(command, sys.argv[2:]):
        console.print(f"[red]Unknown command:[/red] {command}")
        console.print("Run with [cyan]help[/cyan] for available commands")
        sys.exit(1)
