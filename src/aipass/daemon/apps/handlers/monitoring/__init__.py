# ===================AIPASS====================
# META DATA HEADER
# Name: __init__.py - Monitoring Handlers Package
# Date: 2026-01-30
# Version: 0.1.0
# Category: assistant/handlers/monitoring
#
# CHANGELOG (Max 5 entries):
#   - v0.1.0 (2026-01-30): Initial implementation - FPLAN-0266 Phase 1
#
# CODE STANDARDS:
#   - Handler package init - no Prax imports
#   - Part of Branch Activity Monitoring System
# =============================================

"""
Monitoring handlers for ASSISTANT branch.

Provides activity collection and memory health checking
for the Branch Activity Monitoring System (FPLAN-0266).
"""

from aipass.daemon.apps.handlers.monitoring.activity_collector import (
    load_branch_registry,
    get_branch_paths,
    scan_branch_activity,
    get_all_branch_activity,
)

from aipass.daemon.apps.handlers.monitoring.memory_health import (
    check_memory_files_exist,
    validate_memory_structure,
    check_freshness,
    get_memory_health_status,
)

from aipass.daemon.apps.handlers.monitoring.red_flag_detector import (
    get_branch_status,
    get_red_flag_summary,
)

__all__ = [
    # activity_collector
    'load_branch_registry',
    'get_branch_paths',
    'scan_branch_activity',
    'get_all_branch_activity',
    # memory_health
    'check_memory_files_exist',
    'validate_memory_structure',
    'check_freshness',
    'get_memory_health_status',
    # red_flag_detector
    'get_branch_status',
    'get_red_flag_summary',
]
