# =================== AIPass ====================
# Name: hook_test.py
# Version: 1.5.0
# Description: Portable hook test runner — every hook with mock data; provider parity and smoke with real sessions
# Branch: hooks
# Layer: apps/modules
# Created: 2026-07-10
# Modified: 2026-10-28
# =============================================

"""Portable hook test runner.

Every fire aims at a throwaway branch skeleton (hook_data cwd, process cwd and AIPASS_HOME all overridden),
so no run touches the real branch's memory.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

from rich.table import Table

from aipass.hooks.apps.modules import engine
from aipass.hooks.apps.modules.engine import dispatch
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.config.loader import aipass_home, config_unavailable_reason, find_project_config
from aipass.hooks.apps.handlers.config.trust_registry import read_registry
from aipass.hooks.apps.handlers.json import files as json_files
from aipass.hooks.apps.handlers.module_root import module_file
from aipass.hooks.apps.handlers.parity import runner, smoke
from aipass.hooks.apps.modules.write_ownership import project_of
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, err_console

CONSOLE = err_console

HELP_COMMANDS = [
    ("test [--verbose]", "Fire every hook with mock data and report results"),
    ("parity [--branch @x] [--lane A,..] [--json]", "Same prompts headless on Claude and Codex, hook by hook"),
    ("smoke [--provider ..] [--branch @x] [--json]", "One live turn per provider: pass, fail or skip, and why"),
]

REPORTS_DIR = module_file(__file__).parents[2] / "artifacts" / "reports"

_SYNTHETIC_PATH = os.path.join(tempfile.gettempdir(), "hook_test_synthetic.txt")

# Handlers resolve CLAUDE_CODE_SESSION_ID env-first: without an override a mock PreCompact
# arms the real session's regroup backstop.
_MOCK_SESSION_ID = "hook-test-mock"

# Read at the mutation itself by handlers that write another citizen's tree (rollover,
# auto_process), which no environment seam confines.
PROBE_ENV_VAR = "AIPASS_HOOK_PROBE"

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

    Never under src/aipass, so a handler walking upward out of it finds nothing rather than the real fleet.
    """
    branch = destination / real_branch.name
    trinity = branch / ".trinity"
    json_files.make_directory(trinity)

    for name in _SKELETON_MEMORY_FILES:
        source = real_branch / ".trinity" / name
        if source.is_file():
            shutil.copy2(source, trinity / name)

    return branch


def _dispatch_seen(event_type: str, stdin_data: str, config: dict) -> tuple[str, int, list[dict]]:
    """engine.dispatch, plus each handler's own result: past a crashed injector the event still exits 0."""
    seen: list[dict] = []
    run_handler, run_hook = engine._run_handler, engine._run_hook
    engine._run_handler = lambda *a, **k: seen.append(run_handler(*a, **k)) or seen[-1]
    engine._run_hook = lambda *a, **k: seen.append(run_hook(*a, **k)) or seen[-1]
    try:
        output, exit_code = dispatch(event_type, stdin_data, config)
    finally:
        engine._run_handler, engine._run_hook = run_handler, run_hook
    return output, exit_code, seen


def _test_single_hook(event_type: str, hook_name: str, hook_def: dict, stdin_data: str, verbose: bool) -> dict:
    """Dispatch one hook and return its result dict."""
    single_config = {"hooks_enabled": True, event_type: {hook_name: hook_def}}
    enabled = hook_def.get("enabled", True)

    start = time.monotonic()
    try:
        output, exit_code, seen = _dispatch_seen(event_type, stdin_data, single_config)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        own = seen[-1] if seen else {}
        crashed = enabled and exit_code != 2 and own.get("exit_code") == -1
        if crashed:
            error = str(own.get("stderr", ""))[:200]
            return {
                "hook": hook_name,
                "status": "crashed",
                "elapsed_ms": elapsed_ms,
                "exit_code": exit_code,
                "error": error,
            }

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

    Config discovery happens before the cwd moves: the skeleton has no hooks.json.
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
        # cwd first: a caller left standing in a deleted directory is the worst outcome.
        os.chdir(real_cwd)
        _restore_env("CLAUDE_CODE_SESSION_ID", prior_session)
        _restore_env("AIPASS_HOME", prior_home)
        _restore_env(PROBE_ENV_VAR, prior_probe)
        shutil.rmtree(workspace, ignore_errors=True)

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


