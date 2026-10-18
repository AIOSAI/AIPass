# =================== AIPass ====================
# Name: monitoring.py
# Description: PRAX Logging Handler
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""PRAX Logging Monitoring Handler"""

import sys
import time
from typing import Callable, Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.prax.apps.handlers.json import json_handler


def run_monitoring_loop(
    status_callback: Callable[[], Dict[str, Any]], interval: int = 5, status_interval: int = 300
) -> None:
    """Run continuous monitoring loop - HANDLER implements logic"""
    module_name = "prax_logger"
    json_handler.log_operation("monitoring_configured", {"interval": interval, "status_interval": status_interval})

    try:
        logger.info(f"[{module_name}] Logger capture active - monitoring all modules")
        logger.info(f"[{module_name}] Terminal output enabled - you'll see live logs below")
        logger.info("Press Ctrl+C to stop logging...")
        logger.info("=" * 60)
        sys.stdout.flush()

        counter = 0
        while True:
            time.sleep(interval)
            counter += interval

            if counter % status_interval == 0:
                logger.info("\n" + "=" * 60)
                status = status_callback()
                modules_count = status.get("total_modules", 0)
                loggers_count = status.get("individual_loggers", 0)
                logger.info(
                    f"[{module_name}] Status: {modules_count} modules discovered, {loggers_count} loggers active"
                )
                logger.info("=" * 60)
                sys.stdout.flush()

    except KeyboardInterrupt:
        logger.info(f"\n[{module_name}] Shutting down continuous logging...")
        sys.stdout.flush()
        raise  # Re-raise to let caller handle cleanup
