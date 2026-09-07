# =================== AIPass ====================
# Name: claude.py
# Version: 1.0.0
# Description: Claude Code bridge — entry point for provider hook settings
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-05-18
# Modified: 2026-05-18
# =============================================

"""
Claude Code bridge.

Thin entry point called from ~/.claude/settings.json hook entries.
Normalizes Claude Code's stdin/stdout format and calls the engine.

Supports two forms:
  claude.py EventType          — dispatch ALL enabled hooks for that event
  claude.py EventType:hook_name — dispatch ONLY that one hook (separate output)
"""

import sys

from aipass.hooks.apps.modules.engine import dispatch
from aipass.hooks.apps.handlers.config.loader import find_project_config
from aipass.prax.apps.modules.logger import system_logger as logger


def main() -> None:
    """Entry point — receive event type from Claude Code, dispatch via engine."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: claude.py <EventType> or claude.py <EventType:hook_name>\n")
        sys.exit(1)

    arg = sys.argv[1]
    hook_filter = None
    if ":" in arg:
        event_type, hook_filter = arg.split(":", 1)
    else:
        event_type = arg

    stdin_data = ""
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read()

    config = find_project_config()
    if config is None:
        config = {"hooks_enabled": True}
        logger.info("[HOOKS:claude] no project config found, using defaults")

    if hook_filter:
        full_config: dict = config
        hook_def = full_config.get(event_type, {}).get(hook_filter, {})
        config = {"hooks_enabled": True, event_type: {hook_filter: hook_def}}

    output, exit_code = dispatch(event_type, stdin_data, config)
    if output:
        stream = sys.stderr if exit_code == 2 else sys.stdout
        stream.write(output)
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
