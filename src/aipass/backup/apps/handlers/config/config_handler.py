# =================== AIPass ====================
# Name: config_handler.py
# Description: Backup system configuration and patterns
# Version: 2.0.2
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""
Backup System Configuration Handler

Centralized configuration management for backup system.
Contains all backup modes, ignore patterns, and configuration constants.
Pure configuration with helper functions for pattern access and filtering.
"""

# =============================================
# IMPORTS
# =============================================

from pathlib import Path
from typing import Dict, Set, List, Optional

# =============================================
# CONFIGURATION CONSTANTS
# =============================================

# Base backup directory - dynamically determined relative to branch root
# Module is in apps/handlers/config/, so parent.parent.parent.parent gets to branch root
BASE_BACKUP_DIR = str(Path(__file__).parent.parent.parent.parent / "backups")

# Specific backup destinations for each system
BACKUP_DESTINATIONS = {
    "system_snapshot": f"{BASE_BACKUP_DIR}",
    "versioned_backup": f"{BASE_BACKUP_DIR}",
}

# =============================================
# IGNORE PATTERNS
# =============================================

# Global ignore patterns (what NOT to backup across all systems)
GLOBAL_IGNORE_PATTERNS = [
    # Python cache and temp files
    "__pycache__",
    "*.pyc",
    "*.pyo",

    # Virtual environments
    ".venv",
    "venv",

    # Node.js
    "node_modules",
    "npm-debug.log",
    "yarn-error.log",

    # Operating system files
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "nul",  # Windows reserved filename issue

    # Temporary files
    #"temp",
    ".temp",
    "tmp",
    ".tmp",
    "*.tmp",
    "*.temp",

    # Build and distribution directories
    "build",
    "dist",
    "install",
    "lib",
    "bin",

    # IDE and editor files
    "*.swp",
    "*.swo",
    "*~",

    # Backup directories (prevent recursive backups) - CRITICAL!
    "backups",  # Matches any directory named "backups"
    "backup_system/backups",  # Explicit path to our backup directory
    "*/backups",  # Any backups subdirectory
    "system_snapshot",  # Snapshot backup folder name
    "versioned_backup",  # Versioned backup folder name
    "deleted_branches",  # Deleted/archived branches (trash folder)

    # System backups and trash
    "TimeShift*",
    "timeshift*",
    ".local/share/Trash",
    "Trash",

    # Linux system directories (don't backup user settings/cache)
    ".local",
    ".cache",
    ".config",
    ".mozilla",
    ".gnupg",
    ".ssh",
    ".vscode/cli",  # VS Code CLI binary (large, regenerates)
    ".vscode/extensions",  # VS Code extensions (large, regenerates)
    ".vscode-server",  # VS Code remote server
    ".npm-global",
    ".pki",
    ".dotnet",
    ".var",  # System application data (Flatpak, etc)
    ".backup",  # Old backup directories
    ".antigravity",  # AI assistant cache/data
    ".gemini",  # AI assistant cache
    "snap",  # Snap package directories (broken symlinks, system-managed)

    # Version control (huge number of files!)
    ".git",  # Git repositories are version controlled elsewhere

    # IDE and editor directories
    ".idea",  # IntelliJ IDEA settings
    ".eclipse",  # Eclipse settings

    # Claude Code session files (change every session) - synced from .gitignore
    #".claude/projects",
    ".claude/todos",
    ".claude/shell-snapshots",
    ".claude/ide",
    ".claude/statsig",
    #".claude/plugins",
    ".claude/.credentials.json",
    ".claude/debug",
    ".claude/file-history",
    ".claude/history.jsonl",
    ".claude/.update.lock",
    ".claude/.projects",
    #".claude/hooks/.last_diagnostics_file",
    ".serena/logs",
    ".code",

    # Development cache/build directories
    ".npm",
    ".cargo",
    ".rustup",
    ".gem",
    ".gradle",
    ".m2",

    # Application data we don't need in backups
    ".thunderbird",
    ".wine",
    ".steam",
    ".zoom",

    # User directories that shouldn't be backed up
    "Downloads",
    #"Music",
    "Videos",
    "Pictures",
    "Dropbox",
    "system_logs",
    "external_repos",       # External git repos - version controlled elsewhere
    "mcp_servers/context7",      # External MCP server repo
    "mcp_servers/playwright-mcp", # External MCP server repo
    "mcp_servers/serena",        # External MCP server repo
    "mcp_servers/servers",       # External MCP server repo
    "mcp_servers/dropbox",       # External MCP server repo

    # Archive and compressed files
    "*.zip",
    "*.tar",
    "*.gz",
    "*.bz2",
    "*.rar",
    "*.7z",
    "*.whl",  # Python wheel files (long filenames in archives)

    # Large binary/image files (VMs, disk images)
    "*.img",  # Disk images (sandbox.img, etc - can be 50GB+)
    "*.iso",  # ISO files
    "*.vmdk",  # Virtual machine disk
    "*.vdi",  # VirtualBox disk image
    "*.qcow2",  # QEMU disk image

    # Image/media files (screenshots, icons, etc.)
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.svg",
    "*.webp",
    "*.ico",
    "*.bmp",
    "*.tiff",
    "*.tif",

    # Log files
    "*.log",
    "logs",

    # Most JSON files (frequent changes, not human-readable diffs)
    "*_data.json",
    "*_log.json",
    "*_registry.json",
    "snapshot_backup.json",
    "snapshot_backup_changelog.json",

    # Miscellaneous
    "*.db",
    "*.bashrc",
    "*.bash_history",
    "*.bash_logout",
    #"*.claude.json.backup",
    #"*.env",
    "*.lesshst",
    "*.npmrc",
    "*.sudo_as_admin_successful",
]

# Notable patterns to highlight when skipped
CLI_TRACKING_PATTERNS = []

# Files that should be backed up but NOT generate diff files
DIFF_IGNORE_PATTERNS = [
    # Log files (append-only, huge diffs)
    "*.log",
    "*.logs",
    "system_logs/*.log",

    # Most JSON files (frequent changes, not human-readable diffs)
    #"*_config.json",
    #"*_data.json",
    #"*_log.json",
    #"*_registry.json",

    # Python cache/compiled
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "__pycache__/*",

    # Database files
    "*.db",
    "*.sqlite",
    "*.sqlite3",

    # Binary/media files
    "*.exe",
    "*.dll",
    "*.so",
    "*.dylib",

    # Pickle/cache files
    "*.pkl",
    "*.pickle",

    # Temporary files
    "*.tmp",
    "*.temp",
    "*.bak",
    "~*",
]

# Files that should be backed up despite matching ignore patterns
# Synced from .gitignore exceptions (! prefix patterns)
IGNORE_EXCEPTIONS = [
    ".gitignore",  # Root .gitignore file should be backed up
    "*.local.md",  # AIPass session tracking files (caught by .local pattern but should be backed up)
    ".vscode/settings.json",  # VS Code settings
    "*/.claude/settings.local.json",  # Claude local settings in any directory
    "tools/cleanup_configs/*.json",  # Cleanup config files
    "*_config.json",  # All config JSON files
    "drone/commands/global/*.json",  # Drone global commands
    ".claude.json",  # Claude config
    ".mcp.json",  # MCP config
    ".config/nerd-dictation/*",  # Nerd dictation config
    ".commands.json",  # Commands config
    "BRANCH_REGISTRY.json",  # Core ecosystem registry - vital file

    # === TEMPLATES: FULL EXCEPTION - EVERY FILE ===
    "templates/**",  # FULL EXCEPTION: Include EVERY file in templates directory
    "*/templates/**",  # Templates in any subdirectory
    "templates/*/**",  # All subdirectories and files in templates
    "*/templates/*/**",  # All subdirectories and files in templates anywhere

    # === TEMPLATE SUBDIRECTORIES (explicit) ===
    "templates/ai_branch_setup_template/ai_mail.local/**",
    "templates/ai_branch_setup_template/logs/**",
    "templates/ai_branch_setup_template/standards.local/**",
    "templates/ai_branch_setup_template/.claude/**",
    "templates/ai_branch_setup_template/.archive/**",

    # === MARKERS ===
    ".gitkeep",  # Include all .gitkeep marker files (especially in templates)
    ".gitattributes",  # Git attributes files
    ".local.json"
]

# Files that SHOULD have diffs created (exceptions to ignore patterns)
DIFF_INCLUDE_PATTERNS = [
    "profile.json",
    "pyrightconfig.json",
    "package.json",
    ".mcp.json",
    "settings.json",
    "settings.local.json",
]

# =============================================
# BACKUP MODE CONFIGURATIONS
# =============================================

BACKUP_MODES = {
    'snapshot': {
        'name': 'System Snapshot',
        'description': 'Dynamic instant backup (overwrites previous)',
        'destination': BACKUP_DESTINATIONS["system_snapshot"],
        'folder_name': 'system_snapshot',
        'behavior': 'dynamic',  # overwrites previous
        'usage': 'Quick saves before changes'
    },
    'versioned': {
        'name': 'Versioned Backup',
        'description': 'Cumulative version history (keeps all file versions)',
        'destination': BACKUP_DESTINATIONS["versioned_backup"],
        'folder_name': 'versioned_backup',
        'behavior': 'versioned',  # keeps all versions
        'usage': 'Complete file version history in single location'
    },
}

# =============================================
# HELPER FUNCTIONS
# =============================================

def get_ignore_patterns() -> List[str]:
    """Get the global ignore patterns list

    Returns:
        Copy of global ignore patterns list
    """
    return GLOBAL_IGNORE_PATTERNS.copy()


def get_cli_tracking_patterns() -> List[str]:
    """Get the CLI tracking patterns list

    Returns:
        Copy of CLI tracking patterns list
    """
    return CLI_TRACKING_PATTERNS.copy()


def get_backup_destination(system_name: str) -> str:
    """Get backup destination for a specific backup system

    Args:
        system_name: Name of the backup system

    Returns:
        Path to backup destination, or base directory if not found
    """
    return BACKUP_DESTINATIONS.get(system_name, BASE_BACKUP_DIR)


def filter_tracked_items(skipped_items: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """Filter skipped items to only show project-specific items

    Uses CLI tracking patterns to identify important items worth showing to user.

    Args:
        skipped_items: Dictionary with 'directories' and 'files' sets

    Returns:
        Filtered dictionary with only tracked items
    """
    tracking_patterns = get_cli_tracking_patterns()
    filtered_items = {
        "directories": set(),
        "files": set()
    }

    def matches_pattern(item_path: str, patterns: List[str]) -> bool:
        """Check if item path matches any tracking pattern"""
        for pattern in patterns:
            if pattern in item_path or item_path.startswith(pattern):
                return True
            # Check wildcard patterns
            if pattern.startswith('*') and item_path.endswith(pattern[1:]):
                return True
        return False

    # Filter directories
    for directory in skipped_items.get("directories", set()):
        if matches_pattern(directory, tracking_patterns):
            filtered_items["directories"].add(directory)

    # Filter files
    for file_path in skipped_items.get("files", set()):
        if matches_pattern(file_path, tracking_patterns):
            filtered_items["files"].add(file_path)

    return filtered_items


def should_ignore(path: Path, ignore_patterns: Optional[List[str]] = None,
                  exceptions: Optional[List[str]] = None,
                  backup_dest: Optional[Path] = None) -> bool:
    """Check if a file/folder should be ignored based on patterns.

    Centralizes ignore pattern matching logic used during backup scanning.
    Checks exceptions first (files that should NOT be ignored), then patterns.

    Args:
        path: Path object to check
        ignore_patterns: List of patterns to ignore (defaults to GLOBAL_IGNORE_PATTERNS)
        exceptions: List of exception patterns (defaults to IGNORE_EXCEPTIONS)
        backup_dest: Optional backup destination to always ignore

    Returns:
        True if path should be ignored, False otherwise

    Example:
        # From backup engine
        should_ignore(Path("/home/user/file.pyc"))  # True
        should_ignore(Path("/home/user/.gitignore"))  # False (exception)
    """
    import os

    # Use defaults if not provided
    if ignore_patterns is None:
        ignore_patterns = GLOBAL_IGNORE_PATTERNS
    if exceptions is None:
        exceptions = IGNORE_EXCEPTIONS

    path_str = str(path)
    parts = set(path_str.split(os.sep))
    name = path.name

    # Always ignore backup destination if provided
    if backup_dest and str(backup_dest) in path_str:
        return True

    # Ignore paths containing 'Backups'
    if 'Backups' in parts:
        return True

    # Check exceptions first - files that should NOT be ignored
    for exception in exceptions:
        # Full path matching for template exceptions
        if "**" in exception:
            # Convert glob pattern to regex-like check
            exception_parts = exception.split("/**")[0]  # Get everything before /**
            if exception_parts in path_str or exception_parts in "/".join(parts):
                return False  # Matches exception pattern - don't ignore
        elif exception.startswith('*') and name.endswith(exception[1:]):
            return False  # Matches wildcard exception pattern
        elif exception == name:
            return False  # Exact match
        elif exception in path_str:
            return False  # Exception pattern is in the full path

    # Check ignore patterns
    for pattern in ignore_patterns:
        # Special case: "backups" should only match directory names, not filenames
        if pattern == "backups":
            if "backups" in parts:  # Only ignore if "backups" is a directory in the path
                return True
        elif pattern == name:
            return True
        elif pattern.startswith('*') and name.endswith(pattern[1:]):
            return True
        elif pattern in parts or pattern in path_str:
            return True

    return False

# =============================================
# MODULE INITIALIZATION
# =============================================

# No initialization needed - pure configuration
