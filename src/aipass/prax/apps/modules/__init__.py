"""PRAX Modules - Public API

Reference: docs/logging_api.md
"""

# The arg gate is re-exported so apps/prax.py talks to the modules layer, never a handler.
from aipass.prax.apps.handlers.cli.arg_gate import (
    UnknownArgument,
    did_you_mean,
    refuse,
    unknown_option,
)

__all__ = ["UnknownArgument", "did_you_mean", "refuse", "unknown_option"]
