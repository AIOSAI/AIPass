"""
PRAX Modules - Public API

Modules in this directory are SERVICES that PRAX provides to other branches.
Other branches import from here to use PRAX services.

Available modules:
- logger: System-wide logging service
  Import: from aipass.prax.apps.modules.logger import system_logger

  Usage:
    system_logger.info("Your message")
    system_logger.warning("Warning message")
    system_logger.error("Error message")

  Logs auto-route to: {repo_root}/system_logs/<your_module>.log
"""

# The unknown-argument gate is re-exported here on purpose: the entry point
# (apps/prax.py) talks to the modules layer, never to a handler directly. The
# gate itself lives in apps/handlers/cli/arg_gate.py, where the modules import
# it from.
from aipass.prax.apps.handlers.cli.arg_gate import (  # noqa: E402
    UnknownArgument,
    did_you_mean,
    refuse,
    unknown_option,
)

__all__ = ["UnknownArgument", "did_you_mean", "refuse", "unknown_option"]
