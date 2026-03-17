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

Extracted from monitor_module.py to maintain 3-layer architecture:
  module (orchestration) -> handler (implementation)
"""

import json as _json
from pathlib import Path
from typing import Optional, Dict

from watchdog.events import FileSystemEventHandler

from aipass.prax import logger

# Trigger integration (graceful fallback if unavailable)
try:
    from aipass.trigger.apps.modules.core import trigger
    _trigger_available = True
except ImportError:
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

    def _parse_agent_activity(self, file_path, branch):
        """Parse Claude Code session JSONL to show agent actions.

        Returns True if an event was emitted (or deduped), False on failure.
        """
        try:
            path_key = str(file_path)
            current_size = file_path.stat().st_size
            last_pos = self._jsonl_positions.get(path_key, 0)

            # File shrunk or new - reset
            if current_size < last_pos:
                last_pos = 0

            if current_size <= last_pos:
                return True  # No new data, but not an error

            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(last_pos)
                new_data = f.read()
                self._jsonl_positions[path_key] = f.tell()

            # Parse last meaningful line
            lines = [l for l in new_data.strip().split('\n') if l.strip()]
            if not lines:
                return True  # Empty, not an error

            for line in reversed(lines):
                try:
                    entry = _json.loads(line)
                except _json.JSONDecodeError:
                    continue

                entry_type = entry.get('type', '')
                msg = entry.get('message', {}) if isinstance(entry.get('message'), dict) else {}
                content = msg.get('content', [])

                # Skip noise entries - look for next meaningful one
                if entry_type in ('progress', 'system', 'file-history-snapshot', 'queue-operation'):
                    continue

                action_text = None

                if entry_type == 'assistant' and isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get('type', '')

                        if item_type == 'thinking':
                            action_text = '💭 Thinking'
                            break
                        elif item_type == 'tool_use':
                            tool_name = item.get('name', '')
                            inp = item.get('input', {})
                            if tool_name in ('Read', 'Edit', 'Write'):
                                fp = inp.get('file_path', '')
                                short = fp.split('/')[-1] if '/' in fp else fp
                                action_text = f"🔧 {tool_name}: {short}"
                            elif tool_name == 'Bash':
                                desc = inp.get('description', '')
                                if not desc:
                                    cmd = inp.get('command', '')[:120]
                                    desc = cmd
                                action_text = f"⚡ Bash: {desc[:120]}"
                            elif tool_name in ('Grep', 'Glob'):
                                pat = inp.get('pattern', '')[:80]
                                action_text = f"🔍 {tool_name}: {pat}"
                            elif tool_name == 'Task':
                                desc = inp.get('description', '')[:80]
                                action_text = f"🚀 Agent: {desc}"
                            else:
                                action_text = f"🔧 {tool_name}"
                            break
                        elif item_type == 'text':
                            text = item.get('text', '').strip()[:200]
                            if text:
                                action_text = f"💬 {text}"
                            break

                elif entry_type == 'user':
                    # Skip tool_result entries (noise - every tool call produces one)
                    # Only show actual user messages (new prompts)
                    is_tool_result = False
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get('type') == 'tool_result':
                                is_tool_result = True
                                break
                    if not is_tool_result:
                        action_text = '📩 User message'

                if action_text:
                    # Dedup: skip if same action for same session
                    if self._last_agent_action.get(path_key) == action_text:
                        return True  # Deduped, not an error
                    self._last_agent_action[path_key] = action_text

                    evt = MonitoringEvent(
                        priority=1,
                        event_type='agent',
                        branch=branch,
                        action='activity',
                        message=action_text,
                        level='info'
                    )
                    if self._event_queue:
                        self._event_queue.enqueue(evt)
                    return True

            # All lines were progress/system - that's fine
            return True

        except Exception as e:
            logger.info(f"[monitor] JSONL parse error for {file_path.name}: {e}")
            return False

    # =========================================================================
    # INTERNAL EVENT PROCESSING
    # =========================================================================

    def _handle_event(self, action, path_str):
        """Process file event and push to queue."""
        try:
            file_path = Path(path_str)

            # Check if should monitor this path
            if not should_monitor(file_path):
                return

            # Detect branch from path
            branch = detect_branch_from_path(str(file_path))

            # Claude Code JSONL files: parse agent activity instead of raw modification
            if file_path.suffix == '.jsonl' and '.claude/projects/' in path_str:
                # Distinguish subagents from main sessions
                # Main: ~/.claude/projects/{hash}/{uuid}.jsonl
                # Sub:  ~/.claude/projects/{hash}/{uuid}/subagents/agent-{id}.jsonl
                if '/subagents/' in path_str:
                    branch = branch + ' agent'
                if self._parse_agent_activity(file_path, branch):
                    return  # Parsed successfully, don't show raw event
                # Parsing failed - fall through to show raw file event

            # Check if this file indicates a command (python3 direct calls)
            if action == 'modified' and file_path.name in self._command_indicator_files:
                cmd = self._command_indicator_files[file_path.name]
                dedup_key = f"{branch}:{cmd}"
                if self._last_file_command.get(file_path.name) != dedup_key:
                    self._last_file_command[file_path.name] = dedup_key
                    cmd_event = MonitoringEvent(
                        priority=2,
                        event_type='command',
                        branch=branch,
                        action='executed',
                        message=cmd,
                        level='info'
                    )
                    if self._event_queue:
                        self._event_queue.enqueue(cmd_event)
                # Still show the file event too (don't return)

            # Get priority
            priority_level = get_priority(file_path, action)

            # Build display name with context (branch-relative path or short path)
            display_name = file_path.name
            # Show parent dir for context when file is deep in a branch
            parts = file_path.parts
            # Find branch root and show relative path from there
            for i, part in enumerate(parts):
                if part in ('apps', 'handlers', 'modules', 'docs', 'templates'):
                    display_name = '/'.join(parts[i:])
                    break

            # Create event
            evt = MonitoringEvent(
                priority=0,  # Will be set based on level
                event_type='file',
                branch=branch,
                action=action,
                message=f"{action.upper()}: {display_name}",
                level=priority_level if priority_level in ['error', 'warning', 'info'] else 'info'
            )

            # Push to queue
            if self._event_queue:
                self._event_queue.enqueue(evt)
        except Exception as e:
            # Log error but don't crash the watcher
            logger.error(f"[monitor] Error handling {action} event for {path_str}: {e}")
