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

from aipass.prax.apps.modules.logger import get_direct_logger
from watchdog.observers import Observer as WatchdogObserver
from watchdog.events import FileSystemEventHandler

# Import from prax config
from aipass.prax.apps.handlers.config.load import get_system_logs_dir

# Import monitoring infrastructure
from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent, MonitoringQueue
from aipass.prax.apps.handlers.monitoring.branch_detector import detect_branch_from_log

from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

# Trigger integration - graceful fallback if trigger not available
try:
    from aipass.trigger.apps.modules.core import trigger

    HAS_TRIGGER = True
except ImportError as e:
    logger.info("[log_watcher] trigger module not available: %s", e)
    trigger = None  # type: ignore[assignment]
    HAS_TRIGGER = False


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

    def _process_log_line(self, branch: str, line: str, file_path: str) -> None:
        """Process a single log line: detect commands or emit as log event."""
        if not line.strip():
            return
        command_info = self._extract_command_info(line)
        if command_info:
            self._emit_command_separator(branch, command_info)
            return
        if self._should_display_log(line):
            level = self._detect_log_level(line)
            self._emit_log_event(branch, line, level, file_path)

    def _read_new_content(self, file_path: str) -> Optional[str]:
        """Read new content from a log file since last position.

        Returns the new content string, or None if nothing new.
        """
        current_size = Path(file_path).stat().st_size
        last_pos = self.log_positions.get(file_path, 0)

        if current_size < last_pos:
            last_pos = 0

        if current_size <= last_pos:
            return None

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(last_pos)
            new_lines = f.read()
            self.log_positions[file_path] = f.tell()

        return new_lines if new_lines.strip() else None

    def on_modified(self, event):
        """Watch for log file modifications and push events to queue."""
        if event.is_directory:
            return

        file_path = str(event.src_path)

        if not file_path.endswith(".log"):
            return

        if str(get_system_logs_dir()) not in file_path:
            return

        try:
            new_content = self._read_new_content(file_path)
            if not new_content:
                return

            branch = detect_branch_from_log(file_path)
            for line in new_content.strip().split("\n"):
                self._process_log_line(branch, line, file_path)

        except Exception as e:
            logger.info(f"Error reading log file {file_path}: {e}")

    def _should_display_log(self, _log_line: str) -> bool:
        """Check if log line should be displayed. No filtering — show everything."""
        return True

    def _detect_log_level(self, log_line: str) -> str:
        """Detect log level from log line. Returns 'error', 'warning', 'info', or 'debug'."""
        _LEVEL_MARKERS = {
            "error": (" - ERROR - ", " ERROR ", "[ERROR]", " - CRITICAL - ", " CRITICAL ", "[CRITICAL]"),
            "warning": (" - WARNING - ", " WARNING ", "[WARNING]"),
            "debug": (" - DEBUG - ", " DEBUG ", "[DEBUG]"),
        }
        for level, markers in _LEVEL_MARKERS.items():
            if any(m in log_line for m in markers):
                return level
        return "info"

    def _match_flow_command(self, log_line: str) -> Optional[Dict[str, Optional[str]]]:
        """Match flow plan commands from log line."""
        if "Creating" in log_line:
            return {"command": "flow create plan", "caller": None, "target": None}
        if "Closing" in log_line:
            match = re.search(r"(?:FPLAN|PLAN)[- ]?(\d+)", log_line)
            plan_id = match.group(1) if match else ""
            return {"command": f"flow close plan {plan_id}".strip(), "caller": None, "target": None}
        if "Opening" in log_line:
            match = re.search(r"(?:FPLAN|PLAN)[- ]?(\d+)", log_line)
            plan_id = match.group(1) if match else ""
            return {"command": f"flow open plan {plan_id}".strip(), "caller": None, "target": None}
        if "Loaded module:" in log_line and not self.last_command_per_branch.get("FLOW", "").startswith("FLOW:flow"):
            return {"command": "flow command", "caller": None, "target": None}
        return None

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
                args = match.group(1).replace("'", "").replace('"', "")
                return {"command": f"drone {args}", "caller": None, "target": None}

        # Pattern 2: Flow plan commands
        if "[FLOW]" in log_line or "FLOW_PLAN]" in log_line:
            result = self._match_flow_command(log_line)
            if result:
                return result

        # Pattern 3: Seedgo audit commands - extract target branch
        if "[seedgo]" in log_line.lower() and "audit" in log_line.lower():
            match = re.search(r"Auditing\s+(\w+)", log_line)
            if match:
                target = match.group(1).upper()
                return {"command": f"seedgo audit @{target.lower()}", "caller": None, "target": target}

        # Pattern 4: Seedgo checklist commands
        if "standards_checklist" in log_line.lower() and "Running" in log_line:
            match = re.search(r"Running\s+(\w+)\s+standard\s+check\s+on\s+(.+)", log_line)
            if match:
                return {"command": f"seedgo checklist {match.group(2)}", "caller": None, "target": None}

        # Pattern 5: AI Mail commands - extract target
        if "[ai_mail]" in log_line.lower():
            if "Sending" in log_line:
                # Try to extract recipient
                target_match = re.search(r"to\s+@?(\w+)", log_line, re.IGNORECASE)
                target = target_match.group(1).upper() if target_match else None
                return {"command": "ai_mail send", "caller": None, "target": target}
            elif "inbox" in log_line.lower():
                return {"command": "ai_mail inbox", "caller": None, "target": None}

        # Pattern 6: Prax commands
        if "[prax]" in log_line.lower():
            if "monitor" in log_line.lower():
                return {"command": "prax monitor", "caller": None, "target": None}
            elif "status" in log_line.lower():
                return {"command": "prax status", "caller": None, "target": None}

        # Pattern 8: Backup operations (direct python3 calls)
        if "[backup" in log_line.lower():
            if "snapshot" in log_line.lower() and (
                "Starting" in log_line or "Running" in log_line or "Complete" in log_line
            ):
                return {"command": "backup snapshot", "caller": None, "target": None}
            elif "versioned" in log_line.lower() and ("Starting" in log_line or "Running" in log_line):
                return {"command": "backup versioned", "caller": None, "target": None}
            elif "sync" in log_line.lower() and ("Starting" in log_line or "Running" in log_line):
                return {"command": "backup sync", "caller": None, "target": None}

        # Pattern 9: Memory operations (direct python3 calls)
        if "[memory]" in log_line.lower() or "memory" in log_line.lower():
            if "rollover" in log_line.lower() and ("Starting" in log_line or "Processing" in log_line):
                return {"command": "memory rollover", "caller": None, "target": None}
            elif "search" in log_line.lower() and "query" in log_line.lower():
                return {"command": "memory search", "caller": None, "target": None}

        # Pattern 10: Spawn operations (direct python3 calls)
        if "[spawn]" in log_line.lower():
            if "Creating" in log_line and "branch" in log_line.lower():
                match = re.search(r"Creating\s+(?:branch\s+)?(\w+)", log_line)
                target = match.group(1).upper() if match else None
                return {"command": "spawn create branch", "caller": None, "target": target}

        # Pattern 11: Trigger operations (direct python3 calls)
        if "[trigger]" in log_line.lower():
            if "fired" in log_line.lower() or "triggered" in log_line.lower():
                return {"command": "trigger fire", "caller": None, "target": None}

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
                return {"command": display_cmd, "caller": caller, "target": target}

        # Pattern 7: ALL drone command executions - HIGH PRIORITY
        # Format: "Executing command [CALLER:PRAX]: seedgo.py audit @prax"
        if "Executing" in log_line and "command" in log_line:
            return self._match_executing_command(log_line)

        return None

    def _match_executing_command(self, log_line: str) -> Optional[Dict[str, Optional[str]]]:
        """Match 'Executing command' log lines and extract caller/target info."""
        caller_match = re.search(r"\[CALLER:(\w+)\]", log_line)
        caller = caller_match.group(1) if caller_match else None

        cmd_match = re.search(r"Executing(?:\s+activated)?\s+command(?:\s*\[CALLER:\w+\])?:\s*(.+)", log_line)
        if not cmd_match:
            return None

        cmd = cmd_match.group(1).strip()
        target = self._extract_target_from_cmd(cmd)

        # Clean up command display - simplify paths
        display_cmd = re.sub(r"[^\s]*/aipass/(\w+)/apps/\w+\.py", lambda m: f"@{m.group(1)}", cmd)
        display_cmd = re.sub(r"[^\s]*/aipass/(\w+)", lambda m: f"@{m.group(1)}", display_cmd)

        return {"command": display_cmd, "caller": caller, "target": target}

    @staticmethod
    def _extract_target_from_cmd(cmd: str) -> Optional[str]:
        """Extract target branch from a command string."""
        target_match = re.search(r"@(\w+)", cmd)
        if target_match:
            return target_match.group(1).upper()
        path_match = re.search(r"/aipass/(\w+)", cmd)
        if path_match:
            return path_match.group(1).upper()
        return None

    def _emit_command_separator(self, branch: str, command_info) -> None:
        """
        Emit command separator event to queue with caller and target attribution.
        Deduplicates consecutive identical commands per branch.
        """
        # Handle dict format (new) and legacy string/tuple formats
        if isinstance(command_info, dict):
            command = command_info.get("command", "")
            caller = command_info.get("caller")
            target = command_info.get("target")
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
            event_type="command",
            branch=branch,
            action="executed",
            message=command,
            level="info",
            timestamp=datetime.now(),
            caller=caller,
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
        if " | " in log_line:
            parts = log_line.split(" | ")
            if len(parts) >= 4:
                # Format: [BRANCH] TIMESTAMP | SOURCE | LEVEL | MESSAGE
                # Return everything after the LEVEL part
                return " | ".join(parts[3:]).strip()
            elif len(parts) >= 2:
                # Simpler format, return last part
                return parts[-1].strip()

        # Fallback: return as-is if can't parse
        return log_line.strip()

    def _emit_log_event(self, branch: str, log_line: str, level: str, log_file_path: Optional[str] = None) -> None:
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
        if HAS_TRIGGER and level == "error":
            # Extract module name from log line if possible
            module_name = "unknown"
            if " | " in log_line:
                parts = log_line.split(" | ")
                if len(parts) >= 2:
                    module_name = parts[1].strip()

            trigger.fire(
                "error_detected",  # type: ignore[union-attr]
                branch=branch,
                message=clean_message,
                error_hash=_generate_error_hash(module_name, clean_message),
                timestamp=current_time.isoformat(),
                log_file=log_file_path or "unknown",
                module_name=module_name,
            )

        # Create monitoring event
        log_event = MonitoringEvent(
            priority=0,  # Auto-calculated from level
            event_type="log",
            branch=branch,
            action="logged",
            message=clean_message,
            level=level,
            timestamp=current_time,
        )

        # Push to queue
        self.event_queue.enqueue(log_event)

    def initialize_positions(self):
        """
        Initialize log positions to END of existing files.

        Only show NEW entries after watcher starts.
        """
        if not get_system_logs_dir().exists():
            logger.warning(f"System logs directory not found: {get_system_logs_dir()}")
            return

        for log_file in get_system_logs_dir().glob("*.log"):
            try:
                self.log_positions[str(log_file)] = log_file.stat().st_size
            except Exception as e:
                logger.info(f"Could not get size for {log_file}: {e}")


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

if __name__ == "__main__":
    """
    Standalone test - starts log watcher and prints events from queue.

    Usage:
        drone @prax log-watcher

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
                timestamp = event.timestamp.strftime("%H:%M:%S")

                # Color by level
                level_colors = {
                    "error": "red",
                    "warning": "yellow",
                    "info": "white",
                    "debug": "dim",
                }
                color = level_colors.get(event.level, "white")

                # Print event
                if event.event_type == "command":
                    console.print(f"\n[bold green]{event.message}[/bold green]\n")
                else:
                    console.print(
                        f"[dim]{timestamp}[/dim] [cyan][{event.branch:>8}][/cyan] [{color}]{event.message}[/{color}]"
                    )

            # Small delay to prevent CPU spinning
            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("[log_watcher] Stopped by user")
        console.print("\n[yellow]Stopping log watcher...[/yellow]")
        stop_log_watcher()
        queue.stop()
        console.print("[green]Log watcher stopped[/green]")
