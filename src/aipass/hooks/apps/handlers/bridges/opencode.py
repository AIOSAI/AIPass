# =================== AIPass ====================
# Name: opencode.py
# Version: 1.5.1
# Description: OpenCode bridge — the aipass.ts plugin's calls, mapped to Claude's protocol, answered in one JSON line
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-10-28
# Modified: 2026-11-22
# =============================================

"""OpenCode bridge.

OpenCode has no shell-hook config: its plugin (opencode_plugin.ts, installed as aipass.ts) runs the
manifest's cli.opencode rows, each a call of this file. Tool names and keys become Claude's here, once.
The answer is one JSON object: {"deny": reason}, {"context": text}, {"entry": {"key", "value"}} or {}.
See docs/wiring.md.
"""

import contextlib
import importlib.util
import json
import os
import sys
import time

GUARDED_EVENTS = frozenset({"PreToolUse"})

PROVIDER = "opencode"

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

TOOLS = {
    "shell": "Bash",
    "edit": "Edit",
    "write": "Write",
    "read": "Read",
    "glob": "Glob",
    "grep": "Grep",
    "webfetch": "WebFetch",
    "websearch": "WebSearch",
    "subagent": "Task",
    "skill": "Skill",
}

#: Input keys renamed on the file tools only: Grep's and Glob's ``path`` is a search root in both protocols.
FILE_TOOLS = frozenset({"edit", "write", "read"})
FILE_KEYS = {
    "path": "file_path",
    "filePath": "file_path",
    "oldString": "old_string",
    "newString": "new_string",
    "replaceAll": "replace_all",
}

CODE_TOOL = "execute"

#: OpenCode's file tool on gpt- models, which get no edit or write: a Codex-style patch in input.patchText.
PATCH_TOOL = "patch"

#: The grounding loaders: their text becomes a keyed instruction entry, which OpenCode keeps through a compaction.
GROUNDING = {
    "SessionStart:culture": "aipass-culture",
    "UserPromptSubmit:tier0_kernel": "aipass-kernel",
    "UserPromptSubmit:navmap": "aipass-navmap",
    "UserPromptSubmit:branch_prompt": "aipass-branch-prompt",
    "UserPromptSubmit:identity_injector": "aipass-identity",
}

UNGATED = (
    "OpenCode's execute tool runs code no AIPass gate can read, so it does not run here. "
    "Use the shell tool for commands and the edit or write tool for files."
)

BROKEN = (
    "HOOKS BROKEN: the AIPass hook engine could not run ({error}).\n"
    "Every gate it runs is down, so nothing they guard runs until it is fixed.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Hooks broken" "<what you ran, and this text>"'
)

#: Where a break is recorded: @trigger's branch watcher reads src/aipass/*/logs/*.log for ERROR lines.
BREAK_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "logs", "bridge.log")
LIVE_BREAK_LOG = BREAK_LOG


def _as_object(text: str) -> dict | None:
    """*text* as a JSON object, or None when it is plain text."""
    try:
        doc = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return doc if isinstance(doc, dict) else None


def claude_payload(payload: dict) -> dict:
    """The plugin's payload in Claude's shape: OpenCode's ``tool``/``input`` become ``tool_name``/``tool_input``."""
    out = {key: value for key, value in payload.items() if key not in ("tool", "input")}
    out["provider"] = PROVIDER
    tool = payload.get("tool")
    if isinstance(tool, str):
        given = payload.get("input")
        given = given if isinstance(given, dict) else {}
        out["tool_name"] = TOOLS.get(tool, tool)
        out["tool_input"] = {FILE_KEYS.get(k, k): v for k, v in given.items()} if tool in FILE_TOOLS else given
    return out


def answer(output: str, exit_code: int) -> dict:
    """The engine's Claude-protocol answer as the plugin's: a deny reason, context text, or nothing.

    Exit 2 denies whatever the text, as Claude Code does; so does a JSON block or a deny or ask decision,
    since OpenCode's plugin cannot ask the owner.
    """
    doc = _as_object(output)
    own = doc.get("hookSpecificOutput") if doc is not None else None
    own = own if isinstance(own, dict) else {}
    decided = own.get("permissionDecision") in ("deny", "ask") or (doc or {}).get("decision") == "block"
    if exit_code == 2 or decided:
        reason = (doc or {}).get("reason") or own.get("permissionDecisionReason") or output.strip()
        return {"deny": reason or "Blocked by AIPass hook"}
    if doc is None:
        return {"context": output} if output.strip() else {}
    context = own.get("additionalContext") or doc.get("additionalContext") or ""
    return {"context": context} if context else {}


