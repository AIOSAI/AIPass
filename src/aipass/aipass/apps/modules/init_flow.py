# =================== AIPass ====================
# Name: init_flow.py
# Description: 12-stage guided first-run setup — aipass init command
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
aipass init — guided first-run setup

12 resumable stages. State persists to .aipass/init_progress.json.
Ctrl-C at any stage resumes next time from that stage.

Usage:
    aipass init                          # show progress / introspection
    aipass init run                      # interactive
    aipass init run --non-interactive    # CI/headless, all defaults
    aipass init run --name Patrick --cli claude
    aipass init run --dry-run            # walk all 12 stages, no destructive ops
                                         #   - skips drone @spawn create (stage 8)
                                         #   - skips tmux/wt handoff (stage 11)
                                         #   - does NOT write .aipass/init_progress.json
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from aipass.cli.apps.modules import console, warning
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.system_detect.system_detector import (
    detect_cpu,
    detect_docker,
    detect_git,
    detect_install_method,
    detect_os,
    detect_python,
    detect_ram,
    detect_shell,
    detect_tmux,
    detect_wt,
)

try:
    import questionary as _questionary  # type: ignore[import-untyped]

    HAS_QUESTIONARY = True
except ImportError as _qe:
    logger.info("[init_flow] questionary not installed, using numbered-list menus: %s", _qe)
    _questionary = None  # type: ignore[assignment]
    HAS_QUESTIONARY = False

COMMAND = "init"
TOTAL_STAGES = 12

_BRANCH_ROOT = Path(__file__).resolve().parents[2]


def _get_local_json_path() -> Path:
    """Resolve init progress file from CWD (user's project)."""
    return Path.cwd() / ".aipass" / "init_progress.json"


def _resolve_package_dir() -> str | None:
    """Find the src/<package>/ path in CWD project.

    Looks for a directory under src/ that contains an __init__.py.
    Returns the relative path like 'src/my_project' or None if not found.
    """
    src_dir = Path.cwd() / "src"
    if not src_dir.is_dir():
        return None
    for child in src_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            return f"src/{child.name}"
    return None


CLI_CHOICES = ["claude", "codex", "gemini", "other"]
# Flag variants for CLI launch — these are user-facing config values, not code-level flags
FLAG_CHOICES = ["default", "skip-permissions"]
STYLE_CHOICES = ["building-my-own-project", "improving-aipass", "just-exploring"]


# --- LOCAL JSON HELPERS ---
def _read_local_json() -> dict:
    """Read init progress file, returning empty dict on failure."""
    local_json = _get_local_json_path()
    if not local_json.exists() or local_json.stat().st_size == 0:
        return {}
    try:
        with open(local_json, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[init_flow] local.json read error: %s", exc)
        return {}


def _fire_file_deleted(path: str) -> None:
    """Fire trigger event for temp file deletion, ignoring ImportError."""
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire("file_deleted", path=path, reason="write_failure_cleanup")
    except ImportError as exc:
        logger.warning("[init_flow] trigger unavailable for file_deleted event: %s", exc)


def _write_local_json(data: dict) -> None:
    """Write init progress file atomically via temp-file rename."""
    local_json = _get_local_json_path()
    dir_ = local_json.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_), prefix=".local_", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, local_json)
    except OSError as exc:
        logger.warning("[init_flow] write failed, cleaning up %s: %s", tmp_path, exc)
        _fire_file_deleted(tmp_path)
        try:
            os.unlink(tmp_path)
        except OSError as _ue:
            logger.warning("[init_flow] temp file cleanup failed: %s", _ue)
        raise


def _get_setup_progress() -> dict:
    """Return setup_progress section from local.json."""
    data = _read_local_json()
    return data.get("setup_progress", {"last_completed_stage": 0, "stages": {}})


def _get_last_completed_stage() -> int:
    """Return the last completed stage number (0 if fresh)."""
    return _get_setup_progress().get("last_completed_stage", 0)


