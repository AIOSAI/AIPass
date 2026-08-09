# =================== AIPass ====================
# Name: monitor.py
# Description: Unified Monitoring Module
# Version: 0.3.1
# Created: 2025-11-23
# Modified: 2026-08-08
# =============================================

"""PRAX Monitor Module - Mission Control for Autonomous Branches."""

import os
import sys
import argparse
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

# Prax logger (system-wide, always first)
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services (display/output formatting)
from aipass.cli.apps.modules import console, header, error

from aipass.prax.apps.handlers.json import json_handler

# Monitoring handlers (connected subsystems)
from aipass.prax.apps.handlers.monitoring import (
    print_event,  # unified_stream.py
    print_command_separator,  # unified_stream.py - command headers
    print_hook_event,  # unified_stream.py - hook fire/skip display
    MonitoringQueue,  # event_queue.py
    ModuleTracker,  # module_tracker.py
)
from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent
from aipass.prax.apps.handlers.monitoring.telegram_relay import (
    init_relay,
    relay_event,
    stop_relay,
    is_relay_enabled_by_env,
)
from aipass.prax.apps.handlers.monitoring.pid_cache import get_pid_for_branch as _get_pid_for_branch

import json as _json


# =============================================================================
# MODULE STATE
# =============================================================================

# Global monitoring state
_stop_event = threading.Event()  # Thread-safe shutdown signal
_event_queue: Optional[MonitoringQueue] = None
_module_tracker: Optional[ModuleTracker] = None
_display_thread: Optional[threading.Thread] = None
_file_watcher_thread: Optional[threading.Thread] = None
_log_watcher_thread: Optional[threading.Thread] = None
_rate_tracker_thread: Optional[threading.Thread] = None


def print_introspection():
    """Display module introspection - shows connected handlers and architecture."""
    json_handler.log_operation("print_introspection", {"module": "monitor"})
    _handlers = [
        ("1. unified_stream.py", "print_event() - Terminal output formatting"),
        ("2. branch_detector.py", "detect_branch_from_path() - Path-to-branch mapping"),
        ("3. interactive_filter.py", "FilterState, parse_command() - Runtime filtering"),
        ("4. monitoring_filters.py", "should_monitor(), get_priority() - Event filtering"),
        ("5. event_queue.py", "MonitoringEvent, MonitoringQueue - Event buffering"),
        ("6. module_tracker.py", "ModuleTracker - Module execution tracking"),
    ]
    console.print()
    console.print("[bold cyan]PRAX Monitor Module[/bold cyan]")
    console.print()
    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Mission Control for autonomous branch monitoring")
    console.print("  Unified console for file changes, logs, and module activity")
    console.print()
    console.print("[yellow]Connected Handlers (apps/handlers/monitoring/):[/yellow]")
    for name, desc in _handlers:
        console.print(f"\n  [cyan]{name}[/cyan]\n     [dim]{desc}[/dim]")
    console.print("\n  [cyan]7. file watcher (threaded)[/cyan]")
    console.print("     [dim]Real-time file change detection using watchdog[/dim]")
    console.print("     [green]STATUS: Active - monitors ECOSYSTEM_ROOT recursively[/green]")
    console.print("\n  [cyan]8. log monitor (threaded)[/cyan]")
    console.print("     [dim]Log stream processing from SYSTEM_LOGS_DIR[/dim]")
    console.print("     [green]STATUS: Active - watches *.log files for new entries[/green]")
    console.print("\n[dim]Run 'drone @prax monitor --help' for usage[/dim]\n")


def print_help():
    """Drone-compliant help output - command syntax and examples."""
    console.print()
    console.print("[bold cyan]PRAX Monitor - Unified Branch Monitoring[/bold cyan]")
    _cmds = [
        ("drone @prax monitor", "Show module introspection"),
        ("drone @prax monitor run", "Start monitoring all branches"),
        ("drone @prax monitor run all", "Explicit all-branches monitoring"),
        (
            "drone @prax monitor run [branches]",
            "Monitor specific branches (comma-separated)\n    Example: drone @prax monitor run seedgo,cli,flow",
        ),
        (
            "drone @prax monitor run commons",
            "Live social feed of The Commons (posts, comments, votes, reactions), read-only",
        ),
        (
            "drone @prax monitor run commons --logs",
            "Old behavior — tail commons branch's technical prax logs instead of the feed",
        ),
        (
            "drone @prax monitor run --relay",
            "Enable Telegram relay (mirrors feed to prax_monitor bot)"
            "\n    Also enabled by env AIPASS_PRAX_MONITOR_RELAY=1",
        ),
        ("drone @prax monitor --help", "Show this help"),
    ]
    console.print("\n[yellow]Commands:[/yellow]")
    for cmd, desc in _cmds:
        console.print(f"\n  [cyan]{cmd}[/cyan]\n    {desc}")
    console.print("\n[yellow]Interactive Mode Commands:[/yellow]")
    console.print("  [cyan]help[/cyan]          Show available commands")
    console.print("  [cyan]status[/cyan]        Display current monitoring state")
    console.print("  [cyan]filter [branches][/cyan]  Adjust branch filter")
    console.print("  [cyan]quit/exit[/cyan]     Stop monitoring")
    console.print("\n[yellow]Examples:[/yellow]")
    console.print("\n  [dim]# Monitor all branches[/dim]")
    console.print("  $ drone @prax monitor run")
    console.print("\n  [dim]# Monitor specific branches[/dim]")
    console.print("  $ drone @prax monitor run seedgo,cli,flow\n")


