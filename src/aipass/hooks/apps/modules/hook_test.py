# =================== AIPass ====================
# Name: hook_test.py
# Version: 1.1.0
# Description: Portable hook test runner — fires every hook with mock data
# Branch: hooks
# Layer: apps/modules
# Created: 2026-07-10
# Modified: 2026-09-06
# =============================================

"""Portable hook test runner.

Fires every hook from a project's .aipass/hooks.json with mock data
and reports what fired, what blocked, and what crashed. Runnable from
any project directory.

A probe that mutates what it measures is not a probe. Every fire is aimed at a
throwaway branch skeleton in tempdir, so no run touches the real branch's
memory. Three inputs decide which branch a handler acts on, and the runner
overrides all three (:func:`run_test`, skeleton from :func:`_build_skeleton`):

* ``hook_data["cwd"]`` — honoured by pre_compact_prep, compact, the gates.
* the process cwd — read directly by rollover, persistent_alert, email, loader.
* ``AIPASS_HOME`` — rollover's preferred repo-root source.

Two handlers reach past all three into another citizen's tree and get an
explicit refusal instead (``AIPASS_HOOK_PROBE``, checked at their mutation
point, never at their entry): rollover shells out to a fleet-wide memory trim,
and auto_process spawns @memory's real background worker. @memory resolves
neither from cwd nor from AIPASS_HOME — measured 2026-09-06, the name appears
nowhere in its tree — so no environment seam can confine either one.

Usage:
    drone @hooks test [--verbose]
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from aipass.hooks.apps.modules.engine import dispatch
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.config.loader import config_unavailable_reason, find_project_config
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import err_console

CONSOLE = err_console

HELP_COMMANDS = [
    ("test [--verbose]", "Fire every hook with mock data and report results"),
]

_SYNTHETIC_PATH = os.path.join(tempfile.gettempdir(), "hook_test_synthetic.txt")

# Session identity for mock fires. Handlers resolve CLAUDE_CODE_SESSION_ID env-first,
# and a live session's ID leaks into this subprocess — without an override, mock
# PreCompact fires arm the REAL session's regroup backstop (mid-turn RE-GROUND
# injection with no actual compaction).
_MOCK_SESSION_ID = "hook-test-mock"

# Set for the duration of a probe run. Handlers whose real work mutates ANOTHER
# citizen's tree read this at the mutation itself, so everything up to that
# point still executes for real. Two sites today: rollover (fleet-wide memory
# trim) and auto_process (spawns @memory's worker).
PROBE_ENV_VAR = "AIPASS_HOOK_PROBE"

# Copied into the skeleton so handlers get realistic input. passport.json is
# read for identity and observations.json for caps; local.json is the file
# pre_compact_prep stamps, and stamping the COPY is the point.
_SKELETON_MEMORY_FILES = ("local.json", "observations.json", "passport.json")

MOCK_EVENTS = {
    "UserPromptSubmit": {
        "type": "UserPromptSubmit",
        "prompt": "[hook test] synthetic prompt for test runner",
    },
    "PreToolUse": {
        "tool_name": "Read",
        "tool_input": {"file_path": _SYNTHETIC_PATH},
    },
    "PostToolUse": {
        "tool_name": "Read",
        "tool_input": {"file_path": _SYNTHETIC_PATH},
        "tool_output": "synthetic output",
    },
    "SubagentStop": {
        "agent_type": "general-purpose",
        "type": "SubagentStop",
    },
    "Stop": {
        "type": "Stop",
    },
    "Notification": {
        "type": "Notification",
        "message": "[hook test] synthetic notification",
    },
    "PreCompact": {
        "compact_type": "PreCompact",
    },
    "SessionStart": {
        "type": "SessionStart",
    },
}


def _restore_env(name: str, prior: str | None) -> None:
    """Put one environment variable back exactly as it was — unset stays unset."""
    if prior is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = prior


def _build_skeleton(real_branch: Path, destination: Path) -> Path:
    """Build a throwaway branch under ``destination`` and return it.

    ``find_branch_dir`` walks a path for ``src/aipass/<name>`` and otherwise
    accepts any directory holding a ``.trinity/``. The skeleton takes the second
    door on purpose: a tempdir is never under ``src/aipass``, so a handler that
    walks upward out of it finds nothing rather than finding the real fleet.

    No ``AIPASS_REGISTRY.json`` is written. rollover treats the repo root as the
    thing it hands to a subprocess, and a temp root would not confine that
    subprocess anyway — the refusal at the mutation is what does that.
    """
    branch = destination / real_branch.name
    trinity = branch / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)

    for name in _SKELETON_MEMORY_FILES:
        source = real_branch / ".trinity" / name
        if source.is_file():
            shutil.copy2(source, trinity / name)

    return branch


def _test_single_hook(event_type: str, hook_name: str, hook_def: dict, stdin_data: str, verbose: bool) -> dict:
    """Dispatch one hook and return its result dict."""
    single_config = {"hooks_enabled": True, event_type: {hook_name: hook_def}}
    enabled = hook_def.get("enabled", True)

    start = time.monotonic()
    try:
        output, exit_code = dispatch(event_type, stdin_data, single_config)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)

        if not enabled:
            status = "disabled"
        elif exit_code == 2:
            status = "blocked"
        elif output:
            status = "fired"
        else:
            status = "fired (empty output)"

        return {
            "hook": hook_name,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "exit_code": exit_code,
            "output_len": len(output),
            "output_preview": output[:200] if verbose else "",
        }
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        logger.error("[HOOKS:test] %s.%s crashed: %s", event_type, hook_name, exc)
        return {
            "hook": hook_name,
            "status": "crashed",
            "elapsed_ms": elapsed_ms,
            "error": str(exc)[:200],
        }


def run_test(verbose: bool = False) -> dict:
    """Fire every hook with mock data against a throwaway branch, return results.

    Config discovery happens BEFORE the cwd moves — the real project's
    hooks.json is what we are probing, and the skeleton has none.
    """
    config = find_project_config()
    if config is None:
        return {"error": config_unavailable_reason()}

    if not config.get("hooks_enabled", True):
        return {"error": "hooks_enabled is false in project config."}

    results = {}

    real_cwd = Path.cwd()
    prior_session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    prior_home = os.environ.get("AIPASS_HOME")
    prior_probe = os.environ.get(PROBE_ENV_VAR)
    os.environ["CLAUDE_CODE_SESSION_ID"] = _MOCK_SESSION_ID
    os.environ[PROBE_ENV_VAR] = "1"

    workspace = tempfile.mkdtemp(prefix="aipass_hook_probe_")
    skeleton = _build_skeleton(real_cwd, Path(workspace))
    os.environ["AIPASS_HOME"] = str(skeleton)
    os.chdir(skeleton)

    try:
        for event_type, event_hooks in config.items():
            if event_type in ("hooks_enabled", "_comment"):
                continue
            if not isinstance(event_hooks, dict):
                continue

            mock_data = dict(MOCK_EVENTS.get(event_type, {"type": event_type}))
            mock_data.setdefault("session_id", _MOCK_SESSION_ID)
            # Handlers that honour a supplied cwd never see the real branch.
            mock_data["cwd"] = str(skeleton)
            stdin_data = json.dumps(mock_data)

            event_results = []
            for hook_name, hook_def in event_hooks.items():
                if not isinstance(hook_def, dict):
                    continue
                if not hook_def.get("handler", "") and not hook_def.get("command", ""):
                    continue
                result = _test_single_hook(event_type, hook_name, hook_def, stdin_data, verbose)
                event_results.append(result)

            if event_results:
                results[event_type] = event_results
    finally:
        # cwd first: a caller left standing in a deleted directory is worse than
        # any of the state below being briefly wrong.
        os.chdir(real_cwd)
        _restore_env("CLAUDE_CODE_SESSION_ID", prior_session)
        _restore_env("AIPASS_HOME", prior_home)
        _restore_env(PROBE_ENV_VAR, prior_probe)
        shutil.rmtree(workspace, ignore_errors=True)
        # The throwaway aipass-cadence-hook-test-mock.json state file is left in
        # tempdir on purpose: fixed name, overwritten per run, OS-cleans on reboot.

    return results


_STATUS_ICONS = {
    "fired": "[green]✓[/green]",
    "fired (empty output)": "[green]✓[/green]",
    "blocked": "[yellow]⊘[/yellow]",
    "disabled": "[dim]○[/dim]",
    "crashed": "[red]✗[/red]",
}

_STATUS_COUNTS = {"fired", "fired (empty output)", "blocked", "disabled", "crashed"}


def print_results(results: dict, verbose: bool = False) -> None:
    """Render test results to console."""
    if "error" in results:
        CONSOLE.print(f"[red]{results['error']}[/red]")
        return

    counts = {"fired": 0, "blocked": 0, "disabled": 0, "crashed": 0}

    for event_type, hooks in results.items():
        CONSOLE.print(f"\n[bold cyan]{event_type}[/bold cyan]")
        for h in hooks:
            status = h["status"]
            name = h["hook"]
            ms = h.get("elapsed_ms", 0)
            icon = _STATUS_ICONS.get(status, "[dim]?[/dim]")

            if status in ("fired", "fired (empty output)"):
                counts["fired"] += 1
            elif status in counts:
                counts[status] += 1

            CONSOLE.print(f"  {icon} {name:30} {status:20} {ms:>6.0f}ms")
            if verbose and h.get("output_preview"):
                CONSOLE.print(f"      [dim]{h['output_preview']}[/dim]")
            if h.get("error"):
                CONSOLE.print(f"      [red]{h['error']}[/red]")

    CONSOLE.print()
    CONSOLE.print(
        f"[bold]Summary:[/bold] {counts['fired']} fired, "
        f"{counts['blocked']} blocked, {counts['disabled']} disabled, "
        f"{counts['crashed']} crashed"
    )


def print_introspection() -> None:
    """Print module introspection for drone discovery."""
    CONSOLE.print("[cyan]hook_test[/cyan] — Portable hook test runner")
    CONSOLE.print("  Fire every hook with mock data and report what fired.")


def handle_command(command: str, args: list) -> bool:
    """Route 'test' command."""
    if command != "test":
        return False

    if not args:
        print_introspection()
        return True

    if wants_help(args):
        print_introspection()
        return True

    verbose = "--verbose" in args or "-v" in args

    CONSOLE.print("[bold cyan]HOOKS Test Runner[/bold cyan]")
    CONSOLE.print("[dim]Firing every hook with mock data...[/dim]")

    results = run_test(verbose=verbose)
    print_results(results, verbose=verbose)
    return True
