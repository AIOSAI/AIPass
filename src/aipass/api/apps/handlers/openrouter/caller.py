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

from pathlib import Path

# Standard library imports
import inspect
from typing import Dict, Any, Optional, Tuple

# JSON handler
from aipass.api.apps.handlers.json import json_handler

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "openrouter.caller"

# Package root: caller.py -> openrouter/ -> handlers/ -> apps/ -> api/ -> aipass/
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
MODULE_VERSION = "1.0.0"

CALLER_PATTERNS = {
    "flow": "flow_json",
    "prax": "prax_json",
    "skills": "{category}_json",
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
            elif any("skills" in part for part in frame_path.parts):
                result = _detect_skills_caller(frame_path)
                json_handler.log_operation("caller_detected", {"caller": result.get("caller_name"), "category": "skills"})
                return result

        # logger.info(f"[{MODULE_NAME}] Could not detect caller from stack trace")
        return None

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Caller detection failed: {e}")
        return None


def get_caller_name_from_stack() -> Optional[str]:
    """Extract caller name from call stack (simplified version)."""
    caller_info = get_caller_info()
    return caller_info.get('caller_name') if caller_info else None


def detect_caller_from_stack() -> Tuple[Optional[str], Optional[Path]]:
    """
    Compatibility wrapper for provision handler.

    Returns:
        Tuple of (caller_name, json_folder_path) or (None, None)
    """
    caller_info = get_caller_info()
    if caller_info:
        return caller_info.get('caller_name'), caller_info.get('json_folder')
    return None, None


def get_json_folder_path(caller: str) -> Optional[Path]:
    """
    Determine JSON folder path for given caller name.
    Fallback method when stack detection doesn't provide path.
    """
    try:
        if caller.startswith("flow_"):
            base_path = _PACKAGE_ROOT / "flow"
            json_folder = base_path / "flow_json"

        elif caller.startswith("prax_"):
            base_path = _PACKAGE_ROOT / "prax"
            json_folder = base_path / "prax_json"

        elif caller.startswith("skills_"):
            parts = caller.split("_")
            if len(parts) >= 2:
                skills_category = parts[1]
                base_path = _PACKAGE_ROOT / "skills" / f"skills_{skills_category}"
                json_folder = base_path / f"{skills_category}_json"
            else:
                # logger.info(f"[{MODULE_NAME}] Cannot parse skills category from: {caller}")
                return None
        else:
            # logger.info(f"[{MODULE_NAME}] Unknown caller pattern: {caller}")
            return None

        # logger.info(f"[{MODULE_NAME}] Resolved JSON folder for {caller}: {json_folder}")
        return json_folder

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to determine JSON folder for {caller}: {e}")
        return None


def detect_caller_category(caller_path: Path) -> str:
    """Categorize caller based on file path."""
    try:
        path_parts = caller_path.parts

        if "flow" in path_parts:
            return "flow"
        elif "prax" in path_parts:
            return "prax"
        elif any("skills" in part for part in path_parts):
            return "skills"
        else:
            return "unknown"

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to detect category for {caller_path}: {e}")
        return "unknown"


# =============================================
# INTERNAL DETECTION HELPERS
# =============================================

def _detect_flow_caller(frame_path: Path) -> Dict[str, Any]:
    """Detect flow module caller from stack frame path."""
    try:
        flow_index = frame_path.parts.index("flow")
        flow_path = Path(*frame_path.parts[:flow_index + 1])
        json_folder_path = flow_path / "flow_json"
        caller_name = frame_path.stem

        # logger.info(f"[{MODULE_NAME}] Detected flow caller: {caller_name}")

        return {
            "caller_name": caller_name,
            "caller_path": frame_path,
            "json_folder": json_folder_path,
            "category": "flow",
            "detection_method": "stack"
        }

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to detect flow caller: {e}")
        return _create_fallback_info(frame_path)


def _detect_prax_caller(frame_path: Path) -> Dict[str, Any]:
    """Detect prax module caller from stack frame path."""
    try:
        prax_index = frame_path.parts.index("prax")
        prax_path = Path(*frame_path.parts[:prax_index + 1])
        json_folder_path = prax_path / "prax_json"
        caller_name = frame_path.stem

        # logger.info(f"[{MODULE_NAME}] Detected prax caller: {caller_name}")

        return {
            "caller_name": caller_name,
            "caller_path": frame_path,
            "json_folder": json_folder_path,
            "category": "prax",
            "detection_method": "stack"
        }

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to detect prax caller: {e}")
        return _create_fallback_info(frame_path)


def _detect_skills_caller(frame_path: Path) -> Dict[str, Any]:
    """
    Detect skills module caller from stack frame path.
    Skills have category subdirectories (e.g., /skills/skills_api/skill.py)
    """
    try:
        for i, part in enumerate(frame_path.parts):
            if "skills" in part:
                skills_path = Path(*frame_path.parts[:i + 2])
                category = frame_path.parts[i + 1] if i + 1 < len(frame_path.parts) else "skills_api"
                json_folder_path = skills_path / f"{category}_json"
                caller_name = frame_path.stem

                # logger.info(f"[{MODULE_NAME}] Detected skills caller: {caller_name} (category: {category})")

                return {
                    "caller_name": caller_name,
                    "caller_path": frame_path,
                    "json_folder": json_folder_path,
                    "category": "skills",
                    "skills_category": category,
                    "detection_method": "stack"
                }

        # logger.info(f"[{MODULE_NAME}] Could not find skills directory in path: {frame_path}")
        return _create_fallback_info(frame_path)

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to detect skills caller: {e}")
        return _create_fallback_info(frame_path)


def _create_fallback_info(frame_path: Path) -> Dict[str, Any]:
    """Create fallback caller info when detection fails."""
    caller_name = frame_path.stem
    category = detect_caller_category(frame_path)

    # logger.info(f"[{MODULE_NAME}] Using fallback detection for: {caller_name}")

    return {
        "caller_name": caller_name,
        "caller_path": frame_path,
        "json_folder": None,
        "category": category,
        "detection_method": "fallback"
    }


# =============================================
# VALIDATION HELPERS
# =============================================

def validate_caller_info(caller_info: Dict[str, Any]) -> bool:
    """Validate caller information dictionary."""
    try:
        required_fields = ["caller_name", "caller_path", "category", "detection_method"]
        for field in required_fields:
            if field not in caller_info:
                # logger.info(f"[{MODULE_NAME}] Missing required field: {field}")
                return False

        if not caller_info["caller_name"]:
            # logger.info(f"[{MODULE_NAME}] Caller name is empty")
            return False

        if not isinstance(caller_info["caller_path"], Path):
            # logger.info(f"[{MODULE_NAME}] Caller path is not a Path object")
            return False

        valid_categories = ["flow", "prax", "skills", "unknown"]
        if caller_info["category"] not in valid_categories:
            # logger.info(f"[{MODULE_NAME}] Invalid category: {caller_info['category']}")
            return False

        return True

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Validation failed: {e}")
        return False


# =============================================
# MODULE INITIALIZATION
# =============================================

def _initialize():
    """Initialize caller detection module."""
    # logger.info(f"[{MODULE_NAME}] Caller detection handler loaded (v{MODULE_VERSION})")
    pass

_initialize()
