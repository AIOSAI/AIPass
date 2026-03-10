# =================== AIPass ====================
# Name: log_setup.py
# Description: Log file directory and handle preparation
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Log Setup Handler

Prepares log file directory and returns an open file handle for subprocess output.
Extracted from dplan_flow.py to comply with 3-tier architecture
(modules must not do direct file operations).

Usage:
    from aipass.flow.apps.handlers.dplan.log_setup import prepare_log_file
"""

from pathlib import Path
from typing import Dict, Any, Optional
import io


# =============================================================================
# CONFIGURATION
# =============================================================================

# log_setup.py → dplan/ → handlers/ → apps/ → flow/
FLOW_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOG_DIR = FLOW_ROOT / "logs"


# =============================================================================
# OPERATIONS
# =============================================================================

def prepare_log_file(filename: str = "post_close_runner.log",
                     log_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Ensure log directory exists and return an open file handle for appending.

    Args:
        filename: Log file name (default: post_close_runner.log)
        log_dir: Override log directory (default: flow/logs/)

    Returns:
        Dict with keys:
            success (bool): Whether preparation succeeded
            file_handle (Optional[io.TextIOWrapper]): Open file handle, or None on failure
            log_path (Optional[Path]): Full path to log file
            error (str): Error description if failed, empty string on success
    """
    target_dir = log_dir or DEFAULT_LOG_DIR
    log_path = target_dir / filename

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log_path, "a", encoding="utf-8")
        return {
            "success": True,
            "file_handle": fh,
            "log_path": log_path,
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "file_handle": None,
            "log_path": log_path,
            "error": f"Failed to prepare log file {log_path}: {e}",
        }
