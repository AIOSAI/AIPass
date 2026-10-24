# =================== AIPass ====================
# Name: claude.py
# Version: 2.0.1
# Description: Claude Code bridge — mounts the promoted hook code, fails closed on PreToolUse
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-05-18
# Modified: 2026-10-24
# =============================================

"""
Claude Code bridge.

Runs the promoted copy (`drone @hooks promote`), never the tree being edited.
A PreToolUse that cannot load or raises is refused (exit 2): Claude Code runs the
tool on any other exit. Every other event exits 0 with the reason on stderr.
"""

import importlib.util
import json
import os
import sys
import time

GUARDED_EVENTS = frozenset({"PreToolUse"})

#: Where a break is recorded: @trigger's branch watcher reads src/aipass/*/logs/*.log for ERROR lines.
BREAK_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "logs", "bridge.log")

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


def _record_break(event_type: str, line: str) -> None:
    """One ERROR line in prax's format, written with the stdlib: the prax logger can be what broke."""
    entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | bridges.claude | ERROR | {line} on {event_type}\n"
    try:
        with open(BREAK_LOG, "a", encoding="utf-8") as handle:
            handle.write(entry)
    except OSError as exc:
        sys.stderr.write(f"[HOOKS] bridge: the break was not recorded in {BREAK_LOG}: {exc}\n")


def _broken(event_type: str, exc: BaseException) -> None:
    """Refuse a guarded event outright; let any other event pass with the reason on stderr."""
    reason = BROKEN.format(error=f"{type(exc).__name__}: {exc}")
    sys.stderr.write(reason + "\n")
    _record_break(event_type, reason.splitlines()[0])
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
