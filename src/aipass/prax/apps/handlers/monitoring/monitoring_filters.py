# =================== AIPass ====================
# Name: monitoring_filters.py
# Description: Monitoring Filter Patterns
# Version: 1.0.0
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""
Monitoring Filter Patterns

Centralized filter configuration for the prax monitoring system.
Defines what to watch, ignore, and prioritize during filesystem monitoring.
Based on backup_system/config_handler.py's excellent pattern organization.
"""

# =============================================
# IMPORTS
# =============================================

from pathlib import Path
from typing import List, Set, Dict, Optional, Any

from aipass.prax.apps.handlers.json import json_handler

# =============================================
# MONITORING PATTERNS
# =============================================

# Files/folders to NEVER monitor (adapted from GLOBAL_IGNORE_PATTERNS)
# These generate too many events, are non-essential, or are system directories
MONITOR_IGNORE_PATTERNS = [
    # Python cache and temp files (constant changes)
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",

    # Virtual environments (massive file count, not user code)
    ".venv",
    "venv",
    "env",

    # Node.js (massive file count)
    "node_modules",
    "npm-debug.log",
    "yarn-error.log",

    # Version control (Git manages its own changes)
    ".git",

    # Backup directories (prevent circular monitoring)
    "backups",
    "backup_system/backups",
    "*/backups",
    "system_snapshot",
    "versioned_backup",
    "deleted_branches",

    # System logs (prevent feedback loop - log watcher handles these separately)
    "system_logs",
    "*.log",

    # System backups and trash
    "TimeShift*",
    "timeshift*",
    ".local/share/Trash",
    "Trash",

    # Linux system directories (not code, constant changes)
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
    ".gemini",

    # IDE and editor directories (auto-generated, large)
    ".vscode/cli",
    ".vscode/extensions",
    ".vscode-server",
    ".idea",
    ".eclipse",

    # Claude Code internal files (change constantly, not user code)
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

    # Development cache/build directories
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

    # Application data
    ".thunderbird",
    ".wine",
    ".steam",
    ".zoom",

    # User directories (not code)
    "Downloads",
    "Videos",
    "Pictures",
    "Dropbox",

    # Large binary/image files
    "*.img",
    "*.iso",
    "*.vmdk",
    "*.vdi",
    "*.qcow2",

    # Archive and compressed files
    "*.zip",
    "*.tar",
    "*.gz",
    "*.bz2",
    "*.rar",
    "*.7z",
    "*.whl",

    # HuggingFace model cache (sentence-transformers etc.)
    "huggingface",

    # Temporary files (includes Claude Code atomic writes: file.py.tmp.PID.TIMESTAMP)
    "*.tmp",
    "*.temp",
    ".tmp.",
    "*.swp",
    "*.swo",
    "*~",

    # Operating system files
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "nul",
]

# Files to ALWAYS monitor (adapted from IGNORE_EXCEPTIONS)
# These are critical files that override ignore patterns
MONITOR_ALWAYS_PATTERNS = [
    # AIPass memory files - CRITICAL SYSTEM FILES!
    "*.id.json",
    "*.local.json",
    "*.observations.json",
    "*.ai_mail.json",

    # Configuration files
    "*_config.json",
    ".claude.json",
    ".mcp.json",
    ".commands.json",
    ".gitignore",
    ".gitattributes",

    # Python source code
    "*.py",

    # Documentation
    "README.md",
    "CLAUDE.md",
    "*.local.md",

    # VS Code settings
    ".vscode/settings.json",
    ".vscode/settings.local.json",

    # Templates (everything in templates is important)
    "templates/**",
    "*/templates/**",

    # Marker files
    ".gitkeep",
]

# =============================================
# CONTENT FILTERING PATTERNS
# =============================================

# Files to watch but filter their content (NEW for monitoring)
# Instead of showing all changes, apply filters to reduce noise
CONTENT_FILTER_PATTERNS = {
    # Log files: only show errors/warnings, not every append
    "*.log": {
        "filter_mode": "errors_only",
        "show_patterns": ["ERROR", "CRITICAL", "WARNING", "Failed", "Exception"],
        "description": "Only show error-level log entries"
    },

    # Data JSON files: only show structural changes, not data updates
    "*_data.json": {
        "filter_mode": "structure_only",
        "description": "Show only structural changes, not data updates"
    },

    # Registry JSON files: only show new/deleted keys
    "*_registry.json": {
        "filter_mode": "keys_only",
        "description": "Show only new/deleted keys, not value changes"
    },

    # Snapshot files: summarize instead of full content
    "snapshot_*.json": {
        "filter_mode": "summary",
        "description": "Show summary of changes, not full content"
    },
}

# =============================================
# PRIORITY/HIGHLIGHT PATTERNS
# =============================================

# Files to highlight in output based on importance (NEW for monitoring)
# Determines how prominently events are displayed to user
HIGHLIGHT_PATTERNS = {
    # CRITICAL: System-breaking changes
    "critical": [
        "*.id.json",           # Branch identity - system core
        "CLAUDE.md",           # System instructions
        ".gitignore",          # Version control rules
        "*_config.json deletion",  # Config deletion is critical
    ],

    # HIGH: Important files that should stand out
    "high": [
        "*.py deletion",       # Source code deletion
        "*.py creation",       # New source code
        "README.md",           # Documentation
        "*_config.json",       # Configuration changes
    ],

    # MEDIUM: Files worth noting
    "medium": [
        "*.local.json",        # Session files
        "*.observations.json", # Collaboration patterns
        "*.py modification",   # Source code edits
        "*.md",               # Documentation
    ],

    # LOW: Normal files (default)
    # Everything else not matched above
}

# =============================================
# EVENT TYPE CONFIGURATIONS
# =============================================

# Which event types to monitor for each pattern
EVENT_TYPES = {
    "all": ["created", "modified", "deleted", "moved"],
    "changes_only": ["modified", "deleted"],
    "structure_only": ["created", "deleted", "moved"],
}

# Default event types to monitor (can be overridden per pattern)
DEFAULT_EVENT_TYPES = EVENT_TYPES["all"]

# =============================================
# HELPER FUNCTIONS
# =============================================

def should_monitor(path: Path) -> bool:
    """Check if path should be monitored

    Checks ALWAYS patterns first (exceptions that override ignores),
    then checks IGNORE patterns. Default is to monitor if no match.

    Args:
        path: Path object to check

    Returns:
        True if path should be monitored, False otherwise

    Example:
        should_monitor(Path("/home/user/test.py"))  # True
        should_monitor(Path("/home/user/.cache/data"))  # False
        should_monitor(Path("/home/user/FLOW.id.json"))  # True (ALWAYS)
    """
    json_handler.log_operation("monitoring_started", {"path": str(path)})
    import os

    path_str = str(path)
    parts = set(path_str.split(os.sep))
    name = path.name

    # Early exit: Claude Code atomic writes and backups (override ALWAYS patterns)
    # These contain .claude.json as substring, which would match the ALWAYS pattern
    if '.claude.json.backup' in name or '.claude.json.tmp' in name:
        return False

    # Check ALWAYS patterns first (exceptions that override ignores)
    for pattern in MONITOR_ALWAYS_PATTERNS:
        # Template wildcard patterns
        if "**" in pattern:
            exception_parts = pattern.split("/**")[0]
            if exception_parts in path_str or exception_parts in "/".join(parts):
                return True  # Force monitoring
        # Wildcard patterns (*.py, *.json, etc)
        elif pattern.startswith('*') and name.endswith(pattern[1:]):
            return True
        # Exact name match
        elif pattern == name:
            return True
        # Pattern in full path
        elif pattern in path_str:
            return True

    # Check IGNORE patterns
    for pattern in MONITOR_IGNORE_PATTERNS:
        # Directory name matching (must be exact path part, not substring)
        # e.g. ".local" should match ~/.local/ but NOT .ai_mail.local/
        if pattern in ["backups", ".cache", ".git", "node_modules",
                        ".local", ".config", ".var", ".backup"]:
            if pattern in parts:
                return False
        # Exact name match
        elif pattern == name:
            return False
        # Wildcard patterns
        elif pattern.startswith('*') and name.endswith(pattern[1:]):
            return False
        # Pattern in path
        elif pattern in parts or pattern in path_str:
            return False

    # Default: monitor it (inclusive approach)
    return True


def get_priority(path: Path, event_type: str) -> str:
    """Get priority level for an event

    Determines how prominently to display an event to the user.
    Checks patterns with event type suffix first, then base patterns.

    Args:
        path: Path object for the event
        event_type: Type of event (created, modified, deleted, moved)

    Returns:
        Priority level: "critical", "high", "medium", or "low"

    Example:
        get_priority(Path("FLOW.id.json"), "modified")  # "critical"
        get_priority(Path("test.py"), "deleted")  # "high"
        get_priority(Path("data.txt"), "modified")  # "low"
    """
    name = path.name
    path_str = str(path)

    # Check each priority level
    for level, patterns in HIGHLIGHT_PATTERNS.items():
        for pattern in patterns:
            # Pattern with event type (e.g., "*.py deletion")
            if " " in pattern:
                pattern_base, pattern_event = pattern.split(" ", 1)
                if event_type == pattern_event:
                    # Check if path matches pattern
                    if pattern_base.startswith('*') and name.endswith(pattern_base[1:]):
                        return level
                    elif pattern_base == name:
                        return level
            # Pattern without event type (all events)
            else:
                # Wildcard patterns
                if pattern.startswith('*') and name.endswith(pattern[1:]):
                    return level
                # Exact name match
                elif pattern == name:
                    return level
                # Pattern in path
                elif pattern in path_str:
                    return level

    # Default: low priority
    return "low"


def get_content_filter(path: Path) -> Optional[Dict[str, Any]]:
    """Get content filter configuration for a path

    Determines if content should be filtered and how.

    Args:
        path: Path object to check

    Returns:
        Filter config dict if path should be filtered, None otherwise

    Example:
        get_content_filter(Path("system.log"))  # {"filter_mode": "errors_only", ...}
        get_content_filter(Path("test.py"))  # None
    """
    name = path.name

    # Check content filter patterns
    for pattern, config in CONTENT_FILTER_PATTERNS.items():
        # Wildcard patterns
        if pattern.startswith('*') and name.endswith(pattern[1:]):
            return config
        # Exact match
        elif pattern == name:
            return config
        # Pattern in name
        elif pattern.replace('*', '') in name:
            return config

    return None


def get_ignore_patterns() -> List[str]:
    """Get the monitor ignore patterns list

    Returns:
        Copy of monitor ignore patterns list
    """
    return MONITOR_IGNORE_PATTERNS.copy()


def get_always_patterns() -> List[str]:
    """Get the monitor always patterns list

    Returns:
        Copy of monitor always patterns list
    """
    return MONITOR_ALWAYS_PATTERNS.copy()


def should_filter_content(path: Path, content: str, filter_mode: str = "errors_only") -> bool:
    """Determine if content should be displayed based on filter mode

    Used for log files and other high-volume content files where we want
    to reduce noise by only showing relevant entries.

    Args:
        path: Path to the file
        content: Content to filter (single line or chunk)
        filter_mode: Filter mode to apply ("errors_only", "structure_only", etc.)

    Returns:
        True if content should be shown, False if it should be filtered out

    Example:
        should_filter_content(Path("system.log"), "ERROR: Failed", "errors_only")  # True
        should_filter_content(Path("system.log"), "INFO: Starting", "errors_only")  # False
    """
    if filter_mode == "errors_only":
        # Only show lines with error/warning keywords
        error_keywords = ["ERROR", "CRITICAL", "WARNING", "Failed", "Exception",
                         "Traceback", "error:", "warning:", "WARN"]
        content_upper = content.upper()
        return any(keyword.upper() in content_upper for keyword in error_keywords)

    elif filter_mode == "structure_only":
        # For JSON files - would need to parse and compare structure
        # For now, show everything (implementation placeholder)
        return True

    elif filter_mode == "keys_only":
        # For registry files - would need to compare keys
        # For now, show everything (implementation placeholder)
        return True

    elif filter_mode == "summary":
        # For snapshot files - would need to summarize
        # For now, show everything (implementation placeholder)
        return True

    # Default: show everything
    return True


def filter_log_content(content: str, show_errors: bool = True,
                       show_warnings: bool = True,
                       show_info: bool = False) -> Optional[str]:
    """Filter log content based on level preferences

    Extracts relevant lines from log content based on user's level preferences.
    Useful for processing log file changes without overwhelming the user.

    Args:
        content: Log content to filter (can be multi-line)
        show_errors: Include ERROR and CRITICAL level messages
        show_warnings: Include WARNING level messages
        show_info: Include INFO level messages

    Returns:
        Filtered content string with only relevant lines, or None if nothing matches

    Example:
        >>> content = "INFO: Starting\\nERROR: Failed\\nINFO: Done"
        >>> filter_log_content(content, show_errors=True, show_info=False)
        "ERROR: Failed"
    """
    lines = content.split('\n')
    filtered_lines = []

    for line in lines:
        line_upper = line.upper()

        # Check for errors
        if show_errors and any(kw in line_upper for kw in
                              ["ERROR", "CRITICAL", "EXCEPTION", "TRACEBACK", "FAILED"]):
            filtered_lines.append(line)
            continue

        # Check for warnings
        if show_warnings and any(kw in line_upper for kw in
                                ["WARNING", "WARN"]):
            filtered_lines.append(line)
            continue

        # Check for info
        if show_info and "INFO" in line_upper:
            filtered_lines.append(line)
            continue

    # Return filtered content or None if nothing matched
    if filtered_lines:
        return '\n'.join(filtered_lines)
    return None


def apply_content_filter(path: Path, content: str,
                        show_errors: bool = True,
                        show_warnings: bool = True,
                        show_info: bool = False) -> Optional[str]:
    """Apply appropriate content filter based on file type

    Main entry point for content filtering. Checks if file has a content
    filter pattern defined, then applies the appropriate filter.

    Args:
        path: Path to the file
        content: File content to filter
        show_errors: Include error-level content
        show_warnings: Include warning-level content
        show_info: Include info-level content

    Returns:
        Filtered content string, original content if no filter, or None if all filtered

    Example:
        >>> apply_content_filter(Path("system.log"), "INFO: test\\nERROR: fail")
        "ERROR: fail"
        >>> apply_content_filter(Path("test.py"), "print('hello')")
        "print('hello')"  # No filter for .py files
    """
    # Get content filter config for this file
    filter_config = get_content_filter(path)

    # No filter defined - return original content
    if not filter_config:
        return content

    filter_mode = filter_config.get("filter_mode")

    # Apply errors_only filter (for log files)
    if filter_mode == "errors_only":
        return filter_log_content(content, show_errors, show_warnings, show_info)

    # Other filter modes not yet implemented - return original
    # TODO: Implement structure_only, keys_only, summary filters
    return content


# =============================================
# MODULE INITIALIZATION
# =============================================

# No initialization needed - pure configuration