# =============================================================================
# CORE COMMAND HANDLER (Required for auto-discovery)
# =============================================================================


def handle_command(command: str, args: List[str]) -> bool:
    """Handle monitor command - required for auto-discovery by prax.py."""
    if command != "monitor":
        return False

    # Introspection gate — bare command shows module info
    if not args:
        print_introspection()
        return True

    # Help intercept
    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    # Subcommand routing
    subcmd = args[0]
    if subcmd == "run":
        return _dispatch_run(args[1:])

    # Unknown subcommand
    error(f"Unknown monitor subcommand: {subcmd}")
    print_help()
    return True


def _dispatch_run(run_args: List[str]) -> bool:
    """Route 'monitor run' — a bare 'commons' target opens the live social feed.

    'commons --logs' escapes back to the branch-log tail, and mixed lists
    (e.g. 'seedgo,commons') keep treating commons as a branch (feed is
    standalone-only in v1).
    """
    positional = [a for a in run_args if not a.startswith("--")]
    target = positional[0] if positional else None
    logs_escape = "--logs" in run_args

    if target == "commons" and not logs_escape:
        from aipass.prax.apps.handlers.monitoring.commons_feed import run_commons_feed

        feed_args = [a for a in run_args if a != target]
        relay_enabled = "--relay" in feed_args or is_relay_enabled_by_env()
        relay_config = _load_relay_config() if relay_enabled else None
        return run_commons_feed(feed_args, relay_config=relay_config)

    return _run_monitor([a for a in run_args if a != "--logs"])


def _load_relay_config() -> Optional[dict]:
    """Load Telegram relay config from @api secrets."""
    try:
        from aipass.api.apps.modules.secrets import get_secret

        return get_secret("telegram", "prax_monitor", as_json=True)
    except Exception as e:
        logger.info("[monitor] Could not load relay config: %s", e)
        return None


def _run_monitor(args: List[str]) -> bool:
    """Launch Mission Control live monitoring."""
    global _event_queue, _module_tracker
    global _display_thread, _file_watcher_thread, _log_watcher_thread, _rate_tracker_thread

    json_handler.log_operation("monitor_started", {"args": args})
    logger.info(f"Starting unified monitoring (args: {args})")

    # Initialize monitoring subsystems
    _event_queue = MonitoringQueue()
    _module_tracker = ModuleTracker()
    _stop_event.clear()

    # Initialize Telegram relay (--relay flag or env var)
    _relay_enabled = "--relay" in args or is_relay_enabled_by_env()
    if _relay_enabled:
        args = [a for a in args if a != "--relay"]
    init_relay(_relay_enabled, _load_relay_config() if _relay_enabled else None)
    if _relay_enabled:
        console.print("[green]monitor → Telegram relay ON (prax_monitor)[/green]")

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

    try:
        _interactive_loop()
    except KeyboardInterrupt:
        logger.info("[monitor] KeyboardInterrupt escaped interactive loop")
        console.print("\n[yellow]Monitoring stopped.[/yellow]")

    _stop_threads()

    # sys.exit(0) prevents drone's post-execution json_handler from running
    # after the monitor exits, avoiding a json.load crash on Ctrl+C.
    sys.exit(0)


def _start_threads():
    """Start all monitoring threads"""
    global _display_thread, _file_watcher_thread, _log_watcher_thread, _rate_tracker_thread

    _display_thread = threading.Thread(target=_display_worker, daemon=True)
    _display_thread.start()

    _file_watcher_thread = threading.Thread(target=_file_watcher_worker, daemon=True)
    _file_watcher_thread.start()

    _log_watcher_thread = threading.Thread(target=_log_watcher_worker, daemon=True)
    _log_watcher_thread.start()

    _rate_tracker_thread = threading.Thread(target=_rate_tracker_worker, daemon=True)
    _rate_tracker_thread.start()

    logger.info("All monitoring threads started")


