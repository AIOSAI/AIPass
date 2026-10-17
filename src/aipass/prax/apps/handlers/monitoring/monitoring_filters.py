# =================== AIPass ====================
# Name: monitoring_filters.py
# Description: Monitoring Filter Patterns
# Version: 1.1.0
# Created: 2025-11-23
# Modified: 2026-10-17
# =============================================

"""Monitoring Filter Patterns"""

from pathlib import Path
from typing import Dict, Optional, Any

from aipass.prax.apps.handlers.discovery.filtering import in_sandbox
from aipass.prax.apps.handlers.json import json_handler

MONITOR_IGNORE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "npm-debug.log",
    "yarn-error.log",
    ".git",
    # Backup directories (prevent circular monitoring)
    "backups",
    "backup/backups",
    "*/backups",
    "system_snapshot",
    "versioned_backup",
    "deleted_branches",
    # System logs (prevent feedback loop - log watcher handles these separately)
    "system_logs",
    "*.log",
    "TimeShift*",
    "timeshift*",
    ".local/share/Trash",
    "Trash",
    ".cache",
    ".local",
    ".config",
    ".mozilla",
    ".gnupg",
    ".ssh",
    ".pki",
    ".dotnet",
    ".var",
    ".backup",
    ".antigravity",
    ".vscode/cli",
    ".vscode/extensions",
    ".vscode-server",
    ".idea",
    ".eclipse",
    ".claude/todos",
    ".claude/shell-snapshots",
    ".claude/ide",
    ".claude/statsig",
    ".claude/.credentials.json",
    ".claude/debug",
    ".claude/file-history",
    ".claude/history.jsonl",
    ".claude/.update.lock",
    ".claude/plugins",
    ".claude/telemetry",
    ".claude.json.backup",
    ".claude.json.tmp",
    ".last_diagnostics_file",
    ".serena/logs",
    ".code",
    ".npm",
    ".cargo",
    ".rustup",
    ".gem",
    ".gradle",
    ".m2",
    "build",
    "dist",
    "install",
    "lib",
    "bin",
    ".thunderbird",
    ".wine",
    ".steam",
    ".zoom",
    "Downloads",
    "Videos",
    "Pictures",
    "Dropbox",
    "*.img",
    "*.iso",
    "*.vmdk",
    "*.vdi",
    "*.qcow2",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.bz2",
    "*.rar",
    "*.7z",
    "*.whl",
    "huggingface",
    # Temporary files (includes Claude Code atomic writes: file.py.tmp.PID.TIMESTAMP)
    "*.tmp",
    "*.temp",
    ".tmp.",
    "*.swp",
    "*.swo",
    "*~",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "nul",
]

MONITOR_ALWAYS_PATTERNS = [
    "*.id.json",
    "*.local.json",
    "*.observations.json",
    "*.ai_mail.json",
    "*_config.json",
    ".claude.json",
    ".mcp.json",
    ".commands.json",
    ".gitignore",
    ".gitattributes",
    "*.py",
    "README.md",
    "CLAUDE.md",
    "*.local.md",
    ".vscode/settings.json",
    ".vscode/settings.local.json",
    "templates/**",
    "*/templates/**",
    ".gitkeep",
]

CONTENT_FILTER_PATTERNS = {
    "*.log": {
        "filter_mode": "errors_only",
        "show_patterns": ["ERROR", "CRITICAL", "WARNING", "Failed", "Exception"],
        "description": "Only show error-level log entries",
    },
    "*_data.json": {"filter_mode": "structure_only", "description": "Show only structural changes, not data updates"},
    "*_registry.json": {"filter_mode": "keys_only", "description": "Show only new/deleted keys, not value changes"},
    "snapshot_*.json": {"filter_mode": "summary", "description": "Show summary of changes, not full content"},
}

HIGHLIGHT_PATTERNS = {
    "critical": [
        "*.id.json",  # Branch identity - system core
        "CLAUDE.md",  # System instructions
        ".gitignore",  # Version control rules
        "*_config.json deletion",  # Config deletion is critical
    ],
    "high": [
        "*.py deletion",  # Source code deletion
        "*.py creation",  # New source code
        "README.md",  # Documentation
        "*_config.json",  # Configuration changes
    ],
    "medium": [
        "*.local.json",  # Session files
        "*.observations.json",  # Collaboration patterns
        "*.py modification",  # Source code edits
        "*.md",  # Documentation
    ],
}

EVENT_TYPES = {
    "all": ["created", "modified", "deleted", "moved"],
    "changes_only": ["modified", "deleted"],
    "structure_only": ["created", "deleted", "moved"],
}

