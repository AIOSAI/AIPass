# =================== AIPass ====================
# Name: claude.py
# Version: 2.0.0
# Description: Claude Code bridge — mounts the promoted hook code, fails closed on PreToolUse
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-05-18
# Modified: 2026-09-30
# =============================================

"""
Claude Code bridge.

Thin entry point called from the provider settings hook entries:
  claude.py EventType          — dispatch ALL enabled hooks for that event
  claude.py EventType:hook_name — dispatch ONLY that one hook (separate output)

Since 2.0.0 (DPLAN-0356):
  - The hook code is the PROMOTED copy (mount.py, `drone @hooks promote`), never
    the tree being edited. This script runs from the source tree, so it holds
    nothing but argv, stdin, the mount and one call: engine.run_event owns the
    rest and changes only through promote.
  - Failure mode: a PreToolUse call whose hook code cannot load or raises is
    REFUSED (block JSON, exit 2): Claude Code runs the tool on any other exit, so
    a bridge that dies quietly is every gate off. Every other event exits 0 with
    the reason on stderr: an injector that cannot load costs its text, never the
    prompt.
"""

import importlib.util
import json
import os
import sys

GUARDED_EVENTS = frozenset({"PreToolUse"})

BROKEN = (
    "HOOKS BROKEN: the AIPass hook engine could not run ({error}).\n"
    "Every gate it runs is down, so nothing they guard runs until it is fixed.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Hooks broken" "<what you ran, and this text>"'
)


def _mount() -> str:
    """Serve aipass.hooks.apps from the promoted copy; on a bad copy, from the source tree, loudly."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("_aipass_hooks_mount", os.path.join(here, "mount.py"))
    if spec is None or spec.loader is None:
        raise ImportError("mount.py has no import spec")
    mount = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mount)
    try:
        served = mount.mount(mount.branch_root(__file__))
    except Exception as exc:  # a bad promoted copy: the source still gates, and says so
        from aipass.prax.apps.modules.logger import system_logger as logger

        logger.error("[HOOKS] bridge: promoted copy unusable, serving the source tree: %s", exc)
        served = "source (fallback)"
    if os.environ.get(mount.OVERRIDE_ENV):
        sys.stderr.write(f"[HOOKS] served by {served}\n")
    return served


def _broken(event_type: str, exc: BaseException) -> None:
    """Refuse a guarded event outright; let any other event pass with the reason on stderr."""
    reason = BROKEN.format(error=f"{type(exc).__name__}: {exc}")
    sys.stderr.write(reason + "\n")
    try:
        from aipass.prax.apps.modules.logger import system_logger as logger

        logger.error("[HOOKS] bridge: %s on %s", reason.splitlines()[0], event_type)
    except Exception as log_exc:  # the logger can be what broke; stderr above already carries it
        sys.stderr.write(f"[HOOKS] bridge: logger unavailable too: {log_exc}\n")
    if event_type in GUARDED_EVENTS:
        sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(2)


def main() -> None:
    """Entry point — receive event type from Claude Code, dispatch via the promoted engine."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: claude.py <EventType> or claude.py <EventType:hook_name>\n")
        sys.exit(1)

    arg = sys.argv[1]
    event_type = arg.split(":", 1)[0]
    stdin_data = "" if sys.stdin.isatty() else sys.stdin.read()

    try:
        _mount()
        from aipass.hooks.apps.modules.engine import run_event

        output, exit_code = run_event(arg, stdin_data)
    except Exception as exc:  # fail closed on the guarded event, see _broken
        _broken(event_type, exc)
        return

    if output:
        sys.stdout.write(output)
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
