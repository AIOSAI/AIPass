# =================== AIPass ====================
# Name: call.py
# Description: Handler for invoking a registered integration contract driver
# Version: 1.0.1
# Created: 2026-04-15
# Modified: 2026-10-24
# =============================================
"""Call a registered integration contract."""

from typing import Callable

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler


def invoke(driver_fn: Callable, contract_name: str, args: list[str]) -> dict:
    """Invoke a contract driver with the given args."""
    try:
        result = driver_fn(*args)
        json_handler.log_operation(
            "integrations_call", {"contract": contract_name, "arg_count": len(args), "success": True}
        )
        return {"result": str(result) if result is not None else None, "success": True, "error": None}
    except Exception as e:
        logger.error(f"[call] Driver '{contract_name}' raised: {e}")
        json_handler.log_operation("integrations_call", {"contract": contract_name, "success": False, "error": str(e)})
        return {"result": None, "success": False, "error": str(e)}
