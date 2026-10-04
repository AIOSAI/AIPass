# =================== AIPass ====================
# Name: gates.py
# Version: 1.1.0
# Description: Which hooks are gates, and how each one fails — in code, never in config
# Branch: hooks
# Layer: apps/handlers/config
# Created: 2026-09-30
# Modified: 2026-10-01
# =============================================

"""Gates are not injectors (DPLAN-0356 item 2).

The engine's crash isolation ("one broken hook never blocks the rest") was
written for injectors in May and applied to gates unchanged, so a gate that
failed to import, raised or timed out simply stepped aside. Four gate crashes
and ~140 subagent_gate timeouts were allowed that way.

This list is CODE, not a config flag: config is data an agent might reach, and a
gate's failure mode is not something a config may relax.

  - :data:`FAIL_CLOSED`: a handler here that fails to import, raises, times out
    or exits 2 without a decision is answered with a BLOCK carrying
    :data:`BROKEN_GATE`, and the engine logs it at ERROR, the line @trigger
    escalates.
  - :data:`FAIL_OPEN`: gates whose failure is allowed, each with its reason. A
    block in their event cannot be cured from inside the session it blocks.

Anything in neither list is an injector and keeps the skip-on-error rule.

:func:`builtin_config` is the gate set that runs when no readable AIPass config
exists. :func:`gate_config` cuts the gate set out of a config.
"""

import copy

_SECURITY = "aipass.hooks.apps.handlers.security"

#: handler path -> the event's hook entry name in the AIPass config, and what a failure costs.
FAIL_CLOSED: dict[str, str] = {
    f"{_SECURITY}.edit_gate.handle": "every write fence (ownership, cross-project, inbox, .trinity caps)",
    f"{_SECURITY}.git_gate.handle": "raw git and gh, and the protected config files",
    f"{_SECURITY}.rm_gate.handle": "raw rm, drone rm and every other delete verb",
    f"{_SECURITY}.testwrite_gate.handle": "new test files",
    f"{_SECURITY}.registry_gate.handle": "the *_REGISTRY.json files",
    f"{_SECURITY}.edit_gate.tripwire_snapshot": "the shell-memory tripwire's before-image",
    f"{_SECURITY}.edit_gate.tripwire": "the shell-memory tripwire's report",
}

#: handler path -> why its failure is allowed.
FAIL_OPEN: dict[str, str] = {
    f"{_SECURITY}.presence_gate.handle": (
        "a broken presence gate would refuse every prompt in every seat, the owner's included, "
        "and the prompt it refuses is the one that would fix it"
    ),
    f"{_SECURITY}.presence_gate.handle_stop": "a no-op on Stop",
    f"{_SECURITY}.subagent_gate.handle": (
        "a block at SubagentStop keeps the sub-agent running; a gate that cannot finish would block "
        "every stop and trap it in a loop. Its failure is logged, and the main session's own gates still run"
    ),
}

GATE_HANDLERS = frozenset(FAIL_CLOSED) | frozenset(FAIL_OPEN)

BROKEN_GATE = (
    "GATE BROKEN: {gate} could not run ({why}). It guards {guards}.\n"
    "Nothing it guards runs until it is fixed.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Gate broken: {gate}" "<what you ran, and this text>"'
)

