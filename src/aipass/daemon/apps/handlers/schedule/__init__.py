# ===================AIPASS====================
# META DATA HEADER
# Name: __init__.py - Schedule Handlers Package
# Date: 2026-02-04
# Version: 1.0.0
# Category: assistant/handlers/schedule
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-02-04): Initial package setup
#
# CODE STANDARDS:
#   - Handlers implement logic, modules orchestrate
#   - No cross-branch imports, no Prax logger
# =============================================

"""
Schedule handlers for ASSISTANT's scheduled follow-ups system.
"""

from aipass.daemon.apps.handlers.schedule.task_registry import (
    load_tasks,
    save_tasks,
    create_task,
    delete_task,
    get_due_tasks,
    mark_completed,
    parse_due_date
)

__all__ = [
    'load_tasks',
    'save_tasks',
    'create_task',
    'delete_task',
    'get_due_tasks',
    'mark_completed',
    'parse_due_date'
]
