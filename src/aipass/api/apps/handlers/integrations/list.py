# =================== AIPass ====================
# Name: list.py
# Description: Handler for listing registered integration contracts
# Version: 1.0.0
# Created: 2026-04-15
# Modified: 2026-04-15
# =============================================
"""
List registered integration contracts.

Accepts a pre-fetched list of contract names from the calling module layer.
No module imports — the module layer owns bridge access and passes data in.
"""

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler


def get_contracts(contracts: list[str]) -> dict:
    """
    Log and return contract listing result.

    Args:
        contracts: Pre-fetched sorted list of contract names from bridge.

    Returns:
        dict with keys: contracts (list[str]), count (int), success (bool).
    """
    try:
        json_handler.log_operation("integrations_list", {"count": len(contracts), "contracts": contracts})
        return {"contracts": contracts, "count": len(contracts), "success": True}
    except Exception as e:
        logger.error(f"[list] Failed to process contracts: {e}")
        return {"contracts": [], "count": 0, "success": False}
