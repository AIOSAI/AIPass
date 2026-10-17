# ===================AIPASS====================
# META DATA HEADER
# Name: __init__.py - Schedule Handlers Package
# Date: 2026-02-04
# Version: 2.0.0
# Category: daemon/handlers/schedule
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2026-06-25): task_registry archived (TDPLAN-0008); package
#     now exposes runstate + discovery for the live .daemon/ scheduler.
#   - v1.0.0 (2026-02-04): Initial package setup
#
# CODE STANDARDS:
#   - Handlers implement logic, modules orchestrate
#   - No cross-branch imports, no Prax logger
# =============================================

"""
Schedule handlers for daemon's decentralized .daemon/ scheduler.
"""

from aipass.daemon.apps.handlers.schedule.runstate import (
    load_runstate,
    save_runstate,
    update_job_runstate,
    is_job_due,
    job_key,
)
from aipass.daemon.apps.handlers.schedule.discovery import discover_jobs

__all__ = [
    "load_runstate",
    "save_runstate",
    "update_job_runstate",
    "is_job_due",
    "job_key",
    "discover_jobs",
]
