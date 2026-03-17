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
import re

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

    def track_stop(self, module_name: str, exit_code: int = 0):
        """Track module completion"""
        if module_name in self.active_modules:
            module_info = self.active_modules.pop(module_name)
            module_info['end_time'] = datetime.now()
            module_info['exit_code'] = exit_code
            module_info['status'] = 'completed' if exit_code == 0 else 'failed'

            # Add to history
            self.completed_modules.append(module_info)
            if len(self.completed_modules) > self.max_history:
                self.completed_modules.pop(0)

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

    def parse_log_for_commands(self, log_line: str) -> Optional[Dict]:
        """Parse log line for command execution patterns"""

        # Pattern: "Drone started with args: ['seed', 'audit']"
        if 'Drone started with args:' in log_line:
            match = re.search(r"args:\s*\[([^\]]+)\]", log_line)
            if match:
                args = match.group(1).replace("'", "").replace('"', '')
                return {
                    'type': 'drone',
                    'command': f"drone {args}",
                    'timestamp': datetime.now()
                }

        # Pattern: "Executing command: flow create PLAN0001"
        if 'Executing command:' in log_line:
            match = re.search(r"Executing command:\s*(.+)", log_line)
            if match:
                return {
                    'type': 'command',
                    'command': match.group(1),
                    'timestamp': datetime.now()
                }

        # Pattern: Module start/stop indicators
        if 'Module started:' in log_line:
            match = re.search(r"Module started:\s*(\w+)", log_line)
            if match:
                self.track_start(match.group(1), "unknown")
                return {
                    'type': 'module_start',
                    'module': match.group(1),
                    'timestamp': datetime.now()
                }

        return None

    def format_active_modules(self) -> str:
        """Format active modules for display"""
        active = self.get_active()
        if not active:
            return "No modules currently running"

        lines = ["Active Modules:"]
        for module in active:
            duration = (datetime.now() - module['start_time']).seconds
            lines.append(f"  • {module['name']}: {module['command']} ({duration}s)")

        return "\n".join(lines)

# Global instance
tracker = ModuleTracker()
