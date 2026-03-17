# =================== AIPass ====================
# Name: monitor_module.py
# Description: Unified Monitoring Module
# Version: 0.3.0
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""
PRAX Monitor Module - Mission Control for Autonomous Branches

Unified monitoring orchestrator that provides real-time visibility into:
- File changes across all branches (file watcher)
- Log events from all modules (log monitoring)
- Branch activity and state changes
- Module execution tracking
- System health and status

Purpose:
    Single command interface for monitoring all autonomous branch activity.
    Replaces fragmented monitoring with unified Mission Control console.
    Enables multi-agent workflow visibility and coordination.

Usage:
    prax monitor              # Monitor all branches (quiet mode)
    prax monitor all          # Explicit all-branches monitoring
    prax monitor seed,cli     # Monitor specific branches

Interactive Commands:
    help                      # Show available commands
    status                    # Display current monitoring state
    filter [branches]         # Adjust branch filter
    quit/exit                 # Stop monitoring

Architecture:
    This module is thin orchestration layer only. All implementation
    delegated to specialized handlers in apps/handlers/monitoring/:

    - unified_stream.py       → Terminal output formatting
    - branch_detector.py      → Path-to-branch mapping
    - interactive_filter.py   → Runtime filter adjustment
    - monitoring_filters.py   → Event filtering logic (TODO)
    - event_queue.py          → Event buffering and deduplication
    - module_tracker.py       → Module execution tracking
    - filesystem_handler.py   → Real-time file change detection (FileSystemEventHandler)
    - log_watcher.py          → Log stream processing
