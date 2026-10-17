# =================== AIPass ====================
# Name: list.py
# Description: Handler for listing registered integration contracts
# Version: 1.0.0
# Created: 2026-04-15
# Modified: 2026-10-17
# =============================================
"""List registered integration contracts."""

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler


def get_contracts(contracts: list[str]) -> dict:
    """Log and return contract listing result."""
    try:
        json_handler.log_operation("integrations_list", {"count": len(contracts), "contracts": contracts})
        return {"contracts": contracts, "count": len(contracts), "success": True}
    except Exception as e:
        logger.error(f"[list] Failed to process contracts: {e}")
        return {"contracts": [], "count": 0, "success": False}
