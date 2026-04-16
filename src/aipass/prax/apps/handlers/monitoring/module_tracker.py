# =================== AIPass ====================
# Name: module_tracker.py
# Description: Module Execution Tracker
# Version: 0.1.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""Track module execution and drone commands"""

from typing import Dict, List

from aipass.prax.apps.handlers.json import json_handler


class ModuleTracker:
    """Track active modules and their execution"""

    def __init__(self):
        self.active_modules: Dict[str, Dict] = {}
        self.completed_modules: List[Dict] = []
        self.max_history = 100
        json_handler.log_operation("module_tracker_initialized", {"max_history": self.max_history})


# Global instance
tracker = ModuleTracker()
