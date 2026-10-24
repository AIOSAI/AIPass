# =================== AIPass ====================
# Name: filesystem_handler.py
# Description: FileSystem Event Handler
# Version: 0.3.0
# Created: 2026-03-08
# Modified: 2026-10-23
# =============================================

"""PRAX Filesystem Event Handler"""

import contextlib
import json as _json
from pathlib import Path
from typing import Optional, Dict

from watchdog.events import FileSystemEventHandler

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.monitoring.event_queue import MonitoringEvent, MonitoringQueue
from aipass.prax.apps.handlers.monitoring.branch_detector import detect_branch_from_path
from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor, get_priority
from aipass.prax.apps.handlers.monitoring.log_watcher import read_new_lines
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()


class MonitoringFileHandler(FileSystemEventHandler):
    """File system event handler that pushes events to the monitoring queue."""

    def __init__(
        self,
        event_queue: Optional[MonitoringQueue] = None,
        command_indicator_files: Optional[Dict[str, str]] = None,
        sandbox_root: Optional[Path] = None,
    ):
        super().__init__()
        self._event_queue = event_queue
        self._command_indicator_files = command_indicator_files or {}
        # Below this root no event from a dropbox or an .archive is shown (should_monitor)
        self._sandbox_root = sandbox_root
        json_handler.log_operation("file_change_handled", {"has_queue": event_queue is not None})
        self._last_file_command: Dict[str, str] = {}
        self._jsonl_positions: Dict[str, int] = {}
        self._last_agent_action: Dict[str, str] = {}
        self._session_models: Dict[str, str] = {}
        self._session_branches: Dict[str, str] = {}
        self._branch_warn_logged: set = set()

    @property
    def event_queue(self) -> Optional[MonitoringQueue]:
        """The monitoring event queue used to publish file events."""
        return self._event_queue

    @event_queue.setter
    def event_queue(self, queue: Optional[MonitoringQueue]):
        """Replace the event queue (e.g. after handler construction)."""
        self._event_queue = queue

    def on_created(self, event):
        """Handle file creation events."""
        if not event.is_directory:
            self._handle_event("created", event.src_path)

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory:
            self._handle_event("modified", event.src_path)

    def on_deleted(self, event):
        """Handle file deletion events."""
        if not event.is_directory:
            self._handle_event("deleted", event.src_path)

    def on_moved(self, event):
        """Handle file move/rename events."""
        if not event.is_directory:
            # dest_path can be bytes or str, normalize to str for comparison
            dest_path_str = event.dest_path.decode() if isinstance(event.dest_path, bytes) else event.dest_path
            src_path_str = event.src_path.decode() if isinstance(event.src_path, bytes) else event.src_path
            if "Trash" in dest_path_str or ".local/share/Trash" in dest_path_str:
                self._handle_event("deleted", src_path_str)
            elif ".tmp." in src_path_str or src_path_str.endswith(".tmp"):
                # Atomic write: tmp file moved to real file = modification
                self._handle_event("modified", dest_path_str)
            else:
                self._handle_event("moved", dest_path_str)

    @staticmethod
    def _format_tool_action(item: dict) -> Optional[str]:
        """Format a tool_use JSONL item into a display string."""
        tool_name = item.get("name", "")
        inp = item.get("input", {})
        if tool_name in ("Read", "Edit", "Write"):
            fp = inp.get("file_path", "")
            short = fp.split("/")[-1] if "/" in fp else fp
            return f"🔧 {tool_name}: {short}"
        if tool_name == "Bash":
            desc = inp.get("description", "") or inp.get("command", "")[:120]
            return f"⚡ Bash: {desc[:120]}"
        if tool_name in ("Grep", "Glob"):
            return f"🔍 {tool_name}: {inp.get('pattern', '')[:80]}"
        if tool_name in ("Task", "Agent"):
            return f"🚀 Agent: {inp.get('description', '')[:80]}"
        if tool_name == "WebFetch":
            return f"🌐 WebFetch: {inp.get('url', '')[:80]}"
        if tool_name == "WebSearch":
            return f"🔍 WebSearch: {inp.get('query', '')[:80]}"
        if tool_name == "Monitor":
            return f"⚡ Monitor: {inp.get('command', '')[:120]}"
        if tool_name == "Skill":
            return f"🎯 Skill: {inp.get('skill', '')[:80]}"
        if tool_name == "NotebookEdit":
            fp = inp.get("notebook_path", "")
            short = fp.split("/")[-1] if "/" in fp else fp
            return f"🔧 NotebookEdit: {short}"
        return f"🔧 {tool_name}"

    @staticmethod
    def _extract_model_from_entry(entry: dict) -> Optional[str]:
        """Extract model name from a Claude Code JSONL entry."""
        msg = entry.get("message", {}) if isinstance(entry.get("message"), dict) else {}
        return msg.get("model")

    @staticmethod
    def _extract_action_from_entry(entry: dict) -> Optional[str]:
        """Extract a display action string from a JSONL entry."""
        entry_type = entry.get("type", "")
        msg = entry.get("message", {}) if isinstance(entry.get("message"), dict) else {}
        content = msg.get("content", [])

        if entry_type in ("progress", "system", "file-history-snapshot", "queue-operation"):
            return None

        if entry_type == "assistant" and isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type", "")
                if item_type == "thinking":
                    return "💭 Thinking"
                if item_type == "tool_use":
                    return MonitoringFileHandler._format_tool_action(item)
                if item_type == "text":
                    text = item.get("text", "").strip()
                    return f"💬 {text}" if text else None

        if entry_type == "user":
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        return None
            return "📩 User message"

        return None

    @staticmethod
    def _branch_from_cwd(cwd: str) -> Optional[str]:
        """Extract branch name from a CWD path like /path/to/src/aipass/devpulse."""
        if not cwd:
            return None
        parts = Path(cwd).parts
        if "aipass" in parts:
            idx = parts.index("aipass")
            if idx + 1 < len(parts):
                return parts[idx + 1].upper()
        # External project under ~/Projects/: branch_detector gives the full label (AIPL/POLYGLOT)
        projects_base = Path.home() / "Projects"
        try:
            Path(cwd).relative_to(projects_base)
            result = detect_branch_from_path(cwd)
            if result and result != "UNKNOWN":
                return result
        except ValueError:
            logger.info(
                f"[monitor] Live monitor file watcher is ignoring a folder outside "
                f"the watched area (~/Projects/): {cwd}"
            )
        # Fallback: check src/{name} for branches outside aipass namespace
        if "src" in parts:
            idx = parts.index("src")
            if idx + 1 < len(parts):
                return parts[idx + 1].upper()
        return None

    def _read_codex_cwd(self, file_path) -> Optional[str]:
        """Read CWD from the first line (session_meta) of a Codex JSONL file."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline().strip()
            if not first_line:
                return None
            meta = _json.loads(first_line)
            if meta.get("type") != "session_meta":
                return None
            return meta.get("payload", {}).get("cwd", "")
        except (OSError, _json.JSONDecodeError) as e:
            logger.info(f"[monitor] Could not read Codex session_meta: {e}")
            return None

    def _get_codex_branch(self, file_path, path_key: str) -> str:
        """Get branch for a Codex session, reading session_meta if needed."""
        if path_key in self._session_branches:
            return self._session_branches[path_key]

        cwd = self._read_codex_cwd(file_path)
        branch = self._branch_from_cwd(cwd) if cwd else None
        result = branch or "CODEX"
        self._session_branches[path_key] = result
        return result

    @staticmethod
    def _shorten_model(model: str) -> str:
        """Shorten a model identifier for display."""
        if not model:
            return ""
        m = model.lower()
        if "opus" in m:
            return "opus"
        if "sonnet" in m:
            return "sonnet"
        if "haiku" in m:
            return "haiku"
        if m.startswith("gpt-"):
            return m  # already short: gpt-4o, gpt-5.4
        if m.startswith("o") and any(c.isdigit() for c in m):
            return m  # o1, o3, o4-mini
        return model[:15]

    def _tag_branch_with_model(self, path_key: str, branch: str) -> str:
        """Append model tag to branch if known for this session."""
        model = self._session_models.get(path_key, "")
        if model:
            return f"{branch}/{model}"
        return branch

    @staticmethod
    def _extract_codex_action(entry: dict) -> Optional[str]:
        """Extract a display action string from a Codex JSONL entry."""
        entry_type = entry.get("type", "")
        payload = entry.get("payload", {})

        if entry_type == "event_msg":
            event_type = payload.get("type", "")
            if event_type == "agent_message":
                text = payload.get("text", "") or payload.get("message", "")
                if text:
                    return f"💬 {str(text)[:120]}"
                return "💬 Agent response"
            if event_type == "user_message":
                return "📩 User message"
            if event_type == "token_count":
                return "💭 Thinking"
            if event_type == "task_started":
                return "🚀 Task started"
            if event_type == "task_complete":
                return "✅ Task complete"
            return None

        if entry_type == "response_item":
            return MonitoringFileHandler._parse_codex_response_item(payload)

        if entry_type in ("session_meta", "turn_context"):
            return None

        return None

    @staticmethod
    def _parse_codex_response_item(payload: dict) -> Optional[str]:
        """Parse a Codex response_item payload into a display string."""
        item = payload.get("item", payload)
        item_type = item.get("type", "")
        if item_type == "function_call":
            return f"🔧 {item.get('name', 'tool')}"
        if item_type == "function_call_output":
            return None
        if item_type != "message":
            return None
        content = item.get("content", [])
        if not isinstance(content, list):
            return "💬 Agent response"
        for part in content:
            if isinstance(part, dict) and part.get("text"):
                return f"💬 {part['text'][:120]}"
        return "💬 Agent response"

    def _read_new_jsonl_lines(self, file_path, path_key: str) -> Optional[list]:
        """Read new complete lines from a JSONL file since last position. Returns None if no new data."""
        lines, self._jsonl_positions[path_key] = read_new_lines(file_path, self._jsonl_positions.get(path_key, 0))
        return lines or None

    def _safe_parse_json(self, line: str, label: str) -> Optional[dict]:
        """Parse a JSON line, logging errors. Returns None on failure."""
        try:
            return _json.loads(line)
        except _json.JSONDecodeError as e:
            logger.info(f"[monitor] Skipping malformed {label} JSONL: {e}")
            return None

    def _emit_agent_event(self, path_key: str, branch: str, action_text: str) -> bool:
        """Emit an agent activity event, deduplicating against last action."""
        if self._last_agent_action.get(path_key) == action_text:
            return True
        self._last_agent_action[path_key] = action_text
        tagged_branch = self._tag_branch_with_model(path_key, branch)
        evt = MonitoringEvent(
            priority=1,
            event_type="agent",
            branch=tagged_branch,
            action="activity",
            message=action_text,
            level="info",
        )
        if self._event_queue:
            self._event_queue.enqueue(evt)
        return True

    def _extract_codex_model(self, entry: dict, path_key: str) -> None:
        """Extract model from a Codex JSONL entry if present."""
        entry_type = entry.get("type", "")
        payload = entry.get("payload", {})
        model = ""
        if entry_type == "turn_context":
            model = payload.get("model", "")
        if model:
            self._session_models[path_key] = self._shorten_model(model)

    def _parse_codex_activity(self, file_path, branch):
        """Parse Codex session JSONL to show agent actions."""
        try:
            path_key = str(file_path)
            lines = self._read_new_jsonl_lines(file_path, path_key)
            if lines is None:
                return True

            for line in reversed(lines):
                entry = self._safe_parse_json(line, "Codex")
                if entry is None:
                    continue
                self._extract_codex_model(entry, path_key)
                action_text = self._extract_codex_action(entry)
                if not action_text:
                    continue
                return self._emit_agent_event(path_key, branch, action_text)

            return True
        except Exception as e:
            logger.info(f"[monitor] Codex JSONL parse error for {file_path.name}: {e}")
            return False

    _MAX_AGENT_EVENTS_PER_BATCH = 3

    def _parse_agent_activity(self, file_path, branch):
        """Parse Claude Code session JSONL to show agent actions; True if emitted or deduped.

        Emits only the last few distinct actions, so a large batch after a poll gap does not flood."""
        try:
            path_key = str(file_path)
            lines = self._read_new_jsonl_lines(file_path, path_key)
            if lines is None:
                return True

            pending_actions = []
            last_seen = self._last_agent_action.get(path_key)

            for line in lines:
                try:
                    entry = _json.loads(line)
                except _json.JSONDecodeError as e:
                    logger.info(f"[monitor] Skipping malformed JSONL line: {e}")
                    continue

                model = self._extract_model_from_entry(entry)
                if model:
                    self._session_models[path_key] = self._shorten_model(model)

                action_text = self._extract_action_from_entry(entry)
                if not action_text:
                    continue

                if action_text == last_seen:
                    continue
                last_seen = action_text
                pending_actions.append(action_text)

            for action_text in pending_actions[-self._MAX_AGENT_EVENTS_PER_BATCH :]:
                tagged_branch = self._tag_branch_with_model(path_key, branch)
                evt = MonitoringEvent(
                    priority=1,
                    event_type="agent",
                    branch=tagged_branch,
                    action="activity",
                    message=action_text,
                    level="info",
                )
                if self._event_queue:
                    self._event_queue.enqueue(evt)

            if pending_actions:
                self._last_agent_action[path_key] = pending_actions[-1]

            return True

        except Exception as e:
            logger.info(f"[monitor] JSONL parse error for {file_path.name}: {e}")
            return False

    def _check_command_indicator(self, action, file_path, branch):
        """Check if file event indicates a command and emit separator if so."""
        if action != "modified" or file_path.name not in self._command_indicator_files:
            return
        cmd = self._command_indicator_files[file_path.name]
        dedup_key = f"{branch}:{cmd}"
        if self._last_file_command.get(file_path.name) == dedup_key:
            return
        self._last_file_command[file_path.name] = dedup_key
        cmd_event = MonitoringEvent(
            priority=2,
            event_type="command",
            branch=branch,
            action="executed",
            message=cmd,
            level="info",
        )
        if self._event_queue:
            self._event_queue.enqueue(cmd_event)

    def _handle_event(self, action, path_str):
        """Process file event and push to queue."""
        try:
            file_path = Path(path_str)

            if not should_monitor(file_path, self._sandbox_root):
                return

            branch = detect_branch_from_path(str(file_path))

            # Markers use forward slashes; match on a local copy so Windows paths match too
            norm = path_str.replace("\\", "/")

            if file_path.suffix == ".jsonl" and action != "created" and str(file_path) not in self._jsonl_positions:
                # A transcript first seen mid-life starts at its end: its history is not live activity.
                with contextlib.suppress(OSError):
                    self._jsonl_positions[str(file_path)] = file_path.stat().st_size

            if file_path.suffix == ".jsonl" and ".claude/projects/" in norm:
                if "/subagents/" in norm:
                    branch = branch + " agent"
                if self._parse_agent_activity(file_path, branch):
                    return

            if file_path.suffix == ".jsonl" and ".codex/sessions/" in norm:
                codex_branch = self._get_codex_branch(file_path, path_str)
                if self._parse_codex_activity(file_path, codex_branch):
                    return

            self._check_command_indicator(action, file_path, branch)

            priority_level = get_priority(file_path, action)
            display_name = self._build_display_name(file_path)

            evt = MonitoringEvent(
                priority=0,
                event_type="file",
                branch=branch,
                action=action,
                message=f"{action.upper()}: {display_name}",
                level=priority_level if priority_level in ["error", "warning", "info"] else "info",
            )
            if self._event_queue:
                self._event_queue.enqueue(evt)
        except Exception as e:
            logger.error(
                f"[monitor] The live monitor file watcher could not show a file change — unexpected "
                f"{type(e).__name__} on {action} of {path_str}. The file itself is fine; "
                f"file watching continues."
            )

    @staticmethod
    def _build_display_name(file_path: Path) -> str:
        """Build branch-relative display name for a file path."""
        parts = file_path.parts
        for i, part in enumerate(parts):
            if part in ("apps", "handlers", "modules", "docs", "templates"):
                return "/".join(parts[i:])
        return file_path.name
