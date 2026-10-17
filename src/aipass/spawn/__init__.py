"""AIPass Spawn Module — Create new agents from templates."""

from typing import TYPE_CHECKING, Any

# Lazy (PEP 562): an eager import of core loads prax and the json shim past the handlers fence.
if TYPE_CHECKING:
    from aipass.spawn.apps.modules.core import spawn_agent

__all__ = ["spawn_agent"]


def __getattr__(name: str) -> Any:
    """Import spawn_agent from apps/modules/core on its first access."""
    if name == "spawn_agent":
        from aipass.spawn.apps.modules.core import spawn_agent

        return spawn_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