DEFAULT_EVENT_TYPES = EVENT_TYPES["all"]


def should_monitor(path: Path, root: Optional[Path] = None) -> bool:
    """Check if path should be monitored

    A dropbox, an .archive or a __pycache__ below root is never watched; ALWAYS beats IGNORE."""
    json_handler.log_operation("monitoring_started", {"path": str(path)})
    import os

    if root is not None and in_sandbox(path, root):
        return False

    path_str = str(path)
    parts = set(path_str.split(os.sep))
    name = path.name

    # These contain .claude.json as substring, which would match the ALWAYS pattern
    if ".claude.json.backup" in name or ".claude.json.tmp" in name:
        return False

    if ".codex/sessions/" in path_str and name.endswith(".jsonl"):
        return True

    if _matches_always_patterns(path_str, parts, name):
        return True

    if _matches_ignore_patterns(path_str, parts, name):
        return False

    return True


_PARTS_ONLY_IGNORE = {"backups", ".cache", ".git", "node_modules", ".local", ".config", ".var", ".backup"}


def _matches_always_patterns(path_str: str, parts: set, name: str) -> bool:
    """Check if path matches any ALWAYS (force-monitor) pattern."""
    for pattern in MONITOR_ALWAYS_PATTERNS:
        if "**" in pattern:
            exception_parts = pattern.split("/**")[0]
            if exception_parts in path_str or exception_parts in "/".join(parts):
                return True
        if pattern.startswith("*") and name.endswith(pattern[1:]):
            return True
        if pattern == name or pattern in path_str:
            return True
    return False


def _matches_ignore_patterns(path_str: str, parts: set, name: str) -> bool:
    """Check if path matches any IGNORE pattern."""
    for pattern in MONITOR_IGNORE_PATTERNS:
        if pattern in _PARTS_ONLY_IGNORE:
            if pattern in parts:
                return True
            continue
        if pattern == name:
            return True
        if pattern.startswith("*") and name.endswith(pattern[1:]):
            return True
        if pattern in parts or pattern in path_str:
            return True
    return False


def get_priority(path: Path, event_type: str) -> str:
    """Get priority level for an event"""
    name = path.name
    path_str = str(path)

    for level, patterns in HIGHLIGHT_PATTERNS.items():
        for pattern in patterns:
            if _pattern_matches_event(pattern, name, path_str, event_type):
                return level

    return "low"


def _pattern_matches_event(pattern: str, name: str, path_str: str, event_type: str) -> bool:
    """Check if a single highlight pattern matches the given event."""
    if " " in pattern:
        pattern_base, pattern_event = pattern.split(" ", 1)
        if event_type != pattern_event:
            return False
        return (pattern_base.startswith("*") and name.endswith(pattern_base[1:])) or pattern_base == name

    if pattern.startswith("*") and name.endswith(pattern[1:]):
        return True
    return pattern == name or pattern in path_str


def get_content_filter(path: Path) -> Optional[Dict[str, Any]]:
    """Get content filter configuration for a path"""
    name = path.name
    name_lower = name.lower()

    for pattern, config in CONTENT_FILTER_PATTERNS.items():
        bare = pattern.replace("*", "")
        if pattern.startswith("*") and name_lower.endswith(pattern[1:]):
            return config
        if pattern == name or bare in name_lower:
            return config

    return None


def filter_log_content(
    content: str, show_errors: bool = True, show_warnings: bool = True, show_info: bool = False
) -> Optional[str]:
    """Filter log content based on level preferences"""
    lines = content.split("\n")
    filtered_lines = []

    for line in lines:
        line_upper = line.upper()

        if show_errors and any(kw in line_upper for kw in ["ERROR", "CRITICAL", "EXCEPTION", "TRACEBACK", "FAILED"]):
            filtered_lines.append(line)
            continue

        if show_warnings and any(kw in line_upper for kw in ["WARNING", "WARN"]):
            filtered_lines.append(line)
            continue

        if show_info and "INFO" in line_upper:
            filtered_lines.append(line)
            continue

    if filtered_lines:
        return "\n".join(filtered_lines)
    return None


def apply_content_filter(
    path: Path, content: str, show_errors: bool = True, show_warnings: bool = True, show_info: bool = False
) -> Optional[str]:
    """Apply appropriate content filter based on file type"""
    filter_config = get_content_filter(path)

    if not filter_config:
        return content

    filter_mode = filter_config.get("filter_mode")

    if filter_mode == "errors_only":
        return filter_log_content(content, show_errors, show_warnings, show_info)

    # Other filter modes not yet implemented - return original
    return content