def _stop_threads():
    """Stop all monitoring threads and Telegram relay"""
    global _event_queue

    _stop_event.set()
    stop_relay()

    if _event_queue:
        _event_queue.stop()

    # Join all daemon threads with timeout
    for t in (_display_thread, _file_watcher_thread, _log_watcher_thread, _rate_tracker_thread):
        if t is not None and t.is_alive():
            t.join(timeout=2.0)

    logger.info("All monitoring threads stopped")


def _render_event(event) -> None:
    """Render a single monitoring event to the console, and relay to Telegram."""
    branch_pid = _get_pid_for_branch(event.branch)

    if event.event_type == "command":
        caller = getattr(event, "caller", None)
        target = None
        if hasattr(event, "action") and event.action and ":" in event.action:
            parts = event.action.split(":", 1)
            if len(parts) == 2 and parts[1]:
                target = parts[1]
        print_command_separator(event.branch, event.message, caller, target)
    elif event.event_type == "hook":
        print_hook_event(event.branch, event.message, event.action)
    else:
        print_event(event.event_type, event.branch, event.message, event.level, pid=branch_pid)

    relay_event(event)


def _display_worker():
    """Display thread - pulls events from queue and displays them. No filtering."""
    global _event_queue

    while not _stop_event.is_set():
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
                # Branch root non-recursive — README.md
                dirs.append((branch_path, False))
                # .trinity/ non-recursive — identity files
                trinity_dir = branch_path / ".trinity"
                if trinity_dir.exists():
                    dirs.append((trinity_dir, False))
        except (ValueError, OSError) as e:
            logger.warning(
                f"[monitor] Could not read the branch registry ({type(e).__name__}), so the live "
                f"monitor will watch no branch folders for file changes — only the CLI session "
                f"folders. The log feed is unaffected and the registry file was not modified."
            )

    # Watch CLI session directories for agent activity tracking
    claude_projects = Path.home() / ".claude" / "projects"
    if claude_projects.exists():
        dirs.append((claude_projects, True))

    codex_sessions = Path.home() / ".codex" / "sessions"
    if codex_sessions.exists():
        dirs.append((codex_sessions, True))

    return dirs


def _emit_watcher_event(level: str, message: str) -> None:
    """Push a monitoring event about watcher status to the queue."""
    if not _event_queue:
        return
    priority = 1 if level == "error" else 2
    _event_queue.enqueue(
        MonitoringEvent(
            priority=priority,
            event_type="log",
            branch="PRAX",
            action=level,
            level=level,
            timestamp=datetime.now(),
            message=message,
        )
    )


def _inotify_fix_message(err: OSError) -> str:
    """Return the correct sysctl fix for the specific inotify limit hit."""
    import errno as _errno

    if err.errno == _errno.ENOSPC:  # Errno 28 — max_user_watches
        return "inotify watch limit reached (max_user_watches). Fix: sudo sysctl -w fs.inotify.max_user_watches=524288"
    elif err.errno == _errno.EMFILE:  # Errno 24 — max_user_instances
        return (
            "inotify instance limit reached (max_user_instances). "
            "Fix: sudo sysctl -w fs.inotify.max_user_instances=1024"
        )
    else:
        return f"inotify error ({err}). Check system inotify limits."


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
        fix_msg = _inotify_fix_message(e)
        logger.warning(
            f"[monitor] The live monitor's file watcher cannot use the fast kernel notifications "
            f"({e}) — switching to polling, which still sees every change but reacts more slowly. "
            f"Nothing is lost."
        )
        _emit_watcher_event("warning", f"File watcher: {fix_msg} Using polling fallback (slower).")

    try:
        from watchdog.observers.polling import PollingObserver

        observer = PollingObserver(timeout=2)
        for watch_dir, recursive in watch_dirs:
            observer.schedule(handler, str(watch_dir), recursive=recursive)
        observer.start()
        logger.info("[monitor] File watcher: polling fallback active")
        return observer
    except Exception as e2:
        logger.error(
            f"[monitor] The live monitor's file watcher could not start at all — polling failed too "
            f"({type(e2).__name__}). File changes will not appear on screen; the log feed and the "
            f"on-disk logs are unaffected."
        )
        _emit_watcher_event("error", "File watcher: completely unavailable — no file events")
        return None


