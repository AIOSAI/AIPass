# =================== AIPass ====================
# Name: caller.py
# Description: OpenRouter Caller Detection Handler
# Version: 1.0.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
OpenRouter Caller Detection Handler

Stack-based caller detection with JSON folder path resolution.
Supports flow, prax, and skills module detection.

Usage:
    from aipass.api.apps.handlers.openrouter.caller import get_caller_info

    caller_info = get_caller_info()
    if caller_info:
        caller_name = caller_info['caller_name']
        json_folder = caller_info['json_folder']
"""

# Standard library imports
import inspect
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "openrouter.caller"
MODULE_VERSION = "1.0.0"

CALLER_PATTERNS = {
    "flow": "flow_json",
    "prax": "prax_json",
}

# =============================================
# CALLER DETECTION FUNCTIONS
# =============================================


def get_caller_info() -> Optional[Dict[str, Any]]:
    """
    Detect calling module via stack inspection.

    Returns dict with: caller_name, caller_path, json_folder, category, detection_method
    Returns None if detection fails.
    """
    try:
        stack = inspect.stack()

        for frame_info in stack[1:]:
            frame_path = Path(frame_info.filename)

            if "flow" in frame_path.parts:
                result = _detect_flow_caller(frame_path)
                json_handler.log_operation("caller_detected", {"caller": result.get("caller_name"), "category": "flow"})
                return result
            elif "prax" in frame_path.parts:
                result = _detect_prax_caller(frame_path)
                json_handler.log_operation("caller_detected", {"caller": result.get("caller_name"), "category": "prax"})
                return result
        logger.info(f"[{MODULE_NAME}] Could not detect caller from stack trace")
        return None

    except Exception as e:
        logger.error(f"Caller detection failed: {e}")
        return None


def detect_caller_from_stack() -> Tuple[Optional[str], Optional[Path]]:
    """
    Compatibility wrapper for provision handler.

    Returns:
        Tuple of (caller_name, json_folder_path) or (None, None)
    """
    caller_info = get_caller_info()
    if caller_info:
        return caller_info.get("caller_name"), caller_info.get("json_folder")
    return None, None


def detect_caller_category(caller_path: Path) -> str:
    """Categorize caller based on file path."""
    try:
        path_parts = caller_path.parts

        if "flow" in path_parts:
            return "flow"
        elif "prax" in path_parts:
            return "prax"
        else:
            return "unknown"

    except Exception as e:
        logger.error(f"Failed to detect category for {caller_path}: {e}")
        return "unknown"


# =============================================
# INTERNAL DETECTION HELPERS
# =============================================


def _detect_flow_caller(frame_path: Path) -> Dict[str, Any]:
    """Detect flow module caller from stack frame path."""
    try:
        flow_index = frame_path.parts.index("flow")
        flow_path = Path(*frame_path.parts[: flow_index + 1])
        json_folder_path = flow_path / "flow_json"
        caller_name = frame_path.stem

        logger.info(f"[{MODULE_NAME}] Detected flow caller: {caller_name}")

        return {
            "caller_name": caller_name,
            "caller_path": frame_path,
            "json_folder": json_folder_path,
            "category": "flow",
            "detection_method": "stack",
        }

    except Exception as e:
        logger.error(f"Failed to detect flow caller: {e}")
        return _create_fallback_info(frame_path)


def _detect_prax_caller(frame_path: Path) -> Dict[str, Any]:
    """Detect prax module caller from stack frame path."""
    try:
        prax_index = frame_path.parts.index("prax")
        prax_path = Path(*frame_path.parts[: prax_index + 1])
        json_folder_path = prax_path / "prax_json"
        caller_name = frame_path.stem

        logger.info(f"[{MODULE_NAME}] Detected prax caller: {caller_name}")

        return {
            "caller_name": caller_name,
            "caller_path": frame_path,
            "json_folder": json_folder_path,
            "category": "prax",
            "detection_method": "stack",
        }

    except Exception as e:
        logger.error(f"Failed to detect prax caller: {e}")
        return _create_fallback_info(frame_path)


def _create_fallback_info(frame_path: Path) -> Dict[str, Any]:
    """Create fallback caller info when detection fails."""
    caller_name = frame_path.stem
    category = detect_caller_category(frame_path)

    logger.info(f"[{MODULE_NAME}] Using fallback detection for: {caller_name}")

    return {
        "caller_name": caller_name,
        "caller_path": frame_path,
        "json_folder": None,
        "category": category,
        "detection_method": "fallback",
    }


# =============================================
# MODULE INITIALIZATION
# =============================================


def _initialize():
    """Initialize caller detection module."""
    logger.info(f"[{MODULE_NAME}] Caller detection handler loaded (v{MODULE_VERSION})")


_initialize()
