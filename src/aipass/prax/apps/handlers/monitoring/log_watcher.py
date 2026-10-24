# =================== AIPass ====================
# Name: log_watcher.py
# Description: Log File Monitor
# Version: 1.2.0
# Created: 2025-11-23
# Modified: 2026-10-24
# =============================================

"""PRAX Log Watcher - Event Queue Integration"""

import ast
import os
import sys
from pathlib import Path

from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import re

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax.apps.modules.logger import get_direct_logger
from watchdog.observers import Observer as WatchdogObserver  # type: ignore
from watchdog.events import FileSystemEventHandler  # type: ignore

from aipass.prax.apps.handlers.config.load import get_system_logs_dir

from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent, MonitoringQueue
from aipass.prax.apps.handlers.monitoring.branch_detector import detect_branch_from_log

from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

# No trigger fire here: @trigger's own log watcher fires the full payload; this one feeds Mission Control only.


_log_observer: Any = None


def read_new_lines(path, last_pos: int) -> Tuple[List[str], int]:
    """Non-blank complete lines appended after last_pos, and the offset just past the last newline.

    A trailing line still being written is left unread, so the next call gets it whole."""
    size = Path(path).stat().st_size
    if size < last_pos:  # truncated or rotated: start over
        last_pos = 0
    if size <= last_pos:
        return [], last_pos
    with open(path, "rb") as f:
        f.seek(last_pos)
        data = f.read(size - last_pos)
    end = data.rfind(b"\n")
    if end < 0:
        return [], last_pos
    text = data[: end + 1].decode("utf-8", errors="ignore")
    return [line for line in text.splitlines() if line.strip()], last_pos + end + 1