def _file_watcher_worker():
    """File watcher thread - watches filesystem changes and pushes to queue"""
    global _event_queue

    from aipass.prax.apps.handlers.monitoring.filesystem_handler import MonitoringFileHandler

    COMMAND_INDICATOR_FILES = {
        "standards_audit_log.json": "seedgo audit",
        "standards_checklist_log.json": "seedgo checklist",
    }

    handler = MonitoringFileHandler(
        event_queue=_event_queue,
        command_indicator_files=COMMAND_INDICATOR_FILES,
    )

    from aipass.prax.apps.handlers.config.load import _find_repo_root

    repo_root = _find_repo_root()
    watch_dirs = _get_watch_directories(repo_root)

    if not watch_dirs:
        logger.error(
            "[monitor] The live monitor found no folders to watch, so file changes will not appear "
            "on screen. The log feed and the on-disk logs are unaffected."
        )
        _emit_watcher_event("warning", "File watcher: no watch directories found — file events disabled")
        return

    logger.info(f"[monitor] File watcher: {len(watch_dirs)} watches scheduled")
    observer = _start_observer_with_fallback(handler, watch_dirs)
    if not observer:
        return

    try:
        while not _stop_event.is_set():
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
        fix_msg = _inotify_fix_message(e)
        logger.warning(
            f"[monitor] The live monitor's log watcher cannot use the fast kernel notifications "
            f"({e}) — switching to polling, which still reads every log line but shows it a little "
            f"later. Nothing is lost."
        )
        _emit_watcher_event("warning", f"Log watcher: {fix_msg} Using polling fallback (slower).")

    try:
        start_log_watcher(event_queue, use_polling=True)
        return True
    except Exception as e2:
        logger.error(
            f"[monitor] The live monitor's log watcher could not start at all — polling failed too "
            f"({type(e2).__name__}). Log lines will not appear on screen; branches still write their "
            f"logs to disk, so nothing is lost."
        )
        _emit_watcher_event("error", "Log watcher: completely unavailable — no log events")
        return False


def _log_watcher_worker():
    """Log watcher thread - uses proper log_watcher.py with all improvements"""
    global _event_queue

    from aipass.prax.apps.handlers.monitoring.log_watcher import stop_log_watcher

    if _event_queue is None:
        logger.error(
            "[monitor] The live monitor's log watcher could not start — the display queue it feeds "
            "was never created. Log lines will not appear on screen; branches still write their "
            "logs to disk. This one is a bug."
        )
        return

    if not _start_log_watcher_with_fallback(_event_queue):
        return

    try:
        while not _stop_event.is_set():
            time.sleep(0.1)
    finally:
        stop_log_watcher()


def _rate_tracker_worker():
    """Rate tracker thread — scans system_logs/ for runaway growth every SCAN_INTERVAL."""
    from aipass.prax.apps.handlers.monitoring.rate_tracker import scan_rates, configure, SCAN_INTERVAL
    from aipass.prax.apps.handlers.config.load import get_system_logs_dir

    try:
        from aipass.trigger.apps.modules.core import trigger

        event_cb = trigger.fire
    except ImportError as exc:
        logger.info("[monitor] trigger not available for rate tracker: %s", exc)
        event_cb = None

    configure(logs_dir=get_system_logs_dir(), event_callback=event_cb)

    while not _stop_event.is_set():
        try:
            scan_rates()
        except Exception as exc:
            logger.info("[monitor] Rate tracker scan error: %s", exc)
        _stop_event.wait(SCAN_INTERVAL)


def _handle_interactive_cmd(cmd: str, get_help_text) -> None:
    """Dispatch an interactive monitor command."""
    if cmd == "help":
        console.print(get_help_text())
        return
    if cmd == "status":
        _print_status()
        return
    error(f"Unknown command: {cmd}")
    console.print("[dim]Type 'help' for available commands[/dim]")


def _interactive_loop():
    """Interactive command loop - handles user input, or passive loop if no TTY"""
    global _event_queue

    # Non-TTY mode: just keep alive
    if not sys.stdin.isatty():
        logger.info("[monitor] No TTY detected - passive mode (Ctrl+C to stop)")
        try:
            while not _stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("[monitor] Stopped by user (passive mode)")
            console.print("\n[yellow]Stopping monitoring...[/yellow]")
        return

    from aipass.prax.apps.handlers.monitoring.interactive_filter import parse_command, get_help_text

    while not _stop_event.is_set():
        try:
            user_input = input().strip()
            if not user_input:
                continue

            cmd, _cmd_args = parse_command(user_input)
            if not cmd:
                continue

            if cmd in ["quit", "exit", "q"]:
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


# MAIN BLOCK (Standalone execution support)

if __name__ == "__main__":
    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="PRAX Unified Monitoring - Mission Control", add_help=False)
    parser.add_argument("--help", action="store_true", help="Show help message")
    parser.add_argument("--introspect", action="store_true", help="Show module introspection")
    parser.add_argument("branches", nargs="?", help="Branches to monitor (comma-separated)")

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
    handled = handle_command("monitor", _cmd_args)
    sys.exit(0 if handled else 1)
