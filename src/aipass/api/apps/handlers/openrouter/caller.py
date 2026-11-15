# =================== AIPass ====================
# Name: caller.py
# Description: OpenRouter Caller Detection Handler
# Version: 1.0.3
# Created: 2025-11-16
# Modified: 2026-10-24
# =============================================

"""OpenRouter Caller Detection Handler"""

import inspect
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax import logger

from aipass.api.apps.handlers.json import json_handler

MODULE_NAME = "openrouter.caller"
MODULE_VERSION = "1.0.0"

CALLER_PATTERNS = {
    "flow": "flow_json",
    "prax": "prax_json",
}


def get_caller_info() -> Optional[Dict[str, Any]]:
    """
    Detect calling module via stack inspection.

    A failure answers None like no caller, on purpose: a raise (or a narrowed catch) would end
    client.get_response before its request is sent. The logged error line tells the two apart.
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


def _detect_flow_caller(frame_path: Path) -> Dict[str, Any]:
    """Detect flow module caller from stack frame path; get_caller_info only calls it when "flow" is a part."""
    flow_index = frame_path.parts.index("flow")
    flow_path = Path(*frame_path.parts[: flow_index + 1])
    caller_name = frame_path.stem

    logger.info(f"[{MODULE_NAME}] Detected flow caller: {caller_name}")

    return {
        "caller_name": caller_name,
        "caller_path": frame_path,
        "json_folder": flow_path / "flow_json",
        "category": "flow",
        "detection_method": "stack",
    }


def _detect_prax_caller(frame_path: Path) -> Dict[str, Any]:
    """Detect prax module caller from stack frame path; get_caller_info only calls it when "prax" is a part."""
    prax_index = frame_path.parts.index("prax")
    prax_path = Path(*frame_path.parts[: prax_index + 1])
    caller_name = frame_path.stem

    logger.info(f"[{MODULE_NAME}] Detected prax caller: {caller_name}")

    return {
        "caller_name": caller_name,
        "caller_path": frame_path,
        "json_folder": prax_path / "prax_json",
        "category": "prax",
        "detection_method": "stack",
    }


def _initialize():
    """Initialize caller detection module."""
    logger.info(f"[{MODULE_NAME}] Caller detection handler loaded (v{MODULE_VERSION})")


_initialize()