"""

import sys
import argparse
import threading
import time
from pathlib import Path
from typing import List, Optional

# Prax logger (system-wide, always first)
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services (display/output formatting)
from aipass.cli.apps.modules import console, header, error

from aipass.prax.apps.handlers.json import json_handler

# Monitoring handlers (connected subsystems)
from aipass.prax.apps.handlers.monitoring import (
    print_event,              # unified_stream.py
    print_command_separator,  # unified_stream.py - command headers
    MonitoringQueue,          # event_queue.py
    ModuleTracker,            # module_tracker.py
)
# NOTE: FileSystemEventHandler implementation lives in:
#   aipass.prax.apps.handlers.monitoring.filesystem_handler.MonitoringFileHandler
# It handles trigger events for file_created/file_deleted/file_modified/file_moved


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def normalize_branch_arg(arg: str) -> str:
    """
    Convert path or name to branch name.

    DRONE now resolves @branch arguments to full paths before passing to modules.
    This function normalizes both formats to branch names.

    The package structure is: .../src/aipass/{module}/apps/...
    Find "aipass" in path parts, then the next part is the module name.

    Args:
        arg: Branch name (e.g., "flow") or full path (e.g., ".../src/aipass/flow")

    Returns:
        Uppercase branch name (e.g., "FLOW")

    Examples:
        >>> normalize_branch_arg("flow")
        "FLOW"
        >>> normalize_branch_arg("/path/to/src/aipass/flow")
        "FLOW"
    """
    if arg.startswith('/'):
        from pathlib import Path
        parts = Path(arg).parts
        # Check if path contains "aipass" - extract module name after it
        if 'aipass' in parts:
            idx = parts.index('aipass')
            if idx + 1 < len(parts):
                return parts[idx + 1].upper()
        # Otherwise, use last part of path
        return Path(arg).name.upper()
    return arg.upper()

# =============================================================================
# PID CACHE - Maps branch names to active agent PIDs from dispatch lock files
# =============================================================================

import json as _json

_pid_cache: dict[str, int] = {}
_pid_cache_lock = threading.Lock()
_pid_cache_last_refresh: float = 0.0
_PID_CACHE_TTL = 30.0  # Refresh every 30 seconds


def _refresh_pid_cache() -> None:
    """Scan dispatch lock files to build branch→PID mapping."""
    global _pid_cache_last_refresh
    import time as _time
    now = _time.time()
    if now - _pid_cache_last_refresh < _PID_CACHE_TTL:
        return
    _pid_cache_last_refresh = now

    try:
        from aipass.prax.apps.handlers.config.load import _find_repo_root
        registry_path = _find_repo_root() / "AIPASS_REGISTRY.json"
        if not registry_path.exists():
            return
        data = _json.loads(registry_path.read_text(encoding="utf-8"))
        new_cache: dict[str, int] = {}
        for branch in data.get("branches", []):
            branch_path = Path(branch.get("path", ""))
            lock_path = branch_path / "ai_mail.local" / ".dispatch.lock"
            if not lock_path.exists():
                continue
            try:
                lock_data = _json.loads(lock_path.read_text(encoding="utf-8"))
                pid = lock_data.get("pid", 0)
                if pid and (sys.platform == "linux" and Path(f"/proc/{pid}").exists()):
                    name = branch.get("name", "").upper()
                    if name:
                        new_cache[name] = pid
            except (ValueError, OSError):
                continue
        with _pid_cache_lock:
            _pid_cache.clear()
            _pid_cache.update(new_cache)
    except Exception as e:
        logger.info(f"[monitor] PID cache refresh failed: {e}")


def _get_pid_for_branch(branch: str) -> Optional[int]:
    """Look up PID for a branch from the cache."""
    _refresh_pid_cache()
    base = branch.upper()
    if base.endswith(' AGENT'):
        base = base[:-6]
    with _pid_cache_lock:
        return _pid_cache.get(base)


# =============================================================================
# MODULE STATE
# =============================================================================

# Global monitoring state
_monitoring_active = False
_event_queue: Optional[MonitoringQueue] = None
_module_tracker: Optional[ModuleTracker] = None
_display_thread: Optional[threading.Thread] = None
_file_watcher_thread: Optional[threading.Thread] = None
_log_watcher_thread: Optional[threading.Thread] = None


# =============================================================================
# CORE COMMAND HANDLER (Required for auto-discovery)
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle monitor command - required for auto-discovery by prax.py

    Args:
        command: Command name from prax.py dispatcher
        args: Command arguments (branch filters, flags, etc.)

    Returns:
        True if command was handled (command == "monitor")
        False if not our command (pass to next handler)
    """
    if command != 'monitor':
        return False

    if not args:
        print_introspection()
        return True

    global _monitoring_active, _event_queue, _module_tracker
    global _display_thread, _file_watcher_thread, _log_watcher_thread

    json_handler.log_operation("monitor_started", {"args": args})
    logger.info(f"Starting unified monitoring (args: {args})")

    # Initialize monitoring subsystems
    _event_queue = MonitoringQueue()
    _module_tracker = ModuleTracker()
    _monitoring_active = True

    _is_tty = sys.stdin.isatty()

    # Display header
    console.print()
    header("PRAX Mission Control - Unified Monitoring")
    console.print()
    console.print("[green]Live — all branches, all levels, no filters[/green]")
    if _is_tty:
        console.print("[dim]Type 'help' for commands[/dim]")
    else:
        console.print("[dim]Ctrl+C to stop[/dim]")
    console.print()

    # Start monitoring threads
    _start_threads()

    # Enter interactive mode
    _interactive_loop()

    # Cleanup on exit
    _stop_threads()

    return True


def _start_threads():
    """Start all monitoring threads"""
    global _display_thread, _file_watcher_thread, _log_watcher_thread

    # Display thread - pulls from event queue and displays
    _display_thread = threading.Thread(target=_display_worker, daemon=True)
    _display_thread.start()

    # File watcher thread - watches filesystem changes
    _file_watcher_thread = threading.Thread(target=_file_watcher_worker, daemon=True)
    _file_watcher_thread.start()

    # Log watcher thread - watches log files
    _log_watcher_thread = threading.Thread(target=_log_watcher_worker, daemon=True)
    _log_watcher_thread.start()

    logger.info("All monitoring threads started")


def _stop_threads():
    """Stop all monitoring threads"""
    global _monitoring_active, _event_queue

    _monitoring_active = False

    if _event_queue:
        _event_queue.stop()

    # Give threads time to finish
    time.sleep(0.5)

    logger.info("All monitoring threads stopped")


