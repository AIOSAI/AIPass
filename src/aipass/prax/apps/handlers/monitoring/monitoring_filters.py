# =================== AIPass ====================
# Name: monitoring_filters.py
# Description: Monitoring Filter Patterns
# Version: 1.1.0
# Created: 2025-11-23
# Modified: 2026-10-23
# =============================================

"""Monitoring Filter Patterns"""

from pathlib import Path
from typing import Optional

from aipass.prax.apps.handlers.discovery.filtering import in_sandbox

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
    "AGENTS.md",
    "*.local.md",
    ".vscode/settings.json",
    ".vscode/settings.local.json",
    "templates/**",
    "*/templates/**",
    ".gitkeep",
]

HIGHLIGHT_PATTERNS = {
    "critical": [
        "*.id.json",  # Branch identity - system core
        "CLAUDE.md",  # System instructions
        "AGENTS.md",  # System instructions, the one file since DPLAN-0418
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


def should_monitor(path: Path, root: Optional[Path] = None) -> bool:
    """Check if path should be monitored

    A dropbox, an .archive or a __pycache__ below root is never watched; ALWAYS beats IGNORE."""
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


# Whole path segments only: as substrings "lib" would hide "/robin/" and "env" hide "/seven/".
_PARTS_ONLY_IGNORE = {
    "backups",
    ".cache",
    ".git",
    "node_modules",
    ".local",
    ".config",
    ".var",
    ".backup",
    "lib",
    "bin",
    "env",
    "build",
    "dist",
    "install",
}


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
