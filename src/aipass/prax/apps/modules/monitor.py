# =================== AIPass ====================
# Name: monitor.py
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
    drone @prax monitor              # Show introspection
    drone @prax monitor run          # Monitor all branches
    drone @prax monitor run seedgo,cli # Monitor specific branches

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
    - monitoring_filters.py   → Event filtering logic
    - event_queue.py          → Event buffering and deduplication
    - module_tracker.py       → Module execution tracking
    - filesystem_handler.py   → Real-time file change detection (FileSystemEventHandler)
    - log_watcher.py          → Log stream processing
"""

import sys
import argparse
import threading
import time
from datetime import datetime
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
from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent
# NOTE: FileSystemEventHandler implementation lives in:
#   aipass.prax.apps.handlers.monitoring.filesystem_handler.MonitoringFileHandler
# It handles trigger events for file_created/file_deleted/file_modified/file_moved


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

# =============================================================================
# PID CACHE - Maps branch names to active agent PIDs from dispatch lock files
# =============================================================================

import json as _json

_pid_cache: dict[str, int] = {}
_pid_cache_lock = threading.Lock()
_pid_cache_last_refresh: float = 0.0
_PID_CACHE_TTL = 30.0  # Refresh every 30 seconds


def _parse_lock_pid(branch_entry: dict, new_cache: dict[str, int]) -> None:
    """Parse a single dispatch lock file and add to cache if PID is live."""
    branch_path = Path(branch_entry.get("path", ""))
    lock_path = branch_path / "ai_mail.local" / ".dispatch.lock"
    if not lock_path.exists():
        return
    try:
        lock_data = _json.loads(lock_path.read_text(encoding="utf-8"))
        pid = lock_data.get("pid", 0)
        if not pid or not (sys.platform == "linux" and Path(f"/proc/{pid}").exists()):
            return
        name = branch_entry.get("name", "").upper()
        if name:
            new_cache[name] = pid
    except (ValueError, OSError) as e:
        logger.info("[monitor] Skipping dispatch lock %s: %s", lock_path, e)


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
            _parse_lock_pid(branch, new_cache)
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

    # Introspection gate — bare command shows module info
    if not args:
        print_introspection()
        return True

    # Help intercept
    if args[0] in ('--help', '-h', 'help'):
        print_help()
        return True

    # Subcommand routing
    subcmd = args[0]
    if subcmd == 'run':
        return _run_monitor(args[1:])

    # Unknown subcommand
    error(f"Unknown monitor subcommand: {subcmd}")
    print_help()
    return True


def _run_monitor(args: List[str]) -> bool:
    """Launch Mission Control live monitoring."""
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


def _render_event(event) -> None:
    """Render a single monitoring event to the console."""
    branch_pid = _get_pid_for_branch(event.branch)

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


def _display_worker():
    """Display thread - pulls events from queue and displays them. No filtering."""
    global _monitoring_active, _event_queue

    while _monitoring_active:
        if not _event_queue:
            time.sleep(0.1)
            continue

        event = _event_queue.dequeue(timeout=0.1)
        if event:
            _render_event(event)


def _get_watch_directories(repo_root: Path) -> list[tuple[Path, bool]]:
    """Get targeted directories to watch instead of entire repo root.

    Returns (path, recursive) tuples. Watches apps/ recursively for code,
    branch roots non-recursively for STATUS/README, and .trinity/ for identity.

    Some branches (backup, memory) have 10,000+ dirs in data stores.
    Watching only apps/ keeps inotify count under ~800.
    """
    dirs: list[tuple[Path, bool]] = []

    # Load branch paths from registry
    registry_path = repo_root / "AIPASS_REGISTRY.json"
    if registry_path.exists():
        try:
            data = _json.loads(registry_path.read_text(encoding="utf-8"))
            for branch in data.get("branches", []):
                branch_path = repo_root / branch.get("path", "")
                if not branch_path.exists():
                    continue
                # apps/ recursive — source code changes
                apps_dir = branch_path / "apps"
                if apps_dir.exists():
                    dirs.append((apps_dir, True))
                # Branch root non-recursive — STATUS.local.md, README.md
                dirs.append((branch_path, False))
                # .trinity/ non-recursive — identity files
                trinity_dir = branch_path / ".trinity"
                if trinity_dir.exists():
                    dirs.append((trinity_dir, False))
        except (ValueError, OSError) as e:
            logger.warning(f"[monitor] Failed to read registry: {e}")

    # Watch Claude Code project sessions for agent activity tracking
    claude_projects = Path.home() / ".claude" / "projects"
    if claude_projects.exists():
        dirs.append((claude_projects, True))

    return dirs


def _emit_watcher_event(level: str, message: str) -> None:
    """Push a monitoring event about watcher status to the queue."""
    if not _event_queue:
        return
    priority = 1 if level == 'error' else 2
    _event_queue.enqueue(MonitoringEvent(
        priority=priority, event_type='log', branch='PRAX',
        action=level, level=level, timestamp=datetime.now(),
        message=message,
    ))


def _start_observer_with_fallback(handler, watch_dirs):
    """Start watchdog observer, falling back to polling on inotify failure.

    Returns the started observer, or None if both methods fail.
    """
    from watchdog.observers import Observer

    observer = Observer()
    for watch_dir, recursive in watch_dirs:
        observer.schedule(handler, str(watch_dir), recursive=recursive)

    try:
        observer.start()
        return observer
    except OSError as e:
        logger.warning(f"[monitor] inotify unavailable: {e} — switching to polling")
        _emit_watcher_event('warning',
            "File watcher: inotify watch limit reached (VSCode/editors consume most of the 65K default). "
            "Using polling fallback (slower). Fix: sudo sysctl -w fs.inotify.max_user_watches=524288")

    try:
        from watchdog.observers.polling import PollingObserver
        observer = PollingObserver(timeout=2)
        for watch_dir, recursive in watch_dirs:
            observer.schedule(handler, str(watch_dir), recursive=recursive)
        observer.start()
        logger.info("[monitor] File watcher: polling fallback active")
        return observer
    except Exception as e2:
        logger.error(f"[monitor] Polling fallback also failed: {e2}")
        _emit_watcher_event('error', "File watcher: completely unavailable — no file events")
        return None


def _file_watcher_worker():
    """File watcher thread - watches filesystem changes and pushes to queue"""
    global _monitoring_active, _event_queue

    from aipass.prax.apps.handlers.monitoring.filesystem_handler import MonitoringFileHandler

    COMMAND_INDICATOR_FILES = {
        'standards_audit_log.json': 'seedgo audit',
        'standards_checklist_log.json': 'seedgo checklist',
    }

    handler = MonitoringFileHandler(
        event_queue=_event_queue,
        command_indicator_files=COMMAND_INDICATOR_FILES,
    )

    from aipass.prax.apps.handlers.config.load import _find_repo_root
    repo_root = _find_repo_root()
    watch_dirs = _get_watch_directories(repo_root)

    if not watch_dirs:
        logger.error("[monitor] No watch directories found — file watcher disabled")
        _emit_watcher_event('warning', "File watcher: no watch directories found — file events disabled")
        return

    logger.info(f"[monitor] File watcher: {len(watch_dirs)} watches scheduled")
    observer = _start_observer_with_fallback(handler, watch_dirs)
    if not observer:
        return

    try:
        while _monitoring_active:
            time.sleep(0.1)
    finally:
        observer.stop()
        observer.join()


def _start_log_watcher_with_fallback(event_queue) -> bool:
    """Start log watcher, falling back to polling on inotify failure.

    Returns True if started successfully, False otherwise.
    """
    from aipass.prax.apps.handlers.monitoring.log_watcher import start_log_watcher

    try:
        start_log_watcher(event_queue)
        return True
    except OSError as e:
        logger.warning(f"[monitor] Log watcher inotify failed: {e} — switching to polling")
        _emit_watcher_event('warning',
            "Log watcher: inotify watch limit reached (VSCode/editors consume most of the 65K default). "
            "Using polling fallback (slower). Fix: sudo sysctl -w fs.inotify.max_user_watches=524288")

    try:
        start_log_watcher(event_queue, use_polling=True)
        return True
    except Exception as e2:
        logger.error(f"[monitor] Log watcher polling fallback failed: {e2}")
        _emit_watcher_event('error', "Log watcher: completely unavailable — no log events")
        return False


def _log_watcher_worker():
    """Log watcher thread - uses proper log_watcher.py with all improvements"""
    global _monitoring_active, _event_queue

    from aipass.prax.apps.handlers.monitoring.log_watcher import stop_log_watcher

    if _event_queue is None:
        logger.error("[monitor] Event queue not initialized for log watcher")
        return

    if not _start_log_watcher_with_fallback(_event_queue):
        return

    try:
        while _monitoring_active:
            time.sleep(0.1)
    finally:
        stop_log_watcher()


def _handle_interactive_cmd(cmd: str, get_help_text) -> None:
    """Dispatch an interactive monitor command."""
    if cmd == 'help':
        console.print(get_help_text())
        return
    if cmd == 'status':
        _print_status()
        return
    error(f"Unknown command: {cmd}")
    console.print("[dim]Type 'help' for available commands[/dim]")


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
            logger.info("[monitor] Stopped by user (passive mode)")
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

            cmd, _cmd_args = parse_command(user_input)
            if not cmd:
                continue

            if cmd in ['quit', 'exit', 'q']:
                console.print("[yellow]Stopping monitoring...[/yellow]")
                break

            _handle_interactive_cmd(cmd, get_help_text)

        except KeyboardInterrupt:
            logger.info("[monitor] Stopped by user")
            console.print("\n[yellow]Stopping monitoring...[/yellow]")
            break
        except EOFError:
            logger.info("[monitor] EOF received, stopping interactive loop")
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

    console.print("[dim]Run 'drone @prax monitor --help' for usage[/dim]")
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
    console.print("  [cyan]drone @prax monitor[/cyan]")
    console.print("    Show module introspection")
    console.print()
    console.print("  [cyan]drone @prax monitor run[/cyan]")
    console.print("    Start monitoring all branches")
    console.print()
    console.print("  [cyan]drone @prax monitor run all[/cyan]")
    console.print("    Explicit all-branches monitoring")
    console.print()
    console.print("  [cyan]drone @prax monitor run [branches][/cyan]")
    console.print("    Monitor specific branches (comma-separated)")
    console.print("    Example: drone @prax monitor run seedgo,cli,flow")
    console.print()
    console.print("  [cyan]drone @prax monitor --help[/cyan]")
    console.print("    Show this help")
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
    console.print("  $ drone @prax monitor run")
    console.print()
    console.print("  [dim]# Monitor specific branches[/dim]")
    console.print("  $ drone @prax monitor run seedgo,cli,flow")
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