def resolve_branch(target: str) -> Path | None:
    """A path, or @name looked up in AIPass's registry, then in each trusted project's."""
    if not target.startswith("@"):
        path = Path(target).expanduser()
        return path.resolve() if path.is_dir() else None
    name = target[1:].lower()
    for root in [aipass_home(), *(Path(p) for p in read_registry().get("projects", {}))]:
        project = project_of(root) if root else None
        for row in (project.branches or ()) if project else ():
            if row.name == name:
                return row.path
    return None


def _other_branch(branch: Path) -> Path:
    """A sibling branch in the same project: lane C's cross-branch write target."""
    project = project_of(branch)
    for row in (project.branches or ()) if project else ():
        if row.path != branch:
            return row.path
    return branch.parent / "parity_other_branch"


def run_parity(branch: Path, lanes: list[str], providers: list[str]) -> dict:
    """Each lane's prompt once per provider (a shared prompt runs once), then compared row by row."""
    notes = [f"lane A probe mail: {runner.send_probe_mail(branch)}"] if "A" in lanes else []
    other = _other_branch(branch)
    sessions: dict[tuple[str, str], tuple[str, list[dict], bool]] = {}
    rows = []
    for lane in lanes:
        prompt = runner.lane_prompt(lane, branch, other)
        for provider in providers:
            if (provider, prompt) not in sessions:
                sessions[(provider, prompt)] = runner.run_session(provider, prompt, branch)
                notes.append(f"lane {lane} {provider}: session {sessions[(provider, prompt)][0] or 'none'}")
        for row in (r for r in runner.ROWS if r.lane == lane):
            readings = {}
            for provider in providers:
                session_id, entries, moved = sessions[(provider, prompt)]
                readings[provider] = runner.observe(row, entries, moved) if session_id and entries else runner.NO_DATA
            rows.append({**row.__dict__, "readings": readings, "verdict": runner.verdict(row, readings)})
    ok = not [r for r in rows if r["verdict"] in runner.FAILING]
    return {"branch": str(branch), "providers": providers, "rows": rows, "notes": notes, "ok": ok}


def print_parity(results: dict) -> None:
    """One table: row, one column per provider run, verdict; accepted differences carry their reason."""
    table = Table(title=f"parity @ {results['branch']}")
    for column in ("Lane", "Row", *results["providers"], "Verdict"):
        table.add_column(column)
    styles = {runner.SAME: "green", runner.ACCEPTED: "yellow"}
    for row in results["rows"]:
        mark = f"{row['verdict']} ({row['accepted']})" if row["verdict"] == runner.ACCEPTED else row["verdict"]
        cells = [row["readings"][p] for p in results["providers"]]
        style = styles.get(row["verdict"], "bold red")
        table.add_row(row["lane"], row["label"], *cells, f"[{style}]{mark}[/{style}]")
    CONSOLE.print(table)
    for note in results["notes"]:
        CONSOLE.print(f"[dim]{note}[/dim]")


