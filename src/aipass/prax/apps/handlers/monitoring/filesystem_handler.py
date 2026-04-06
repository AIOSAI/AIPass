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
3. Parses CLI session files for agent activity tracking (Claude Code, Codex, Gemini)

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
        # Track model per session file for display tags
        self._session_models: Dict[str, str] = {}
        # Track detected branch per CLI session file (from session metadata)
        self._session_branches: Dict[str, str] = {}
        # Track files we've already warned about for branch detection
        self._branch_warn_logged: set = set()

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
    def _extract_model_from_entry(entry: dict) -> Optional[str]:
        """Extract model name from a Claude Code JSONL entry."""
        msg = entry.get('message', {}) if isinstance(entry.get('message'), dict) else {}
        return msg.get('model')

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

    # =========================================================================
    # CLI SESSION BRANCH DETECTION
    # =========================================================================

    @staticmethod
    def _branch_from_cwd(cwd: str) -> Optional[str]:
        """Extract branch name from a CWD path like /path/to/src/aipass/devpulse."""
        if not cwd:
            return None
        parts = Path(cwd).parts
        if 'aipass' in parts:
            idx = parts.index('aipass')
            if idx + 1 < len(parts):
                return parts[idx + 1].upper()
        # Fallback: check src/{name} for branches outside aipass namespace
        if 'src' in parts:
            idx = parts.index('src')
            if idx + 1 < len(parts):
                return parts[idx + 1].upper()
        return None

    def _get_codex_branch(self, file_path, path_key: str) -> str:
        """Get branch for a Codex session, reading session_meta if needed."""
        if path_key in self._session_branches:
            return self._session_branches[path_key]

        # Read first line of JSONL for session_meta
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                first_line = f.readline().strip()
                if first_line:
                    meta = _json.loads(first_line)
                    if meta.get('type') == 'session_meta':
                        cwd = meta.get('payload', {}).get('cwd', '')
                        branch = self._branch_from_cwd(cwd)
                        if branch:
                            self._session_branches[path_key] = branch
                            return branch
        except (OSError, _json.JSONDecodeError) as e:
            if path_key not in self._branch_warn_logged:
                logger.info(f"[monitor] Could not read Codex session_meta: {e}")
                self._branch_warn_logged.add(path_key)

        self._session_branches[path_key] = 'CODEX'
        return 'CODEX'

    def _get_gemini_branch(self, file_path, path_key: str) -> str:
        """Get branch for a Gemini session from project slug in path."""
        if path_key in self._session_branches:
            return self._session_branches[path_key]

        # Path format: ~/.gemini/tmp/<project-slug>/chats/session-*.json
        # Project slug maps to a directory via ~/.gemini/projects.json
        parts = Path(file_path).parts
        if 'tmp' in parts:
            idx = parts.index('tmp')
            if idx + 1 < len(parts):
                slug = parts[idx + 1]
                # Try to resolve slug to real branch via projects.json
                projects_file = Path.home() / '.gemini' / 'projects.json'
                if projects_file.exists():
                    try:
                        data = _json.loads(projects_file.read_text())
                        for project_path, project_slug in data.get('projects', {}).items():
                            if project_slug == slug:
                                branch = self._branch_from_cwd(project_path)
                                if branch:
                                    self._session_branches[path_key] = branch
                                    return branch
                    except (OSError, _json.JSONDecodeError):
                        pass
                # Fallback: use slug as branch name
                self._session_branches[path_key] = slug.upper()
                return slug.upper()

        self._session_branches[path_key] = 'GEMINI'
        return 'GEMINI'

    # =========================================================================
    # MODEL TAG HELPERS
    # =========================================================================

    @staticmethod
    def _shorten_model(model: str) -> str:
        """Shorten a model identifier for display."""
        if not model:
            return ''
        m = model.lower()
        # Claude models
        if 'opus' in m:
            return 'opus'
        if 'sonnet' in m:
            return 'sonnet'
        if 'haiku' in m:
            return 'haiku'
        # OpenAI/Codex models
        if m.startswith('gpt-'):
            return m  # already short: gpt-4o, gpt-5.4
        if m.startswith('o') and any(c.isdigit() for c in m):
            return m  # o1, o3, o4-mini
        # Gemini models
        if 'gemini' in m:
            # gemini-3-flash-preview → gemini-3-flash
            parts = m.replace('gemini-', '').split('-')
            return 'gemini-' + '-'.join(p for p in parts if p != 'preview')
        # Fallback: first 15 chars
        return model[:15]

    def _tag_branch_with_model(self, path_key: str, branch: str) -> str:
        """Append model tag to branch if known for this session."""
        model = self._session_models.get(path_key, '')
        if model:
            return f"{branch}/{model}"
        return branch

    # =========================================================================
    # CODEX AGENT ACTIVITY PARSING (JSONL sessions)
    # =========================================================================

    @staticmethod
    def _extract_codex_action(entry: dict) -> Optional[str]:
        """Extract a display action string from a Codex JSONL entry."""
        entry_type = entry.get('type', '')
        payload = entry.get('payload', {})

        if entry_type == 'event_msg':
            event_type = payload.get('type', '')
            if event_type == 'agent_message':
                text = payload.get('text', '') or payload.get('message', '')
                if text:
                    return f"💬 {str(text)[:120]}"
                return '💬 Agent response'
            if event_type == 'user_message':
                return '📩 User message'
            if event_type == 'token_count':
                return '💭 Thinking'
            if event_type == 'task_started':
                return '🚀 Task started'
            if event_type == 'task_complete':
                return '✅ Task complete'
            return None

        if entry_type == 'response_item':
            item = payload.get('item', payload)
            item_type = item.get('type', '')
            if item_type == 'function_call':
                name = item.get('name', 'tool')
                args = item.get('arguments', '')
                if isinstance(args, str) and len(args) > 80:
                    args = args[:80] + '...'
                return f"🔧 {name}"
            if item_type == 'function_call_output':
                return None  # Skip output events
            if item_type == 'message':
                content = item.get('content', [])
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            text = part.get('text', '')
                            if text:
                                return f"💬 {text[:120]}"
                return '💬 Agent response'
            return None

        if entry_type == 'session_meta':
            return None  # Skip metadata

        if entry_type == 'turn_context':
            return None  # Skip context snapshots

        return None

    # =========================================================================
    # GEMINI AGENT ACTIVITY PARSING (full JSON sessions)
    # =========================================================================

    @staticmethod
    def _extract_gemini_action(message: dict) -> Optional[str]:
        """Extract a display action string from a Gemini session message."""
        msg_type = message.get('type', '')

        if msg_type == 'user':
            return '📩 User message'

        if msg_type == 'gemini':
            # Check for tool calls first
            tool_calls = message.get('toolCalls', [])
            if tool_calls:
                last_tool = tool_calls[-1]
                name = last_tool.get('displayName', last_tool.get('name', 'tool'))
                return f"🔧 {name}"

            # Check for thoughts
            thoughts = message.get('thoughts', [])
            if thoughts:
                return '💭 Thinking'

            # Text response
            content = message.get('content', [])
            if isinstance(content, list) and content:
                for part in content:
                    if isinstance(part, dict):
                        text = part.get('text', '').strip()
                        if text:
                            return f"💬 {text[:120]}"
            elif isinstance(content, str) and content.strip():
                return f"💬 {content.strip()[:120]}"

            return '💬 Agent response'

        return None

    def _parse_gemini_activity(self, file_path, branch):
        """Parse Gemini session JSON to show agent actions.

        Gemini rewrites the entire file on each change, so we track
        the message count and only process new messages.
        """
        try:
            path_key = str(file_path)
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                data = _json.load(f)

            messages = data.get('messages', [])
            last_count = self._jsonl_positions.get(path_key, 0)

            if len(messages) <= last_count:
                return True  # No new messages

            self._jsonl_positions[path_key] = len(messages)

            # Extract model from gemini messages
            for msg in messages:
                model = msg.get('model', '')
                if model:
                    self._session_models[path_key] = self._shorten_model(model)
                    break

            # Process new messages (most recent first for dedup)
            new_messages = messages[last_count:]
            for msg in reversed(new_messages):
                action_text = self._extract_gemini_action(msg)
                if not action_text:
                    continue

                if self._last_agent_action.get(path_key) == action_text:
                    return True
                self._last_agent_action[path_key] = action_text

                tagged_branch = self._tag_branch_with_model(path_key, branch)
                evt = MonitoringEvent(
                    priority=1, event_type='agent', branch=tagged_branch,
                    action='activity', message=action_text, level='info',
                )
                if self._event_queue:
                    self._event_queue.enqueue(evt)
                return True

            return True
        except (_json.JSONDecodeError, OSError) as e:
            logger.info(f"[monitor] Gemini parse error for {file_path.name}: {e}")
            return False

    def _parse_codex_activity(self, file_path, branch):
        """Parse Codex session JSONL to show agent actions.

        Same JSONL tail-and-parse approach as Claude Code, but uses
        _extract_codex_action() for Codex-specific event types.
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
                    logger.info(f"[monitor] Skipping malformed Codex JSONL: {e}")
                    continue

                # Extract model from session_meta or response_item
                if entry.get('type') == 'session_meta':
                    model = entry.get('payload', {}).get('model', '')
                    if model:
                        self._session_models[path_key] = self._shorten_model(model)
                elif entry.get('type') == 'response_item':
                    model = entry.get('payload', {}).get('item', {}).get('model', '')
                    if model:
                        self._session_models[path_key] = self._shorten_model(model)

                action_text = self._extract_codex_action(entry)
                if not action_text:
                    continue

                if self._last_agent_action.get(path_key) == action_text:
                    return True
                self._last_agent_action[path_key] = action_text

                tagged_branch = self._tag_branch_with_model(path_key, branch)
                evt = MonitoringEvent(
                    priority=1, event_type='agent', branch=tagged_branch,
                    action='activity', message=action_text, level='info',
                )
                if self._event_queue:
                    self._event_queue.enqueue(evt)
                return True

            return True
        except Exception as e:
            logger.info(f"[monitor] Codex JSONL parse error for {file_path.name}: {e}")
            return False

    # =========================================================================
    # CLAUDE CODE AGENT ACTIVITY PARSING (JSONL sessions)
    # =========================================================================

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

                # Extract model for display tag
                model = self._extract_model_from_entry(entry)
                if model:
                    self._session_models[path_key] = self._shorten_model(model)

                action_text = self._extract_action_from_entry(entry)
                if not action_text:
                    continue

                if self._last_agent_action.get(path_key) == action_text:
                    return True
                self._last_agent_action[path_key] = action_text

                tagged_branch = self._tag_branch_with_model(path_key, branch)
                evt = MonitoringEvent(
                    priority=1, event_type='agent', branch=tagged_branch,
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

            # Codex JSONL files: parse agent activity
            if file_path.suffix == '.jsonl' and '.codex/sessions/' in path_str:
                codex_branch = self._get_codex_branch(file_path, path_str)
                if self._parse_codex_activity(file_path, codex_branch):
                    return

            # Gemini JSON session files: parse agent activity
            if file_path.suffix == '.json' and '.gemini/tmp/' in path_str and '/chats/' in path_str:
                gemini_branch = self._get_gemini_branch(file_path, path_str)
                if self._parse_gemini_activity(file_path, gemini_branch):
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
