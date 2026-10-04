# =================== AIPass ====================
# Name: codex.py
# Version: 2.0.0
# Description: Codex bridge — mounts the promoted hook code, fails closed on PreToolUse
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-07-10
# Modified: 2026-09-30
# =============================================

"""Codex bridge.

Thin entry point called from .codex/hooks.json hook entries.
Normalizes Codex's stdin/stdout format and calls the engine.

Codex protocol differences from Claude Code:
  - stdin: uses 'input' instead of 'tool_input' for tool parameters
  - stdout: wraps output in hookSpecificOutput envelope
  - blocking: permissionDecision + permissionDecisionReason (not exit code 2)

Supports two forms:
  codex.py EventType          — dispatch ALL enabled hooks for that event
  codex.py EventType:hook_name — dispatch ONLY that one hook (separate output)

Since 2.0.0 (DPLAN-0356), as claude.py: the hook code is the promoted copy
(mount.py), engine.run_event owns everything past argv and stdin, and a
PreToolUse call whose hook code cannot load or raises is DENIED. Every other
event answers an empty document.
"""

import importlib.util
import json
import os
import sys

from aipass.prax.apps.modules.logger import system_logger as logger

GUARDED_EVENTS = frozenset({"PreToolUse"})

BROKEN = (
    "HOOKS BROKEN: the AIPass hook engine could not run ({error}).\n"
    "Every gate it runs is down, so nothing they guard runs until it is fixed.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Hooks broken" "<what you ran, and this text>"'
)


def _normalize_stdin(stdin_data: str) -> str:
    """Remap Codex field names to engine-expected names."""
    if not stdin_data.strip():
        return stdin_data
    try:
        parsed = json.loads(stdin_data)
        if "input" in parsed and "tool_input" not in parsed:
            parsed["tool_input"] = parsed.pop("input")
        return json.dumps(parsed)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.info("[HOOKS:codex] stdin normalization failed: %s", exc)
        return stdin_data


def _wrap_output(event_type: str, output: str, exit_code: int) -> str:
    """Wrap engine output into Codex hookSpecificOutput envelope."""
    if exit_code == 2:
        try:
            decision = json.loads(output)
            if decision.get("decision") == "block":
                reason = decision.get("reason", "Blocked by AIPass hook")
                return json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": event_type,
                            "permissionDecision": "deny",
                            "permissionDecisionReason": reason,
                        },
                        "systemMessage": reason,
                    }
                )
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            logger.info("[HOOKS:codex] block output parse failed: %s", exc)

    if not output:
        return json.dumps({})

    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": event_type,
                "additionalContext": output,
            },
        }
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
        return mount.mount(mount.branch_root(__file__))
    except Exception as exc:  # a bad promoted copy: the source still gates, and says so
        logger.error("[HOOKS:codex] promoted copy unusable, serving the source tree: %s", exc)
        return "source (fallback)"


def _broken_output(event_type: str, exc: BaseException) -> str:
    """Deny a guarded event outright; any other event gets an empty document."""
    reason = BROKEN.format(error=f"{type(exc).__name__}: {exc}")
    logger.error("[HOOKS:codex] bridge: %s on %s", reason.splitlines()[0], event_type)
    if event_type in GUARDED_EVENTS:
        return _wrap_output(event_type, json.dumps({"decision": "block", "reason": reason}), 2)
    return json.dumps({})


def main() -> None:
    """Entry point — receive event type from Codex, dispatch via the promoted engine."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: codex.py <EventType> or codex.py <EventType:hook_name>\n")
        sys.exit(1)

    arg = sys.argv[1]
    event_type = arg.split(":", 1)[0]
    stdin_data = "" if sys.stdin.isatty() else sys.stdin.read()

    try:
        _mount()
        from aipass.hooks.apps.modules.engine import run_event

        output, exit_code = run_event(arg, _normalize_stdin(stdin_data))
    except Exception as exc:  # fail closed on the guarded event, see _broken_output
        sys.stdout.write(_broken_output(event_type, exc))
        return

    sys.stdout.write(_wrap_output(event_type, output, exit_code))


if __name__ == "__main__":
    main()
