# =================== AIPass ====================
# Name: call.py
# Description: Handler for invoking a registered integration contract driver
# Version: 1.0.0
# Created: 2026-04-15
# Modified: 2026-04-15
# =============================================
"""
Call a registered integration contract.

Accepts a resolved driver callable and args from the calling module layer.
No module imports — the module layer owns bridge access and passes the driver in.
Returns a result dict; display is handled by the module layer.
"""

from typing import Callable

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler


def invoke(driver_fn: Callable, contract_name: str, args: list[str]) -> dict:
    """
    Invoke a contract driver with the given args.

    Args:
        driver_fn: Resolved callable from bridge (already looked up by module layer).
        contract_name: Name of the contract being called (for logging).
        args: Arguments forwarded to the driver function.

    Returns:
        dict with keys: result (str | None), success (bool), error (str | None).
    """
    try:
        result = driver_fn(*args)
        json_handler.log_operation("integrations_call", {"contract": contract_name, "args": args, "success": True})
        return {"result": str(result) if result is not None else None, "success": True, "error": None}
    except Exception as e:
        logger.error(f"[call] Driver '{contract_name}' raised: {e}")
        json_handler.log_operation("integrations_call", {"contract": contract_name, "success": False, "error": str(e)})
        return {"result": None, "success": False, "error": str(e)}