class LogFileWatcher(FileSystemEventHandler):
    """Watch log files and push events to monitoring queue."""

    def __init__(self, event_queue: MonitoringQueue):
        """Initialize log watcher."""
        super().__init__()
        self.event_queue = event_queue
        self.log_positions: Dict[str, int] = {}
        self.last_command_per_branch: Dict[str, str] = {}

    def _process_log_line(self, branch: str, line: str) -> None:
        """Process a single log line: detect hooks, commands, or emit as log event."""
        if not line.strip():
            return
        hook_info = self._extract_hook_info(line)
        if hook_info:
            self._emit_hook_event(branch, hook_info)
            return
        command_info = self._extract_command_info(line)
        if command_info:
            self._emit_command_separator(branch, command_info)
            return
        self._emit_log_event(branch, line, self._detect_log_level(line))

    def _read_new_content(self, file_path: str) -> List[str]:
        """Complete new lines of a log file since its last position."""
        lines, self.log_positions[file_path] = read_new_lines(file_path, self.log_positions.get(file_path, 0))
        return lines

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
            lines = self._read_new_content(file_path)
            if not lines:
                return

            branch = detect_branch_from_log(file_path)
            for line in lines:
                self._process_log_line(branch, line)

        except Exception as e:
            logger.info(f"Error reading log file {file_path}: {e}")

    _HOOK_PATTERN = re.compile(r"\[HOOKS\]\s+(\w+)\s+(\w+)")

    def _extract_hook_info(self, log_line: str) -> Optional[Dict[str, str]]:
        """Extract hook event info from structured [HOOKS] log lines.

        Contract with hooks: [HOOKS] cadence fired loader=global turn=35 period=5 offset=0 session=..."""
        match = self._HOOK_PATTERN.search(log_line)
        if not match:
            return None
        name = match.group(1)
        action = match.group(2)
        details: Dict[str, str] = {"name": name, "action": action}
        for kv_match in re.finditer(r"(\w+)=(\S+)", log_line):
            details[kv_match.group(1)] = kv_match.group(2)
        return details

    def _emit_hook_event(self, branch: str, hook_info: Dict[str, str]) -> None:
        """Emit a hook event to the monitoring queue."""
        action = hook_info.get("action", "unknown")
        name = hook_info.get("name", "hook")
        loader = hook_info.get("loader", "")
        turn = hook_info.get("turn", "")
        period = hook_info.get("period", "")
        offset = hook_info.get("offset", "")
        session = hook_info.get("session", "")

        parts = [f"{name}:{action}"]
        if loader:
            parts.append(f"loader={loader}")
        if turn:
            parts.append(f"t={turn}")
        if period:
            parts.append(f"p={period}")
        if offset and offset != "0":
            parts.append(f"off={offset}")
        if session:
            parts.append(f"s={session[:8]}")
        message = " ".join(parts)

        level = "success" if action == "fired" else "info"

        hook_event = MonitoringEvent(
            priority=2,
            event_type="hook",
            branch=branch,
            action=action,
            message=message,
            level=level,
            timestamp=datetime.now(),
        )
        self.event_queue.enqueue(hook_event)

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
        """Extract command info (command, caller, target) from a log line, or None."""
        # Format: "Drone started with args: ['close', 'plan', '0098']"
        if "Drone started with args:" in log_line or "[drone] Drone started with args:" in log_line:
            match = re.search(r"args:\s*\[([^\]]+)\]", log_line)
            if match:
                # The command as typed, its @branch read as the target, as _match_executing_command shows.
                try:
                    args = [str(arg) for arg in ast.literal_eval(f"[{match.group(1)}]")]
                except (ValueError, SyntaxError) as exc:
                    # The phrase this branch matches is kept out of the line, so it is not parsed again
                    logger.info("[log_watcher] drone args not a literal list (%s), shown as raw text", exc)
                    args = [match.group(1).replace("'", "").replace('"', "")]
                command = " ".join(args)
                return {"command": f"drone {command}", "caller": None, "target": self._extract_target_from_cmd(command)}

        if "[FLOW]" in log_line or "FLOW_PLAN]" in log_line:
            result = self._match_flow_command(log_line)
            if result:
                return result

        if "[seedgo]" in log_line.lower() and "audit" in log_line.lower():
            match = re.search(r"Auditing\s+(\w+)", log_line)
            if match:
                target = match.group(1).upper()
                return {"command": f"seedgo audit @{target.lower()}", "caller": None, "target": target}

        if "standards_checklist" in log_line.lower() and "Running" in log_line:
            match = re.search(r"Running\s+(\w+)\s+standard\s+check\s+on\s+(.+)", log_line)
            if match:
                return {"command": f"seedgo checklist {match.group(2)}", "caller": None, "target": None}

        if "[ai_mail]" in log_line.lower():
            if "Sending" in log_line:
                target_match = re.search(r"to\s+@?(\w+)", log_line, re.IGNORECASE)
                target = target_match.group(1).upper() if target_match else None
                return {"command": "ai_mail send", "caller": None, "target": target}
            elif "inbox" in log_line.lower():
                return {"command": "ai_mail inbox", "caller": None, "target": None}

        if "[prax]" in log_line.lower():
            if "monitor" in log_line.lower():
                return {"command": "prax monitor", "caller": None, "target": None}
            elif "status" in log_line.lower():
                return {"command": "prax status", "caller": None, "target": None}

        if "[backup" in log_line.lower():
            if "snapshot" in log_line.lower() and (
                "Starting" in log_line or "Running" in log_line or "Complete" in log_line
            ):
                return {"command": "backup snapshot", "caller": None, "target": None}
            elif "versioned" in log_line.lower() and ("Starting" in log_line or "Running" in log_line):
                return {"command": "backup versioned", "caller": None, "target": None}
            elif "sync" in log_line.lower() and ("Starting" in log_line or "Running" in log_line):
                return {"command": "backup sync", "caller": None, "target": None}

        if "[memory]" in log_line.lower() or "memory" in log_line.lower():
            if "rollover" in log_line.lower() and ("Starting" in log_line or "Processing" in log_line):
                return {"command": "memory rollover", "caller": None, "target": None}
            elif "search" in log_line.lower() and "query" in log_line.lower():
                return {"command": "memory search", "caller": None, "target": None}

        if "[spawn]" in log_line.lower():
            if "Creating" in log_line and "branch" in log_line.lower():
                match = re.search(r"Creating\s+(?:branch\s+)?(\w+)", log_line)
                target = match.group(1).upper() if match else None
                return {"command": "spawn create branch", "caller": None, "target": target}

        if "[trigger]" in log_line.lower():
            if "fired" in log_line.lower() or "triggered" in log_line.lower():
                return {"command": "trigger fire", "caller": None, "target": None}

        # Routing carries the caller; it must match before the generic Executing match below.
        # Format: "Routing @flow [CALLER:PRAX] → create ['.', 'Subject']"
        if "Routing @" in log_line and "[CALLER:" in log_line:
            caller_match = re.search(r"\[CALLER:(\w+)\]", log_line)
            caller = caller_match.group(1) if caller_match else None

            route_match = re.search(r"Routing\s+@(\w+).*?→\s*(\S+)\s*(.*)", log_line)
            if route_match:
                target = route_match.group(1).upper()
                cmd_name = route_match.group(2)
                cmd_args = route_match.group(3).strip()
                display_cmd = f"drone @{route_match.group(1)} {cmd_name} {cmd_args}".strip()
                return {"command": display_cmd, "caller": caller, "target": target}

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

        display_cmd = re.sub(r"[^\s]*/aipass/(\w+)/apps/\w+\.py", lambda m: f"@{m.group(1)}", cmd)
        display_cmd = re.sub(r"[^\s]*/aipass/(\w+)", lambda m: f"@{m.group(1)}", display_cmd)

        return {"command": display_cmd, "caller": caller, "target": target}

    @staticmethod
    def _extract_target_from_cmd(cmd: str) -> Optional[str]:
        """Extract target branch from a command string."""
        target_match = re.search(r"@(\w+)", cmd)
        if target_match:
            return target_match.group(1).upper()
        norm = cmd.replace("\\", "/")
        path_match = re.search(r"/aipass/(\w+)", norm)
        if path_match:
            return path_match.group(1).upper()
        return None

    def _emit_command_separator(self, branch: str, command_info) -> None:
        """Emit a command separator event, skipping a repeat of the branch's last command."""
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
        """Parse raw log line to extract just the message content.

        Raw format: [BRANCH_NAME] TIMESTAMP | SOURCE | LEVEL | MESSAGE"""
        if " | " in log_line:
            parts = log_line.split(" | ")
            if len(parts) >= 4:
                return " | ".join(parts[3:]).strip()
            elif len(parts) >= 2:
                return parts[-1].strip()

        return log_line.strip()

    def _emit_log_event(self, branch: str, log_line: str, level: str) -> None:
        """Create and emit log event to monitoring queue."""
        clean_message = self._parse_log_message(log_line)
        current_time = datetime.now()

        log_event = MonitoringEvent(
            priority=0,  # Auto-calculated from level
            event_type="log",
            branch=branch,
            action="logged",
            message=clean_message,
            level=level,
            timestamp=current_time,
        )

        self.event_queue.enqueue(log_event)

    def initialize_positions(self):
        """Initialize log positions to END of existing files, so only new entries show."""
        if not get_system_logs_dir().exists():
            logger.warning(
                f"[log_watcher] The live monitor's log watcher found no system logs folder, so no "
                f"log lines will appear on screen. Nothing is lost — branches still write their own "
                f"logs. Expected at: {get_system_logs_dir()}"
            )
            return

        for log_file in get_system_logs_dir().glob("*.log"):
            try:
                self.log_positions[str(log_file)] = log_file.stat().st_size
            except Exception as e:
                logger.info(f"Could not get size for {log_file}: {e}")


