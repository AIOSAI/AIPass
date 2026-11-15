"""system_detect — OS, shell, Python, RAM/CPU, install method detection."""

from aipass.aipass.apps.handlers.system_detect.system_detector import (
    detect_claude_code,
    detect_cpu,
    detect_git,
    detect_install_method,
    detect_os,
    detect_python,
    detect_ram,
    detect_shell,
)

__all__ = [
    "detect_claude_code",
    "detect_cpu",
    "detect_git",
    "detect_install_method",
    "detect_os",
    "detect_python",
    "detect_ram",
    "detect_shell",
]