def _save_stage(stage: int, stage_data: dict | None = None, dry_run: bool = False) -> None:
    """Persist stage completion to local.json setup_progress.

    When dry_run=True the call is a no-op (pure read flow).
    """
    if dry_run:
        logger.info("[init_flow] dry-run: skipping _save_stage(%d)", stage)
        return
    data = _read_local_json()
    progress = data.get("setup_progress", {"last_completed_stage": 0, "stages": {}})
    progress["last_completed_stage"] = stage
    progress["stages"][str(stage)] = {
        "status": "done",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(stage_data or {}),
    }
    data["setup_progress"] = progress
    _write_local_json(data)


def _prompt(msg: str, default: str = "") -> str:
    """Simple input prompt with optional default."""
    display = f"{msg} [{default}]: " if default else f"{msg}: "
    try:
        val = input(display).strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        raise KeyboardInterrupt


def _choose(msg: str, choices: List[str], default: str | None = None) -> str:
    """Arrow-key menu via questionary, or numbered-list fallback."""
    if HAS_QUESTIONARY and _questionary is not None:
        try:
            result = _questionary.select(msg, choices=choices, default=default).ask()
            if result is None:
                raise KeyboardInterrupt
            return result
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            logger.warning("[init_flow] questionary.select failed, using fallback: %s", exc)

    console.print(f"\n{msg}")
    for i, choice in enumerate(choices, 1):
        marker = " [dim](default)[/dim]" if choice == default else ""
        console.print(f"  {i}. {choice}{marker}")
    default_idx = str(choices.index(default) + 1) if default in choices else "1"
    while True:
        raw = _prompt("Choice (number)", default_idx)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError as exc:
            logger.info("[init_flow] invalid menu input %r: %s", raw, exc)
        console.print("[red]Invalid choice.[/red]")


# --- STAGE FUNCTIONS ---
def stage_1_welcome(dry_run: bool = False) -> Dict[str, Any]:
    """Print welcome banner and greeting."""
    console.print()
    console.print("[bold cyan]  █████╗ ██╗██████╗  █████╗ ███████╗███████╗[/bold cyan]")
    console.print("[bold cyan] ██╔══██╗██║██╔══██╗██╔══██╗██╔════╝██╔════╝[/bold cyan]")
    console.print("[bold cyan] ███████║██║██████╔╝███████║███████╗███████╗ [/bold cyan]")
    console.print("[bold cyan] ██╔══██║██║██╔═══╝ ██╔══██║╚════██║╚════██║[/bold cyan]")
    console.print("[bold cyan] ██║  ██║██║██║     ██║  ██║███████║███████║[/bold cyan]")
    console.print("[bold cyan] ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝[/bold cyan]")
    console.print()
    console.print("[bold]Hi, I am AIPass — your AI passport and front door to the ecosystem.[/bold]")
    console.print("Let's walk through setup together. This takes about 5 minutes.")
    if shutil.which("drone"):
        console.print()
        console.print(
            "[dim]Tip: Open another terminal and run [cyan]drone @prax monitor run[/cyan] to watch activity live.[/dim]"
        )
    if dry_run:
        console.print("[yellow]\\[dry-run][/yellow] No state will be written, no subprocesses launched.")
    console.print()
    console.print("[bold cyan]Step 1/12[/bold cyan] — Welcome")
    _save_stage(1, dry_run=dry_run)
    return {}


