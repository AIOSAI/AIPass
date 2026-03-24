# =================== AIPass ====================
# Name: module_tracker.py
# Description: Module Execution Tracker
# Version: 0.1.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""Track module execution and drone commands"""

from typing import Dict, List, Optional
from datetime import datetime

from aipass.prax.apps.handlers.json import json_handler

class ModuleTracker:
    """Track active modules and their execution"""

    def __init__(self):
        self.active_modules: Dict[str, Dict] = {}
        self.completed_modules: List[Dict] = []
        self.max_history = 100

    def track_start(self, module_name: str, command: str, pid: Optional[int] = None):
        """Track module start"""
        json_handler.log_operation("module_tracked", {"module": module_name, "command": command})
        self.active_modules[module_name] = {
            'command': command,
            'pid': pid,
            'start_time': datetime.now(),
            'status': 'running'
        }

    def get_active(self) -> List[Dict]:
        """Get list of active modules"""
        return [
            {
                'name': name,
                **info
            }
            for name, info in self.active_modules.items()
            if info['status'] == 'running'
        ]

# Global instance
tracker = ModuleTracker()
