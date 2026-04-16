# =================== AIPass ====================
# Name: monitoring.py
# Description: PRAX Logging Handler
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2026-03-09
# =============================================

"""
PRAX Logging Monitoring Handler

Implements the continuous monitoring loop for the logging system.
HANDLER pattern: Contains the business logic for continuous monitoring.

This is the thick implementation that modules/logger.py calls.
"""

import sys
import time
from typing import Callable, Dict, Any

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.prax.apps.handlers.json import json_handler


def run_monitoring_loop(
    status_callback: Callable[[], Dict[str, Any]], interval: int = 5, status_interval: int = 300
) -> None:
    """Run continuous monitoring loop - HANDLER implements logic

    This is the thick handler that contains the actual control loop.

    Args:
        status_callback: Function to call to get system status
        interval: Check interval in seconds (default: 5)
        status_interval: Status update interval in seconds (default: 300 = 5 minutes)

    Raises:
        KeyboardInterrupt: When user presses Ctrl+C (caught and handled gracefully)
    """
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

            # Status update at specified interval
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