def _display_worker():
    """Display thread - pulls events from queue and displays them. No filtering."""
    global _monitoring_active, _event_queue

    while _monitoring_active:
        if not _event_queue:
            time.sleep(0.1)
            continue

        event = _event_queue.dequeue(timeout=0.1)

        if event:
            # Resolve PID for this branch
            branch_pid = _get_pid_for_branch(event.branch)

            # Display the event
            if event.event_type == 'command':
                caller = getattr(event, 'caller', None)
                target = None
                if hasattr(event, 'action') and event.action and ':' in event.action:
                    parts = event.action.split(':', 1)
                    if len(parts) == 2 and parts[1]:
                        target = parts[1]
                print_command_separator(event.branch, event.message, caller, target)
            else:
                print_event(event.event_type, event.branch, event.message, event.level, pid=branch_pid)


def _file_watcher_worker():
    """File watcher thread - watches filesystem changes and pushes to queue"""
    global _monitoring_active, _event_queue

    from watchdog.observers import Observer
    from aipass.prax.apps.handlers.monitoring.filesystem_handler import MonitoringFileHandler

    # Files whose modification indicates a command is running (python3 direct calls)
    # Maps filename -> command description. Used to emit command separators from file events.
    COMMAND_INDICATOR_FILES = {
        'standards_audit_log.json': 'seed audit',
        'standards_checklist_log.json': 'seed checklist',
    }

    # Create observer and start watching
    # Watch from repo root (covers all modules)
    from aipass.prax.apps.handlers.config.load import _find_repo_root
    observer = Observer()
    handler = MonitoringFileHandler(
        event_queue=_event_queue,
        command_indicator_files=COMMAND_INDICATOR_FILES,
    )
    watch_dir = _find_repo_root()
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()

    try:
        while _monitoring_active:
            time.sleep(0.1)
    finally:
        observer.stop()
        observer.join()


def _log_watcher_worker():
    """Log watcher thread - uses proper log_watcher.py with all improvements"""
    global _monitoring_active, _event_queue

    from aipass.prax.apps.handlers.monitoring.log_watcher import start_log_watcher, stop_log_watcher

    # Start the proper log watcher (has command detection, branch detection, message parsing)
    # Guard against None - should never happen since we initialize before starting threads
    if _event_queue is None:
        logger.error("[monitor] Event queue not initialized for log watcher")
        return
    _observer = start_log_watcher(_event_queue)

    try:
        while _monitoring_active:
            time.sleep(0.1)
    finally:
        stop_log_watcher()


def _interactive_loop():
    """Interactive command loop - handles user input, or passive loop if no TTY"""
    global _monitoring_active

    # Non-TTY mode: just keep alive
    if not sys.stdin.isatty():
        logger.info("[monitor] No TTY detected - passive mode (Ctrl+C to stop)")
        try:
            while _monitoring_active:
                time.sleep(0.5)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping monitoring...[/yellow]")
        return

    from aipass.prax.apps.handlers.monitoring.interactive_filter import (
        parse_command,
        get_help_text
    )

    while _monitoring_active:
        try:
            user_input = input().strip()
            if not user_input:
                continue

            cmd, cmd_args = parse_command(user_input)
            if not cmd:
                continue

            if cmd in ['quit', 'exit', 'q']:
                console.print("[yellow]Stopping monitoring...[/yellow]")
                break
            elif cmd == 'help':
                console.print(get_help_text())
            elif cmd == 'status':
                _print_status()
            else:
                error(f"Unknown command: {cmd}")
                console.print("[dim]Type 'help' for available commands[/dim]")

        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping monitoring...[/yellow]")
            break
        except EOFError:
            break


def _print_status():
    """Display current monitoring status"""
    global _event_queue

    console.print()
    console.print("[bold cyan]Monitoring Status:[/bold cyan]")
    console.print("  [green]Mode:[/green] Live — all branches, all levels, no filters")
    if _event_queue:
        console.print(f"  [yellow]Queue size:[/yellow] {_event_queue.size()}")
    console.print()


# =============================================================================
# INTROSPECTION (Module metadata and handler connections)
# =============================================================================

