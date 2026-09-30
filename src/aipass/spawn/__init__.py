"""
AIPass Spawn Module — Create new agents from templates.

Usage:
    from aipass.spawn import spawn_agent
    result = spawn_agent("/path/to/new/agent", role="My Role", purpose="My Purpose")
"""

from aipass.spawn.apps.modules.core import spawn_agent

__all__ = ["spawn_agent"]