def stage_2_system_detect(non_interactive: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Detect OS, Python, shell, RAM, CPU, install method, and optional tools."""
    console.print()
    console.print("[bold cyan]Step 2/12[/bold cyan] — System detection")

    from rich.table import Table

    py = detect_python()
    git = detect_git()
    sh = detect_shell()
    os_info = detect_os()
    ram = detect_ram()
    cpu = detect_cpu()
    install = detect_install_method()
    has_tmux = detect_tmux()
    has_wt = detect_wt()
    has_docker = detect_docker()

    table = Table(show_header=False, box=None)
    table.add_column("key", style="cyan")
    table.add_column("value")
    table.add_row("OS", f"{os_info['os_name']} {os_info['release']}")
    table.add_row("Python", py["version"])
    table.add_row("shell", sh["name"])
    table.add_row("RAM", f"{ram['total_gb']} GB")
    table.add_row("CPU", f"{cpu['count']} cores")
    table.add_row("install", install)
    table.add_row("git", git["version"] if git["found"] else "not found")
    table.add_row("tmux", "yes" if has_tmux else "no")
    if sys.platform == "win32":
        table.add_row("wt.exe", "yes" if has_wt else "no")
    table.add_row("docker", "yes" if has_docker else "no")
    console.print(table)

    console.print()
    console.print(f"You are on [cyan]{os_info['os_name']}[/cyan] with Python [cyan]{py['version']}[/cyan].")
    install_labels = {"dev": "development (editable source)", "pip": "pip", "clone": "git clone", "unknown": "unknown"}
    console.print(f"Install type: [cyan]{install_labels.get(install, install)}[/cyan]")

    system_data: Dict[str, Any] = {
        "os": os_info["os_name"],
        "python": py["version"],
        "shell": sh["name"],
        "ram_gb": ram["total_gb"],
        "install": install,
        "has_docker": has_docker,
        "has_tmux": has_tmux,
    }
    _save_stage(2, system_data, dry_run=dry_run)
    return system_data


def stage_3_doctor(non_interactive: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Run aipass doctor health checks inline."""
    console.print()
    console.print("[bold cyan]Step 3/12[/bold cyan] — System health check")

    error_count = 0
    provider_gaps: Dict[str, Any] = {}
    try:
        from aipass.aipass.apps.modules import doctor

        error_count = doctor.run_doctor(interactive=not non_interactive)
        try:
            for r in doctor._check_provider_manifest():
                if r.glyph != doctor.GLYPH_PASS:
                    provider_gaps[r.label] = r.detail
        except Exception as exc:
            logger.warning("[init_flow] provider manifest check failed: %s", exc)
    except Exception as exc:
        logger.warning("[init_flow] doctor run failed: %s", exc)
        warning(f"Doctor check skipped: {exc}")

    if error_count > 0:
        warning(f"{error_count} issue(s) found above — review when convenient.")
    else:
        console.print("[green]✓[/green] Health check passed.")

    _save_stage(3, {"doctor_errors": error_count}, dry_run=dry_run)
    return {"doctor_errors": error_count, "provider_gaps": provider_gaps}


def stage_4_user_profile(
    non_interactive: bool = False,
    name_override: str | None = None,
    system_data: dict | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Collect user name and OS, save to profile."""
    console.print()
    console.print("[bold cyan]Step 4/12[/bold cyan] — User profile")

    from aipass.aipass.apps.modules import profile as profile_mod

    if name_override:
        name = name_override
    elif non_interactive:
        name = "User"
    else:
        name = _prompt("What's your name?", "User")

    os_name = (system_data or {}).get("os") or detect_os()["os_name"]

    existing = profile_mod.get_user_profile()
    existing.update(
        {
            "name": name,
            "os": os_name,
            "shell": (system_data or {}).get("shell"),
            "install_method": (system_data or {}).get("install"),
            "first_seen": existing.get("first_seen") or datetime.now(timezone.utc).isoformat(),
        }
    )
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would save profile: {existing}")
    else:
        profile_mod.save_profile(existing)

    console.print(f"[green]✓[/green] Hello, {name}!")
    _save_stage(4, {"name": name}, dry_run=dry_run)
    return {"name": name}


def stage_5_style_questions(
    non_interactive: bool = False,
    style_override: str | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Ask what the user wants to do — routes tone of later stages."""
    console.print()
    console.print("[bold cyan]Step 5/12[/bold cyan] — What brings you here?")

    if style_override and style_override in STYLE_CHOICES:
        style = style_override
    elif non_interactive:
        style = STYLE_CHOICES[0]
    else:
        style = _choose("What are you looking to do?", STYLE_CHOICES, default=STYLE_CHOICES[0])

    console.print(f"[green]✓[/green] Got it: {style}")
    _save_stage(5, {"style": style}, dry_run=dry_run)
    return {"style": style}


def stage_6_tool_choice(
    non_interactive: bool = False,
    cli_override: str | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Choose CLI tool and launch flag variant."""
    console.print()
    console.print("[bold cyan]Step 6/12[/bold cyan] — CLI tool choice")

    if cli_override and cli_override in CLI_CHOICES:
        cli_choice = cli_override
    elif non_interactive:
        cli_choice = "claude"
    else:
        cli_choice = _choose("Which CLI tool do you use?", CLI_CHOICES, default="claude")

    if non_interactive:
        flag_variant = "default"
    else:
        flag_variant = _choose(
            f"How should I launch {cli_choice}?",
            FLAG_CHOICES,
            default="default",
        )

    console.print(f"[green]✓[/green] {cli_choice} ({flag_variant})")
    _save_stage(6, {"cli": cli_choice, "flag_variant": flag_variant}, dry_run=dry_run)

    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would save preferred_cli={cli_choice} to profile")
    else:
        try:
            from aipass.aipass.apps.modules import profile as profile_mod

            p = profile_mod.get_user_profile()
            p["preferred_cli"] = cli_choice
            profile_mod.save_profile(p)
        except Exception as exc:
            logger.warning("[init_flow] could not persist cli to profile: %s", exc)

    return {"cli": cli_choice, "flag_variant": flag_variant}


def stage_7_docker_offer(
    non_interactive: bool = False,
    no_docker: bool = False,
    has_docker: bool | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Offer Docker sandbox test if Docker is detected."""
    console.print()
    console.print("[bold cyan]Step 7/12[/bold cyan] — Docker")

    if has_docker is None:
        has_docker = detect_docker()

    if not has_docker or no_docker or non_interactive:
        reason = "not detected" if not has_docker else ("--no-docker" if no_docker else "non-interactive")
        console.print(f"[dim]Docker offer skipped ({reason}).[/dim]")
        _save_stage(7, {"docker": "skipped"}, dry_run=dry_run)
        return {"docker": "skipped"}

    raw = _prompt("Test in a Docker sandbox? [y/N]", "N")
    use_docker = raw.lower() in ("y", "yes")
    result = "yes" if use_docker else "no"
    console.print(f"[green]✓[/green] Docker: {result}")
    _save_stage(7, {"docker": result}, dry_run=dry_run)
    return {"docker": result}


def stage_8_first_agent(non_interactive: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Create the user's first AI agent via drone @spawn."""
    console.print()
    console.print("[bold cyan]Step 8/12[/bold cyan] — Create your first agent")
    console.print("Let's create your first AI agent (citizen).")

    if non_interactive:
        agent_name = "my-agent"
    else:
        agent_name = _prompt("Agent name (letters, hyphens, no spaces)", "my-agent") or "my-agent"

    package_dir = _resolve_package_dir()
    if package_dir:
        agent_path = f"{package_dir}/{agent_name}"
    else:
        agent_path = f"src/{agent_name}"
    console.print(f"Running: [cyan]drone @spawn create {agent_path}[/cyan]")

    success = False
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would run: drone @spawn create {agent_path}")
        success = True
    else:
        try:
            proc = subprocess.run(["drone", "@spawn", "create", agent_path], timeout=60)
            success = proc.returncode == 0
        except FileNotFoundError as exc:
            logger.warning("[init_flow] drone not found in stage 8: %s", exc)
            warning("drone not found — skipping agent creation.")
        except subprocess.TimeoutExpired as exc:
            logger.warning("[init_flow] spawn timed out in stage 8: %s", exc)
            warning("spawn timed out — agent may still be created.")

    if success:
        console.print(f"[green]✓[/green] Agent created at {agent_path}")

    _save_stage(8, {"agent_name": agent_name, "agent_path": agent_path, "success": success}, dry_run=dry_run)
    return {"agent_name": agent_name, "agent_path": agent_path}


def stage_9_ping_sweep(non_interactive: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Ping all registered branches via test-convention emails."""
    console.print()
    console.print("[bold cyan]Step 9/12[/bold cyan] — Pinging agents")

    from aipass.aipass.apps.handlers import ping_sweep

    branches = ping_sweep._discover_branches()
    if not branches:
        console.print("[dim]  No branches registered yet — skipping ping sweep.[/dim]")
        _save_stage(9, {"results": {}, "skipped": True}, dry_run=dry_run)
        return {"ping_results": {}}

    # Standalone projects can't ping agents via drone (drone only knows AIPass's registry).
    # Only attempt ping if we're inside the AIPass source tree.
    aipass_registry = _BRANCH_ROOT.parent / "AIPASS_REGISTRY.json"
    if not aipass_registry.exists():
        if len(branches) == 1:
            console.print("[dim]  1 agent registered. Ping skipped — ping is for multi-agent projects.[/dim]")
        else:
            console.print(f"[dim]  Found {len(branches)} agent(s) in this project.[/dim]")
            console.print("[dim]  Ping skipped — agents will be reachable after handoff (next step).[/dim]")
        _save_stage(9, {"results": {}, "skipped_standalone": True}, dry_run=dry_run)
        return {"ping_results": {}}

    console.print(f"[dim]  Found {len(branches)} agent(s). Checking reachability...[/dim]")
    console.print(
        "[dim]  (Agents with a running session will auto-ack; new agents will time out — that's normal.)[/dim]"
    )

    results = ping_sweep.sweep_all_branches(timeout=10)

    for branch, status in results.items():
        if status == "ack":
            glyph = "[green]✓[/green]"
        elif status == "timeout":
            glyph = "[yellow]—[/yellow]"
        else:
            glyph = "[red]✗[/red]"
        label = "reachable" if status == "ack" else "not running" if status == "timeout" else "error"
        console.print(f"  {glyph} @{branch}: {label}")

    summary = ping_sweep.sweep_summary(results)
    console.print(f"  {summary}")
    _save_stage(9, {"results": results}, dry_run=dry_run)
    return {"ping_results": results}


def stage_10_smoke_test(non_interactive: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Verify drone and aipass binaries are on PATH."""
    console.print()
    console.print("[bold cyan]Step 10/12[/bold cyan] — Smoke test")

    drone_bin = shutil.which("drone")
    aipass_bin = shutil.which("aipass")

    if drone_bin:
        console.print(f"[green]✓[/green] drone: {drone_bin}")
    else:
        warning("drone not on PATH — run: pip install -e .")

    if aipass_bin:
        console.print(f"[green]✓[/green] aipass: {aipass_bin}")
    else:
        warning("aipass not on PATH — run: pip install -e .")

    _save_stage(10, {"drone": drone_bin, "aipass": aipass_bin}, dry_run=dry_run)
    return {"drone": drone_bin, "aipass": aipass_bin}


def stage_11_handoff(
    cli_choice: str = "claude",
    flag_variant: str = "default",
    agent_path: str = "src/my-agent",
    non_interactive: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Launch user's chosen CLI in a new session via handoff module."""
    console.print()
    console.print("[bold cyan]Step 11/12[/bold cyan] — Handoff")

    init_prompt = "I just completed aipass init. I am ready to start. What should I do first?"

    console.print()
    console.print("  Your agent is ready. The next step opens an interactive session with it.")
    console.print(f"  [dim]CLI: {cli_choice} | Agent: {agent_path}[/dim]")

    if dry_run:
        from aipass.aipass.apps.handlers.handoff_platform import build_manual_command

        command = build_manual_command(cli_choice, init_prompt, agent_path, flag_variant)
        console.print(f"[yellow]\\[dry-run][/yellow] would launch handoff: {command}")
        launched = False
    elif non_interactive:
        from aipass.aipass.apps.modules import handoff as handoff_mod

        launched = handoff_mod.do_handoff(
            cli=cli_choice,
            prompt=init_prompt,
            cwd=agent_path,
            flag_variant=flag_variant,
        )
        from aipass.aipass.apps.handlers.handoff_platform import build_manual_command

        command = build_manual_command(cli_choice, init_prompt, agent_path, flag_variant)
    else:
        console.print()
        input("  Press Enter to chat with your agent...")
        from aipass.aipass.apps.modules import handoff as handoff_mod

        launched = handoff_mod.do_handoff(
            cli=cli_choice,
            prompt=init_prompt,
            cwd=agent_path,
            flag_variant=flag_variant,
        )
        from aipass.aipass.apps.handlers.handoff_platform import build_manual_command

        command = build_manual_command(cli_choice, init_prompt, agent_path, flag_variant)

    _save_stage(11, {"command": command, "launched": launched}, dry_run=dry_run)
    return {"handoff_command": command, "launched": launched}


def _write_init_report(agent_path: str, accumulated: Dict[str, Any], dry_run: bool = False) -> None:
    """Drop init_report.json into the agent's dropbox."""
    if dry_run or not agent_path:
        return
    dropbox = Path(agent_path) / "dropbox"
    dropbox.mkdir(parents=True, exist_ok=True)
    system_data = {k: accumulated.get(k) for k in ("os", "python", "shell", "ram_gb", "install") if accumulated.get(k)}
    report = {
        "created": datetime.now(timezone.utc).isoformat(),
        "project_name": Path.cwd().name,
        "project_path": str(Path.cwd()),
        "agent_name": accumulated.get("agent_name", Path(agent_path).name.upper()),
        "agent_number": 1,
        "is_orchestrator": True,
        "install_method": accumulated.get("install", "unknown"),
        "cli_choice": accumulated.get("cli", "claude"),
        "total_agents": 1,
        "system": system_data,
        "note": "You are the first agent created in this project. You are the orchestrator. After dispatching work to other agents, monitor them with: drone @devpulse watchdog agent @target",
    }
    provider_gaps = accumulated.get("provider_gaps", {})
    if provider_gaps:
        report["provider_gaps"] = provider_gaps
        report["provider_action"] = (
            "Provider settings need configuring. Tell the user what is missing and point them to provider_manifest.json for details."
        )
    report_path = dropbox / "init_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    logger.info("[init_flow] init report written to %s", report_path)


def stage_12_done(accumulated: Dict[str, Any] | None = None, dry_run: bool = False) -> Dict[str, Any]:
    """Print completion summary and drop init report."""
    console.print()
    console.print("[bold cyan]Step 12/12[/bold cyan] — Done!")
    console.print()
    console.print("[bold green]✓ Setup complete![/bold green]")
    console.print()
    console.print("  [cyan]aipass help[/cyan]     [dim]# Ask any question[/dim]")
    console.print("  [cyan]aipass doctor[/cyan]   [dim]# Check system health[/dim]")
    console.print("  [cyan]aipass profile[/cyan]  [dim]# View your profile[/dim]")
    console.print()
    if accumulated:
        _write_init_report(accumulated.get("agent_path", ""), accumulated, dry_run=dry_run)
    _save_stage(12, dry_run=dry_run)
    return {}


# --- MAIN RUNNER ---
def _preflight_check() -> str | None:
    """Return an error message if CWD is unsafe for init, else None."""
    cwd = Path.cwd()
    # Block if inside an agent directory
    if (cwd / ".trinity" / "passport.json").is_file():
        return (
            "This directory is an agent branch (has .trinity/passport.json).\n"
            "Agents are managed by 'drone @spawn', not 'aipass init'."
        )
    # Block if inside an existing AIPass project (registry above us)
    for parent in [cwd] + list(cwd.parents):
        for f in parent.iterdir():
            if f.is_file() and f.name.endswith("_REGISTRY.json"):
                return (
                    f"Already inside an AIPass project (found {f.name} at {parent}).\n"
                    "Use 'aipass init update' to upgrade an existing project."
                )
        if parent == parent.parent:
            break
    return None


def run_init(
    non_interactive: bool = False,
    name: str | None = None,
    cli: str | None = None,
    style: str | None = None,
    no_docker: bool = False,
    dry_run: bool = False,
) -> int:
    """Run the 12-stage init flow. Returns 0 on success."""
    # Pre-flight: refuse to run inside existing projects or agent dirs
    err = _preflight_check()
    if err:
        console.print(f"[red]✗[/red] {err}")
        return 1

    # Ensure scaffold exists (creates registry, .aipass, etc. if missing)
    cwd = Path.cwd()
    if not list(cwd.glob("*_REGISTRY.json")):
        from aipass.aipass.apps.handlers.init.bootstrap import init_project

        if not dry_run:
            init_project(cwd)
        else:
            console.print("[yellow]\\[dry-run][/yellow] would create project scaffold")

    # In dry-run we ignore on-disk progress so the full flow always walks.
    last_done = 0 if dry_run else _get_last_completed_stage()

    if last_done >= TOTAL_STAGES:
        console.print("[green]✓[/green] Setup already complete.")
        console.print("[dim]Run 'aipass doctor' to check status.[/dim]")
        return 0

    if last_done > 0:
        warning(f"Resuming from stage {last_done + 1}...")

    accumulated: Dict[str, Any] = {}

    stage_fns = [
        (1, lambda: stage_1_welcome(dry_run=dry_run)),
        (2, lambda: stage_2_system_detect(non_interactive, dry_run=dry_run)),
        (3, lambda: stage_3_doctor(non_interactive, dry_run=dry_run)),
        (4, lambda: stage_4_user_profile(non_interactive, name, accumulated, dry_run=dry_run)),
        (5, lambda: stage_5_style_questions(non_interactive, style, dry_run=dry_run)),
        (6, lambda: stage_6_tool_choice(non_interactive, cli, dry_run=dry_run)),
        (7, lambda: stage_7_docker_offer(non_interactive, no_docker, accumulated.get("has_docker"), dry_run=dry_run)),
        (8, lambda: stage_8_first_agent(non_interactive, dry_run=dry_run)),
        (9, lambda: stage_9_ping_sweep(non_interactive, dry_run=dry_run)),
        (10, lambda: stage_10_smoke_test(non_interactive, dry_run=dry_run)),
        (
            11,
            lambda: stage_11_handoff(
                accumulated.get("cli", "claude"),
                accumulated.get("flag_variant", "default"),
                accumulated.get("agent_path", "src/my-agent"),
                non_interactive,
                dry_run=dry_run,
            ),
        ),
        (12, lambda: stage_12_done(accumulated=accumulated, dry_run=dry_run)),
    ]

    for stage_num, fn in stage_fns:
        if stage_num <= last_done:
            continue
        try:
            result = fn() or {}
            accumulated.update(result)
        except KeyboardInterrupt:
            logger.info("[init_flow] init paused at stage %d by user", stage_num)
            warning(f"Paused at stage {stage_num}. Run 'aipass init run' to resume.")
            return 0
        except Exception as exc:
            logger.warning("[init_flow] stage %d error: %s", stage_num, exc)
            warning(f"Stage {stage_num} error: {exc} — continuing.")
            _save_stage(stage_num, {"error": str(exc)}, dry_run=dry_run)

    return 0


# --- INTROSPECTION + HELP ---
def print_introspection() -> None:
    """Show module info and current setup progress."""
    progress = _get_setup_progress()
    last = progress.get("last_completed_stage", 0)
    console.print()
    console.print("[bold cyan]init_flow Module[/bold cyan]")
    console.print("12-stage guided first-run setup, resumable")
    console.print()
    if last == 0:
        console.print("[dim]Setup not started. Run: aipass init run[/dim]")
    elif last >= TOTAL_STAGES:
        console.print("[green]✓[/green] Setup complete.")
    else:
        console.print(f"[yellow]In progress:[/yellow] stage {last}/{TOTAL_STAGES} completed.")
        console.print(f"[dim]Run 'aipass init run' to resume from stage {last + 1}.[/dim]")
    console.print()


def print_help() -> None:
    """Print usage help for the init command."""
    console.print()
    console.print("[bold cyan]aipass init[/bold cyan] — guided first-run setup")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass init run[/green]                      [dim]# interactive[/dim]")
    console.print("  [green]aipass init run --non-interactive[/green]    [dim]# CI/headless[/dim]")
    console.print("  [green]aipass init run --name Patrick[/green]       [dim]# pre-fill name[/dim]")
    console.print("  [green]aipass init run --cli claude[/green]         [dim]# pre-fill CLI[/dim]")
    console.print("  [green]aipass init run --no-docker[/green]          [dim]# skip docker offer[/dim]")
    console.print("  [green]aipass init run --dry-run[/green]            [dim]# walk all stages, no writes[/dim]")
    console.print()
    console.print("[yellow]STAGES:[/yellow] 12 stages, each saved — resume on ctrl-C")
    console.print()


# --- COMMAND HANDLER ---
def _handle_init_scaffold(args: list[str]) -> int:
    """Handle `aipass init [target] [name]` — instant project scaffold."""
    from aipass.aipass.apps.handlers.init.bootstrap import init_project

    target = Path(args[0]) if args else Path.cwd()
    project_name = args[1] if len(args) > 1 else None
    try:
        result = init_project(target, project_name)
        console.print(f"\n[green]✓[/green] Project initialized at [bold]{target}[/bold]")
        console.print()

        # Find the package directory to show in guidance
        package_dir = None
        for child in (target / "src").iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                package_dir = child
                break

        console.print("[bold]Project structure:[/bold]")
        console.print(f"  {target}/")
        if package_dir:
            rel_pkg = package_dir.relative_to(target)
            console.print(f"  └── {rel_pkg}/    [dim]← agents live here[/dim]")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        if str(target) != str(Path.cwd()):
            console.print(f"  [cyan]cd {target}[/cyan]")
        console.print("  [cyan]aipass init agent <name>[/cyan]    [dim]# create your first agent[/dim]")
        console.print("  [cyan]aipass init run[/cyan]             [dim]# full guided setup (optional)[/dim]")
        console.print()

        json_handler.log_operation("aipass_init", {"target": str(target), "result": result})
        return 0
    except Exception as exc:
        logger.warning("[init_flow] scaffold failed: %s", exc)
        console.print(f"[red]✗[/red] Init failed: {exc}")
        return 1


def _handle_init_update(args: list[str]) -> int:
    """Handle `aipass init update [target]` — refresh managed scaffold files."""
    from aipass.aipass.apps.handlers.init.bootstrap import update_project

    target = Path(args[0]) if args else Path.cwd()
    try:
        result = update_project(target)
        updated = result.get("updated_files", [])
        current = result.get("already_current", [])
        if updated:
            console.print(f"[green]✓[/green] Updated {len(updated)} file(s):")
            for f in updated:
                console.print(f"  [green]+[/green] {f}")
        else:
            console.print("[green]✓[/green] All files already current.")
        if current:
            console.print(f"  ({len(current)} already up to date)")
        # Heal registry: prune stale entries (e.g. cross-project ../paths)
        try:
            from aipass.spawn.apps.modules.sync_registry import sync_registry

            sync_result = sync_registry(fix=True)
            pruned = sync_result.get("stale", [])
            if pruned:
                console.print(f"  [green]Registry healed:[/green] removed {len(pruned)} stale entry(ies)")
        except Exception as sync_exc:
            logger.warning("[init_flow] registry sync during update skipped: %s", sync_exc)

        json_handler.log_operation("aipass_init_update", {"target": str(target), "result": result})
        return 0
    except Exception as exc:
        logger.warning("[init_flow] update failed: %s", exc)
        console.print(f"[red]✗[/red] Update failed: {exc}")
        return 1


def _handle_init_agent(args: list[str]) -> int:
    """Handle `aipass init agent <name>` — create a new agent via spawn."""
    if not args:
        console.print("[red]✗[/red] Usage: aipass init agent <name>")
        return 1
    agent_name = args[0]
    import subprocess as _sp

    package_dir = _resolve_package_dir()
    if package_dir:
        agent_path = f"{package_dir}/{agent_name}"
    else:
        agent_path = f"src/{agent_name}"

    cmd = ["drone", "@spawn", "create", agent_path]
    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
    result = _sp.run(cmd, capture_output=False)
    return result.returncode


def handle_command(command: str, args: list[str]) -> bool:
    """Route init subcommands. Returns True if handled, False otherwise."""
    if command != COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    if args[0] == "agent":
        sys.exit(_handle_init_agent(args[1:]))
        return True

    if args[0] == "update":
        sys.exit(_handle_init_update(args[1:]))
        return True

    if args[0] == "run" or args[0].startswith("--"):
        run_args = args[1:] if args[0] == "run" else args
        non_interactive = "--non-interactive" in run_args

        def _flag_value(flag: str) -> str | None:
            """Extract the value after a named flag, or None if absent."""
            if flag not in run_args:
                return None
            idx = run_args.index(flag)
            return run_args[idx + 1] if idx + 1 < len(run_args) else None

        name = _flag_value("--name")
        cli = _flag_value("--cli")
        style = _flag_value("--style")
        no_docker = "--no-docker" in run_args
        dry_run = "--dry-run" in run_args

        result = run_init(
            non_interactive=non_interactive,
            name=name,
            cli=cli,
            style=style,
            no_docker=no_docker,
            dry_run=dry_run,
        )
        json_handler.log_operation(
            "init_run",
            {"non_interactive": non_interactive, "dry_run": dry_run, "exit": result},
        )
        sys.exit(result)
        return True

    # Positional args = target path and/or project name for scaffold
    err = _preflight_check()
    if err:
        console.print(f"[red]✗[/red] {err}")
        sys.exit(1)
    sys.exit(_handle_init_scaffold(args))
    return True


if __name__ == "__main__":
    handle_command("init", sys.argv[1:])
