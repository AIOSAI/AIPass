"""
Monitoring Handlers Package

Provides unified monitoring capabilities for PRAX system.
Handlers for file watching, log monitoring, branch detection, and filtering.
"""

# Export main handler interfaces
from .unified_stream import print_event, print_command_separator
from .branch_detector import detect_branch_from_path
from .interactive_filter import (
    parse_command,
    get_help_text,
)
from .monitoring_filters import (
    should_monitor,
    get_priority,
    get_content_filter,
    apply_content_filter,
    filter_log_content,
)
from .event_queue import MonitoringEvent, MonitoringQueue, global_queue
from .module_tracker import ModuleTracker
from .filesystem_handler import MonitoringFileHandler
from .file_watcher_integration import (
    start_file_watcher,
    stop_file_watcher,
    is_file_watcher_running,
    get_file_watcher_stats,
    FileWatcherManager,
)
from .log_watcher import start_log_watcher, stop_log_watcher, is_log_watcher_active

__all__ = [
    "print_event",
    "print_command_separator",
    "detect_branch_from_path",
    "parse_command",
    "get_help_text",
    "should_monitor",
    "get_priority",
    "get_content_filter",
    "apply_content_filter",
    "filter_log_content",
    "MonitoringEvent",
    "MonitoringQueue",
    "global_queue",
    "ModuleTracker",
    "MonitoringFileHandler",
    "start_file_watcher",
    "stop_file_watcher",
    "is_file_watcher_running",
    "get_file_watcher_stats",
    "FileWatcherManager",
    "start_log_watcher",
    "stop_log_watcher",
    "is_log_watcher_active",
]
