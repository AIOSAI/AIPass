"""Hooks' import door (`from aipass.hooks import <name>`), and the marker that names this conftest uniquely.

Without it pytest imports this branch's conftest as the bare `tests.conftest`; two such branches abort collection.
"""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # each name typed from its home
    from aipass.hooks.apps.handlers.config.trust_registry import (
        REGISTRY_PATH,
        enroll,
        is_trusted,
        read_registry,
        registry_path,
        revoke,
    )
    from aipass.hooks.apps.modules.grounding_content import BRANCH_CHAR_BUDGET
    from aipass.hooks.apps.modules.sandbox import build_policy, build_srt_config, resolve_bwrap_command
    from aipass.hooks.apps.handlers.notification.sound import SOUND_FLAG, is_muted

_TRUST = "aipass.hooks.apps.handlers.config.trust_registry"
_SANDBOX = "aipass.hooks.apps.modules.sandbox"
_SOUND = "aipass.hooks.apps.handlers.notification.sound"

_HOMES = {
    "build_policy": _SANDBOX,
    "build_srt_config": _SANDBOX,
    "resolve_bwrap_command": _SANDBOX,
    "BRANCH_CHAR_BUDGET": "aipass.hooks.apps.modules.grounding_content",
    "is_muted": _SOUND,
    "SOUND_FLAG": _SOUND,
    "enroll": _TRUST,
    "is_trusted": _TRUST,
    "read_registry": _TRUST,
    "revoke": _TRUST,
    "registry_path": _TRUST,
    "REGISTRY_PATH": _TRUST,
}

__all__ = list(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access, never cached: a patch on the home reaches every caller."""
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
