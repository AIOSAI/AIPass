# =================== AIPass ====================
# Name: filesystem_handler.py
# Description: FileSystem Event Handler
# Version: 0.1.0
# Created: 2026-03-08
# Modified: 2026-03-09
# =============================================

"""
PRAX Filesystem Event Handler

Watchdog FileSystemEventHandler that processes filesystem events and:
1. Pushes events to the monitoring event queue for display
2. Fires trigger events for cross-module integration
3. Parses Claude Code JSONL sessions for agent activity tracking

Extracted from monitor.py to maintain 3-layer architecture:
  module (orchestration) -> handler (implementation)
"""

import json as _json
from pathlib import Path
from typing import Optional, Dict

from watchdog.events import FileSystemEventHandler

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

# Trigger integration (graceful fallback if unavailable)
try:
    from aipass.trigger.apps.modules.core import trigger
    _trigger_available = True
except ImportError as e:
    logger.info(f"[monitor] trigger module not available, falling back: {e}")
    trigger = None  # type: ignore[assignment]
    _trigger_available = False

# Monitoring subsystem imports
from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent, MonitoringQueue
from aipass.prax.apps.handlers.monitoring.branch_detector import detect_branch_from_path
from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor, get_priority
from aipass.prax.apps.handlers.json import json_handler