def start_log_watcher(event_queue: MonitoringQueue, use_polling: bool = False) -> Any:
    """Start watching log files and pushing events to queue."""
    global _log_observer

    if _log_observer and _log_observer.is_alive():
        logger.warning(
            "[log_watcher] The live monitor's log watcher was already running — stopping the old "
            "one and starting fresh. On-disk logs are untouched; the screen may briefly skip lines."
        )
        stop_log_watcher()

    watcher = LogFileWatcher(event_queue)

    # Soft start: seek to end of all logs, only show NEW activity after this
    watcher.initialize_positions()

    if use_polling:
        from watchdog.observers.polling import PollingObserver  # type: ignore

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
    """Check if log watcher is currently active."""
    return _log_observer is not None and _log_observer.is_alive()


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

    queue = MonitoringQueue()

    observer = start_log_watcher(queue)

    try:
        while True:
            event = queue.dequeue(timeout=0.5)

            if event:
                timestamp = event.timestamp.strftime("%H:%M:%S")

                level_colors = {
                    "error": "red",
                    "warning": "yellow",
                    "info": "white",
                    "debug": "dim",
                }
                color = level_colors.get(event.level, "white")

                if event.event_type == "command":
                    console.print(f"\n[bold green]{event.message}[/bold green]\n")
                else:
                    console.print(
                        f"[dim]{timestamp}[/dim] [cyan][{event.branch:>8}][/cyan] [{color}]{event.message}[/{color}]"
                    )

            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("[log_watcher] Stopped by user")
        console.print("\n[yellow]Stopping log watcher...[/yellow]")
        stop_log_watcher()
        queue.stop()
        console.print("[green]Log watcher stopped[/green]")
