# =================== AIPass ====================
# Name: log_watcher.py
# Description: Log File Monitor
# Version: 1.0.0
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""
PRAX Log Watcher - Event Queue Integration

Monitors log files in real-time and pushes events to the monitoring queue.

Features:
- Real-time log tailing with position tracking
- Color coding detection by log level
- Command detection and formatting
- Branch detection from log file path
- Thread-safe event queue integration

Based on: apps/handlers/discovery/watcher.py (production-ready log tailing)
"""

from pathlib import Path

from datetime import datetime
from typing import Optional, Dict, Any
import re

from aipass.prax import logger
from watchdog.observers import Observer as WatchdogObserver
from watchdog.events import FileSystemEventHandler

# Import from prax config
from aipass.prax.apps.handlers.config.load import get_system_logs_dir

# Import monitoring infrastructure
from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent, MonitoringQueue
from aipass.prax.apps.handlers.monitoring.branch_detector import detect_branch_from_log

# Trigger integration - graceful fallback if trigger not available
try:
    from aipass.trigger.apps.modules.core import trigger
    HAS_TRIGGER = True
except ImportError:
    trigger = None  # type: ignore[assignment]
    HAS_TRIGGER = False

from aipass.prax.apps.handlers.json import json_handler

# Logger
# logger imported from aipass.prax


def _generate_error_hash(module_name: str, message: str) -> str:
    """
    Generate a hash for error deduplication.

    Same module + message = same hash, allowing trigger rules to
    deduplicate repeated errors.

    Args:
        module_name: Name of the module that generated the error
        message: The error message content

    Returns:
        8-character hash string for deduplication
    """
    import hashlib
    content = f"{module_name}:{message}"
    return hashlib.md5(content.encode()).hexdigest()[:8]

# Global observer instance
_log_observer: Any = None


class LogFileWatcher(FileSystemEventHandler):
    """
    Watch log files and push events to monitoring queue.

    Adapted from discovery/watcher.py PythonFileWatcher.on_modified()
    with event queue integration instead of console output.
    """

    def __init__(self, event_queue: MonitoringQueue):
        """
        Initialize log watcher.

        Args:
            event_queue: MonitoringQueue instance for event delivery
        """
        super().__init__()
        self.event_queue = event_queue
        # Track file positions for log tailing
        self.log_positions: Dict[str, int] = {}
        # Track last command execution for command detection
        self.last_command: Optional[str] = None
        # Track command per branch to avoid duplicate command separators
        self.last_command_per_branch: Dict[str, str] = {}

    def on_modified(self, event):
        """
        Watch for log file modifications and push events to queue.

        Adapted from discovery/watcher.py with these changes:
        1. Pushes to event_queue instead of console.print
        2. Detects branch from log file name/path
        3. Preserves color coding info in event level field
        4. Emits command separator events when command detected
        """
        if event.is_directory:
            return

        file_path = str(event.src_path)

        # Only watch .log files
        if not file_path.endswith('.log'):
            return

        # Only watch files in system_logs directory
        if str(get_system_logs_dir()) not in file_path:
            return

        try:
            # Get current file size
            current_size = Path(file_path).stat().st_size

            # Get last known position
            last_pos = self.log_positions.get(file_path, 0)

            # If file shrunk (rotated), reset position
            if current_size < last_pos:
                last_pos = 0

            # Read new content
            if current_size > last_pos:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(last_pos)
                    new_lines = f.read()

                    if new_lines.strip():
                        # Extract branch from log file path
                        branch = detect_branch_from_log(file_path)

                        # Process new log lines
                        for line in new_lines.strip().split('\n'):
                            if line.strip():
                                # Check if this is a new command execution
                                command_info = self._extract_command_info(line)
                                if command_info:
                                    self._emit_command_separator(branch, command_info)
                                    continue  # Skip regular log output - separator IS the display

                                # Filter out initialization noise
                                if self._should_display_log(line):
                                    # Detect log level and create event
                                    level = self._detect_log_level(line)
                                    self._emit_log_event(branch, line, level, file_path)

                    # Update position
                    self.log_positions[file_path] = f.tell()

        except Exception as e:
            # Log error but don't crash watcher
            logger.info(f"Error reading log file {file_path}: {e}")

    def _should_display_log(self, _log_line: str) -> bool:
        """Check if log line should be displayed. No filtering — show everything."""
        return True

    def _detect_log_level(self, log_line: str) -> str:
        """
        Detect log level from log line.

        Adapted from discovery/watcher.py _format_log_with_color()
        Returns level string instead of formatting with color codes.

        Returns:
            'error', 'warning', 'info', or 'debug'
        """
        # Check for error markers
        if ' - ERROR - ' in log_line or ' ERROR ' in log_line or '[ERROR]' in log_line:
            return 'error'

        # Check for warning markers
        elif ' - WARNING - ' in log_line or ' WARNING ' in log_line or '[WARNING]' in log_line:
            return 'warning'

        # Check for critical markers
        elif ' - CRITICAL - ' in log_line or ' CRITICAL ' in log_line or '[CRITICAL]' in log_line:
            return 'error'  # Map critical to error for priority

        # Check for debug markers
        elif ' - DEBUG - ' in log_line or ' DEBUG ' in log_line or '[DEBUG]' in log_line:
            return 'debug'

        # Default to info
        else:
            return 'info'

    def _extract_command_info(self, log_line: str) -> Optional[Dict[str, Optional[str]]]:
        """
        Extract command information from log line if it's a new command execution.

        Returns dict with keys: command, caller (optional), target (optional)
        or None if not a command line.
        """
        # Pattern 1: Drone commands - "Drone started with args: ['close', 'plan', '0098']"
        if "Drone started with args:" in log_line or "[drone] Drone started with args:" in log_line:
            match = re.search(r"args:\s*\[([^\]]+)\]", log_line)
            if match:
                args = match.group(1).replace("'", "").replace('"', '')
                return {'command': f"drone {args}", 'caller': None, 'target': None}

        # Pattern 2: Flow plan commands
        if "[FLOW]" in log_line or "FLOW_PLAN]" in log_line:
            if "Creating" in log_line:
                return {'command': "flow create plan", 'caller': None, 'target': None}
            elif "Closing" in log_line:
                match = re.search(r"(?:FPLAN|PLAN)[- ]?(\d+)", log_line)
                plan_id = match.group(1) if match else ""
                return {'command': f"flow close plan {plan_id}".strip(), 'caller': None, 'target': None}
            elif "Opening" in log_line:
                match = re.search(r"(?:FPLAN|PLAN)[- ]?(\d+)", log_line)
                plan_id = match.group(1) if match else ""
                return {'command': f"flow open plan {plan_id}".strip(), 'caller': None, 'target': None}
            elif "Loaded module:" in log_line and not self.last_command_per_branch.get('FLOW', '').startswith('FLOW:flow'):
                return {'command': "flow command", 'caller': None, 'target': None}

        # Pattern 3: Seed audit commands - extract target branch
        if "[seed]" in log_line.lower() and "audit" in log_line.lower():
            match = re.search(r"Auditing\s+(\w+)", log_line)
            if match:
                target = match.group(1).upper()
                return {'command': f"seed audit @{target.lower()}", 'caller': None, 'target': target}

        # Pattern 4: Seed checklist commands
        if "standards_checklist" in log_line.lower() and "Running" in log_line:
            match = re.search(r"Running\s+(\w+)\s+standard\s+check\s+on\s+(.+)", log_line)
            if match:
                return {'command': f"seed checklist {match.group(2)}", 'caller': None, 'target': None}

        # Pattern 5: AI Mail commands - extract target
        if "[ai_mail]" in log_line.lower():
            if "Sending" in log_line:
                # Try to extract recipient
                target_match = re.search(r"to\s+@?(\w+)", log_line, re.IGNORECASE)
                target = target_match.group(1).upper() if target_match else None
                return {'command': "ai_mail send", 'caller': None, 'target': target}
            elif "inbox" in log_line.lower():
                return {'command': "ai_mail inbox", 'caller': None, 'target': None}

        # Pattern 6: Prax commands
        if "[prax]" in log_line.lower():
            if "monitor" in log_line.lower():
                return {'command': "prax monitor", 'caller': None, 'target': None}
            elif "status" in log_line.lower():
                return {'command': "prax status", 'caller': None, 'target': None}

        # Pattern 8: Backup system operations (direct python3 calls)
        if "[backup" in log_line.lower():
            if "snapshot" in log_line.lower() and ("Starting" in log_line or "Running" in log_line or "Complete" in log_line):
                return {'command': "backup_system snapshot", 'caller': None, 'target': None}
            elif "versioned" in log_line.lower() and ("Starting" in log_line or "Running" in log_line):
                return {'command': "backup_system versioned", 'caller': None, 'target': None}
            elif "sync" in log_line.lower() and ("Starting" in log_line or "Running" in log_line):
                return {'command': "backup_system sync", 'caller': None, 'target': None}

        # Pattern 9: Memory Bank operations (direct python3 calls)
        if "[memory_bank]" in log_line.lower() or "memory_bank" in log_line.lower():
            if "rollover" in log_line.lower() and ("Starting" in log_line or "Processing" in log_line):
                return {'command': "memory_bank rollover", 'caller': None, 'target': None}
            elif "search" in log_line.lower() and "query" in log_line.lower():
                return {'command': "memory_bank search", 'caller': None, 'target': None}

        # Pattern 10: Cortex operations (direct python3 calls)
        if "[cortex]" in log_line.lower():
            if "Creating" in log_line and "branch" in log_line.lower():
                match = re.search(r"Creating\s+(?:branch\s+)?(\w+)", log_line)
                target = match.group(1).upper() if match else None
                return {'command': "cortex create branch", 'caller': None, 'target': target}

        # Pattern 11: Trigger operations (direct python3 calls)
        if "[trigger]" in log_line.lower():
            if "fired" in log_line.lower() or "triggered" in log_line.lower():
                return {'command': "trigger fire", 'caller': None, 'target': None}

        # Pattern 12: Drone routing with caller attribution - HIGHEST PRIORITY
        # Format: "Routing @flow [CALLER:PRAX] → create ['.', 'Subject']"
        if "Routing @" in log_line and "[CALLER:" in log_line:
            caller_match = re.search(r"\[CALLER:(\w+)\]", log_line)
            caller = caller_match.group(1) if caller_match else None

            # Extract target branch and command from "Routing @target ... → command [args]"
            route_match = re.search(r"Routing\s+@(\w+).*?→\s*(\S+)\s*(.*)", log_line)
            if route_match:
                target = route_match.group(1).upper()
                cmd_name = route_match.group(2)
                cmd_args = route_match.group(3).strip()
                display_cmd = f"drone @{route_match.group(1)} {cmd_name} {cmd_args}".strip()
                return {'command': display_cmd, 'caller': caller, 'target': target}

        # Pattern 7: ALL drone command executions - HIGH PRIORITY
        # Format: "Executing command [CALLER:PRAX]: seed.py audit @prax"
        if "Executing" in log_line and "command" in log_line:
            caller_match = re.search(r"\[CALLER:(\w+)\]", log_line)
            caller = caller_match.group(1) if caller_match else None

            cmd_match = re.search(r"Executing(?:\s+activated)?\s+command(?:\s*\[CALLER:\w+\])?:\s*(.+)", log_line)
            if cmd_match:
                cmd = cmd_match.group(1).strip()
                # Extract target from command (e.g., "seed.py audit @prax" -> PRAX)
                # Or "seed.py audit /path/to/src/aipass/prax" -> PRAX
                target = None
                target_match = re.search(r'@(\w+)', cmd)
                if target_match:
                    target = target_match.group(1).upper()
                else:
                    # Check for full path target (src/aipass/{module} structure)
                    path_match = re.search(r'/aipass/(\w+)', cmd)
                    if path_match:
                        target = path_match.group(1).upper()

                # Clean up command display - simplify paths
                display_cmd = cmd
                # Replace full paths with @branch notation
                display_cmd = re.sub(r'[^\s]*/aipass/(\w+)/apps/\w+\.py', lambda m: f"@{m.group(1)}", display_cmd)
                display_cmd = re.sub(r'[^\s]*/aipass/(\w+)', lambda m: f"@{m.group(1)}", display_cmd)

                return {'command': display_cmd, 'caller': caller, 'target': target}

        return None

    def _emit_command_separator(self, branch: str, command_info) -> None:
        """
        Emit command separator event to queue with caller and target attribution.
        Deduplicates consecutive identical commands per branch.
        """
        # Handle dict format (new) and legacy string/tuple formats
        if isinstance(command_info, dict):
            command = command_info.get('command', '')
            caller = command_info.get('caller')
            target = command_info.get('target')
        elif isinstance(command_info, tuple):
            command, caller = command_info
            target = None
        else:
            command = command_info
            caller = None
            target = None

        # Deduplicate: skip if same command just emitted for this branch
        dedup_key = f"{branch}:{command}"
        if self.last_command_per_branch.get(branch) == dedup_key:
            return
        self.last_command_per_branch[branch] = dedup_key

        separator_event = MonitoringEvent(
            priority=2,
            event_type='command',
            branch=branch,
            action='executed',
            message=command,
            level='info',
            timestamp=datetime.now(),
            caller=caller
        )

        # Store target in action field since MonitoringEvent doesn't have a target field
        if target:
            separator_event.action = f"executed:{target}"

        self.event_queue.enqueue(separator_event)

    def _parse_log_message(self, log_line: str) -> str:
        """
        Parse raw log line to extract just the message content.

        Raw format: [BRANCH_NAME] TIMESTAMP | SOURCE | LEVEL | MESSAGE
        Returns just the MESSAGE part to avoid duplicate prefixes.

        Args:
            log_line: Raw log line from log file

        Returns:
            Cleaned message content
        """
        # Try to extract message after last pipe separator
        if ' | ' in log_line:
            parts = log_line.split(' | ')
            if len(parts) >= 4:
                # Format: [BRANCH] TIMESTAMP | SOURCE | LEVEL | MESSAGE
                # Return everything after the LEVEL part
                return ' | '.join(parts[3:]).strip()
            elif len(parts) >= 2:
                # Simpler format, return last part
                return parts[-1].strip()

        # Fallback: return as-is if can't parse
        return log_line.strip()

    def _emit_log_event(self, branch: str, log_line: str, level: str,
                        log_file_path: Optional[str] = None) -> None:
        """
        Create and emit log event to monitoring queue.

        Also fires trigger event for ERROR level logs to enable
        automated error response workflows.

        Args:
            branch: Branch name detected from log file
            log_line: Raw log line content
            level: Log level (error, warning, info, debug)
            log_file_path: Path to the log file (for trigger events)
        """
        # Parse to extract clean message (remove embedded prefix)
        clean_message = self._parse_log_message(log_line)
        current_time = datetime.now()

        # Fire trigger event for ERROR level logs
        if HAS_TRIGGER and level == 'error':
            # Extract module name from log line if possible
            module_name = 'unknown'
            if ' | ' in log_line:
                parts = log_line.split(' | ')
                if len(parts) >= 2:
                    module_name = parts[1].strip()

            trigger.fire('error_detected',  # type: ignore[union-attr]
                branch=branch,
                message=clean_message,
                error_hash=_generate_error_hash(module_name, clean_message),
                timestamp=current_time.isoformat(),
                log_file=log_file_path or 'unknown',
                module_name=module_name
            )

        # Create monitoring event
        log_event = MonitoringEvent(
            priority=0,  # Auto-calculated from level
            event_type='log',
            branch=branch,
            action='logged',
            message=clean_message,
            level=level,
            timestamp=current_time
        )

        # Push to queue
        self.event_queue.enqueue(log_event)

    def initialize_positions(self):
        """
        Initialize log positions to END of existing files.

        Only show NEW entries after watcher starts.
        Call replay_recent() before this to show startup context.
        """
        if not get_system_logs_dir().exists():
            logger.warning(f"System logs directory not found: {get_system_logs_dir()}")
            return

        for log_file in get_system_logs_dir().glob("*.log"):
            try:
                self.log_positions[str(log_file)] = log_file.stat().st_size
            except Exception as e:
                logger.info(f"Could not get size for {log_file}: {e}")

    def replay_recent(self, num_lines: int = 1):
        """
        Replay the last N lines from each log file as startup context.

        Shows recent activity so the monitor isn't blank on startup.
        Skips command separators (stale) and noise patterns.

        Args:
            num_lines: Number of recent lines to replay per log file
        """
        logs_dir = get_system_logs_dir()
        if not logs_dir.exists():
            return

        for log_file in sorted(logs_dir.glob("*.log")):
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    all_lines = f.readlines()

                if not all_lines:
                    continue

                recent = all_lines[-num_lines:]
                branch = detect_branch_from_log(str(log_file))

                for line in recent:
                    line = line.strip()
                    if not line:
                        continue

                    # Skip commands in replay (they're stale)
                    if self._extract_command_info(line):
                        continue

                    if self._should_display_log(line):
                        level = self._detect_log_level(line)
                        self._emit_log_event(branch, line, level, str(log_file))

            except Exception as e:
                logger.info(f"Error replaying {log_file}: {e}")


def start_log_watcher(event_queue: MonitoringQueue, use_polling: bool = False) -> Any:
    """
    Start watching log files and pushing events to queue.

    Args:
        event_queue: MonitoringQueue instance for event delivery
        use_polling: If True, use PollingObserver instead of native inotify

    Returns:
        Observer instance
    """
    global _log_observer

    # Stop existing observer if running
    if _log_observer and _log_observer.is_alive():
        logger.warning("Log watcher already running, stopping existing instance")
        stop_log_watcher()

    # Create watcher instance
    watcher = LogFileWatcher(event_queue)

    # Replay recent lines for startup context (before seeking to EOF)
    watcher.replay_recent(num_lines=2)

    # Soft start: seek to end of all logs, only show NEW activity after this
    watcher.initialize_positions()

    # Create observer — polling fallback when inotify unavailable
    if use_polling:
        from watchdog.observers.polling import PollingObserver
        observer = PollingObserver(timeout=1)
        logger.info("Log watcher using polling observer (1s interval)")
    else:
        observer = WatchdogObserver()

    observer.schedule(watcher, str(get_system_logs_dir()), recursive=False)
    observer.start()

    _log_observer = observer

    mode = "polling" if use_polling else "inotify"
    json_handler.log_operation("log_watcher_started", {"log_dir": str(get_system_logs_dir()), "mode": mode})
    logger.info(f"Log watcher started ({mode}), monitoring: {get_system_logs_dir()}")

    return observer


def stop_log_watcher():
    """Stop the log watcher"""
    global _log_observer

    if _log_observer and _log_observer.is_alive():
        _log_observer.stop()
        _log_observer.join(timeout=5.0)
        _log_observer = None
        logger.info("Log watcher stopped")


def is_log_watcher_active() -> bool:
    """
    Check if log watcher is currently active.

    Returns:
        True if watcher is running, False otherwise
    """
    return _log_observer is not None and _log_observer.is_alive()


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == '__main__':
    """
    Standalone test - starts log watcher and prints events from queue.

    Usage:
        python3 log_watcher.py

    Then trigger some log activity in another terminal:
        prax [command]

    Press Ctrl+C to stop.
    """
    import time
    from aipass.cli.apps.modules import console

    console.print("[bold cyan]PRAX Log Watcher Test[/bold cyan]")
    console.print()
    console.print(f"Monitoring: {get_system_logs_dir()}")
    console.print("Press Ctrl+C to stop")
    console.print()

    # Create event queue
    queue = MonitoringQueue()

    # Start watcher
    observer = start_log_watcher(queue)

    try:
        # Event processing loop
        while True:
            # Check for events
            event = queue.dequeue(timeout=0.5)

            if event:
                # Format and display event
                timestamp = event.timestamp.strftime('%H:%M:%S')

                # Color by level
                level_colors = {
                    'error': 'red',
                    'warning': 'yellow',
                    'info': 'white',
                    'debug': 'dim',
                }
                color = level_colors.get(event.level, 'white')

                # Print event
                if event.event_type == 'command':
                    console.print(f"\n[bold green]{event.message}[/bold green]\n")
                else:
                    console.print(
                        f"[dim]{timestamp}[/dim] "
                        f"[cyan][{event.branch:>8}][/cyan] "
                        f"[{color}]{event.message}[/{color}]"
                    )

            # Small delay to prevent CPU spinning
            time.sleep(0.1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping log watcher...[/yellow]")
        stop_log_watcher()
        queue.stop()
        console.print("[green]Log watcher stopped[/green]")
