"""
AIPass Spawn Module — Create new agents from templates.

Usage:
    from aipass.spawn import spawn_agent
    result = spawn_agent("/path/to/new/agent", role="My Role", purpose="My Purpose")

spawn_agent is resolved lazily (PEP 562): importing this package no longer
imports apps/modules/core, which loaded prax and the json shim (274 modules)
on every import of the package and was a second eager door past the handlers
fence (DPLAN-0404, spawn's fence leg).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aipass.spawn.apps.modules.core import spawn_agent

__all__ = ["spawn_agent"]


def __getattr__(name: str) -> Any:
    """Import spawn_agent from apps/modules/core on its first access."""
    if name == "spawn_agent":
        from aipass.spawn.apps.modules.core import spawn_agent

        return spawn_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