class MonitoringFileHandler(FileSystemEventHandler):
    """
    File system event handler that pushes events to the monitoring queue
    and fires trigger events for cross-module integration.

    Args:
        event_queue: MonitoringQueue instance to push events into
        command_indicator_files: Map of filename -> command description for
            detecting commands from file modifications
    """

    def __init__(
        self,
        event_queue: Optional[MonitoringQueue] = None,
        command_indicator_files: Optional[Dict[str, str]] = None,
    ):
        super().__init__()
        self._event_queue = event_queue
        self._command_indicator_files = command_indicator_files or {}
        json_handler.log_operation("file_change_handled", {"has_queue": event_queue is not None})
        # Track last command emitted per file to avoid duplicate separators
        self._last_file_command: Dict[str, str] = {}
        # Track JSONL file positions for incremental reading
        self._jsonl_positions: Dict[str, int] = {}
        # Track last agent action per session to avoid duplicate displays
        self._last_agent_action: Dict[str, str] = {}

    # -- public property so the module can swap queues after construction ------
    @property
    def event_queue(self) -> Optional[MonitoringQueue]:
        return self._event_queue

    @event_queue.setter
    def event_queue(self, queue: Optional[MonitoringQueue]):
        self._event_queue = queue

    # =========================================================================
    # WATCHDOG EVENT METHODS
    # =========================================================================

    def on_created(self, event):
        if not event.is_directory:
            self._handle_event('created', event.src_path)
            self._fire_trigger('file_created', path=event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._handle_event('modified', event.src_path)
            self._fire_trigger('file_modified', path=event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._handle_event('deleted', event.src_path)
            self._fire_trigger('file_deleted', path=event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            # dest_path can be bytes or str, normalize to str for comparison
            dest_path_str = event.dest_path.decode() if isinstance(event.dest_path, bytes) else event.dest_path
            src_path_str = event.src_path.decode() if isinstance(event.src_path, bytes) else event.src_path
            if 'Trash' in dest_path_str or '.local/share/Trash' in dest_path_str:
                # Moved to Trash = deletion
                self._handle_event('deleted', src_path_str)
                self._fire_trigger('file_deleted', path=src_path_str)
            elif '.tmp.' in src_path_str or src_path_str.endswith('.tmp'):
                # Atomic write: tmp file moved to real file = modification
                self._handle_event('modified', dest_path_str)
                self._fire_trigger('file_modified', path=dest_path_str)
            else:
                self._handle_event('moved', dest_path_str)
                self._fire_trigger('file_moved', src_path=src_path_str, dest_path=dest_path_str)

    # =========================================================================
    # TRIGGER INTEGRATION
    # =========================================================================

    def _fire_trigger(self, event_name: str, **kwargs):
        """Fire a trigger event for cross-module integration."""
        if not _trigger_available:
            return
        try:
            trigger.fire(event_name, **kwargs)  # type: ignore[union-attr]
        except Exception as e:
            logger.warning(f"[monitor] trigger.fire('{event_name}') failed: {e}")

    # =========================================================================
    # AGENT ACTIVITY PARSING (Claude Code JSONL sessions)
    # =========================================================================

    @staticmethod
    def _format_tool_action(item: dict) -> Optional[str]:
        """Format a tool_use JSONL item into a display string."""
        tool_name = item.get('name', '')
        inp = item.get('input', {})
        if tool_name in ('Read', 'Edit', 'Write'):
            fp = inp.get('file_path', '')
            short = fp.split('/')[-1] if '/' in fp else fp
            return f"🔧 {tool_name}: {short}"
        if tool_name == 'Bash':
            desc = inp.get('description', '') or inp.get('command', '')[:120]
            return f"⚡ Bash: {desc[:120]}"
        if tool_name in ('Grep', 'Glob'):
            return f"🔍 {tool_name}: {inp.get('pattern', '')[:80]}"
        if tool_name == 'Task':
            return f"🚀 Agent: {inp.get('description', '')[:80]}"
        return f"🔧 {tool_name}"

    @staticmethod
    def _extract_action_from_entry(entry: dict) -> Optional[str]:
        """Extract a display action string from a JSONL entry."""
        entry_type = entry.get('type', '')
        msg = entry.get('message', {}) if isinstance(entry.get('message'), dict) else {}
        content = msg.get('content', [])

        if entry_type in ('progress', 'system', 'file-history-snapshot', 'queue-operation'):
            return None

        if entry_type == 'assistant' and isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get('type', '')
                if item_type == 'thinking':
                    return '💭 Thinking'
                if item_type == 'tool_use':
                    return MonitoringFileHandler._format_tool_action(item)
                if item_type == 'text':
                    text = item.get('text', '').strip()
                    return f"💬 {text}" if text else None

        if entry_type == 'user':
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'tool_result':
                        return None
            return '📩 User message'

        return None

    def _parse_agent_activity(self, file_path, branch):
        """Parse Claude Code session JSONL to show agent actions.

        Returns True if an event was emitted (or deduped), False on failure.
        """
        try:
            path_key = str(file_path)
            current_size = file_path.stat().st_size
            last_pos = self._jsonl_positions.get(path_key, 0)

            if current_size < last_pos:
                last_pos = 0
            if current_size <= last_pos:
                return True

            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(last_pos)
                new_data = f.read()
                self._jsonl_positions[path_key] = f.tell()

            lines = [l for l in new_data.strip().split('\n') if l.strip()]
            if not lines:
                return True

            for line in reversed(lines):
                try:
                    entry = _json.loads(line)
                except _json.JSONDecodeError as e:
                    logger.info(f"[monitor] Skipping malformed JSONL line: {e}")
                    continue

                action_text = self._extract_action_from_entry(entry)
                if not action_text:
                    continue

                if self._last_agent_action.get(path_key) == action_text:
                    return True
                self._last_agent_action[path_key] = action_text

                evt = MonitoringEvent(
                    priority=1, event_type='agent', branch=branch,
                    action='activity', message=action_text, level='info',
                )
                if self._event_queue:
                    self._event_queue.enqueue(evt)
                return True

            return True

        except Exception as e:
            logger.info(f"[monitor] JSONL parse error for {file_path.name}: {e}")
            return False

    # =========================================================================
    # INTERNAL EVENT PROCESSING
    # =========================================================================

    def _check_command_indicator(self, action, file_path, branch):
        """Check if file event indicates a command and emit separator if so."""
        if action != 'modified' or file_path.name not in self._command_indicator_files:
            return
        cmd = self._command_indicator_files[file_path.name]
        dedup_key = f"{branch}:{cmd}"
        if self._last_file_command.get(file_path.name) == dedup_key:
            return
        self._last_file_command[file_path.name] = dedup_key
        cmd_event = MonitoringEvent(
            priority=2, event_type='command', branch=branch,
            action='executed', message=cmd, level='info',
        )
        if self._event_queue:
            self._event_queue.enqueue(cmd_event)

    def _handle_event(self, action, path_str):
        """Process file event and push to queue."""
        try:
            file_path = Path(path_str)

            if not should_monitor(file_path):
                return

            branch = detect_branch_from_path(str(file_path))

            # Claude Code JSONL files: parse agent activity
            if file_path.suffix == '.jsonl' and '.claude/projects/' in path_str:
                if '/subagents/' in path_str:
                    branch = branch + ' agent'
                if self._parse_agent_activity(file_path, branch):
                    return

            self._check_command_indicator(action, file_path, branch)

            priority_level = get_priority(file_path, action)
            display_name = self._build_display_name(file_path)

            evt = MonitoringEvent(
                priority=0, event_type='file', branch=branch, action=action,
                message=f"{action.upper()}: {display_name}",
                level=priority_level if priority_level in ['error', 'warning', 'info'] else 'info',
            )
            if self._event_queue:
                self._event_queue.enqueue(evt)
        except Exception as e:
            logger.error(f"[monitor] Error handling {action} event for {path_str}: {e}")

    @staticmethod
    def _build_display_name(file_path: Path) -> str:
        """Build branch-relative display name for a file path."""
        parts = file_path.parts
        for i, part in enumerate(parts):
            if part in ('apps', 'handlers', 'modules', 'docs', 'templates'):
                return '/'.join(parts[i:])
        return file_path.name