def _mount() -> str:
    """Serve aipass.hooks.apps from the promoted copy; on a bad copy, from the source tree, loudly."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("_aipass_hooks_mount", os.path.join(here, "mount.py"))
    if spec is None or spec.loader is None:
        raise ImportError("mount.py has no import spec")
    mount = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mount)
    return mount.mount_or_source(__file__, "opencode")


def _reason(exc: BaseException) -> str:
    """The BROKEN text for *exc*; one whose message itself raises is named by its type, and still denied."""
    try:
        return BROKEN.format(error=f"{type(exc).__name__}: {exc}")
    except Exception:
        return BROKEN.format(error=f"{type(exc).__name__}, whose message could not be read")


def _record_break(event_type: str, line: str) -> None:
    """Append one ERROR line in prax's format, after the answer has left: an attempt, never a wait."""
    if "_pytest" in sys.modules and BREAK_LOG == LIVE_BREAK_LOG:
        return  # prax's own test seam: a suite run's break never lands in the live log medic reads
    try:
        entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | bridges.opencode | ERROR | {line} on {event_type}\n"
        fd = os.open(BREAK_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK, 0o666)
        try:
            os.write(fd, entry.encode("utf-8", "backslashreplace"))
        finally:
            os.close(fd)
    except BaseException as exc:  # the answer is already out: nothing the record raises may change it
        with contextlib.suppress(BaseException):
            sys.stderr.write(
                f"[hooks:opencode] bridge: the break was not recorded in {BREAK_LOG}: {type(exc).__name__}: {exc}\n"
            )


def _broken(event_type: str, exc: BaseException) -> None:
    """Deny a guarded event outright; any other event answers nothing. Answer first, record after."""
    reason = _reason(exc)
    sys.stdout.write(json.dumps({"deny": reason} if event_type in GUARDED_EVENTS else {}))
    sys.stdout.flush()
    with contextlib.suppress(BaseException):
        sys.stderr.write(reason.encode("utf-8", "backslashreplace").decode("utf-8") + "\n")
    _record_break(event_type, reason.splitlines()[0])


def _run_patch(arg: str, payload: dict) -> tuple[str, int]:
    """A patch is judged as the Codex bridge judges apply_patch: one Claude call per file, the first exit 2 denies."""
    from aipass.hooks.apps.handlers.bridges import codex

    given = payload.get("input")
    patch = given.get("patchText", "") if isinstance(given, dict) else ""
    rest = claude_payload({key: value for key, value in payload.items() if key not in ("tool", "input")})
    return codex._run_calls(
        arg, json.dumps({**rest, "tool_name": codex.PATCH_TOOL, "tool_input": {"command": str(patch)}})
    )


def run(arg: str, stdin_data: str) -> dict:
    """One plugin call: the event *arg* (``Event`` or ``Event:hook``) on the plugin's payload, answered.

    A broken engine raises out of here; main answers for it (see _broken).
    """
    event_type = arg.split(":", 1)[0]
    payload = _as_object(stdin_data) or {}
    if event_type in GUARDED_EVENTS and payload.get("tool") == CODE_TOOL:
        return {"deny": UNGATED}
    if payload.get("session_id"):
        # Cadence and the ledgers key a seat on this variable; the OpenCode server inherits none, or a stale one.
        os.environ[SESSION_ENV] = str(payload["session_id"])
    _mount()
    from aipass.hooks.apps.handlers.json import json_handler
    from aipass.hooks.apps.modules.engine import run_event

    if payload.get("tool") == PATCH_TOOL:
        output, exit_code = _run_patch(arg, payload)
    else:
        output, exit_code = run_event(arg, json.dumps(claude_payload(payload)))
    json_handler.log_operation("bridge", {"event": arg, "exit_code": exit_code})
    result = answer(output, exit_code)
    key = GROUNDING.get(arg)
    # Only a plugin that says it keeps entries gets one; an older installed copy would drop the text.
    if key and "context" in result and payload.get("keeps_entries") is True:
        return {"entry": {"key": key, "value": result["context"]}}
    return result


def main() -> None:
    """Entry point — receive the event from the aipass.ts plugin, answer on stdout in one JSON line."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: opencode.py <EventType> or opencode.py <EventType:hook_name>\n")
        sys.exit(1)
    try:
        stdin_data = "" if sys.stdin.isatty() else sys.stdin.read()
        result = run(sys.argv[1], stdin_data)
    except BaseException as exc:  # fail closed on the guarded event, however it broke: see _broken
        _broken(sys.argv[1].split(":", 1)[0], exc)
        return
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
