# =================== AIPass ====================
# Name: claude.py
# Version: 2.3.1
# Description: Claude Code bridge — mounts the promoted hook code, fails closed on PreToolUse
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-05-18
# Modified: 2026-11-22
# =============================================

"""Claude Code bridge: runs the promoted copy (`drone @hooks promote`), never the tree being edited.

A PreToolUse that cannot load or raises is refused (exit 2, set in a finally): Claude Code runs the
tool on any other exit. Every other event exits 0 with the reason on stderr.
One call is let through while the engine is broken: the admin seat's recovery command (safe_mode.py).
"""

import contextlib
import importlib.util
import json
import os
import sys
import time

GUARDED_EVENTS = frozenset({"PreToolUse"})

#: Where a break is recorded: @trigger's branch watcher reads src/aipass/*/logs/*.log for ERROR lines.
BREAK_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "logs", "bridge.log")
LIVE_BREAK_LOG = BREAK_LOG

#: Loaded by path, and only once the engine has failed: it imports nothing of aipass.
SAFE_MODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "safe_mode.py")

BROKEN = (
    "HOOKS BROKEN: the AIPass hook engine could not run ({error}).\n"
    "Every gate it runs is down, so nothing they guard runs until it is fixed.\n"
    "Safe mode, the admin seat only: {diagnose}\n"
    "No seat can act: a fresh agent started outside the project works "
    "src/aipass/flow/templates/playbook_plans/recovery.md\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Hooks broken" "<what you ran, and this text>"'
)


def _mount() -> str:
    """Serve aipass.hooks.apps from the promoted copy; on a bad copy, from the source tree, loudly (mount.py)."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("_aipass_hooks_mount", os.path.join(here, "mount.py"))
    if spec is None or spec.loader is None:
        raise ImportError("mount.py has no import spec")
    mount = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mount)
    served = mount.mount_or_source(__file__, "claude")
    if os.environ.get(mount.OVERRIDE_ENV):
        sys.stderr.write(f"[hooks] served by {served}\n")
    return served


def _safe_mode(stdin_data: str) -> bool:
    """True when safe_mode.py lets this one call through; raises when it cannot load or judge (the caller refuses)."""
    spec = importlib.util.spec_from_file_location("_aipass_hooks_safe_mode", SAFE_MODE)
    if spec is None or spec.loader is None:
        raise ImportError("safe_mode.py has no import spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.allows(stdin_data) is True


def _printable(text: str) -> str:
    """*text* safe on a UTF-8 stream: a lone surrogate (a path that is not UTF-8) becomes its escape."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _record_break(event_type: str, line: str) -> None:
    """Append one ERROR line in prax's format, after the answer has left: an attempt, never a wait."""
    if "_pytest" in sys.modules and BREAK_LOG == LIVE_BREAK_LOG:
        return  # prax's own test seam: a suite run's break never lands in the live log medic reads
    try:
        entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | bridges.claude | ERROR | {line} on {event_type}\n"
        fd = os.open(BREAK_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK, 0o666)
        try:
            os.write(fd, entry.encode("utf-8", "backslashreplace"))
        finally:
            os.close(fd)
    except BaseException as exc:  # the answer is already out: nothing the record raises may change it
        with contextlib.suppress(BaseException):
            sys.stderr.write(
                f"[hooks] bridge: the break was not recorded in {BREAK_LOG}: {type(exc).__name__}: {exc}\n"
            )


def _broken(event_type: str, exc: BaseException, stdin_data: str = "") -> None:
    """Refuse a guarded event outright, unless safe mode lets this call through; any other event passes.

    Answer first, record after.
    """
    code = 2 if event_type in GUARDED_EVENTS else 0
    try:
        if code and _safe_mode(stdin_data):
            return
    except BaseException as trouble:  # the engine is already down: a safe mode that cannot judge refuses, loudly
        with contextlib.suppress(BaseException):
            sys.stderr.write(f"[hooks] safe mode could not judge this call: {type(trouble).__name__}: {trouble}\n")
    try:
        diagnose = " ".join(("python3", "-I", SAFE_MODE, "diagnose"))
        reason = _printable(BROKEN.format(error=f"{type(exc).__name__}: {exc}", diagnose=diagnose))
        sys.stderr.write(reason + "\n")
        if code:
            sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))
        sys.stdout.flush()
        sys.stderr.flush()
        _record_break(event_type, reason.splitlines()[0])
    finally:
        if code:
            sys.exit(code)


def main() -> None:
    """Entry point — receive event type from Claude Code, dispatch via the promoted engine."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: claude.py <EventType> or claude.py <EventType:hook_name>\n")
        sys.exit(1)

    arg = sys.argv[1]
    event_type = arg.split(":", 1)[0]

    stdin_data = ""
    try:
        stdin_data = "" if sys.stdin.isatty() else sys.stdin.read()
        _mount()
        from aipass.hooks.apps.handlers.json import json_handler
        from aipass.hooks.apps.modules.engine import run_event

        output, exit_code = run_event(arg, stdin_data)
        json_handler.log_operation("bridge", {"event": arg, "exit_code": exit_code})
    except BaseException as exc:  # fail closed on the guarded event, however it broke: see _broken
        _broken(event_type, exc, stdin_data)
        return

    try:
        if output:
            sys.stdout.write(_printable(output))
    finally:
        if exit_code:
            sys.exit(exit_code)


if __name__ == "__main__":
    main()