_BUILTIN: dict = {
    "hooks_enabled": True,
    "UserPromptSubmit": {
        "presence_gate": {
            "enabled": True,
            "handler": f"{_SECURITY}.presence_gate.handle",
            "matcher": "",
            "timeout": 90,
        },
    },
    "PreToolUse": {
        "pre_edit_gate": {
            "enabled": True,
            "handler": f"{_SECURITY}.edit_gate.handle",
            "matcher": "Bash|Edit|MultiEdit|Write|NotebookEdit",
        },
        "git_gate": {
            "enabled": True,
            "handler": f"{_SECURITY}.git_gate.handle",
            "matcher": "Bash|Edit|MultiEdit|Write|NotebookEdit",
        },
        "rm_gate": {"enabled": True, "handler": f"{_SECURITY}.rm_gate.handle", "matcher": "Bash"},
        "testwrite_gate": {
            "enabled": True,
            "handler": f"{_SECURITY}.testwrite_gate.handle",
            "matcher": "Bash|Edit|MultiEdit|Write|NotebookEdit",
        },
        "registry_gate": {
            "enabled": True,
            "handler": f"{_SECURITY}.registry_gate.handle",
            "matcher": "Bash|Edit|MultiEdit|Write|NotebookEdit",
        },
        "trinity_tripwire_snapshot": {
            "enabled": True,
            "handler": f"{_SECURITY}.edit_gate.tripwire_snapshot",
            "matcher": "Bash",
        },
    },
    "PostToolUse": {
        "trinity_tripwire": {"enabled": True, "handler": f"{_SECURITY}.edit_gate.tripwire", "matcher": "Bash"},
    },
    "SubagentStop": {
        "subagent_stop_gate": {
            "enabled": True,
            "handler": f"{_SECURITY}.subagent_gate.handle",
            "matcher": "",
            "timeout": 60,
        },
    },
    "_source": "builtin",
}


def is_fail_closed(handler: str) -> bool:
    """True when a failure of *handler* must refuse what it guards."""
    return handler in FAIL_CLOSED


def broken_gate_reason(hook_name: str, handler: str, why: str) -> str:
    """The one fixed text a broken fail-closed gate answers with."""
    return BROKEN_GATE.format(gate=hook_name, why=why, guards=FAIL_CLOSED.get(handler, "its tool calls"))


def builtin_config() -> dict:
    """The gate set in code: what runs when no AIPass config can be read. A fresh copy per call."""
    return copy.deepcopy(_BUILTIN)


def guarded_tools() -> frozenset[str]:
    """Every tool a built-in PreToolUse gate guards — what the provider's PreToolUse matcher must reach (R7).

    Read off the gate set's own matchers, so a gate that starts guarding a new
    tool names it here without a second list to keep in step.
    """
    tools: set[str] = set()
    for entry in _BUILTIN.get("PreToolUse", {}).values():
        if isinstance(entry, dict) and entry.get("handler") in FAIL_CLOSED:
            tools.update(name for name in str(entry.get("matcher", "")).split("|") if name)
    return frozenset(tools)


def gate_config(config: dict) -> dict:
    """The gate entries of *config*, every event, as a config of their own (a fresh copy).

    Returns:
        ``{"hooks_enabled": True, <event>: {<name>: <entry>}}`` holding only the
        entries whose handler is a gate. Empty of events when *config* holds none.
    """
    out: dict = {"hooks_enabled": True}
    for event, entries in config.items():
        if not isinstance(entries, dict):
            continue
        gates = {
            name: copy.deepcopy(entry)
            for name, entry in entries.items()
            if isinstance(entry, dict) and entry.get("handler") in GATE_HANDLERS
        }
        if gates:
            out[event] = gates
    return out


def has_gates(config: dict) -> bool:
    """True when *config* carries at least one gate entry."""
    return any(isinstance(v, dict) for k, v in gate_config(config).items() if k != "hooks_enabled")


def enforce(config: dict, gate_set: dict) -> dict:
    """*config* with every gate of *gate_set* forced on over it, and the master switch on.

    For a project config that may not switch the AIPass gates off. A project
    entry under a gate's name is replaced by the gate's own entry.
    """
    out = copy.deepcopy(config)
    out["hooks_enabled"] = True
    for event, entries in gate_set.items():
        if event == "hooks_enabled" or not isinstance(entries, dict):
            continue
        target = out.get(event)
        if not isinstance(target, dict):
            target = {}
            out[event] = target
        for name, entry in entries.items():
            target[name] = copy.deepcopy(entry)
    return out