def _parity_command(args: list) -> bool:
    """drone @hooks parity: exit 1 on a real difference, so a merge train can gate on it."""
    if wants_help(args):
        CONSOLE.print("[bold cyan]parity[/bold cyan] — the same scripted prompts on Claude, Codex, OpenCode, compared")
        CONSOLE.print(
            "  drone @hooks parity [--branch @canary|<path>] [--lane A,B,C,D,E,F] [--provider claude,codex,opencode]"
        )
        CONSOLE.print(
            "  --provider defaults to claude,codex; opencode loads its plugin from OPENCODE_CONFIG_DIR when set"
        )
        CONSOLE.print("  --json   also write artifacts/reports/parity_<date>.json")
        CONSOLE.print("Lane J is A,B,C with --branch at an external project's citizen. Exit 1 on DIFFERENT or no data.")
        return True
    parser = argparse.ArgumentParser(prog="drone @hooks parity", add_help=False)
    parser.add_argument("--branch", default="@canary")
    parser.add_argument("--lane", default=",".join(runner.LANES))
    parser.add_argument("--provider", default=",".join(runner.DEFAULT_PROVIDERS))
    parser.add_argument("--json", action="store_true")
    opts, _unknown = parser.parse_known_args(args)
    branch = resolve_branch(opts.branch)
    lanes = [lane for part in opts.lane.upper().split(",") for lane in (("A", "B", "C") if part == "J" else (part,))]
    providers = [p for p in opts.provider.lower().split(",") if p in runner.PROVIDERS]
    bad = [lane for lane in lanes if lane not in runner.LANES]
    if branch is None or bad or not providers:
        CONSOLE.print(f"[red]parity: no branch {opts.branch!r}, unknown lane {bad}, or no provider[/red]")
        sys.exit(1)
    results = run_parity(branch, list(dict.fromkeys(lanes)), providers)
    print_parity(results)
    if opts.json:
        json_files.make_directory(REPORTS_DIR)
        report = REPORTS_DIR / f"parity_{date.today().isoformat()}.json"
        json_files.write_json_file(report, results)
        CONSOLE.print(f"[dim]written: {report}[/dim]")
    if not results["ok"]:
        sys.exit(1)
    return True


def _smoke_line(result: smoke.SmokeResult) -> str:
    if result.status == smoke.PASS:
        return f"{result.provider} pass ({result.elapsed_ms / 1000:.1f} s, {result.session_id})"
    return f"{result.provider} {result.status} ({result.why})"


def _smoke_command(args: list) -> bool:
    """drone @hooks smoke: one isolated live turn per provider; exit 1 on any fail, 0 on pass or skip."""
    if wants_help(args):
        CONSOLE.print("[bold cyan]smoke[/bold cyan] — one 'say ok' turn per provider, its hook nonce read back")
        CONSOLE.print("  drone @hooks smoke [--provider claude,codex,opencode] [--branch @x|<path>] [--json]")
        CONSOLE.print("  --branch defaults to the current directory; --model provider=model, comma-separated")
        CONSOLE.print("  pass: the temporal hook's ack is in the provider's own record of that session")
        CONSOLE.print("  skip: not installed, not logged in, rate or free limit, plugin not installed, no readback")
        CONSOLE.print("  --json   one JSON array on stdout. Exit 1 on any fail.")
        return True
    parser = argparse.ArgumentParser(prog="drone @hooks smoke", add_help=False)
    parser.add_argument("--branch", default=".")
    parser.add_argument("--provider", default=",".join(runner.PROVIDERS))
    parser.add_argument("--model", default="")
    parser.add_argument("--json", action="store_true")
    opts, _unknown = parser.parse_known_args(args)
    branch = resolve_branch(opts.branch)
    providers = list(dict.fromkeys(p for p in opts.provider.lower().split(",") if p in runner.PROVIDERS))
    models = dict(pair.split("=", 1) for pair in opts.model.split(",") if "=" in pair)
    if branch is None or not providers:
        CONSOLE.print(f"[red]smoke: no branch {opts.branch!r}, or no provider[/red]")
        sys.exit(1)
    results = [smoke.smoke(p, branch, models.get(p, "")) for p in providers]
    if opts.json:
        console.print_json(json.dumps([r.__dict__ for r in results]))
    else:
        console.print("smoke: " + " · ".join(_smoke_line(r) for r in results), markup=False, highlight=False)
    if any(r.status == smoke.FAIL for r in results):
        sys.exit(1)
    return True


def print_introspection() -> None:
    """Print module introspection for drone discovery."""
    CONSOLE.print("[cyan]hook_test[/cyan] — Portable hook test runner")
    CONSOLE.print("  Fire every hook with mock data and report what fired.")


def handle_command(command: str, args: list) -> bool:
    """Route the 'test', 'parity' and 'smoke' commands."""
    if command == "parity":
        return _parity_command(args)
    if command == "smoke":
        return _smoke_command(args)
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