def print_introspection():
    """Display module introspection - shows connected handlers and architecture"""
    console.print()
    console.print("[bold cyan]PRAX Monitor Module[/bold cyan]")
    console.print()
    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Mission Control for autonomous branch monitoring")
    console.print("  Unified console for file changes, logs, and module activity")
    console.print()

    console.print("[yellow]Connected Handlers (apps/handlers/monitoring/):[/yellow]")
    console.print()
    console.print("  [cyan]1. unified_stream.py[/cyan]")
    console.print("     [dim]→ print_event() - Terminal output formatting[/dim]")
    console.print()
    console.print("  [cyan]2. branch_detector.py[/cyan]")
    console.print("     [dim]→ detect_branch_from_path() - Path-to-branch mapping[/dim]")
    console.print()
    console.print("  [cyan]3. interactive_filter.py[/cyan]")
    console.print("     [dim]→ FilterState, parse_command() - Runtime filtering[/dim]")
    console.print()
    console.print("  [cyan]4. monitoring_filters.py[/cyan]")
    console.print("     [dim]→ should_monitor(), get_priority() - Event filtering[/dim]")
    console.print()
    console.print("  [cyan]5. event_queue.py[/cyan]")
    console.print("     [dim]→ MonitoringEvent, MonitoringQueue - Event buffering[/dim]")
    console.print()
    console.print("  [cyan]6. module_tracker.py[/cyan]")
    console.print("     [dim]→ ModuleTracker - Module execution tracking[/dim]")
    console.print()
    console.print("  [cyan]7. file watcher (threaded)[/cyan]")
    console.print("     [dim]→ Real-time file change detection using watchdog[/dim]")
    console.print("     [green]STATUS: Active - monitors ECOSYSTEM_ROOT recursively[/green]")
    console.print()
    console.print("  [cyan]8. log monitor (threaded)[/cyan]")
    console.print("     [dim]→ Log stream processing from SYSTEM_LOGS_DIR[/dim]")
    console.print("     [green]STATUS: Active - watches *.log files for new entries[/green]")
    console.print()

    console.print("[dim]Run 'python3 monitor_module.py --help' for usage[/dim]")
    console.print()


# =============================================================================
# HELP OUTPUT (Drone-compliant command documentation)
# =============================================================================

def print_help():
    """Drone-compliant help output - command syntax and examples"""
    console.print()
    console.print("[bold cyan]PRAX Monitor - Unified Branch Monitoring[/bold cyan]")
    console.print()

    console.print("[yellow]Commands:[/yellow]")
    console.print()
    console.print("  [cyan]monitor[/cyan]")
    console.print("    Start monitoring all branches (quiet mode)")
    console.print()
    console.print("  [cyan]monitor all[/cyan]")
    console.print("    Explicit all-branches monitoring")
    console.print()
    console.print("  [cyan]monitor [branches][/cyan]")
    console.print("    Monitor specific branches (comma-separated)")
    console.print("    Example: monitor seed,cli,flow")
    console.print()

    console.print("[yellow]Interactive Mode Commands:[/yellow]")
    console.print()
    console.print("  [cyan]help[/cyan]          Show available commands")
    console.print("  [cyan]status[/cyan]        Display current monitoring state")
    console.print("  [cyan]filter [branches][/cyan]  Adjust branch filter")
    console.print("  [cyan]quit/exit[/cyan]     Stop monitoring")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print()
    console.print("  [dim]# Monitor all branches[/dim]")
    console.print("  $ prax monitor")
    console.print()
    console.print("  [dim]# Monitor specific branches[/dim]")
    console.print("  $ prax monitor seed,cli,flow")
    console.print()
    console.print("  [dim]# Standalone execution[/dim]")
    console.print("  $ python3 monitor_module.py")
    console.print()


# =============================================================================
# MAIN BLOCK (Standalone execution support)
# =============================================================================

if __name__ == "__main__":
    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="PRAX Unified Monitoring - Mission Control",
        add_help=False
    )
    parser.add_argument('--help', action='store_true', help='Show help message')
    parser.add_argument('--introspect', action='store_true', help='Show module introspection')
    parser.add_argument('branches', nargs='?', help='Branches to monitor (comma-separated)')

    args = parser.parse_args()

    # Handle flags
    if args.help:
        print_help()
        sys.exit(0)

    if args.introspect:
        print_introspection()
        sys.exit(0)

    # Prepare arguments for handle_command
    _cmd_args = []
    if args.branches:
        _cmd_args = [args.branches]

    # Execute monitor command
    handled = handle_command('monitor', _cmd_args)
    sys.exit(0 if handled else 1)
